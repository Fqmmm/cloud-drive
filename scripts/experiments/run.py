"""Prepare, build, accept and run Liu Qiyu's experiments from one entrypoint."""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from support import Context, ROOT, init_env, sanitize, save, utc


def acceptance(ctx, folder):
    sys.path.insert(0, str(ROOT / "scripts" / "smoke"))
    from functional import Acceptance
    folder.mkdir(parents=True, exist_ok=False)
    ctx.audit = folder / "execution.jsonl"
    ctx.snapshot(folder / "environment")
    suite = Acceptance(ctx.base, ctx.env_file, ctx.project)
    output, fatal = io.StringIO(), None
    began = utc()
    try:
        with redirect_stdout(output):
            suite.accounts()
            suite.directories_and_files()
            suite.sharing()
            suite.outage()
            suite.deletion()
            suite.browser()
    except Exception as error:
        fatal = type(error).__name__ + ": " + str(error)
    finally:
        with redirect_stdout(output):
            try:
                suite.cleanup()
            except Exception as error:
                fatal = fatal or "Cleanup:" + type(error).__name__
        sensitive = [*ctx.sensitive, *suite.sensitive]
        ctx.sensitive.extend(suite.sensitive)
        requirements = {f"FR-{n:02}" for n in range(1, 13)}
        covered = {r["requirement"] for r in suite.results if r["status"] == "PASS"}
        report = dict(started=began, ended=utc(), source_commit=ctx.run(["git", "rev-parse", "HEAD"]).stdout.strip(),
            mode="API+three-isolated-browser-contexts+real-file/minio-outages", project=ctx.project,
            results=suite.results, passed=sum(r["status"] == "PASS" for r in suite.results), total=len(suite.results),
            requirements_covered=sorted(covered), fatal=sanitize(fatal or "", sensitive) or None,
            completed=not fatal and all(r["status"] == "PASS" for r in suite.results) and covered == requirements)
        save(folder / "results.json", report)
        (folder / "acceptance.log").write_text(sanitize(output.getvalue(), sensitive), encoding="utf-8")
        ctx.logs(folder)
        suite.http.close()
    if not report["completed"]:
        raise RuntimeError("Functional acceptance incomplete; see results.json")
    print(f"Acceptance: {report['passed']}/{report['total']} checks passed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "build", "acceptance", "prepare", "all"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--restore-port", type=int, default=8089)
    parser.add_argument("--include-mysql", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,24}", args.run_id) or not 1024 <= args.port <= 65535:
        parser.error("Run ID: 1..24 lower-case letters/digits/hyphens; port: 1024..65535")
    private = ROOT / "artifacts" / "liu" / args.run_id
    env = private / ".env"
    if args.command == "init" or args.command == "all" and not env.exists():
        init_env(env, "cloud-drive-liu-" + args.run_id, args.port)
    ctx = Context(env)
    if args.command in ("build", "all"):
        folder = ROOT / "experiments" / "acceptance" / (args.run_id + "-deployment")
        folder.mkdir(parents=True, exist_ok=False)
        ctx.audit = folder / "execution.jsonl"
        manifest = dict(started=utc(), status="running")
        try:
            ctx.run(["docker", "version"])
            ctx.compose("config", "--quiet")
            ctx.compose("up", "-d", "--build", "--wait", "--wait-timeout", "300", timeout=3600)
            ctx.ready()
            ctx.snapshot(folder)
            manifest["status"] = "complete"
        except Exception as error:
            manifest.update(status="failed", error=sanitize(type(error).__name__ + ": " + str(error), ctx.sensitive))
            raise
        finally:
            manifest["ended"] = utc()
            save(folder / "manifest.json", manifest)
    if args.command in ("acceptance", "all"):
        acceptance(ctx, ROOT / "experiments" / "acceptance" / args.run_id)
    if args.command in ("prepare", "all"):
        folder = ROOT / "experiments" / "datasets" / args.run_id
        folder.mkdir(parents=True, exist_ok=False)
        ctx.audit = folder / "execution.jsonl"
        manifest = dict(started=utc(), status="running", files_per_user=3, users=2,
                        bytes_per_file=[1024, 1048576, 20971520], shares_per_file=2,
                        generation="random.Random(20261117 + size).randbytes(size)", python=sys.version)
        try:
            ctx.prepare(folder)
            ctx.snapshot(folder / "environment")
            manifest["status"] = "complete"
        except Exception as error:
            manifest.update(status="failed", error=sanitize(type(error).__name__ + ": " + str(error), ctx.sensitive))
            raise
        finally:
            manifest["ended"] = utc()
            save(folder / "manifest.json", manifest)
    if args.command == "all":
        e3 = [sys.executable, "-u", "scripts/failure/run.py", "--env-file", str(env), "--run-id", args.run_id]
        if args.include_mysql:
            e3.append("--include-mysql")
        e4 = [sys.executable, "-u", "scripts/persistence/run.py", "--env-file", str(env), "--run-id", args.run_id,
              "--restore-port", str(args.restore_port)]
        if args.restore:
            e4.append("--restore")
        # Exit immediately on an incomplete stage. Failed batches stay immutable.
        for command in (e3, e4):
            subprocess.run(command, cwd=ROOT, check=True)
        subprocess.run([sys.executable, "scripts/experiments/analyze.py", "--run-id", args.run_id], cwd=ROOT, check=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
