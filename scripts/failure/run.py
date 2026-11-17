"""E3: stop/start faults and controlled JVM halt, three independent repeats."""
import argparse
import json
import shutil
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from probes import Scheduler, specifications
from support import Context, ROOT, digest, object_is_absent, sanitize, save, utc, validate_resume_environment

MATRIX = {"F1": "share-service", "F2": "auth-service", "F3": "file-service", "F4": "minio", "F5": "share-service", "F6": "mysql"}


class Observer:
    def __init__(self, ctx, folder):
        self.ctx, self.folder, self.stop = ctx, folder, threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        with (self.folder / "states.jsonl").open("w", encoding="utf-8") as stream:
            while not self.stop.is_set():
                try:
                    value = dict(utc=utc(), epoch=time.time(), containers=self.ctx.inventory())
                except Exception as error:
                    value = dict(utc=utc(), error=type(error).__name__)
                stream.write(json.dumps(value) + "\n")
                stream.flush()
                self.stop.wait(.5)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()


def hook(ctx, enabled, folder):
    """Override for this command only; original private config stays disabled."""
    ctx.compose("up", "-d", "--no-deps", "--force-recreate", "share-service",
                overrides={"EXPERIMENT_FAULTS_ENABLED": str(enabled).lower()})
    ctx.ready()
    ctx.reload()
    # Probe the internal route through the file-service's bash TCP transport.
    # Missing credential gives 403 when enabled and 404 when disabled; never halt.
    request = "exec 3<>/dev/tcp/share-service/8080; printf 'POST /internal/test/exit HTTP/1.1\r\nHost: share-service\r\nContent-Length: 0\r\nConnection: close\r\n\r\n' >&3; cat <&3"
    response = ctx.compose("exec", "-T", "file-service", "timeout", "10", "bash", "-c", request).stdout
    expected = "403" if enabled else "404"
    if response.splitlines()[0].split()[1] != expected:
        raise AssertionError("Fault switch route did not have expected state")
    import requests
    with requests.Session() as session:
        session.trust_env = False
        public = session.post(ctx.base + "/internal/test/exit", timeout=5).status_code
    if public != 404:
        raise AssertionError("Fault route accessible through frontend")
    save(folder / ("hook-enabled.json" if enabled else "hook-disabled.json"), dict(utc=utc(), internal_http=expected, frontend_http=public))


def storage_outage(ctx, folder, item):
    user = ctx.fixtures[0]
    quota = ctx.data("/quota", user=user)["usedBytes"]
    response = ctx.api("/files?parentId=" + user["directory"], "POST", user=user,
                       files={"file": ("must-fail.bin", b"failed upload", "application/octet-stream")}, timeout=20)
    after_upload = ctx.data("/quota", user=user)["usedBytes"]
    deleted = ctx.api("/files/" + item["id"], "DELETE", user=user)
    after_delete = ctx.data("/quota", user=user)["usedBytes"]
    queue = ctx.sql("SELECT object_key,reason,attempts FROM file_db.object_cleanup ORDER BY object_key;")
    result = dict(upload_http=response.status_code, delete_http=deleted.status_code, quota_before=quota,
        quota_after_failed_upload=after_upload, quota_after_delete=after_delete, pending=queue.splitlines(),
        passed=response.status_code == 503 and deleted.status_code == 200 and quota == after_upload
               and after_delete == quota - len(b"delete-only") and item["object_key"] in queue)
    save(folder / "minio-outage.json", result)
    if not result["passed"]:
        raise AssertionError("MinIO outage consistency check failed")


