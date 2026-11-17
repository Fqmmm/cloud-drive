"""Run only the FR-04/05 boundary supplement against an existing isolated stack."""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import sys
import time

from support import Context, ROOT, SERVICES, digest, sanitize, save, utc

sys.path.insert(0, str(ROOT / "scripts/smoke"))
from functional import Acceptance


def validate_host_evidence(value, project):
    if value["project"] != project or value["database"]["cleanup_count"] != 0:
        raise ValueError("Host evidence must identify this project with an empty cleanup queue")
    records = value["containers"]
    if (len(records) != 6 or {r["service"] for r in records} != set(SERVICES)
            or any(r["status"] != "running" or r["health"] != "healthy" for r in records)):
        raise ValueError("Host evidence must show all six expected services healthy")
    return {r["service"]: (r["id"], r["image"]) for r in records}


def finalize(folder, ctx, evidence_path):
    """Attach a later read-only Docker capture to the HTTP-only business run."""
    from datetime import datetime
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    result = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    if manifest["status"] != "awaiting-host-verification" or result["fatal"] or not result.get("http_checks_passed"):
        raise ValueError("Only a successful pending HTTP-only supplement can be finalized")
    before = json.loads((folder / "host-before.json").read_text(encoding="utf-8"))
    after = json.loads(evidence_path.read_text(encoding="utf-8"))
    if validate_host_evidence(before, ctx.project) != validate_host_evidence(after, ctx.project):
        raise AssertionError("Original containers or images changed during supplement")
    if before["database"]["name_collation"] != after["database"]["name_collation"]:
        raise AssertionError("Database collation changed during supplement")
    if datetime.fromisoformat(after["captured_utc"].replace("Z", "+00:00")) < datetime.fromisoformat(result["ended"]):
        raise ValueError("After-capture predates completion of HTTP checks")
    save(folder / "host-after.json", after)
    manifest.update(status="complete", host_verified_utc=utc(), same_containers_and_images=True,
                    cleanup_queue_empty=True, host_evidence="direct read-only Docker commands")
    result.update(completed=True, host_verified_utc=manifest["host_verified_utc"])
    save(folder / "manifest.json", manifest)
    save(folder / "results.json", result)
    print(f"Supplement finalized: {result['passed']}/{result['total']}; original six containers healthy; cleanup queue empty")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host-before", type=Path, help="Use a direct Docker capture when nested Docker is unavailable")
    parser.add_argument("--finalize-with", type=Path, help="Attach the post-run Docker capture to a pending HTTP-only run")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,32}", args.run_id):
        parser.error("Run ID must contain only lower-case letters, digits and hyphens")
    ctx = Context(args.env_file)
    folder = ROOT / "experiments/acceptance" / args.run_id
    if args.finalize_with:
        if args.host_before:
            parser.error("Do not combine --host-before and --finalize-with")
        finalize(folder, ctx, args.finalize_with)
        return
    folder.mkdir(parents=True, exist_ok=False)
    host_before = json.loads(args.host_before.read_text(encoding="utf-8")) if args.host_before else None
    if host_before:
        validate_host_evidence(host_before, ctx.project)
        save(folder / "host-before.json", host_before)
    ctx.audit = folder / "execution.jsonl"
    manifest = dict(started=utc(), status="running", kind="supplement",
                    source_acceptance="20261117-154613", project=ctx.project,
                    scope=["FR-04 concurrent case names", "FR-05 inclusive upload limit",
                           "FR-06 boundary SHA-256", "FR-07 deletion", "FR-08 quota"],
                    implementation_sha256=digest(Path(__file__).read_bytes()),
                    acceptance_sha256=digest((ROOT / "scripts/smoke/functional.py").read_bytes()))
    save(folder / "manifest.json", manifest)

    class Suite(Acceptance):
        def compose(self, *command, sql=None):
            if host_before:
                if sql and "information_schema.COLUMNS" in sql and "active_name" in sql:
                    return host_before["database"]["name_collation"]
                raise RuntimeError("Unexpected Docker operation in HTTP-only supplement")
            return ctx.compose(*command, input_text=sql).stdout.strip()

        def api(self, path, method="GET", data=None, token=None, files=None):
            start = time.time()
            response = super().api(path, method, data, token, files)
            code = None
            if "json" in response.headers.get("Content-Type", ""):
                code = response.json().get("code")
            # No payload, headers or response body: registration/login contain
            # passwords/JWTs, and upload/download bodies are intentionally large.
            with (folder / "api-events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(start_epoch=start, end_epoch=time.time(), method=method,
                    path=path, http_status=response.status_code, business_code=code,
                    request_id=response.headers.get("X-Request-Id")), ensure_ascii=False) + "\n")
            return response

    suite = Suite(ctx.base, ctx.env_file, ctx.project)
    log, fatal = io.StringIO(), None
    try:
        if not host_before:
            ctx.ready()
            ctx.wait_cleanup()
            ctx.snapshot(folder / "before")
        else:
            manifest["execution_mode"] = "HTTP-only with separate direct Docker evidence"
            manifest["source_commit"] = ctx.run(["git", "rev-parse", "HEAD"]).stdout.strip()
            manifest["worktree_status"] = ctx.run(["git", "status", "--porcelain=v1"]).stdout
        manifest["configured_limit_bytes"] = int(ctx.values["MAX_FILE_BYTES"])
        account = "boundary_" + suite.suffix
        suite.data(suite.api("/auth/register", "POST", dict(accountName=account, password=suite.password,
            nickname="刘骐语补充验收", email=account + "@example.test", accountType="personal")))
        login = suite.data(suite.api("/auth/login", "POST", dict(accountName=account, password=suite.password)))
        suite.token = login["token"]
        suite.sensitive.append(suite.token)
        suite.owner_id = int(login["userId"])
        suite.directory = suite.data(suite.api("/directories", "POST", dict(name="边界补充验收", parentId="0"), suite.token))["id"]
        save(ctx.private / (args.run_id + "-account.json"), dict(account=account, password=suite.password,
             user_id=login["userId"], directory_id=suite.directory))
        ctx.sensitive.extend(suite.sensitive)
        with redirect_stdout(log):
            suite.directory_name_boundaries()
            suite.upload_size_boundary()
        # The original six fixtures and twelve shares are verified after the
        # supplement; no baseline records are repurposed for the new tests.
        if not host_before:
            ctx.wait_cleanup()
        ctx.verify(folder / "original-fixtures-verification")
        manifest["original_fixtures_verified"] = True
    except Exception as error:
        fatal = sanitize(type(error).__name__ + ": " + str(error), [*ctx.sensitive, *suite.sensitive])
    finally:
        try:
            suite.cleanup()
            if not host_before:
                ctx.wait_cleanup()
                ctx.ready()
                ctx.snapshot(folder / "after")
                before = json.loads((folder / "before/containers.json").read_text(encoding="utf-8"))
                after = json.loads((folder / "after/containers.json").read_text(encoding="utf-8"))
                identity = lambda records: {r["service"]: (r["id"], r["image"]) for r in records}
                if identity(before) != identity(after):
                    raise AssertionError("Supplement must not replace or rebuild original containers")
                manifest["same_containers_and_images"] = True
                ctx.logs(folder)
        except Exception as error:
            fatal = fatal or "Cleanup:" + type(error).__name__
        suite.http.close()
        manifest.update(ended=utc(), status="failed" if fatal else "awaiting-host-verification" if host_before else "complete")
        save(folder / "manifest.json", manifest)
        result = dict(started=manifest["started"], ended=manifest["ended"], kind="supplement",
            completed=fatal is None and not host_before and bool(suite.results) and all(r["status"] == "PASS" for r in suite.results),
            http_checks_passed=fatal is None and bool(suite.results) and all(r["status"] == "PASS" for r in suite.results),
            passed=sum(r["status"] == "PASS" for r in suite.results), total=len(suite.results),
            results=suite.results, fatal=fatal)
        save(folder / "results.json", result)
        (folder / "acceptance.log").write_text(sanitize(log.getvalue(), [*ctx.sensitive, *suite.sensitive]), encoding="utf-8")
        print(log.getvalue(), end="", flush=True)
        print(f"Supplement: {result['passed']}/{result['total']}; completed={result['completed']}", flush=True)
        if fatal:
            raise RuntimeError("Supplement failed; see archived results.json")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
