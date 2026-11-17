"""Independent read-only verification of actual final delivery records."""
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json

ROOT = Path.cwd()
E3 = ROOT / "experiments/E3/20261117-154613-c1"
E4 = ROOT / "experiments/E4/20261117-154613-c1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


manifest = read(E3 / "manifest.json")
assert manifest["status"] == "complete" and len(manifest["completed"]) == 15
checks = dict(e3_rounds=15, e3_download_checks=0, e3_permission_checks=0, automatic_restarts=0,
              e4_rebuilds=0, e4_download_checks=0, e4_permission_checks=0)
for name in manifest["completed"]:
    folder = E3 / name
    result = read(folder / "result.json")
    assert result["completed"] and not result.get("cleanup_errors")
    downloads = rows(folder / "verification/checksums.csv")
    permissions = read(folder / "verification/permissions.json")
    assert len(downloads) == 18 and all(row["passed"] == "True" for row in downloads)
    assert len(permissions) == 6 and all(row["passed"] for row in permissions)
    checks["e3_download_checks"] += len(downloads)
    checks["e3_permission_checks"] += len(permissions)
    if name.startswith("F4"):
        assert read(folder / "minio-outage.json")["passed"]
        cleanup = read(folder / "cleanup.json")
        assert cleanup["queue_empty"] and cleanup["object_absent"]
    if name.startswith("F5"):
        before = next(r for r in read(folder / "before/containers.json") if r["service"] == "share-service")
        after = next(r for r in read(folder / "after/containers.json") if r["service"] == "share-service")
        assert before["id"] == after["id"] and before["restart_count"] == 0 and after["restart_count"] == 1
        events = [json.loads(line) for line in (folder / "docker-events.jsonl").read_text(encoding="utf-8").splitlines()]
        assert any(event.get("Action") == "die" and event.get("Actor", {}).get("ID") == before["id"]
                   and event["Actor"]["Attributes"].get("exitCode") == "17" for event in events)
        disabled = read(folder / "hook-disabled.json")
        assert disabled["internal_http"] == "404" and disabled["frontend_http"] == 404
        checks["automatic_restarts"] += 1

inherited = read(E3 / "inherited-evidence.json")
assert len(inherited) == 9
for case in inherited:
    source = ROOT / case["source"].replace("\\", "/")
    for item in case["files"]:
        assert sha(source / item["path"]) == item["sha256"] == sha(E3 / case["round"] / item["path"])
checks["inherited_rounds_byte_identical"] = len(inherited)
fingerprint = lambda records: {(r["user_id"], r["file_id"], r["source_bytes"], r["source_sha256"]) for r in records}
assert fingerprint(rows(E3 / "resume-verification/checksums.csv")) == fingerprint(rows(E3 / "F1-r1/verification/checksums.csv"))
checks["original_sample_ids_and_hashes_retained"] = True

baseline = read(E4 / "baseline/metadata.json")
for name in read(E4 / "manifest.json")["completed"]:
    folder = E4 / name
    result = read(folder / "result.json")
    assert result["completed"] and result["container_changed_volume_retained"] and result["object_keys_sizes_equal"]
    assert all(result["metadata_equal"].values()) and read(folder / "verification/metadata.json") == baseline
    checks["e4_rebuilds"] += 1
for name in ["baseline", "mysql-r1/verification", "mysql-r2/verification", "mysql-r3/verification",
             "minio-r1/verification", "minio-r2/verification", "minio-r3/verification", "final", "backup-restore/verification"]:
    downloads = rows(E4 / name / "checksums.csv")
    permissions = read(E4 / name / "permissions.json")
    assert len(downloads) == 18 and all(row["passed"] == "True" for row in downloads)
    assert len(permissions) == 6 and all(row["passed"] for row in permissions)
    checks["e4_download_checks"] += len(downloads)
    checks["e4_permission_checks"] += len(permissions)
assert read(E4 / "deletion/result.json")["passed"]
restore = read(E4 / "backup-restore/result.json")
assert restore["completed"] and restore["new_volumes"] and restore["object_keys_sizes_equal"] and all(restore["metadata_equal"].values())
assert read(E4 / "backup-restore/metadata.json") == read(E4 / "backup-restore/verification/metadata.json")
volumes = lambda data: {m["Name"] for r in data for m in r["mounts"] if m["Type"] == "volume"}
assert volumes(read(E4 / "environment/containers.json")).isdisjoint(volumes(read(E4 / "backup-restore/restored/containers.json")))
private = ROOT / "artifacts/liu/20261117-154613/consistent-backup"
assert sha(private / "database.sql") == restore["database"]["sha256"]
objects = read(E4 / "backup-restore/backup-object-sha256.json")
assert len(objects) == 6
for item in objects:
    assert sha(private / item["path"].replace("\\", "/")) == item["sha256"]
checks.update(deletion_consistency=True, independent_restore=True, private_backup_hashes_verified=True)

figures = read(E3 / "figures/provenance.json")
assert sha(ROOT / "scripts/experiments/figures.py") == figures["generator_sha256"]
for item in figures["inputs"] + figures["figures"]:
    assert sha(ROOT / item["path"].replace("\\", "/")) == item["sha256"]
checks["figures_verified"] = len(figures["figures"])
result = dict(audited_utc=datetime.now(timezone.utc).isoformat(), completed=True, checks=checks,
              measured_service_state_as_of=read(E4 / "manifest.json")["ended"],
              note="Audit of archived records; does not claim a live Docker inspection at audit time")
(E4 / "delivery-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(result, ensure_ascii=False, indent=2))
