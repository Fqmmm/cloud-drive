"""Deployment timing and isolated share-service replacement evidence."""
import csv
import hashlib
import json
import secrets
import threading
import time

from e2_support import Client, MIB, ROOT, StartupObserver, changed_services, full_smoke, inventory, payload, save, utc


def fixture(ctx, private):
    account = "e2_" + secrets.token_hex(6)
    f = dict(account=account, password=secrets.token_hex(16))
    client = Client(ctx.base)
    client.data("/auth/register", "POST", dict(accountName=account, password=f["password"],
        nickname="E2 persistent fixture", email=account + "@example.test", accountType="personal"))
    client.login(f)
    f["userId"] = client.data("/users/me")["userId"]
    f["directory"] = client.data("/directories", "POST", dict(name="E2-preserved", parentId="0"))["id"]
    f["fileId"] = client.data("/files?parentId=" + f["directory"], "POST",
        files={"file": ("E2-preserved.bin", payload(MIB), "application/octet-stream")})["id"]
    f["public"] = client.data("/shares", "POST", dict(fileId=f["fileId"], accessType=0, expireDays=7))
    save(private / "persistent-fixture.local", f)
    client.session.close()
    return f


def verify_fixture(ctx, f, folder, name="preserved-file"):
    client = Client(ctx.base)
    client.login(f)
    response = client.request("/s/" + f["public"]["shareToken"] + "/download", "POST", data={}, anonymous=True)[0]
    result = dict(utc=utc(), status=response.status_code, bytes=len(response.content),
        sha256=hashlib.sha256(response.content).hexdigest(),
        match=response.status_code == 200 and response.content == payload(MIB),
        version=response.headers.get("X-App-Version"), instance=response.headers.get("X-Instance-Id"))
    save(folder / (name + ".json"), result)
    client.session.close()
    if not result["match"]:
        raise RuntimeError("Preserved share/file verification failed")
    return result


def deployment(ctx, root, label, build, preserved=None):
    folder = root / label
    folder.mkdir()
    observer = StartupObserver(ctx.project)
    observer.thread.start()
    started = time.time()
    save(folder / "timing.json", dict(start_epoch=started, started_utc=utc(), complete=False))
    try:
        ctx.compose("config", "--quiet", log=folder / "config-validation.log")
        # Config validation precedes the measured up invocation.
        started = time.time()
        _, command_seconds = ctx.compose("up", "-d", *(["--build"] if build else []), log=folder / "up.log")
        returned = time.time()
        rows = ctx.ready()
        ready = time.time()
        smoke = full_smoke(ctx, folder)
        if preserved:
            verify_fixture(ctx, preserved, folder)
        timing = dict(start_epoch=started, command_return_epoch=returned, command_seconds=command_seconds,
            all_healthy_observed_epoch=ready, all_healthy_observed_seconds=ready - started,
            business_ready_epoch=smoke["passed_epoch"], business_ready_seconds=smoke["passed_epoch"] - started,
            smoke_cleanup_seconds=smoke["cleanup_finished_epoch"] - smoke["passed_epoch"],
            source_build=build, complete=True, observation_resolution_seconds=.5)
        save(folder / "timing.json", timing)
        ctx.snapshot(folder)
        ctx.topology(folder)
        ctx.compose("logs", "--no-color", "--since", str(int(started)), log=folder / "application.log")
        print(label + ": business ready in " + str(round(timing["business_ready_seconds"], 2)) + "s; smoke " + str(smoke["passed"]) + "/" + str(smoke["total"]), flush=True)
        return timing
    finally:
        observer.finish(folder)


