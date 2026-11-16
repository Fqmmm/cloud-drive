"""Recompute all E1 metrics from raw CSV; plot repeated-run medians and ranges."""
import argparse
import csv
import json
from pathlib import Path
import statistics

import numpy as np

from common import ROOT, MIB, save


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def percentiles(values):
    return dict(mean=float(np.mean(values)), p50=float(np.percentile(values, 50)),
                p95=float(np.percentile(values, 95)), p99=float(np.percentile(values, 99))) if values else dict(mean=None, p50=None, p95=None, p99=None)


def statistics_for(rows, start, end):
    cohort = [row for row in rows if row["phase"] == "measure" and start <= float(row["start_epoch"]) < end]
    success = [row for row in cohort if row["success"] == "1"]
    completed = [row for row in success if float(row["end_epoch"]) < end]
    return dict(requests=len(cohort), successes=len(success), failures=len(cohort) - len(success),
        success_rate=len(success) / len(cohort) if cohort else None,
        rps=len(completed) / (end - start), completed_successes_in_window=len(completed),
        successful_completions_after_window=len(success) - len(completed),
        bytes_per_second=sum(int(row.get("payload_bytes", 0)) for row in completed) / (end - start),
        latency_ms=percentiles([float(row["latency_ms"]) for row in cohort]),
        successful_latency_ms=percentiles([float(row["latency_ms"]) for row in success]),
        timeouts=sum(row.get("error_category") == "timeout" for row in cohort))


def analyze_round(folder):
    workload = json.loads((folder / "workload.json").read_text(encoding="utf-8"))
    start, end = workload["measurement"]["start_epoch"], workload["measurement"]["end_epoch"]
    requests = read_csv(folder / "requests.csv")
    result = statistics_for(requests, start, end)
    result["iterations"] = statistics_for(read_csv(folder / "iterations.csv"), start, end)
    result["operations"] = {name: statistics_for([row for row in requests if row["operation"] == name], start, end)
                            for name in sorted({row["operation"] for row in requests})}
    resource_rows = [row for row in read_csv(folder / "resources.csv") if start <= float(row["sample_epoch"]) < end]
    result["resources"] = {}
    for service in sorted({row["service"] for row in resource_rows}):
        rows = [row for row in resource_rows if row["service"] == service]
        cpu = [float(row["cpu_percent"]) for row in rows if row["cpu_percent"]]
        memory = [float(row["memory_working_set_bytes"]) for row in rows]
        result["resources"][service] = dict(samples=len(rows), expected_samples=round(end - start),
            cpu_samples=len(cpu), cpu_missing_samples=len(rows) - len(cpu),
            missing_sample_estimate=max(0, round(end - start) - len(rows)),
            reported_missed_intervals=sum(int(row["missed_intervals"]) for row in rows),
            cpu_mean=float(np.mean(cpu)), cpu_peak=max(cpu), memory_mean_bytes=float(np.mean(memory)), memory_peak_bytes=max(memory),
            io_fields_available=any(row["block_read_bytes"] for row in rows))
    generator = [row for row in read_csv(folder / "load-generator.csv") if start <= float(row["sample_epoch"]) < end]
    result["load_generator"] = {name: dict(mean=float(np.mean([float(row[name]) for row in generator])),
        peak=max(float(row[name]) for row in generator)) for name in ["generator_cpu_percent", "generator_rss_bytes", "collector_cpu_percent", "collector_rss_bytes", "host_cpu_percent"]}
    result["error_categories"] = {}
    downstream = read_csv(folder / "downstream.csv") if (folder / "downstream.csv").exists() else []
    result["downstream"] = {operation: percentiles([float(row["duration_ms"]) for row in downstream if row["operation"] == operation])
                            for operation in sorted({row["operation"] for row in downstream})}
    for row in requests:
        if row["phase"] == "measure" and row["success"] == "0":
            key = row["error_category"] + ":" + row["error_code"]
            result["error_categories"][key] = result["error_categories"].get(key, 0) + 1
    result.update(run_id=folder.name, scenario=workload["scenario"], vus=workload["vus"], repeat=workload["repeat"],
                  file_size_bytes=workload["file_size_bytes"], measure_seconds=end - start,
                  cap_hit=any(workload["upload_cap_hit_by_vu"]), complete=workload.get("complete", False))
    save(folder / "metrics.json", result)
    return result


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def aggregate(results):
    output = []
    for scenario, vus in sorted({(row["scenario"], row["vus"]) for row in results}):
        rows = [row for row in results if (row["scenario"], row["vus"]) == (scenario, vus)]
        record = dict(scenario=scenario, vus=vus, repeats=len(rows), total_requests=sum(row["requests"] for row in rows),
                      total_failures=sum(row["failures"] for row in rows))
        values = {"success_rate": [row["success_rate"] for row in rows], "rps": [row["rps"] for row in rows],
            "iteration_rps": [row["iterations"]["rps"] for row in rows], "p95_ms": [row["latency_ms"]["p95"] for row in rows],
            "p99_ms": [row["latency_ms"]["p99"] for row in rows], "mib_per_second": [row["bytes_per_second"] / MIB for row in rows],
            "file_cpu_peak": [row["resources"]["file-service"]["cpu_peak"] for row in rows],
            "file_memory_peak_mib": [row["resources"]["file-service"]["memory_peak_bytes"] / MIB for row in rows]}
        for name, samples in values.items():
            record.update({name + "_median": statistics.median(samples), name + "_min": min(samples), name + "_max": max(samples)})
        output.append(record)
    return output