def round_run(ctx, folder, fault, repetition, warmup=30, outage=30):
    folder.mkdir(parents=True, exist_ok=False)
    ctx.audit = folder / "execution.jsonl"
    service = MATRIX[fault]
    events = []

    def event(name, **details):
        events.append(dict(name=name, epoch=time.time(), utc=utc(), **details))
        save(folder / "events.json", events)

    scheduler, stopped, failure, extra = None, False, None, None
    try:
        ctx.ready()
        if fault == "F5":
            hook(ctx, True, folder)
        for user in ctx.fixtures:
            ctx.login(user, minimum=warmup + outage + 360)
        if fault == "F4":
            user = ctx.fixtures[0]
            extra = ctx.data("/files?parentId=" + user["directory"], "POST", user=user,
                files={"file": (f"delete-r{repetition}.bin", b"delete-only", "application/octet-stream")})
            key = ctx.sql(f"SELECT object_key FROM file_db.sys_file WHERE id={int(extra['id'])};")
            extra["object_key"] = key
            ctx.wait_cleanup()
        ctx.snapshot(folder / "before")
        save(folder / "parameters.json", dict(fault=fault, repeat=repetition, warmup_seconds=warmup,
            outage_seconds=outage if fault != "F5" else None, interval_seconds=1,
            jwt_exp=ctx.fixtures[0]["exp"], jwt_refreshed_during_round=False))
        scheduler = Scheduler(specifications(ctx), folder / "probe.csv").start()
        with Observer(ctx, folder):
            event("warmup-start")
            time.sleep(warmup)
            if not scheduler.stable(events[-1]["epoch"], count=3):
                raise AssertionError("Baseline did not achieve three consecutive successful ticks")
            # All complete baseline requests must succeed, not just the last three.
            with scheduler.lock:
                if any(r["category"] != "ok" for r in scheduler.rows):
                    raise AssertionError("Baseline contains failures")
            before = ctx.inventory()
            if fault == "F5":
                row = next(r for r in before if r["service"] == service)
                from datetime import datetime
                if time.time() - datetime.fromisoformat(row["started"].replace("Z", "+00:00")).timestamp() < 10:
                    raise AssertionError("JVM has not run for at least 10 seconds")
                if row["path"] != "java":
                    raise AssertionError("Container PID 1 is not the Java exec entrypoint")
            event("t0-inject", service=service)
            injection = events[-1]["epoch"]
            if fault == "F5":
                request = ('exec 3<>/dev/tcp/share-service/8080; '
                    'printf "POST /internal/test/exit HTTP/1.1\\r\\nHost: share-service\\r\\nX-Internal-Token: %s\\r\\nContent-Length: 0\\r\\nConnection: close\\r\\n\\r\\n" "$INTERNAL_API_TOKEN" >&3; cat <&3')
                result = ctx.compose("exec", "-T", "file-service", "timeout", "10", "bash", "-c", request, check=False)
                event("hook-call-returned", exit_code=result.returncode)
                recovery_after = injection
            else:
                stopped = True
                ctx.compose("stop", service)
                event("t2-stop-confirmed")
                save(folder / "stopped.json", ctx.inventory())
                stop_clock = time.monotonic()
                if fault == "F4":
                    storage_outage(ctx, folder, extra)
                time.sleep(max(0, outage - (time.monotonic() - stop_clock)))
                event("t3-start-command")
                recovery_after = events[-1]["epoch"]
                ctx.compose("start", service)
                stopped = False
                event("start-command-returned")
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline and not scheduler.stable(recovery_after):
                time.sleep(.5)
            if not scheduler.stable(recovery_after):
                raise RuntimeError("Business recovery not observed within 240 seconds")
            event("stable-recovery-confirmed")
            after = ctx.snapshot(folder / "after")
            if fault == "F5":
                old = next(r for r in before if r["service"] == service)
                new = next(r for r in after if r["service"] == service)
                if new["id"] != old["id"] or new["restart_count"] <= old["restart_count"]:
                    raise AssertionError("Automatic restart count did not increase on the same container")
            ctx.ready()
            if extra:
                ctx.wait_cleanup()
                remaining = ctx.sql(f"SELECT COUNT(*) FROM file_db.object_cleanup WHERE object_key='{extra['object_key']}';")
                # Read-only object stat: a missing object is required, not merely an empty queue.
                shell = ('mc alias set liu http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && '
                         'mc stat --json liu/cloud-drive/' + extra["object_key"])
                absent = ctx.compose("exec", "-T", "minio", "sh", "-c", shell, check=False)
                missing = object_is_absent(absent.returncode, absent.stdout)
                save(folder / "cleanup.json", dict(queue_empty=remaining == "0", object_stat_exit=absent.returncode, object_absent=missing))
                if remaining != "0" or not missing:
                    raise AssertionError("Deleted object removal not established")
            # Refresh credentials only after all timed probes stop.
        scheduler.finish()
        scheduler = None
        ctx.verify(folder / "verification")
    except Exception as error:
        failure = sanitize(type(error).__name__ + ": " + str(error), ctx.sensitive)
        raise
    finally:
        cleanup_errors = []
        if scheduler:
            scheduler.finish()
        # Read the still-existing faulted container's logs before disabling the
        # hook recreates it; otherwise the exitCode=17 evidence would be lost.
        try:
            ctx.logs(folder)
            if events:
                since = str(int(events[0]["epoch"]))
                until = str(int(time.time()) + 1)
                ctx.run(["docker", "events", "--since", since, "--until", until,
                         "--filter", "label=com.docker.compose.project=" + ctx.project,
                         "--format", "{{json .}}"], timeout=30, private_output=folder / "docker-events.jsonl")
                if fault == "F5" and failure is None:
                    old_id = next(r["id"] for r in before if r["service"] == "share-service")
                    die_events = [json.loads(line) for line in (folder / "docker-events.jsonl").read_text(encoding="utf-8").splitlines()]
                    if not any(e.get("Action") == "die" and e.get("Actor", {}).get("ID") == old_id
                               and e["Actor"]["Attributes"].get("exitCode") == "17" for e in die_events):
                        cleanup_errors.append("missing-Docker-die-exitCode-17")
        except Exception as error:
            cleanup_errors.append("logs:" + type(error).__name__)
        if stopped:
            try:
                ctx.compose("start", service)
            except Exception as error:
                cleanup_errors.append(type(error).__name__)
        if fault == "F5":
            try:
                hook(ctx, False, folder)
            except Exception as error:
                cleanup_errors.append("fault-switch:" + type(error).__name__)
        save(folder / "result.json", dict(fault=fault, repeat=repetition, completed=failure is None and not cleanup_errors,
             fatal=failure, cleanup_errors=cleanup_errors, ended=utc()))
        if cleanup_errors and failure is None:
            raise RuntimeError("Round cleanup incomplete; see result.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--include-mysql", action="store_true")
    parser.add_argument("--pilot", action="store_true", help="Short run; never counted as formal data")
    parser.add_argument("--continue-from", help="Inherit verified completed rounds, with image/probe equality checks")
    args = parser.parse_args()
    if not __import__("re").fullmatch(r"[a-zA-Z0-9-]+", args.run_id):
        parser.error("Invalid run id")
    folder = ROOT / "experiments" / "E3" / args.run_id
    folder.mkdir(parents=True, exist_ok=False)
    ctx = Context(args.env_file)
    faults = list(MATRIX) if args.include_mysql else list(MATRIX)[:5]
    plan = dict(started=utc(), kind="pilot" if args.pilot else "formal", faults=faults, repeats=1 if args.pilot else 3,
                completed=[], status="running")
    save(folder / "manifest.json", plan)
    try:
        if args.continue_from:
            if args.pilot or not __import__("re").fullmatch(r"[a-zA-Z0-9-]+", args.continue_from):
                raise ValueError("Continuation requires formal, uniquely named source data")
            parent = ROOT / "experiments" / "E3" / args.continue_from
            old = json.loads((parent / "manifest.json").read_text(encoding="utf-8"))
            if old["kind"] != "formal" or old["repeats"] != 3 or old["faults"] != faults or old["status"] != "failed":
                raise ValueError("Source is not a compatible interrupted formal matrix")
            ctx.ready()
            previous = json.loads((parent / "environment/containers.json").read_text(encoding="utf-8"))
            environment = json.loads((parent / "environment/environment.json").read_text(encoding="utf-8"))
            source = json.loads((parent / "environment/source-sha256.json").read_text(encoding="utf-8"))
            probe_hash = next(r["sha256"] for r in source if r["path"].replace("\\", "/") == "scripts/experiments/probes.py")
            validate_resume_environment(environment, previous, ctx.inventory(), probe_hash,
                digest((ROOT / "scripts/experiments/probes.py").read_bytes()), ctx.project)
            ctx.verify(folder / "resume-verification")
            inherited = []
            allowed = {f"{fault}-r{repeat}" for fault in faults for repeat in range(1, 4)}
            for name in old["completed"]:
                result = json.loads((parent / name / "result.json").read_text(encoding="utf-8"))
                if name not in allowed or not result["completed"]:
                    raise ValueError("Cannot inherit an incomplete or unknown round")
                shutil.copytree(parent / name, folder / name)
                entries = [dict(path=str(p.relative_to(parent / name)).replace("\\", "/"), sha256=digest(p.read_bytes()))
                           for p in sorted((parent / name).rglob("*")) if p.is_file()]
                if any(digest((folder / name / entry["path"]).read_bytes()) != entry["sha256"] for entry in entries):
                    raise AssertionError("Inherited evidence bytes changed")
                inherited.append(dict(round=name, source=str((parent / name).relative_to(ROOT)), files=entries))
                plan["completed"].append(name)
            plan.update(continued_from=args.continue_from, inherited_rounds=list(old["completed"]),
                        continuation_reason="mc object-not-found JSON validator corrected; app images/probe implementation unchanged")
            save(folder / "inherited-evidence.json", inherited)
            save(folder / "manifest.json", plan)
        ctx.snapshot(folder / "environment")
        for fault in faults:
            for repeat in range(1, plan["repeats"] + 1):
                name = f"{fault}-r{repeat}"
                if name in plan["completed"]:
                    continue
                print("E3 " + name, flush=True)
                round_run(ctx, folder / name, fault, repeat, warmup=12 if args.pilot else 30, outage=5 if args.pilot else 30)
                plan["completed"].append(name)
                save(folder / "manifest.json", plan)
        ctx.ready()
        ctx.wait_cleanup()
        plan["status"] = "complete"
    except Exception as error:
        plan.update(status="failed", error=sanitize(type(error).__name__ + ": " + str(error), ctx.sensitive))
        raise
    finally:
        plan["ended"] = utc()
        save(folder / "manifest.json", plan)


if __name__ == "__main__":
    main()
