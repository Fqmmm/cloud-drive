"""Two-instance routing, cross-instance state and equal-budget P4 comparison."""
from collections import Counter
import csv
import hashlib
import json
import subprocess
import time

from e2_support import Client, MIB, ROOT, checksum, full_smoke, inventory, payload, prepare, save, utc
from run import collector, downstream_evidence, stop_collector, wait_stable
from workload import Workload
from analyze import analyze_round, write_csv


def direct(ctx, row, path, method="GET", token=None, data=None):
    """Use existing MinIO curl as a one-shot client; secrets only enter stdin."""
    ip = next(iter(row["networks"].values()))["ip"]
    lines = ["silent", "show-error", "include", "max-time = 15", "request = " + json.dumps(method),
             "url = " + json.dumps("http://" + ip + ":8080/api/v1" + path)]
    if token:
        lines.append("header = " + json.dumps("Authorization: Bearer " + token))
    if data is not None:
        lines += ["header = \"Content-Type: application/json\"", "data = " + json.dumps(json.dumps(data))]
    args = ["docker", "compose", "--env-file", str(ctx.env_file), "-p", ctx.project,
            "exec", "-T", "minio", "curl", "--config", "-"]
    result = subprocess.run(args, cwd=ROOT, input=("\n".join(lines) + "\n").encode(), capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError("One-shot cross-instance client failed")
    headers, body = result.stdout.split(b"\r\n\r\n", 1)
    parts = headers.decode("latin-1").split("\r\n")
    fields = {line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip() for line in parts[1:] if ":" in line}
    return int(parts[0].split()[1]), fields, body


def routing_and_state(ctx, root, f):
    folder = root / "two-instance-validation"
    folder.mkdir()
    instances = [r for r in ctx.snapshot(folder) if r["service"] == "share-service"]
    if len(instances) != 2:
        raise RuntimeError("Expected two share-service instances")
    rows, counts = [], Counter()
    client = Client(ctx.base)
    client.login(f, refresh=True)
    for index in range(100):
        response = client.request("/shares")[0]
        success = response.status_code == 200 and response.json().get("code") == "00000"
        instance = response.headers.get("X-Instance-Id", "")
        rows.append(dict(sample=index + 1, utc=utc(), status=response.status_code, success=int(success), instance=instance))
        if success:
            counts[instance] += 1
    write_csv(folder / "distribution.csv", rows)
    expected = {r["id"][:12] for r in instances}
    if not all(r["success"] for r in rows) or set(counts) != expected:
        raise RuntimeError("Gateway did not distribute 100 successful requests across both instances")
    evidence = dict(distribution=dict(counts), request_count=100, one_shot_client="curl in existing MinIO container, stdin configuration; no extra container")
    a, b = instances
    status, headers, body = direct(ctx, a, "/shares", "POST", client.token,
        dict(fileId=f["fileId"], accessType=1, expireDays=7))
    created = json.loads(body)
    if status != 200 or created.get("code") != "00000":
        raise RuntimeError("Cross-instance share creation failed")
    share = created["data"]
    path, code = "/s/" + share["shareToken"], dict(extractCode=share["extractCode"])
    evidence["created_on"] = headers.get("x-instance-id")
    status, headers, body = direct(ctx, b, path + "/verify", "POST", data=code)
    evidence["verified_on"] = headers.get("x-instance-id")
    evidence["verify_status"] = status
    if status != 200 or json.loads(body).get("code") != "00000":
        raise RuntimeError("Other instance could not verify the created share")
    status, headers, body = direct(ctx, b, path + "/download", "POST", data=code)
    evidence["download_on"] = headers.get("x-instance-id")
    evidence["download_sha256"] = hashlib.sha256(body).hexdigest()
    evidence["download_match"] = status == 200 and body == payload(MIB)
    if not evidence["download_match"]:
        raise RuntimeError("Cross-instance download checksum failed")
    status, headers, body = direct(ctx, b, "/shares/" + share["id"], "DELETE", token=client.token)
    evidence["cancelled_on"] = headers.get("x-instance-id")
    if status != 200 or json.loads(body).get("code") != "00000":
        raise RuntimeError("Cross-instance cancellation failed")
    status, headers, body = direct(ctx, a, path + "/verify", "POST", data=code)
    evidence["cancel_observed_on"] = headers.get("x-instance-id")
    evidence["cancel_observed_status"] = status
    evidence["cancel_observed_code"] = json.loads(body).get("code")
    if status != 410 or evidence["cancel_observed_code"] != "SHARE_CANCELLED":
        raise RuntimeError("Cancellation was not visible on the original instance")
    if evidence["created_on"] != a["id"][:12] or evidence["verified_on"] != b["id"][:12] or evidence["cancel_observed_on"] != a["id"][:12]:
        raise RuntimeError("Instance identity did not match direct routing evidence")

    limited = client.data("/shares", "POST", dict(fileId=f["fileId"], accessType=1, expireDays=7))
    wrong = "000000" if limited["extractCode"] != "000000" else "111111"
    path = "/s/" + limited["shareToken"] + "/verify"
    limits = []
    for label, target, count in [("A", a, 6), ("B", b, 6)]:
        for index in range(count):
            status, headers, body = direct(ctx, target, path, "POST", data=dict(extractCode=wrong))
            limits.append(dict(instance=headers.get("x-instance-id"), label=label, attempt=index + 1,
                               status=status, code=json.loads(body).get("code")))
    if [r["status"] for r in limits] != [403] * 5 + [429] + [403] * 5 + [429]:
        raise RuntimeError("Per-instance wrong-code limit did not match its configured scope")
    status, headers, body = direct(ctx, a, path, "POST", data=dict(extractCode=limited["extractCode"]))
    evidence["correct_code_bypasses_instance_limit"] = status == 200 and json.loads(body).get("code") == "00000"
    if not evidence["correct_code_bypasses_instance_limit"]:
        raise RuntimeError("Correct code was unexpectedly blocked")
    client.data("/shares/" + limited["id"], "DELETE")
    client.session.close()
    write_csv(folder / "per-instance-limits.csv", limits)
    save(folder / "cross-instance.json", evidence)
    print("Two-instance distribution passed: " + str(dict(counts)) + "; cross-instance state and per-instance limits passed", flush=True)
    return evidence


def performance_round(ctx, root, fixtures, replicas, repeat):
    folder = root / f"scale-{replicas}replicas-vu20-r{repeat}"
    folder.mkdir()
    rows = ctx.snapshot(folder)
    containers = {r["service"] + ("-" + r["number"] if r["service"] == "share-service" else ""): r["id"] for r in rows}
    save(folder / "containers-map.json", containers)
    before = checksum(ctx.base, fixtures)
    work = dict(scenario="P4", vus=20, repeat=repeat, replicas=replicas, file_size_bytes=MIB,
        request_base_url=ctx.base, warmup_seconds=30, measure_seconds=120, minimum_cooldown_seconds=30,
        closed_model="20 independent VUs; verify and download anonymous; 1 s think time after iteration",
        complete=False, upload_cap_hit_by_vu=[False] * 20)
    save(folder / "workload.json", work)
    process, output = collector(folder, folder / "containers-map.json")
    load = None
    def log(message):
        line = utc() + " " + folder.name + ": " + message
        print(line, flush=True)
        with (folder / "execution.log").open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    try:
        load = Workload(ctx.base, fixtures, folder, folder.name, "P4")
        work["jwt_remaining_seconds_before_warmup"] = load.jwt_remaining
        work["warmup"] = load.phase("warmup", 30, log)
        work["measurement"] = load.phase("measure", 120, log)
        load.close()
        load = None
        save(folder / "checksum.json", dict(before=before, after=checksum(ctx.base, fixtures)))
        downstream = []
        for key, container_id in containers.items():
            if key.startswith("share-service-"):
                subfolder = folder / key
                subfolder.mkdir()
                save(subfolder / "containers.json", {"share-service": container_id})
                downstream_evidence(subfolder, work["measurement"], subfolder / "containers.json")
                with (subfolder / "downstream.csv").open(newline="", encoding="utf-8") as file:
                    downstream.extend(dict(row, instance=key) for row in csv.DictReader(file))
        if downstream:
            write_csv(folder / "downstream.csv", downstream)
        work["cooldown"] = wait_stable(folder, 30, log)
        work["complete"] = True
        log("round complete")
    finally:
        if load:
            load.close()
        save(folder / "workload.json", work)
        stop_collector(folder, process, output)
    result = analyze_round(folder)
    result["replicas"] = replicas
    save(folder / "metrics.json", result)
    return result


def scale(ctx, root, private, preserved):
    folder = root / "scale-setup"
    folder.mkdir()
    ctx.compose("up", "-d", "--no-deps", "--scale", "share-service=2", "share-service", log=folder / "scale-up.log")
    ctx.ready(7)
    ctx.reload(folder)
    time.sleep(2)
    routing_and_state(ctx, root, preserved)
    fixture_file = private / "load-fixtures.local"
    if fixture_file.exists():
        raise RuntimeError("Choose a fresh E2 batch rather than reuse ambiguous load fixtures")
    fixtures = prepare(ctx.base, fixture_file, users=20)
    results = []
    # Alternate conditions, reversing the order for repeat 2 to limit temporal bias.
    for repeat, sequence in [(1, [1, 2]), (2, [2, 1]), (3, [1, 2])]:
        for replicas in sequence:
            setup = root / f"scale-{replicas}replicas-r{repeat}-setup"
            setup.mkdir()
            ctx.compose("up", "-d", "--no-deps", "--scale", "share-service=" + str(replicas), "share-service", log=setup / "scale.log")
            ctx.ready(5 + replicas)
            ctx.reload(setup)
            time.sleep(2)
            print(f"SCALE PERFORMANCE replicas={replicas} repeat={repeat}/3", flush=True)
            results.append(performance_round(ctx, root, fixtures, replicas, repeat))
            save(root / "scale-metrics.json", results)
    restore = root / "scale-restored"
    restore.mkdir()
    ctx.compose("up", "-d", "--no-deps", "--scale", "share-service=1", "share-service", log=restore / "scale-down.log")
    ctx.ready(6)
    ctx.reload(restore)
    ctx.snapshot(restore)
    full_smoke(ctx, restore)
    save(root / "scale-complete.json", dict(utc=utc(), rounds=6, restored_replicas=1))
    return results
