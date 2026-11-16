"""Recompute E2 timing and replica summaries; render standalone figures."""
import argparse
import csv
import json
import statistics

import numpy as np

from e2_support import ROOT, save
from analyze import analyze_round, write_csv


def repeated(values):
    return dict(median=statistics.median(values), minimum=min(values), maximum=max(values))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch")
    args = parser.parse_args()
    folder = ROOT / "experiments/E2" / args.batch
    manifest = json.loads((folder / "manifest.json").read_text())
    if not manifest["complete"]:
        raise RuntimeError("Keep incomplete batches separate; do not publish a complete E2 summary")
    starts = []
    for label in ["first-deployment", "cached-r1", "cached-r2", "cached-r3"]:
        timing = json.loads((folder / label / "timing.json").read_text())
        smoke = json.loads((folder / label / "smoke.json").read_text())
        starts.append(dict(label=label, source_build=timing["source_build"], command_seconds=timing["command_seconds"],
            all_healthy_seconds=timing["all_healthy_observed_seconds"], business_ready_seconds=timing["business_ready_seconds"],
            smoke_passed=smoke["passed"], smoke_total=smoke["total"], cleanup_seconds=timing["smoke_cleanup_seconds"]))
    write_csv(folder / "deployment-summary.csv", starts)
    summary = dict(cached_business_ready_seconds=repeated([x["business_ready_seconds"] for x in starts[1:]]))
    results = []
    for source in sorted(folder.glob("scale-*replicas-vu20-r*/metrics.json")):
        result = analyze_round(source.parent)
        result["replicas"] = json.loads((source.parent / "workload.json").read_text())["replicas"]
        save(source, result)
        if not result["complete"]:
            raise RuntimeError("Incomplete replica measurement")
        results.append(result)
    groups = []
    for replicas in sorted({x["replicas"] for x in results}):
        rows = [x for x in results if x["replicas"] == replicas]
        record = dict(replicas=replicas, repeats=len(rows), requests=sum(x["requests"] for x in rows),
            failures=sum(x["failures"] for x in rows), timeouts=sum(x["timeouts"] for x in rows),
            iterations=sum(x["iterations"]["requests"] for x in rows), iteration_failures=sum(x["iterations"]["failures"] for x in rows))
        metrics = dict(http_rps=[x["rps"] for x in rows], iteration_rps=[x["iterations"]["rps"] for x in rows],
            http_p95_ms=[x["latency_ms"]["p95"] for x in rows], http_p99_ms=[x["latency_ms"]["p99"] for x in rows],
            iteration_p95_ms=[x["iterations"]["latency_ms"]["p95"] for x in rows],
            share_cpu_mean_percent=[sum(v["cpu_mean"] for k, v in x["resources"].items() if k.startswith("share-service")) for x in rows],
            share_memory_mean_mib=[sum(v["memory_mean_bytes"] for k, v in x["resources"].items() if k.startswith("share-service")) / 2**20 for x in rows])
        for key, values in metrics.items():
            for name, value in repeated(values).items():
                record[key + "_" + name] = value
        groups.append(record)
    summary["replica_conditions"] = groups
    summary["resource_samples"] = dict(actual=sum(v["samples"] for x in results for v in x["resources"].values()),
        expected=sum(v["expected_samples"] for x in results for v in x["resources"].values()),
        cpu_missing=sum(v["cpu_missing_samples"] for x in results for v in x["resources"].values()))
    if groups:
        write_csv(folder / "replica-summary.csv", groups)
        write_csv(folder / "replica-per-round.csv", [dict(run_id=x["run_id"], replicas=x["replicas"], repeat=x["repeat"],
            requests=x["requests"], failures=x["failures"], rps=x["rps"], iteration_rps=x["iterations"]["rps"],
            http_p95_ms=x["latency_ms"]["p95"], iteration_p95_ms=x["iterations"]["latency_ms"]["p95"]) for x in results])
        resource_rows = [dict(run_id=x["run_id"], replicas=x["replicas"], repeat=x["repeat"], service=name, **values)
                         for x in results for name, values in x["resources"].items()]
        write_csv(folder / "resource-summary.csv", resource_rows)
    save(folder / "summary.json", summary)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150})
    figures = folder / "figures"
    figures.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for key, label in [("command_seconds", "up command returned"), ("all_healthy_seconds", "all containers healthy"),
                       ("business_ready_seconds", "full 86-check API smoke passed")]:
        ax.plot([x["label"] for x in starts], [x[key] for x in starts], marker="o", label=label)
    ax.set(ylabel="Seconds since up invocation", title="E2 deployment: command, health and business readiness")
    ax.legend(fontsize=8)
    ax.grid(alpha=.2)
    for extension in ["png", "svg"]:
        fig.savefig(figures / ("deployment-readiness." + extension))
    plt.close(fig)
    if groups:
        fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout="constrained")
        for ax, metric, label in [(axes[0], "iteration_rps", "Successful business iterations/s"),
                                  (axes[1], "http_p95_ms", "Per-run HTTP P95 (ms)"),
                                  (axes[2], "share_memory_mean_mib", "Sum of share instances' mean memory (MiB)")]:
            centers = [x[metric + "_median"] for x in groups]
            errors = [[x[metric + "_median"] - x[metric + "_minimum"] for x in groups],
                      [x[metric + "_maximum"] - x[metric + "_median"] for x in groups]]
            ax.bar([str(x["replicas"]) for x in groups], centers, yerr=errors, capsize=5, color=["#3977a6", "#d88229"][:len(groups)])
            ax.set(xlabel="Share-service replicas", ylabel=label)
            ax.grid(axis="y", alpha=.2)
        fig.suptitle("20 VU; same Docker CPU/memory budget; median and min-max across three repeats")
        for extension in ["png", "svg"]:
            fig.savefig(figures / ("replica-comparison." + extension))
        plt.close(fig)
    update = folder / "independent-update"
    with (update / "probes.csv").open(newline="", encoding="utf-8") as file:
        probes = list(csv.DictReader(file))
    timing = json.loads((update / "update.json").read_text())
    fig, ax = plt.subplots(figsize=(9, 3.5), layout="constrained")
    for index, operation in enumerate(["login", "files", "share"]):
        rows = [x for x in probes if x["operation"] == operation]
        ax.scatter([float(x["start_epoch"]) - timing["start_epoch"] for x in rows], [index] * len(rows),
            marker="s", c=["#39835d" if x["success"] == "1" else "#c44742" for x in rows], s=32)
    ax.axvline(timing["replace_started_epoch"] - timing["start_epoch"], color="black", linestyle="--", label="replace command")
    ax.set(yticks=[0, 1, 2], yticklabels=["login", "files", "share"], xlabel="Probe start time since update observation began (s)",
        title="Independent update probes: green=success, red=failure; target interval 1 s")
    ax.legend(fontsize=8)
    for extension in ["png", "svg"]:
        fig.savefig(figures / ("update-probes." + extension))
    plt.close(fig)
    for path in figures.glob("*.svg"):
        path.write_text("\n".join(x.rstrip() for x in path.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    print("E2 analysis complete:", len(starts), "deployments;", len(results), "replica rounds", flush=True)


if __name__ == "__main__":
    main()
