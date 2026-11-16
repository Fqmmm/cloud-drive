"""Execute E2 in a fresh project; keep E1 data and restore its running state."""
import argparse
import hashlib
import json
import platform
import re
import secrets
import shutil
import time

import psutil

from e2_support import Context, ROOT, api_engine, checksum, inventory, sanitize, save, settings, utc
from e2_basic import deployment, fixture, update_share
from e2_scale import scale


def private_environment(path, project, batch):
    values = settings(ROOT / ".env.example")
    for name in ["MYSQL_ROOT_PASSWORD", "AUTH_DB_PASSWORD", "FILE_DB_PASSWORD", "SHARE_DB_PASSWORD",
                 "MINIO_ROOT_PASSWORD", "JWT_SECRET", "INTERNAL_API_TOKEN"]:
        values[name] = secrets.token_hex(32)
    values.update(COMPOSE_PROJECT_NAME=project, APP_IMAGE_TAG=batch, HTTP_PORT="8080",
                  PUBLIC_BASE_URL="http://127.0.0.1:8080", MINIO_ROOT_USER="course-e2-storage", SHARE_APP_VERSION="e2-v1")
    with path.open("x", encoding="utf-8") as file:
        file.write("\n".join(k + "=" + v for k, v in values.items()) + "\n")


def protect_e1(ctx, root):
    original = settings(ROOT / ".env")
    project = original["COMPOSE_PROJECT_NAME"]
    before = inventory(project)
    save(root / "e1-before.json", before)
    fixtures_path = ROOT / "artifacts/e1/20261116-e1-formal/fixtures.local"
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8")) if fixtures_path.exists() else []
    base = "http://127.0.0.1:" + original["HTTP_PORT"]
    running = [row["service"] for row in before if row["status"] == "running"]
    if len(running) == 6 and fixtures:
        save(root / "e1-checksum-before.json", dict(small=checksum(base, fixtures), large=checksum(base, fixtures[:5], True)))
    if running:
        ctx.run(["docker", "compose", "--env-file", str(ROOT / ".env"), "-p", project, "stop", *running], root / "e1-stop.log")
    return dict(project=project, before=before, running=running, fixtures=fixtures, base=base)


def restore_e1(ctx, root, protected):
    if not protected:
        return
    if inventory(ctx.project):
        ctx.compose("stop", log=root / "e2-final-stop.log")
        ctx.snapshot(root, "e2-final-stopped.json")
    if protected["running"]:
        ctx.run(["docker", "compose", "--env-file", str(ROOT / ".env"), "-p", protected["project"],
                 "start", *protected["running"]], root / "e1-restore.log")
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            after = inventory(protected["project"])
            if all(r["status"] == "running" and r["health"] == "healthy" for r in after if r["service"] in protected["running"]):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Original E1 services did not become healthy")
        save(root / "e1-after.json", after)
        if {(r["service"], r["id"], r["image_id"]) for r in after} != {(r["service"], r["id"], r["image_id"]) for r in protected["before"]}:
            raise RuntimeError("Original E1 container or image identity changed")
        if len(protected["running"]) == 6 and protected["fixtures"]:
            save(root / "e1-checksum-after.json", dict(small=checksum(protected["base"], protected["fixtures"]),
                                                      large=checksum(protected["base"], protected["fixtures"][:5], True)))