class UpdateProbes:
    def __init__(self, ctx, f, folder):
        self.ctx, self.fixture, self.folder = ctx, f, folder
        self.rows, self.threads, self.lock, self.stop = [], [], threading.Lock(), threading.Event()

    def start(self):
        for name in ["login", "files", "share"]:
            thread = threading.Thread(target=self.probe, args=(name,), daemon=True)
            thread.start()
            self.threads.append(thread)

    def probe(self, operation):
        client = Client(self.ctx.base, self.fixture.get("_token"))
        while not self.stop.is_set():
            began, status, success, version, instance, error = time.time(), 0, False, "", "", ""
            try:
                if operation == "login":
                    r = client.request("/auth/login", "POST", data=dict(accountName=self.fixture["account"], password=self.fixture["password"]), anonymous=True)[0]
                elif operation == "files":
                    r = client.request("/files?parentId=" + self.fixture["directory"])[0]
                else:
                    r = client.request("/s/" + self.fixture["public"]["shareToken"], anonymous=True)[0]
                status = r.status_code
                body = r.json()
                success = status == 200 and body.get("code") == "00000"
                if success and operation == "files":
                    success = self.fixture["fileId"] in {x["id"] for x in body["data"]["items"]}
                if success and operation == "share":
                    success = body["data"]["fileSize"] == MIB
                version, instance = r.headers.get("X-App-Version", ""), r.headers.get("X-Instance-Id", "")
                error = "" if success else "HTTP_OR_BUSINESS_FAILURE"
            except Exception as failure:
                error = type(failure).__name__
            with self.lock:
                self.rows.append(dict(operation=operation, start_epoch=began, end_epoch=time.time(),
                    latency_ms=(time.time() - began) * 1000, status=status, success=int(success),
                    version=version, instance=instance, error=error))
            self.stop.wait(max(0, 1 - (time.time() - began)))
        client.session.close()

    def finish(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=35)
        with (self.folder / "probes.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(sorted(self.rows, key=lambda x: x["start_epoch"]))


def update_share(ctx, root, preserved):
    folder = root / "independent-update"
    folder.mkdir()
    before = ctx.snapshot(folder, "before.json")
    probes = UpdateProbes(ctx, preserved, folder)
    probes.start()
    record = dict(start_epoch=time.time(), old_version=ctx.values["SHARE_APP_VERSION"], new_version="e2-v2")
    try:
        time.sleep(5)
        content = ctx.env_file.read_text(encoding="utf-8")
        ctx.env_file.write_text(content.replace("SHARE_APP_VERSION=" + ctx.values["SHARE_APP_VERSION"], "SHARE_APP_VERSION=e2-v2"), encoding="utf-8")
        _, record["build_seconds"] = ctx.compose("build", "share-service", log=folder / "build.log")
        record["replace_started_epoch"] = time.time()
        _, record["replace_command_seconds"] = ctx.compose("up", "-d", "--no-deps", "share-service", log=folder / "replace.log")
        ctx.ready()
        record["healthy_epoch"] = time.time()
        _, record["nginx_reload_seconds"] = ctx.reload(folder)
        time.sleep(6)
        verified = verify_fixture(ctx, preserved, folder)
        if verified["version"] != "e2-v2":
            raise RuntimeError("Share response did not expose the new version")
        after = ctx.snapshot(folder, "after.json")
        record["changed_services"] = sorted(changed_services(before, after))
        if record["changed_services"] != ["share-service"]:
            raise RuntimeError("Independent update changed another service")
        old, new = [r for r in before if r["service"] == "share-service"][0], [r for r in after if r["service"] == "share-service"][0]
        record["new_image_identity_verified"] = old["image_id"] != new["image_id"] and new["image_version_label"] == "e2-v2"
        if not record["new_image_identity_verified"]:
            raise RuntimeError("Share build version/image identity did not change")
        record["complete"] = True
    finally:
        probes.finish()
        record["end_epoch"] = time.time()
        record["probe_summary"] = {name: dict(requests=len([r for r in probes.rows if r["operation"] == name]),
            failures=len([r for r in probes.rows if r["operation"] == name and not r["success"]])) for name in ["login", "files", "share"]}
        failed = [r for r in probes.rows if r["operation"] == "share" and not r["success"]]
        record["share_failed_probe_interval"] = dict(first=min(r["start_epoch"] for r in failed), last=max(r["end_epoch"] for r in failed)) if failed else None
        record["downtime_resolution"] = "1 s target probing, in-flight requests can span recovery; see raw probes; no failure is not proof of zero downtime"
        save(folder / "update.json", record)
    full_smoke(ctx, folder, "post-update-smoke")
    print("Independent share update passed; " + str(record["probe_summary"]), flush=True)
    return record
