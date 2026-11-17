"""E4: three MySQL and three MinIO replacements, retaining the same volumes."""
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
from support import Context, ROOT, digest, retained_volumes, sanitize, save, utc


def object_identity(path):
    return sorted((item["key"], item["size"]) for item in json.loads(path.read_text(encoding="utf-8")))


def compare_metadata(baseline, actual):
    return {name: baseline[name] == actual[name] for name in baseline}


def round_run(ctx, folder, baseline, objects, service, repeat):
    folder.mkdir(parents=True, exist_ok=False)
    ctx.audit = folder / "execution.jsonl"
    result = dict(service=service, repeat=repeat, started=utc(), completed=False, steps=[])

    def step(name, action):
        began = time.time()
        value = action()
        result["steps"].append(dict(name=name, start_epoch=began, end_epoch=time.time(), seconds=time.time() - began))
        save(folder / "result.json", result)
        return value

    try:
        ctx.ready()
        ctx.wait_cleanup()
        before = step("before-snapshot", lambda: ctx.snapshot(folder / "before"))
        result["backup"] = step("database-backup", lambda: ctx.backup(f"E4-{service}-r{repeat}"))
        step("replace-infrastructure", lambda: ctx.compose("up", "-d", "--no-deps", "--force-recreate", service))
        # Fixed manual recovery is part of E4, never labelled automatic recovery.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            row = next(r for r in ctx.inventory() if r["service"] == service)
            if row["health"] == "healthy":
                break
            time.sleep(1)
        else:
            raise RuntimeError("Replacement infrastructure did not become ready")
        step("manual-application-restart", lambda: ctx.compose("restart", "auth-service", "file-service", "share-service"))
        step("wait-six-healthy", ctx.ready)
        step("nginx-config-test-and-reload", ctx.reload)
        after = step("after-snapshot", lambda: ctx.snapshot(folder / "after"))
        result["container_changed_volume_retained"] = retained_volumes(before, after, service)
        if not result["container_changed_volume_retained"]:
            raise AssertionError("New container did not retain the original named volume")
        step("all-downloads-and-permissions", lambda: ctx.verify(folder / "verification"))
        actual = step("readonly-metadata-and-object-inventory", lambda: ctx.metadata(folder / "verification"))
        result["metadata_equal"] = compare_metadata(baseline, actual)
        result["object_keys_sizes_equal"] = object_identity(folder / "verification" / "objects.json") == objects
        if not all(result["metadata_equal"].values()) or not result["object_keys_sizes_equal"]:
            raise AssertionError("Metadata/object inventory differs from the frozen baseline")
        result["completed"] = True
    except Exception as error:
        result["fatal"] = sanitize(type(error).__name__ + ": " + str(error), ctx.sensitive)
        raise
    finally:
        result["ended"] = utc()
        save(folder / "result.json", result)
        ctx.logs(folder)