def execute(ctx, root, private, extension):
    ctx.compose("config", "--quiet", log=root / "config-validation.log")
    config = json.loads(ctx.compose("config", "--format", "json")[0])
    save(root / "compose.redacted.json", json.loads(sanitize(json.dumps(config), ctx.secrets)))
    info = api_engine("/info")
    environment = dict(captured_utc=utc(), source_commit=ctx.run(["git", "rev-parse", "HEAD"])[0],
        git_status=ctx.run(["git", "status", "--porcelain"])[0], branch=ctx.run(["git", "branch", "--show-current"])[0],
        project=ctx.project, request_base_url=ctx.base, os=platform.platform(), logical_host_cpus=psutil.cpu_count(),
        host_memory_bytes=psutil.virtual_memory().total, disk_free_bytes={d: shutil.disk_usage(d).free for d in ["C:/", "D:/"]},
        docker={k: info[k] for k in ["ServerVersion", "NCPU", "MemTotal", "OperatingSystem", "Driver"]},
        compose_version=ctx.compose("version")[0], tool="Python orchestration controller, API smoke; Windows host",
        first_deployment_cache="Existing base images and BuildKit cache; no forced pull/no-cache; fresh project and empty volumes",
        storage="WSL2 Docker named volumes on unchanged Docker data disk; repository bind mounts on Windows D:",
        extension_budget="Same Docker CPU/memory budget in both replica conditions; no per-service CPU caps added",
        harness_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "scripts/deployment").glob("*.py")})
    save(root / "environment.json", environment)
    ctx.run(["docker", "system", "df"], root / "cache-before.txt")
    ctx.run(["docker", "image", "ls", "--digests", "--no-trunc", "--format", "json"], root / "images-before.jsonl")
    if inventory(ctx.project) or api_engine("/volumes").get("Volumes") and any(
            v["Name"] in [ctx.project + "_mysql_data", ctx.project + "_minio_data"] for v in api_engine("/volumes")["Volumes"]):
        raise RuntimeError("E2 first-deployment project/volumes must be new")
    deployment(ctx, root, "first-deployment", True)
    persistent = fixture(ctx, private)
    warm = []
    for repeat in range(1, 4):
        down_folder = root / ("cached-r" + str(repeat) + "-shutdown")
        down_folder.mkdir()
        before = inventory(ctx.project)
        volume_names = sorted(m["Name"] for row in before for m in row["mounts"] if m["Type"] == "volume")
        _, shutdown_seconds = ctx.compose("down", log=down_folder / "down.log")
        remaining = {v["Name"] for v in api_engine("/volumes").get("Volumes", [])}
        if not set(volume_names).issubset(remaining):
            raise RuntimeError("A retained E2 data volume disappeared")
        save(down_folder / "shutdown.json", dict(seconds=shutdown_seconds, preserved_volumes=volume_names))
        timing = deployment(ctx, root, "cached-r" + str(repeat), False, persistent)
        warm.append(timing)
    update = update_share(ctx, root, persistent)
    save(root / "basic-complete.json", dict(utc=utc(), initial_deployments=1, cached_starts=3,
        independent_share_update=True, original_file_and_share_preserved=True))
    if extension:
        scale(ctx, root, private, persistent)
    ctx.run(["docker", "system", "df"], root / "cache-after.txt")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--basic-only", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]+", args.batch):
        raise ValueError("Invalid batch identifier")
    root = ROOT / "experiments/E2" / args.batch
    private = ROOT / "artifacts/e2" / args.batch
    if min(shutil.disk_usage(d).free for d in ["C:/", "D:/"]) < 8 * 1024 ** 3:
        raise RuntimeError("E2 requires 8 GiB host free space before building")
    root.mkdir(parents=True, exist_ok=False)
    private.mkdir(parents=True, exist_ok=False)
    private_environment(private / "env.local", args.project, args.batch)
    ctx = Context(args.project, private / "env.local")
    protected, fatal = None, None
    manifest = dict(batch=args.batch, project=args.project, started_utc=utc(), extension=not args.basic_only, complete=False)
    save(root / "manifest.json", manifest)
    try:
        protected = protect_e1(ctx, root)
        execute(ctx, root, private, not args.basic_only)
        manifest["complete"] = True
    except Exception as error:
        fatal = type(error).__name__ + ": " + str(error)
        manifest["fatal"] = sanitize(fatal, ctx.secrets)
    finally:
        try:
            restore_e1(ctx, root, protected)
            manifest["original_e1_state_restored"] = True
        except Exception as error:
            manifest["restore_fatal"] = type(error).__name__
            fatal = fatal or "Restoration failed"
            manifest["complete"] = False
        manifest["finished_utc"] = utc()
        save(root / "manifest.json", manifest)
    if fatal:
        print("E2 halted: " + sanitize(fatal, ctx.secrets), flush=True)
        return 1
    print("E2 COMPLETE " + args.batch + "; original E1 services restored; P5 remains paused", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
