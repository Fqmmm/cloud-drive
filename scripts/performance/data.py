"""Explicit preparation/cleanup entry points for experiment-owned fixtures."""
import argparse
import json
from pathlib import Path
import re
import time

from common import ROOT, Client, cleanup_uploads, compose, prepare, save, sql


def cleanup_all(base, fixtures):
    for fixture in fixtures:
        client = Client(base)
        client.login(fixture)
        if client.data("/users/me")["userId"] != fixture["userId"] or not re.fullmatch(r"e1_[0-9a-f]{8}_v[0-9]{2}", fixture["account"]):
            raise RuntimeError("Fixture ownership verification failed")
    cleanup_uploads(base, fixtures)
    for fixture in fixtures:
        client = Client(base)
        client.login(fixture)
        client.data("/shares/" + fixture["shareId"], "DELETE")
        for file_id in [fixture["fileId"], fixture.get("largeFileId")]:
            if file_id:
                response = client.request("/files/" + file_id, "DELETE")[0]
                if response.status_code not in (200, 404):
                    raise RuntimeError("Fixture file cleanup failed")
        for item in client.data("/files?parentId=" + fixture["listDirectory"])["items"]:
            client.data("/directories/" + item["id"], "DELETE")
        for directory in [fixture["listDirectory"], fixture["largeDirectory"], fixture["uploadDirectory"]]:
            client.data("/directories/" + directory, "DELETE")
        if client.data("/quota")["usedBytes"] != 0:
            raise RuntimeError("Fixture quota is not zero after cleanup")
    ids = ",".join(str(int(fixture["userId"])) for fixture in fixtures)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        pending = sql("SELECT COUNT(*) FROM file_db.object_cleanup c JOIN file_db.sys_file f ON c.object_key=f.object_key "
                      f"WHERE f.user_id IN ({ids})")
        if pending == "0":
            break
        time.sleep(3)
    if pending != "0":
        raise RuntimeError("Fixture object cleanup queue has not drained")
    keys = set(sql(f"SELECT object_key FROM file_db.sys_file WHERE user_id IN ({ids}) AND object_key IS NOT NULL").splitlines())
    alias = 'mc alias set e1 http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" </dev/null >/dev/null && '
    output = compose("exec", "-T", "minio", "sh", "-c", alias + "mc ls --recursive --json e1/cloud-drive")
    present = {json.loads(line).get("key") for line in output.splitlines() if line.startswith("{")}
    if present.intersection(keys):
        raise RuntimeError("Experiment objects remain in private storage")
    active = int(sql(f"SELECT COUNT(*) FROM file_db.sys_file WHERE user_id IN ({ids}) AND is_deleted=0"))
    if active:
        raise RuntimeError("Active experiment records remain after cleanup")
    return dict(accounts_retained=len(fixtures), active_files_and_directories=active, quota_bytes=0,
                pending_cleanup=0, experiment_objects_remaining=0, unrelated_data_untouched=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "cleanup-uploads", "cleanup-all"])
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    secret = args.credentials.resolve()
    if not secret.is_relative_to((ROOT / "artifacts" / "e1").resolve()):
        raise RuntimeError("Credentials must remain inside ignored artifacts/e1")
    if args.action == "prepare":
        if secret.exists():
            raise RuntimeError("Credential file already exists; choose a new batch")
        secret.parent.mkdir(parents=True, exist_ok=True)
        prepare(args.base_url, secret, args.users)
        return
    fixtures = json.loads(secret.read_text(encoding="utf-8"))
    result = cleanup_all(args.base_url, fixtures) if args.action == "cleanup-all" else cleanup_uploads(args.base_url, fixtures)
    if args.result:
        save(args.result, result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
