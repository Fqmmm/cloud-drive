"""Run E1's frozen matrix, preserving each run and excluding setup/cleanup."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

import psutil

from common import ROOT, MIB, Client, checksum, cleanup_uploads, command, compose, payload, prepare, save, sql, utc
from resources import engine
from workload import Workload


def environment():
    config = json.loads(compose("config", "--format", "json"))
    for service in config["services"].values():
        for name in service.get("environment", {}):
            if any(word in name.upper() for word in ["PASSWORD", "SECRET", "TOKEN", "MINIO_ROOT_USER"]):
                service["environment"][name] = "<redacted>"
    ids = {name: compose("ps", "-q", name) for name in config["services"]}
    if not all(ids.values()):
        raise RuntimeError("All six services must be running before E1")
    details = json.loads(command(["docker", "inspect", *ids.values()]))
    info_response = engine("/info")
    info = json.load(info_response)
    info_response.close()
    hardware = command(["pwsh", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress"])
    snapshot = dict(captured_utc=utc(), source_commit=command(["git", "rev-parse", "HEAD"]),
        git_status=command(["git", "status", "--porcelain"]), branch=command(["git", "branch", "--show-current"]),
        host=dict(os=platform.platform(), processor=json.loads(hardware), memory_bytes=psutil.virtual_memory().total,
                  logical_cpus=psutil.cpu_count(), disk_free_bytes={drive: shutil.disk_usage(drive).free for drive in ["C:/", "D:/"]}),
        docker={key: info.get(key) for key in ["ServerVersion", "NCPU", "MemTotal", "OperatingSystem", "Driver", "DockerRootDir"]},
        compose_version=compose("version"), context=command(["docker", "context", "show"]),
        tool=dict(name="Python closed-VU harness", python=sys.version, requests=importlib.metadata.version("requests"),
                  psutil=psutil.__version__, location="Windows host; outside the four-CPU Docker VM; shared physical host"),
        storage="Docker Desktop WSL2 named volumes for MySQL/MinIO; repository/init scripts bind-mounted from Windows D:; not bind-mounted business data",
        containers=[dict(service=entry["Config"]["Labels"]["com.docker.compose.service"], id=entry["Id"], image_id=entry["Image"],
                         image_reference=entry["Config"]["Image"], restart_policy=entry["HostConfig"]["RestartPolicy"],
                         resource_limits={key: entry["HostConfig"].get(key) for key in ["NanoCpus", "CpuQuota", "CpuPeriod", "Memory", "MemorySwap"]},
                         mounts=[{key: mount.get(key) for key in ["Type", "Name", "Source", "Destination"]} for mount in entry["Mounts"]]) for entry in details])
    snapshot["java_runtime"] = {}
    for service in ["auth-service", "file-service", "share-service"]:
        probe = subprocess.run(["docker", "compose", "exec", "-T", service, "java", "-XshowSettings:vm", "-version"],
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        snapshot["java_runtime"][service] = [line.strip() for line in probe.stderr.splitlines()
            if any(term in line for term in ["Max. Heap Size", "openjdk version", "Runtime Environment", "Server VM"])]
    snapshot["mysql_version"] = sql("SELECT VERSION()")
    snapshot["tool"]["numpy"] = importlib.metadata.version("numpy")
    snapshot["tool"]["matplotlib"] = importlib.metadata.version("matplotlib")
    snapshot["resource_timestamp_alignment"] = "Use Windows receipt epoch for exact workload windows; retain Engine timestamp independently"
    snapshot["harness_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(__file__).parent.glob("*.py")}
    if any(entry["State"].get("Health", {}).get("Status") != "healthy" for entry in details):
        raise RuntimeError("All six services must be healthy before E1")
    return snapshot, config, ids


def collector(folder, containers_file):
    output = (folder / "collector-output.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-u", str(Path(__file__).with_name("resources.py")),
        str(folder), str(containers_file), str(os.getpid())], cwd=ROOT, stdout=output, stderr=output)
    deadline = time.monotonic() + 20
    while not (folder / "collector.ready").exists():
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("Independent resource collector did not become ready")
        time.sleep(0.1)
    return process, output


def stop_collector(folder, process, output):
    (folder / "collector.stop").touch()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)
    output.close()
    for name in ["collector.stop", "collector.ready"]:
        (folder / name).unlink(missing_ok=True)


def wait_stable(folder, seconds, log):
    """At least 30 s cooling, then require 10 s below 20% of the four-CPU VM."""
    started = time.time()
    time.sleep(seconds)
    threshold = 80.0
    limit = time.monotonic() + 120
    while True:
        with (folder / "resources.csv").open(newline="", encoding="utf-8") as file:
            rows = [row for row in csv.DictReader(file) if float(row["sample_epoch"]) > time.time() - 10 and row["cpu_percent"]]
        totals = {}
        for row in rows:
            bucket = int(float(row["sample_epoch"]))
            totals[bucket] = totals.get(bucket, 0) + float(row["cpu_percent"])
        stable = len(totals) >= min(8, max(1, seconds - 1)) and max(totals.values(), default=999) < threshold
        if stable or time.monotonic() >= limit:
            break
        log("cooldown: waiting for resource stability")
        time.sleep(10)
    return dict(seconds=time.time() - started, stable=stable, threshold_total_cpu_percent=threshold,
                observed_max_total_cpu_percent=max(totals.values(), default=None))


def downstream_evidence(folder, window, containers_file):
    containers = json.loads(containers_file.read_text())
    output = command(["docker", "logs", "--timestamps", "--since", str(int(window["start_epoch"])),
                      "--until", str(int(window["end_epoch"]) + 1), containers["share-service"]])
    with (folder / "downstream.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["utc", "sample_epoch", "operation", "duration_ms", "request_id", "status"])
        writer.writeheader()
        for line in output.splitlines():
            stamp = line.split(" ", 1)[0]
            try:
                epoch = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if not window["start_epoch"] <= epoch < window["end_epoch"]:
                continue
            match = re.search(r"dependency operation=(metadata|content) requestId=([A-Za-z0-9_-]+) durationMs=(\d+)", line)
            if match:
                writer.writerow(dict(utc=stamp, sample_epoch=epoch, operation=match[1], request_id=match[2], duration_ms=match[3], status=""))
            match = re.search(r"request id=([A-Za-z0-9_-]+) category=anonymous-share status=(\d+) durationMs=(\d+)", line)
            if match:
                writer.writerow(dict(utc=stamp, sample_epoch=epoch, operation="share_request", request_id=match[1], status=match[2], duration_ms=match[3]))


def round_run(args, batch, spec, fixtures, snapshot, config, containers_file):
    run_id = batch + f"-{spec['scenario']}-vu{spec['vus']:02}-r{spec['repeat']}"
    folder = ROOT / "experiments" / "E1" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    log_file = (folder / "execution.log").open("w", encoding="utf-8")

    def log(message):
        line = f"{utc()} {run_id}: {message}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    save(folder / "environment.json", snapshot)
    save(folder / "compose.redacted.json", config)
    active = fixtures[:spec["vus"]]
    large = spec["scenario"].startswith("P5")
    worst_bytes = spec["vus"] * args.max_uploads * (20 * MIB if large else MIB)
    if spec["scenario"] in ("P2", "P5U") and min(shutil.disk_usage(drive).free for drive in ["C:/", "D:/"]) < worst_bytes * 1.5:
        raise RuntimeError("Insufficient host disk headroom for capped uploads")
    checksums = dict(before=checksum(args.base_url, active, large))
    for fixture in active:
        client = Client(args.base_url)
        client.login(fixture)
        quota = client.data("/quota")
        per_user_bound = args.max_uploads * (20 * MIB if large else MIB)
        if quota["totalBytes"] - quota["usedBytes"] < per_user_bound:
            raise RuntimeError("Insufficient quota for capped experiment round")
    work = dict(**spec, run_id=run_id, batch=batch, file_size_bytes=20 * MIB if large else MIB,
        request_base_url=args.base_url,
        model="closed constant VUs; stagger first request by VU/VUs seconds; sleep 1 second after each business iteration",
        warmup_seconds=args.warmup, measure_seconds=args.duration, minimum_cooldown_seconds=args.cooldown,
        max_uploads_per_vu_including_warmup=args.max_uploads, maximum_upload_bytes=worst_bytes,
        entries_per_vu=100, request_timeout=dict(connect_seconds=3, read_seconds=30),
        p4="one iteration = anonymous protected-share verify then download; no bearer token; operations tagged separately",
        measurement="HTTP sample cohort starts inside the exact 120 s window; late timeouts remain failures; throughput counts successful completions inside the window",
        hash_seed=20261116, sha256=hashlib.sha256(payload(20 * MIB if large else MIB)).hexdigest())
    save(folder / "workload.json", work)
    process, output = collector(folder, containers_file)
    load = None
    try:
        load = Workload(args.base_url, active, folder, run_id, spec["scenario"], args.max_uploads)
        work["jwt_remaining_seconds_before_warmup"] = load.jwt_remaining
        work["warmup"] = load.phase("warmup", args.warmup, log)
        work["measurement"] = load.phase("measure", args.duration, log)
        work["upload_cap_hit_by_vu"] = load.cap_hits
        work["upload_requests_by_vu_including_warmup"] = load.upload_counts
        load.close()
        load = None
        save(folder / "workload.json", work)
        checksums["after"] = checksum(args.base_url, active, large)
        save(folder / "checksum.json", checksums)
        downstream_evidence(folder, work["measurement"], containers_file)
        if spec["scenario"] in ("P2", "P5U"):
            maintenance = cleanup_uploads(args.base_url, active)
        else:
            maintenance = dict(logical_files_deleted=0, quota_restored=True, maintenance_outside_measurement=True)
        save(folder / "cleanup.json", maintenance)
        log("checksum and scoped cleanup passed; cooling")
        work["cooldown"] = wait_stable(folder, args.cooldown, log)
        work["complete"] = True
        save(folder / "workload.json", work)
        log("round complete; " + str(work["cooldown"]))
    except Exception as error:
        work["fatal_type"] = type(error).__name__
        work["complete"] = False
        save(folder / "workload.json", work)
        log("round failed: " + type(error).__name__)
        raise
    finally:
        if load:
            load.close()
        stop_collector(folder, process, output)
        log_file.close()
    return run_id


def pending_rounds(manifest):
    """Return uncompleted specifications without changing the previous batch."""
    expected = {manifest["batch"] + f"-{spec['scenario']}-vu{spec['vus']:02}-r{spec['repeat']}": spec
                for spec in manifest["matrix"]}
    completed = manifest["completed"]
    if len(expected) != len(manifest["matrix"]) or len(set(completed)) != len(completed):
        raise ValueError("Duplicate matrix or completion records")
    if not set(completed).issubset(expected):
        raise ValueError("Completion record does not belong to the original matrix")
    pending = [spec for name, spec in expected.items() if name not in completed]
    if not pending:
        raise ValueError("Original matrix is already complete")
    return pending


def verify_continuity(previous, snapshot, config):
    """Continuations preserve measured application inputs and measurement code."""
    before = json.loads((previous / "environment.json").read_text(encoding="utf-8"))
    if json.loads((previous / "compose.redacted.json").read_text(encoding="utf-8")) != config:
        raise ValueError("Compose configuration changed since the previous batch")
    for key in ["NCPU", "MemTotal"]:
        if before["docker"][key] != snapshot["docker"][key]:
            raise ValueError("Docker resource budget changed since the previous batch")
    images = lambda env: {entry["service"]: entry["image_id"] for entry in env["containers"]}
    if images(before) != images(snapshot):
        raise ValueError("Application or infrastructure images changed since the previous batch")
    for name in ["common.py", "resources.py", "workload.py"]:
        if before["harness_sha256"][name] != snapshot["harness_sha256"][name]:
            raise ValueError("Measurement or cleanup implementation changed since the previous batch")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--batch")
    parser.add_argument("--continue-from", help="Original formal batch; run unfinished specifications in a new batch")
    parser.add_argument("--max-uploads", type=int, default=150)
    parser.add_argument("--pilot-scenarios", default="P1,P2,P3,P4,P5U,P5D")
    args = parser.parse_args()
    previous = None
    prior_manifest = None
    if args.continue_from:
        if args.pilot or not args.fixtures or not args.fixtures.exists():
            raise ValueError("Continuation requires existing private fixtures and formal mode")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.continue_from):
            raise ValueError("Invalid previous batch identifier")
        previous = ROOT / "experiments" / "E1" / (args.continue_from + "-summary")
        prior_manifest = json.loads((previous / "matrix.json").read_text(encoding="utf-8"))
        if prior_manifest["pilot"]:
            raise ValueError("Cannot continue a pilot as a formal batch")
        pending_rounds(prior_manifest)
        for name in prior_manifest["completed"]:
            work = json.loads((previous.parent / name / "workload.json").read_text(encoding="utf-8"))
            if not work.get("complete") or (work["warmup_seconds"], work["measure_seconds"], work["minimum_cooldown_seconds"]) != (30, 120, 30):
                raise ValueError("Previous completion is incomplete or uses different timing")
            if work["request_base_url"] != args.base_url or work["max_uploads_per_vu_including_warmup"] != args.max_uploads:
                raise ValueError("Continuation request endpoint or upload cap differs")
    args.warmup, args.duration, args.cooldown = (3, 5, 3) if args.pilot else (30, 120, 30)
    batch = args.batch or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ("-pilot" if args.pilot else "-formal")
    summary = ROOT / "experiments" / "E1" / (batch + "-summary")
    summary.mkdir(parents=True, exist_ok=False)
    secret_dir = ROOT / "artifacts" / "e1" / batch
    secret_dir.mkdir(parents=True, exist_ok=True)
    secret_path = args.fixtures or secret_dir / "fixtures.local"
    snapshot, config, containers = environment()
    snapshot["tool"]["request_base_url"] = args.base_url
    if previous:
        verify_continuity(previous, snapshot, config)
        snapshot["continuation_of"] = args.continue_from
    save(summary / "environment.json", snapshot)
    save(summary / "compose.redacted.json", config)
    containers_file = summary / "containers.json"
    save(containers_file, containers)
    if secret_path.exists():
        fixtures = json.loads(secret_path.read_text(encoding="utf-8"))
    else:
        print("Preparing independent accounts and fixture data", flush=True)
        fixtures = prepare(args.base_url, secret_path, users=5 if args.pilot else 20)
    if not args.pilot and len(fixtures) != 20:
        raise RuntimeError("Formal matrix requires 20 independent accounts")
    snapshot["dataset"] = dict(vus=len(fixtures), list_entries_per_vu=100, directory_entries_per_vu=99,
        one_mib_downloads=len(fixtures), twenty_mib_downloads=min(5, len(fixtures)),
        initial_active_file_records=int(sql("SELECT COUNT(*) FROM file_db.sys_file WHERE is_deleted=0")),
        initial_total_file_records=int(sql("SELECT COUNT(*) FROM file_db.sys_file")))
    save(summary / "environment.json", snapshot)
    baseline = summary / "idle"
    baseline.mkdir()
    proc, out = collector(baseline, containers_file)
    print("Recording idle baseline", flush=True)
    time.sleep(5 if args.pilot else 30)
    stop_collector(baseline, proc, out)
    matrix = []
    if args.pilot:
        selected = args.pilot_scenarios.split(",")
        if any(scenario not in ["P1", "P2", "P3", "P4", "P5U", "P5D"] for scenario in selected):
            raise ValueError("Unknown pilot scenario")
        matrix = [dict(scenario=scenario, vus=2, repeat=0, order=index + 1) for index, scenario in enumerate(selected)]
    else:
        orders = [[5, 10, 20], [10, 20, 5], [20, 5, 10]]
        for scenario in ["P1", "P2", "P3", "P4"]:
            for repeat, vus_order in enumerate(orders, 1):
                for vus in vus_order:
                    matrix.append(dict(scenario=scenario, vus=vus, repeat=repeat, order=len(matrix) + 1))
        for scenario in ["P5U", "P5D"]:
            for repeat in range(1, 4):
                matrix.append(dict(scenario=scenario, vus=5, repeat=repeat, order=len(matrix) + 1))
    manifest = dict(batch=batch, pilot=args.pilot, source_commit=snapshot["source_commit"], matrix=matrix,
                    completed=[], started_utc=utc(), fixture_credentials="Only in ignored artifacts/e1; not part of raw public data")
    if prior_manifest:
        matrix = pending_rounds(prior_manifest)
        manifest.update(matrix=matrix, continuation_of=args.continue_from,
            previous_source_commit=prior_manifest["source_commit"],
            previous_completed=prior_manifest["completed"],
            continuity_checks="same images, Compose, Docker CPU/memory, measurement/cleanup code, timing, endpoint and upload cap")
    save(summary / "matrix.json", manifest)
    try:
        for position, spec in enumerate(matrix, 1):
            print(f"MATRIX {position}/{len(matrix)} {spec['scenario']} VU={spec['vus']} repeat={spec['repeat']}", flush=True)
            run_id = round_run(args, batch, spec, fixtures, snapshot, config, containers_file)
            manifest["completed"].append(run_id)
            save(summary / "matrix.json", manifest)
    finally:
        manifest["finished_utc"] = utc()
        save(summary / "matrix.json", manifest)
    print("MATRIX COMPLETE " + batch, flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except Exception as failure:
        print("E1 halted safely: " + type(failure).__name__ + ": " + str(failure), flush=True)
        raise SystemExit(1)