def plot(folder, results, groups):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150})
    figures = folder / "figures"
    figures.mkdir(exist_ok=True)
    names = {"P1": "List (100 entries)", "P2": "Upload (1 MiB)", "P3": "Download (1 MiB)", "P4": "Protected share (2 requests/iteration)"}
    for metric, ylabel, filename in [("rps", "Successful HTTP completions / s", "throughput"),
                                      ("p95_ms", "Per-run P95 HTTP latency (ms; log scale)", "p95")]:
        fig, axis = plt.subplots(figsize=(8, 4.6), layout="constrained")
        for scenario, label in names.items():
            rows = sorted([row for row in groups if row["scenario"] == scenario], key=lambda row: row["vus"])
            if not rows:
                continue
            center = np.array([row[metric + "_median"] for row in rows])
            error = np.array([[row[metric + "_median"] - row[metric + "_min"] for row in rows],
                              [row[metric + "_max"] - row[metric + "_median"] for row in rows]])
            axis.errorbar([row["vus"] for row in rows], center, yerr=error, marker="o", capsize=4, label=label)
        axis.set(xlabel="Concurrent virtual users (closed model; 1 s think time)", ylabel=ylabel, xticks=[5, 10, 20])
        if metric == "p95_ms":
            axis.set_yscale("log")
        axis.grid(alpha=.2)
        axis.legend(fontsize=8)
        for extension in ["png", "svg"]:
            fig.savefig(figures / (filename + "." + extension))
        plt.close(fig)
    extended = [row for row in groups if row["scenario"] in ("P5U", "P5D")]
    if extended:
        fig, axes = plt.subplots(1, 2, figsize=(9, 4), layout="constrained")
        for axis, metric, label in [(axes[0], "mib_per_second", "Successful body throughput (MiB/s)"),
                                     (axes[1], "p95_ms", "Per-run P95 HTTP latency (ms)")]:
            center = [row[metric + "_median"] for row in extended]
            error = [[row[metric + "_median"] - row[metric + "_min"] for row in extended],
                     [row[metric + "_max"] - row[metric + "_median"] for row in extended]]
            axis.bar(["20 MiB upload" if row["scenario"] == "P5U" else "20 MiB download" for row in extended], center,
                     yerr=error, capsize=5, color=["#3977a6", "#d88229"][:len(extended)])
            vu_label = ",".join(str(value) for value in sorted({row["vus"] for row in extended}))
            axis.set(ylabel=label, title=vu_label + " VU; median and min-max across repeats")
            axis.grid(axis="y", alpha=.2)
        for extension in ["png", "svg"]:
            fig.savefig(figures / ("large-files." + extension))
        plt.close(fig)
    candidates = sorted([row for row in results if row["scenario"] == "P4" and row["vus"] == 20], key=lambda row: row["latency_ms"]["p95"])
    if candidates:
        chosen = candidates[len(candidates) // 2]
        source = ROOT / "experiments" / "E1" / chosen["run_id"]
        work = json.loads((source / "workload.json").read_text())
        start, end = work["measurement"]["start_epoch"], work["measurement"]["end_epoch"]
        samples = [row for row in read_csv(source / "resources.csv") if start <= float(row["sample_epoch"]) < end]
        fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True, layout="constrained")
        for service in sorted(chosen["resources"]):
            values = [row for row in samples if row["service"] == service and row["cpu_percent"]]
            seconds = [float(row["sample_epoch"]) - start for row in values]
            axes[0].plot(seconds, [float(row["cpu_percent"]) for row in values], label=service, linewidth=1)
            axes[1].plot(seconds, [float(row["memory_working_set_bytes"]) / MIB for row in values], label=service, linewidth=1)
        axes[0].set(ylabel="CPU % (100% = one core)", title="P4, 20 VU: middle run by P95; formal measurement window")
        axes[0].legend(ncol=3, fontsize=8)
        axes[1].set(ylabel="Working-set memory (MiB)", xlabel="Seconds from formal window start")
        for axis in axes:
            axis.grid(alpha=.2)
        for extension in ["png", "svg"]:
            fig.savefig(figures / ("share-resource-curve." + extension))
        plt.close(fig)
    services = sorted(results[0]["resources"])
    labels, matrix = [], []
    for scenario in names:
        for vus in [5, 10, 20]:
            rows = [row for row in results if row["scenario"] == scenario and row["vus"] == vus]
            if rows:
                labels.append(f"{scenario}, {vus} VU")
                matrix.append([statistics.median(row["resources"][service]["memory_peak_bytes"] / MIB for row in rows) for service in services])
    if matrix:
        fig, axis = plt.subplots(figsize=(9, 6), layout="constrained")
        heat = axis.imshow(matrix, cmap="YlGnBu", aspect="auto")
        axis.set(xticks=range(len(services)), xticklabels=services, yticks=range(len(labels)), yticklabels=labels,
                 title="Median across repeats of each container's measured memory peak (MiB)")
        plt.setp(axis.get_xticklabels(), rotation=25, ha="right")
        for i, values in enumerate(matrix):
            for j, value in enumerate(values):
                axis.text(j, i, f"{value:.0f}", ha="center", va="center", fontsize=8,
                          color="white" if value > np.max(matrix) * .6 else "black")
        fig.colorbar(heat, ax=axis, label="MiB; usage minus inactive file cache")
        for extension in ["png", "svg"]:
            fig.savefig(figures / ("memory-peaks." + extension))
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch")
    args = parser.parse_args()
    folder = ROOT / "experiments" / "E1" / (args.batch + "-summary")
    manifest = json.loads((folder / "matrix.json").read_text(encoding="utf-8"))
    results = [analyze_round(ROOT / "experiments" / "E1" / name) for name in manifest["completed"]]
    save(folder / "metrics.json", results)
    groups = aggregate(results)
    write_csv(folder / "aggregate.csv", groups)
    rows = []
    for item in results:
        rows.append(dict(run_id=item["run_id"], scenario=item["scenario"], vus=item["vus"], repeat=item["repeat"],
            file_size_bytes=item["file_size_bytes"], requests=item["requests"], success_rate=item["success_rate"], failures=item["failures"],
            rps=item["rps"], iteration_rps=item["iterations"]["rps"], mean_ms=item["latency_ms"]["mean"],
            p50_ms=item["latency_ms"]["p50"], p95_ms=item["latency_ms"]["p95"], p99_ms=item["latency_ms"]["p99"],
            mib_per_second=item["bytes_per_second"] / MIB, file_cpu_peak=item["resources"]["file-service"]["cpu_peak"],
            file_memory_peak_mib=item["resources"]["file-service"]["memory_peak_bytes"] / MIB))
    write_csv(folder / "per-round.csv", rows)
    resource_rows = [dict(run_id=item["run_id"], scenario=item["scenario"], vus=item["vus"], repeat=item["repeat"], service=service, **values)
                     for item in results for service, values in item["resources"].items()]
    write_csv(folder / "resource-summary.csv", resource_rows)
    plot(folder, results, groups)
    print("Analyzed", len(results), "rounds; requests", sum(row["requests"] for row in results),
          "failures", sum(row["failures"] for row in results), flush=True)


if __name__ == "__main__":
    main()
