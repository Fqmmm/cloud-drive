"""Generate publication figures from completed E3 CSVs; no synthetic inputs."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]{1,24}", args.run_id):
        parser.error("Invalid run ID")
    root = Path.cwd()
    folder = root / "experiments" / "E3" / args.run_id
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "complete" or len(manifest["completed"]) != 15:
        raise ValueError("Figures require a completed 15-round formal matrix")
    output = folder / "figures"
    output.mkdir(exist_ok=True)
    impacts = read_csv(folder / "impact.csv")
    recoveries = read_csv(folder / "recovery.csv")
    faults = ["F1", "F2", "F3", "F4", "F5"]
    fault_labels = ["F1\nShare stop", "F2\nAuth stop", "F3\nFile stop", "F4\nMinIO stop", "F5\nJVM halt"]
    probes = ["frontend", "login", "files", "personal_download", "share_list", "share_0_verify", "share_0_download", "share_1_verify", "share_1_download"]
    labels = ["Frontend HTML", "New login", "Private list", "Private download", "Share management list", "Public share verify", "Public share download", "Protected share verify", "Protected share download"]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    generated = []

    def export(fig, name):
        for extension in ("png", "pdf"):
            path = output / (name + "." + extension)
            fig.savefig(path, dpi=220, bbox_inches="tight")
            generated.append(path)
        plt.close(fig)

    values = np.empty((len(probes), len(faults)))
    for x, fault in enumerate(faults):
        for y, probe in enumerate(probes):
            selected = [row for row in impacts if row["fault"] == fault and row["probe"] == probe]
            denominator = sum(int(row["window_scheduled"]) for row in selected)
            numerator = sum(int(row["window_success"]) for row in selected)
            values[y, x] = 100 * numerator / denominator if denominator else np.nan
    fig, ax = plt.subplots(figsize=(9.5, 5.3), layout="constrained")
    graphic = ax.imshow(values, vmin=0, vmax=100, cmap="viridis", aspect="auto")
    ax.set_xticks(range(5), fault_labels)
    ax.set_yticks(range(9), labels)
    for (y, x), value in np.ndenumerate(values):
        ax.text(x, y, f"{value:.1f}%", ha="center", va="center", color="white" if value < 60 else "black", fontsize=9)
    fig.colorbar(graphic, ax=ax, label="Successful scheduled requests (%)")
    ax.set_title("Observed availability: injection to stable recovery\nThree repeats combined per fault")
    export(fig, "availability")

    fig, ax = plt.subplots(figsize=(8.8, 4.5), layout="constrained")
    for x, fault in enumerate(faults):
        selected = sorted((row for row in recoveries if row["fault"] == fault), key=lambda row: int(row["repeat"]))
        times = [float(row["recovery_seconds"]) for row in selected]
        color = "#d97706" if fault == "F5" else "#2563eb"
        ax.vlines(x, min(times), max(times), color=color, alpha=.5, linewidth=2)
        ax.scatter(np.array([x] * 3) + [-.12, 0, .12], times, color=color, zorder=3, s=38)
        ax.hlines(statistics.median(times), x - .22, x + .22, color="#111827", linewidth=2.5)
    ax.set_xticks(range(5), fault_labels)
    ax.set_ylabel("Recovery time (s)")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=.2)
    ax.set_title("Time to stable recovery: individual runs, median and range")
    fig.text(.5, -.035, "F1-F4: manual start to stable recovery. F5: injection to stable recovery (automatic).", ha="center", fontsize=9)
    export(fig, "recovery-time")

    for fault in faults:
        fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True, layout="constrained")
        for repeat, ax in enumerate(axes, 1):
            case = folder / f"{fault}-r{repeat}"
            events = json.loads((case / "events.json").read_text(encoding="utf-8"))
            times = {row["name"]: row["epoch"] for row in events}
            t0 = times["t0-inject"]
            recovery = next(row for row in recoveries if row["fault"] == fault and int(row["repeat"]) == repeat)
            t5 = float(recovery["common_t5"])
            data = read_csv(case / "probe.csv")
            for y, probe in enumerate(probes):
                selected = [row for row in data if row["probe"] == probe and row["sent_epoch"]
                            and t0 - 5 <= float(row["sent_epoch"]) <= t5 + 4]
                for success, color in ((True, "#15803d"), (False, "#b91c1c")):
                    points = [float(row["sent_epoch"]) - t0 for row in selected if (row["category"] == "ok") == success]
                    ax.scatter(points, [y] * len(points), marker="|", color=color, s=55, linewidth=1.4)
            ax.axvline(0, color="#111827", linestyle=":", linewidth=1)
            if "t3-start-command" in times:
                ax.axvline(times["t3-start-command"] - t0, color="#2563eb", linestyle="--", linewidth=1)
            ax.axvline(t5 - t0, color="#15803d", linestyle="--", linewidth=1)
            ax.set_yticks(range(9), labels, fontsize=8)
            ax.set_ylim(8.6, -.6)
            ax.set_title(f"{fault}, repeat {repeat}: stable recovery at {t5 - t0:.2f} s after injection", fontsize=10)
            ax.grid(axis="x", alpha=.15)
        axes[-1].set_xlabel("Actual probe send time relative to injection (s)")
        fig.suptitle("Green: success; red: failure. Black: inject; blue: manual start; green dashed: stable recovery.", fontsize=10)
        export(fig, "timeline-" + fault)
    sources = [folder / "impact.csv", folder / "recovery.csv", folder / "manifest.json"]
    for fault in faults:
        for repeat in range(1, 4):
            sources.extend([folder / f"{fault}-r{repeat}" / name for name in ("events.json", "probe.csv")])
    (output / "provenance.json").write_text(json.dumps(dict(matplotlib=matplotlib.__version__, numpy=np.__version__, python=sys.version,
        generator_sha256=sha(Path(__file__)), inputs=[dict(path=str(path.relative_to(root)).replace("\\", "/"), sha256=sha(path)) for path in sources],
        figures=[dict(path=str(path.relative_to(root)).replace("\\", "/"), sha256=sha(path)) for path in generated]), indent=2), encoding="utf-8", newline="\n")
    print("Generated", len(generated), "PNG/PDF figures from recorded data")


if __name__ == "__main__":
    main()