def deletion(ctx, folder):
    """An extra file, with its own share, never one of the frozen samples."""
    folder.mkdir(parents=True, exist_ok=False)
    user = ctx.fixtures[0]
    before = ctx.data("/quota", user=user)["usedBytes"]
    file = ctx.data("/files?parentId=" + user["directory"], "POST", user=user,
                    files={"file": ("extra-delete.bin", b"extra-delete", "application/octet-stream")})
    share = ctx.data("/shares", "POST", user=user, data=dict(fileId=file["id"], accessType=0, expireDays=7))
    ctx.sensitive.append(share["shareToken"])
    key = ctx.sql(f"SELECT object_key FROM file_db.sys_file WHERE id={int(file['id'])};")
    uploaded = ctx.data("/quota", user=user)["usedBytes"]
    first = ctx.api("/files/" + file["id"], "DELETE", user=user).status_code
    second = ctx.api("/files/" + file["id"], "DELETE", user=user).status_code
    after = ctx.data("/quota", user=user)["usedBytes"]
    response = ctx.api("/s/" + share["shareToken"] + "/download", "POST", data={})
    listing = ctx.data("/files?parentId=" + user["directory"], user=user)["items"]
    ctx.wait_cleanup()
    alias = 'mc alias set liu http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && '
    stat = ctx.compose("exec", "-T", "minio", "sh", "-c", alias + "mc stat --json liu/cloud-drive/" + key, check=False)
    result = dict(file_id=file["id"], object_key=key, first_delete_http=first, repeated_delete_http=second,
        quota_before=before, quota_uploaded=uploaded, quota_after=after, old_share_http=response.status_code,
        old_share_business=response.json().get("code"), active_list_absent=file["id"] not in {v["id"] for v in listing},
        object_stat_exit=stat.returncode, object_absent=stat.returncode != 0 and "NoSuchKey" in stat.stdout)
    result["passed"] = (first == 200 and second == 404 and after == before and uploaded == before + len(b"extra-delete")
        and result["active_list_absent"] and result["object_absent"] and response.status_code == 404
        and result["old_share_business"] == "SHARE_FILE_UNAVAILABLE")
    save(folder / "result.json", result)
    if not result["passed"]:
        raise AssertionError("Permanent deletion consistency failed")


