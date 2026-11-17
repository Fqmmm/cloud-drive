"""Read-only audit of the review fixes, against frozen evidence and raw probes."""
import csv
import json
from pathlib import Path
import re

from support import Context, ROOT, digest, save, utc
from supplement import validate_host_evidence


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    e3 = ROOT / "experiments/E3/20261117-154613-c1"
    e4 = ROOT / "experiments/E4/20261117-154613-c1"
    rev = e3 / "analysis-revisions/20261117-failure-window-v2"
    supplement = ROOT / "experiments/acceptance/20261117-review-supp2"
    checks = {}
    previous = read(rev / "evidence-index-before.json")["files"]
    changed = {"experiments/E3/20261117-154613-c1/impact.csv",
               "experiments/E3/20261117-154613-c1/figures/provenance.json",
               "experiments/E4/20261117-154613-c1/evidence-index.json",
               "experiments/E4/20261117-154613-c1/delivery-audit.json"}
    for item in previous:
        if item["path"] not in changed:
            assert digest((ROOT / item["path"]).read_bytes()) == item["sha256"], item["path"]
    checks["previous_index_entries_verified_unchanged"] = sum(x["path"] not in changed for x in previous)
    data = {}
    corrected = 0
    for entry in rows(e3 / "impact.csv"):
        case = e3 / f"{entry['fault']}-r{entry['repeat']}"
        if case not in data:
            data[case] = rows(case / "probe.csv")
        events = {r["name"]: r["epoch"] for r in read(case / "events.json")}
        records = [r for r in data[case] if r["probe"] == entry["probe"]]
        ordered = sorted([r for r in records if float(r["planned_epoch"]) >= events.get("t3-start-command", events["t0-inject"])], key=lambda r: int(r["tick"]))
        recovery = None
        for i in range(len(ordered) - 2):
            group = ordered[i:i+3]
            if all(r["category"] == "ok" for r in group) and int(group[-1]["tick"]) - int(group[0]["tick"]) == 2:
                recovery = float(group[0]["sent_epoch"])
                break
        assert recovery is not None and abs(recovery - float(entry["t5"])) < 1e-6
        failures = [r for r in records if r["sent_epoch"] and float(r["sent_epoch"]) >= events["t0-inject"] and r["category"] != "ok"]
        if failures:
            first_return = min(float(r["returned_epoch"]) for r in failures)
            assert abs(float(entry["failure_window_seconds"]) - max(0, recovery - first_return)) < 1e-6
            corrected += 1
        else:
            assert entry["failure_window_seconds"] == ""
    checks["revised_failure_windows_independently_verified"] = corrected
    assert corrected == 60
    revision = read(rev / "revision.json")
    assert revision["changed_rows"] == 60 and revision["analyzer_after_sha256"] == digest((ROOT / "scripts/experiments/analyze.py").read_bytes())
    assert all(digest((e3 / path).read_bytes()) == value for path, value in revision["raw_probe_sha256"].items())
    checks["raw_probe_files_unchanged"] = len(revision["raw_probe_sha256"])
    provenance = read(e3 / "figures/provenance.json")
    for item in provenance["inputs"] + provenance["figures"]:
        assert digest((ROOT / item["path"]).read_bytes()) == item["sha256"]
    checks["figure_artifacts_verified"] = len(provenance["figures"])
    result, manifest = read(supplement / "results.json"), read(supplement / "manifest.json")
    assert result["completed"] and result["passed"] == result["total"] == 9 and all(r["status"] == "PASS" for r in result["results"])
    assert manifest["status"] == "complete" and manifest["original_fixtures_verified"]
    assert manifest["implementation_sha256"] == digest((ROOT / "scripts/experiments/supplement.py").read_bytes())
    assert manifest["acceptance_sha256"] == digest((ROOT / "scripts/smoke/functional.py").read_bytes())
    project = manifest["project"]
    assert validate_host_evidence(read(supplement / "host-before.json"), project) == validate_host_evidence(read(supplement / "host-after.json"), project)
    cases = {r["case"]: r for r in result["results"]}
    assert cases["file exactly at configured limit uploads successfully"]["input"]["bytes"] == 104857600
    assert cases["exact-limit download size and SHA-256 match source"]["actual"]["sha256"] == cases["exact-limit download size and SHA-256 match source"]["expected"]["sha256"]
    names = cases["simultaneous Case and case match the deployed name rule"]["actual"]["matching_names"]
    assert set(names) == {"Case", "case"} and names["Case"] != names["case"]
    checks["supplementary_checks"] = 9
    downloads = rows(supplement / "original-fixtures-verification/checksums.csv")
    permissions = read(supplement / "original-fixtures-verification/permissions.json")
    assert len(downloads) == 18 and all(r["passed"] == "True" and r["source_sha256"] == r["download_sha256"] for r in downloads)
    assert len(permissions) == 6 and all(r["passed"] for r in permissions)
    checks["original_fixture_downloads_reverified"] = len(downloads)
    checks["original_fixture_permissions_reverified"] = len(permissions)
    index = read(e4 / "evidence-index.json")["files"]
    ctx = Context(ROOT / "artifacts/liu/20261117-154613/.env")
    secret_values = [v.encode() for v in ctx.sensitive if v and len(v) >= 12]
    account = read(ctx.private / "20261117-review-supp2-account.json")
    secret_values.append(account["password"].encode())
    for item in index:
        content = (ROOT / item["path"]).read_bytes()
        assert len(content) == item["bytes"] and digest(content) == item["sha256"], item["path"]
        assert not any(s in content for s in secret_values), "Private credential in " + item["path"]
        assert not re.search(rb'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"extractCode"\s*:\s*"[0-9]{6}"', content)
    checks["current_index_hashes_and_privacy_verified"] = len(index)
    checks["prior_delivery_audit_passed"] = read(e4 / "delivery-audit.json")["completed"]
    outcome = dict(audited_utc=utc(), completed=True, checks=checks,
        note="Independent raw-data recomputation and direct Docker captures; original Git commit remains 1f3eb29 until this fix is committed")
    save(ROOT / "experiments/tool-validation/20261117-liu-review-fix/audit.json", outcome)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
