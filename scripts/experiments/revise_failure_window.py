"""Revise derived failure windows while preserving raw probes and prior values."""
import argparse
import csv
import json
from pathlib import Path

from analyze import report_e3
from support import ROOT, csv_write, digest, save, utc


def records(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def text_digest(path):
    return digest(path.read_bytes().replace(b"\r\n", b"\n"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not __import__("re").fullmatch(r"[a-z0-9-]{1,24}", args.run_id):
        parser.error("Invalid run ID")
    folder = ROOT / "experiments/E3" / args.run_id
    revision = folder / "analysis-revisions/20261117-failure-window-v2"
    if (revision / "revision.json").exists():
        raise ValueError("Revision already exists; do not overwrite the prior audit")
    before = records(revision / "impact-before.csv")
    raw = {str(p.relative_to(folder)).replace("\\", "/"): digest(p.read_bytes())
           for p in folder.glob("F*-r*/probe.csv")}
    recovery_before = text_digest(folder / "recovery.csv")
    summary_before = text_digest(folder / "recovery-summary.csv")
    report_e3(folder, ROOT / "docs/exp/E3-results.md")
    after = records(folder / "impact.csv")
    if len(before) != len(after):
        raise AssertionError("Impact row count changed")
    differences = []
    for old, new in zip(before, after):
        if {k: v for k, v in old.items() if k != "failure_window_seconds"} != {k: v for k, v in new.items() if k != "failure_window_seconds"}:
            raise AssertionError("A field other than failure_window_seconds changed")
        if old["failure_window_seconds"] != new["failure_window_seconds"]:
            differences.append(dict(fault=new["fault"], repeat=new["repeat"], probe=new["probe"],
                previous_seconds=float(old["failure_window_seconds"]), revised_seconds=float(new["failure_window_seconds"]),
                reduction_seconds=float(old["failure_window_seconds"]) - float(new["failure_window_seconds"])))
    if (recovery_before != text_digest(folder / "recovery.csv")
            or summary_before != text_digest(folder / "recovery-summary.csv")):
        raise AssertionError("Recovery outputs changed")
    if any(digest((folder / path).read_bytes()) != value for path, value in raw.items()):
        raise AssertionError("Raw probes changed")
    csv_write(revision / "differences.csv", differences)
    for name in ("impact.csv", "recovery.csv", "recovery-summary.csv"):
        path = folder / name
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    provenance_path = folder / "figures/provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    input_record = next(r for r in provenance["inputs"] if r["path"].endswith("/impact.csv"))
    old_input_hash = input_record["sha256"]
    input_record["sha256"] = digest((folder / "impact.csv").read_bytes())
    # Figures only consume success counts/rates and recovery times; all such
    # fields were compared above. Preserve their original exact PNG/PDF bytes.
    provenance.setdefault("analysis_revisions", []).append(dict(utc=utc(),
        reason="failure_window_seconds now starts at first failed response receipt",
        previous_impact_sha256=old_input_hash, revised_impact_sha256=input_record["sha256"],
        figure_inputs_used_for_plotting_unchanged=True, figure_bytes_preserved=True,
        previous_provenance="analysis-revisions/20261117-failure-window-v2/figures-provenance-before.json"))
    save(provenance_path, provenance)
    save(revision / "revision.json", dict(revised_utc=utc(), status="complete", run_id=args.run_id,
        metric="failure_window_seconds", previous_formula="t5 - first_failed_sent_epoch",
        revised_formula="max(0, t5 - first_failed_returned_epoch)", changed_rows=len(differences),
        maximum_reduction_seconds=max((r["reduction_seconds"] for r in differences), default=0),
        analyzer_before_sha256=digest((revision / "analyze-before.py").read_bytes()),
        analyzer_after_sha256=digest((ROOT / "scripts/experiments/analyze.py").read_bytes()),
        raw_probe_sha256=raw, raw_probes_unchanged=True, recovery_outputs_unchanged=True,
        all_other_impact_fields_unchanged=True, figure_bytes_preserved=True,
        supplementary_acceptance="20261117-review-supp2"))
    report_e3(folder, ROOT / "docs/exp/E3-results.md")
    print(f"Revised {len(differences)} failure windows; raw probes, recovery statistics and chart values preserved")


if __name__ == "__main__":
    main()
