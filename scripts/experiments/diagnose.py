"""Reproduce a baseline anomaly with correlated logs, without injecting faults."""
import argparse
from collections import Counter
from pathlib import Path
import re
import time

from probes import Scheduler, specifications
from support import Context, ROOT, save, sanitize, utc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,40}", args.run_id) or not 30 <= args.seconds <= 600:
        parser.error("Use a unique run ID and 30..600 seconds")
    folder = ROOT / "experiments" / "diagnostics" / args.run_id
    folder.mkdir(parents=True, exist_ok=False)
    ctx = Context(args.env_file)
    ctx.audit = folder / "execution.jsonl"
    result = dict(kind="diagnostic-not-formal", started=utc(), fault_injected=False, max_seconds=args.seconds)
    scheduler = None
    try:
        if args.rebuild:
            print("Rebuilding file/share/frontend services with diagnostic logging", flush=True)
            ctx.compose("up", "-d", "--no-deps", "--build", "file-service", "share-service", "frontend", timeout=900,
                        live_log=folder / "build.live.log")
            ctx.ready()
            ctx.reload()
        ctx.ready()
        for user in ctx.fixtures:
            ctx.login(user, minimum=args.seconds + 300)
        ctx.snapshot(folder / "before")
        scheduler = Scheduler(specifications(ctx), folder / "probe.csv").start()
        print("Probing without faults; stops at first anomaly or time limit", flush=True)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            with scheduler.lock:
                anomalies = [r for r in scheduler.rows if r["category"] != "ok"]
            if anomalies:
                result["anomaly_observed"] = True
                break
            time.sleep(.5)
        scheduler.finish()
        with scheduler.lock:
            result["rows"] = len(scheduler.rows)
            result["categories"] = dict(Counter(r["category"] for r in scheduler.rows))
            result["anomalies"] = [r for r in scheduler.rows if r["category"] != "ok"]
        scheduler = None
        ctx.verify(folder / "verification")
        result["completed"] = True
    except Exception as error:
        result.update(completed=False, fatal=sanitize(type(error).__name__ + ": " + str(error), ctx.sensitive))
        raise
    finally:
        if scheduler:
            scheduler.finish()
        ctx.snapshot(folder / "after")
        ctx.logs(folder)
        result["ended"] = utc()
        save(folder / "result.json", result)
        print("Diagnostic evidence: " + str(folder.relative_to(ROOT)), flush=True)


if __name__ == "__main__":
    main()