def restore_extension(ctx, folder, port):
    """A consistent stopped-write backup, restored into a different project/new volumes."""
    import shutil
    folder.mkdir(parents=True, exist_ok=False)
    ctx.audit = folder / "execution.jsonl"
    result = dict(started=utc(), completed=False, manual_restore=True)
    backup_dir = ctx.private / "consistent-backup"
    backup_dir.mkdir(exist_ok=False)
    destination = None
    try:
        ctx.wait_cleanup()
        ctx.metadata(folder)
        # Stop frontend and writers before taking BOTH halves of the backup.
        ctx.compose("stop", "frontend", "auth-service", "file-service", "share-service")
        began = time.time()
        result["write_pause_epoch"] = began
        result["database"] = ctx.backup("consistent-backup/database")
        alias = 'mc alias set liu http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && '
        ctx.compose("exec", "-T", "minio", "sh", "-c", alias + "mc mirror --overwrite liu/cloud-drive /tmp/liu-consistent-objects")
        ctx.compose("cp", "minio:/tmp/liu-consistent-objects", str(backup_dir / "objects"))
        inventory = [dict(path=str(p.relative_to(backup_dir)), bytes=p.stat().st_size, sha256=digest(p.read_bytes()))
                     for p in sorted((backup_dir / "objects").rglob("*")) if p.is_file()]
        save(folder / "backup-object-sha256.json", inventory)
        result["backup_seconds"] = time.time() - began
        result["backup_bytes"] = result["database"]["bytes"] + sum(r["bytes"] for r in inventory)
        ctx.compose("start", "auth-service", "file-service", "share-service", "frontend")
        ctx.ready()
        ctx.reload()
        result["original_resumed_epoch"] = time.time()
        target_project = ctx.project + "-restore"
        from support import validate_project
        validate_project(target_project)
        target_private = ctx.private / "restore"
        target_private.mkdir(exist_ok=False)
        env = ctx.env_file.read_text(encoding="utf-8")
        for key, value in dict(COMPOSE_PROJECT_NAME=target_project, HTTP_PORT=str(port),
                               PUBLIC_BASE_URL=f"http://127.0.0.1:{port}", EXPERIMENT_FAULTS_ENABLED="false").items():
            env = re.sub(r"(?m)^" + key + r"=.*$", key + "=" + value, env)
        (target_private / ".env").write_text(env, encoding="utf-8")
        shutil.copyfile(ctx.private / "fixtures.json", target_private / "fixtures.json")
        destination = Context(target_private / ".env")
        destination.audit = folder / "restore-execution.jsonl"
        if destination.inventory():
            raise RuntimeError("Restore project is not empty")
        result["restore_started_epoch"] = time.time()
        destination.compose("up", "-d", "--wait", "mysql", "minio")
        destination.compose("exec", "-T", "mysql", "bash", "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -u root --default-character-set=utf8mb4',
            input_text=(backup_dir / "database.sql").read_text(encoding="utf-8"))
        destination.compose("cp", str(backup_dir / "objects"), "minio:/tmp/liu-restore-objects")
        destination.compose("exec", "-T", "minio", "sh", "-c", alias +
            "mc mb --ignore-existing liu/cloud-drive && mc anonymous set none liu/cloud-drive && mc mirror --overwrite /tmp/liu-restore-objects liu/cloud-drive")
        destination.compose("up", "-d", "--wait", "--wait-timeout", "300")
        destination.ready()
        destination.reload()
        destination.snapshot(folder / "restored")
        destination.verify(folder / "verification")
        actual = destination.metadata(folder / "verification")
        original = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        result["metadata_equal"] = compare_metadata(original, actual)
        result["object_keys_sizes_equal"] = object_identity(folder / "objects.json") == object_identity(folder / "verification" / "objects.json")
        original_mounts = {m["Name"] for r in ctx.inventory() for m in r["mounts"] if m["Type"] == "volume"}
        restored_mounts = {m["Name"] for r in destination.inventory() for m in r["mounts"] if m["Type"] == "volume"}
        result["new_volumes"] = bool(restored_mounts) and original_mounts.isdisjoint(restored_mounts)
        result["restore_seconds"] = time.time() - result["restore_started_epoch"]
        result["completed"] = all(result["metadata_equal"].values()) and result["object_keys_sizes_equal"] and result["new_volumes"]
        if not result["completed"]:
            raise AssertionError("Restored dataset/volume evidence differs")
    except Exception as error:
        result["fatal"] = sanitize(type(error).__name__ + ": " + str(error), ctx.sensitive)
        raise
    finally:
        ctx.compose("start", "auth-service", "file-service", "share-service", "frontend")
        ctx.ready()
        ctx.reload()
        if destination:
            destination.logs(folder)
        result["ended"] = utc()
        save(folder / "result.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--restore", action="store_true", help="Also restore consistent backups to a new project")
    parser.add_argument("--restore-port", type=int, default=8089)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9-]+", args.run_id):
        parser.error("Invalid run id")
    folder = ROOT / "experiments" / "E4" / args.run_id
    folder.mkdir(parents=True, exist_ok=False)
    ctx = Context(args.env_file)
    ctx.audit = folder / "execution.jsonl"
    manifest = dict(started=utc(), completed=[], status="running", repeat=3, backup_restore=args.restore)
    save(folder / "manifest.json", manifest)
    try:
        ctx.ready()
        ctx.wait_cleanup()
        ctx.snapshot(folder / "environment")
        ctx.verify(folder / "baseline")
        baseline = ctx.metadata(folder / "baseline")
        objects = object_identity(folder / "baseline" / "objects.json")
        for service in ("mysql", "minio"):
            for repeat in range(1, 4):
                name = f"{service}-r{repeat}"
                print("E4 " + name, flush=True)
                round_run(ctx, folder / name, baseline, objects, service, repeat)
                manifest["completed"].append(name)
                save(folder / "manifest.json", manifest)
        deletion(ctx, folder / "deletion")
        if args.restore:
            restore_extension(ctx, folder / "backup-restore", args.restore_port)
        ctx.ready()
        ctx.wait_cleanup()
        ctx.verify(folder / "final")
        manifest["status"] = "complete"
    except Exception as error:
        manifest.update(status="failed", error=sanitize(type(error).__name__ + ": " + str(error), ctx.sensitive))
        raise
    finally:
        manifest["ended"] = utc()
        save(folder / "manifest.json", manifest)


if __name__ == "__main__":
    main()
