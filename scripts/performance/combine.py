"""Combine disjoint E1 continuation batches without replacing original records."""
import argparse
import json

from common import ROOT, save
from analyze import aggregate, plot, write_csv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base = ROOT / "experiments/E1"
    results, completed = [], []
    for name in args.sources:
        source = base / (name + "-summary")
        manifest = json.loads((source / "matrix.json").read_text())
        rows = json.loads((source / "metrics.json").read_text())
        if {r["run_id"] for r in rows} != set(manifest["completed"]):
            raise ValueError("Metrics and completed source rounds differ")
        results.extend(rows)
        completed.extend(manifest["completed"])
    keys = {(r["scenario"], r["vus"], r["repeat"]) for r in results}
    if len(keys) != len(results) or len(set(completed)) != len(completed):
        raise ValueError("Source batches overlap; never pool replacement rounds")
    folder = base / (args.output + "-summary")
    folder.mkdir(exist_ok=False)
    counts = {name: sum(r["scenario"] == name for r in results) for name in ["P1", "P2", "P3", "P4", "P5U", "P5D"]}
    save(folder / "matrix.json", dict(source_batches=args.sources, completed=completed, completed_rounds=len(results),
        completed_by_scenario=counts, planned_rounds=42, base_rounds_completed=sum(counts[s] for s in ["P1", "P2", "P3", "P4"]),
        note="Derived summary; original batches retained; identify incomplete repeats before interpreting extensions"))
    save(folder / "metrics.json", results)
    write_csv(folder / "aggregate.csv", aggregate(results))
    write_csv(folder / "per-round.csv", [dict(run_id=r["run_id"], scenario=r["scenario"], vus=r["vus"], repeat=r["repeat"],
        requests=r["requests"], failures=r["failures"], rps=r["rps"], iteration_rps=r["iterations"]["rps"],
        p95_ms=r["latency_ms"]["p95"], p99_ms=r["latency_ms"]["p99"], mib_per_second=r["bytes_per_second"] / 2**20) for r in results])
    write_csv(folder / "resource-summary.csv", [dict(run_id=r["run_id"], scenario=r["scenario"], vus=r["vus"], repeat=r["repeat"],
        service=name, **values) for r in results for name, values in r["resources"].items()])
    complete_base = [r for r in results if r["scenario"] in ["P1", "P2", "P3", "P4"]]
    plot(folder, complete_base, aggregate(complete_base))
    print("Combined", len(results), "disjoint E1 rounds", flush=True)


if __name__ == "__main__":
    main()
