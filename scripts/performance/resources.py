"""Independent 1 Hz Docker Engine collector via sequential one-shot stats reads."""
import argparse
import csv
from datetime import datetime, timezone
import http.client
import io
import json
from pathlib import Path
import signal
import threading
import time

import psutil

PIPE = r"\\.\pipe\dockerDesktopLinuxEngine"


def utc():
    return datetime.now(timezone.utc).isoformat()


class PipeSocket:
    def __init__(self):
        self.raw = open(PIPE, "r+b", buffering=0)

    def makefile(self, *args, **kwargs):
        return io.BufferedReader(self.raw)


def engine(path):
    pipe = PipeSocket()
    pipe.raw.write(f"GET /v1.56{path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n".encode())
    response = http.client.HTTPResponse(pipe)
    response.begin()
    if response.status != 200:
        response.close()
        raise RuntimeError("Engine statistics request failed")
    return response


def collect(folder, containers, parent_pid):
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    fields = ["received_utc", "sample_epoch", "engine_utc", "service", "cpu_percent",
              "memory_working_set_bytes", "memory_usage_bytes", "memory_limit_bytes",
              "network_rx_bytes", "network_tx_bytes", "block_read_bytes", "block_write_bytes",
              "interval_seconds", "missed_intervals"]
    errors, previous, intervals = [], {}, {service: [] for service in containers}
    generator, collector = psutil.Process(parent_pid), psutil.Process()
    generator.cpu_percent()
    collector.cpu_percent()
    psutil.cpu_percent()
    with (folder / "resources.csv").open("w", newline="", encoding="utf-8") as file, \
            (folder / "load-generator.csv").open("w", newline="", encoding="utf-8") as process_file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        process_writer = csv.DictWriter(process_file, fieldnames=["sample_epoch", "utc", "generator_cpu_percent",
            "generator_rss_bytes", "collector_cpu_percent", "collector_rss_bytes", "host_cpu_percent", "host_available_memory_bytes"])
        process_writer.writeheader()
        target = time.monotonic()
        while not stop.is_set() and not (folder / "collector.stop").exists():
            sampled = set()
            for service, container in containers.items():
                try:
                    with engine(f"/containers/{container}/stats?stream=false&one-shot=true") as response:
                        stats = json.load(response)
                    now = time.time()
                    cpu = stats["cpu_stats"]
                    last = previous.get(service)
                    percent, gap = None, None
                    if last:
                        prior, then = last
                        delta = cpu["cpu_usage"]["total_usage"] - prior["cpu_usage"]["total_usage"]
                        system = cpu.get("system_cpu_usage", 0) - prior.get("system_cpu_usage", 0)
                        online = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage", [])) or 1
                        percent = delta / system * online * 100 if system > 0 and delta >= 0 else None
                        gap = now - then
                        intervals[service].append(gap)
                    memory = stats.get("memory_stats", {})
                    usage = memory.get("usage", 0)
                    cache = memory.get("stats", {}).get("inactive_file", memory.get("stats", {}).get("total_inactive_file", 0))
                    network = list(stats.get("networks", {}).values())
                    blocks = stats.get("blkio_stats", {}).get("io_service_bytes_recursive")
                    writer.writerow(dict(received_utc=utc(), sample_epoch=now, engine_utc=stats["read"],
                        service=service, cpu_percent=percent,
                        memory_working_set_bytes=max(0, usage - cache), memory_usage_bytes=usage,
                        memory_limit_bytes=memory.get("limit"),
                        network_rx_bytes=sum(n["rx_bytes"] for n in network) if network else None,
                        network_tx_bytes=sum(n["tx_bytes"] for n in network) if network else None,
                        block_read_bytes=sum(b["value"] for b in blocks if b["op"].lower() == "read") if blocks else None,
                        block_write_bytes=sum(b["value"] for b in blocks if b["op"].lower() == "write") if blocks else None,
                        interval_seconds=gap, missed_intervals=max(0, round(gap) - 1) if gap else 0))
                    previous[service] = (cpu, now)
                    sampled.add(service)
                except Exception as error:
                    errors.append(dict(service=service, error_type=type(error).__name__, time=utc()))
            file.flush()
            if len(sampled) == len(containers):
                (folder / "collector.ready").touch()
            try:
                process_writer.writerow(dict(sample_epoch=time.time(), utc=utc(),
                    generator_cpu_percent=generator.cpu_percent(), generator_rss_bytes=generator.memory_info().rss,
                    collector_cpu_percent=collector.cpu_percent(), collector_rss_bytes=collector.memory_info().rss,
                    host_cpu_percent=psutil.cpu_percent(), host_available_memory_bytes=psutil.virtual_memory().available))
                process_file.flush()
            except psutil.NoSuchProcess:
                errors.append(dict(service="load-generator", error_type="NoSuchProcess", time=utc()))
                break
            target += 1
            stop.wait(max(0, target - time.monotonic()))
    summary = {service: dict(samples=len(values) + (1 if service in previous else 0),
                             interval_mean=sum(values) / len(values) if values else None,
                             interval_max=max(values) if values else None) for service, values in intervals.items()}
    (folder / "collector.json").write_text(json.dumps(dict(tool="Docker Engine v1.56 sequential one-shot stats + psutil",
        psutil_version=psutil.__version__, target_interval_seconds=1, errors=errors, intervals=summary,
        cpu_definition="100% is one logical Docker CPU; system ceiling is 400% for four CPUs",
        memory_definition="usage minus inactive_file/total_inactive_file (Docker CLI working-set convention)",
        missing_io="empty values mean unavailable, not zero"), indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("containers", type=Path)
    parser.add_argument("parent_pid", type=int)
    arguments = parser.parse_args()
    collect(arguments.folder, json.loads(arguments.containers.read_text()), arguments.parent_pid)
