"""Independent Linux cgroup sampler plus Windows load-generator accounting."""
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

import psutil

from runtime import DISTRO, LINUX


class Sampler:
    def __init__(self, runtime, folder):
        self.runtime, self.folder = runtime, folder
        self.memory_limit=int(runtime.wsl('head','-n','1','/proc/meminfo').stdout.decode().split()[1])*1024
        self.stop_path = LINUX + "/pids/stop-" + uuid.uuid4().hex
        self.stop_event, self.ready = threading.Event(), threading.Event()
        self.errors, self.intervals, self.last, self.seen = [], {}, {}, set()
        self.tool_cpu, self.tool_rss = 0.0, 0
        self.error_file = (folder / "collector-output.log").open("wb")
        self.process = subprocess.Popen(["wsl.exe", "-d", DISTRO, "-u", "root", "--exec",
            "/opt/java/openjdk/bin/java", "-Xms16m", "-Xmx64m", "-XX:ActiveProcessorCount=1",
            "-cp", LINUX + "/tools", "NativeSampler", self.stop_path], stdout=subprocess.PIPE,
            stderr=self.error_file, text=True, encoding="utf-8")
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.host = threading.Thread(target=self.host_samples, daemon=True)
        self.reader.start(); self.host.start()
        if not self.ready.wait(20):
            self.close()
            raise RuntimeError("Native sampler did not produce all six service records")

    def read(self):
        fields = ["received_utc", "sample_epoch", "engine_utc", "linux_epoch", "service", "cpu_percent",
            "memory_working_set_bytes", "memory_usage_bytes", "memory_limit_bytes", "memory_rss_bytes", "memory_pss_bytes",
            "network_rx_bytes", "network_tx_bytes", "block_read_bytes", "block_write_bytes", "interval_seconds", "missed_intervals"]
        try:
            with (self.folder / "resources.csv").open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=fields); writer.writeheader()
                for row in csv.DictReader(self.process.stdout):
                    if row["service"] == "__collector":
                        self.tool_cpu = float(row["cpu_percent"] or 0)
                        self.tool_rss = int(row["memory_rss_bytes"])
                        continue
                    epoch, name = time.time(), row["service"]
                    gap = epoch - self.last[name] if name in self.last else None
                    if gap is not None: self.intervals.setdefault(name, []).append(gap)
                    self.last[name] = epoch; self.seen.add(name)
                    writer.writerow(dict(received_utc=datetime.now(timezone.utc).isoformat(),
                        sample_epoch=epoch, engine_utc=row["linux_utc"], linux_epoch=row["linux_epoch"], service=name,
                        cpu_percent=row["cpu_percent"], memory_working_set_bytes=row["memory_working_set_bytes"],
                        memory_usage_bytes=row["memory_usage_bytes"], memory_limit_bytes=self.memory_limit,
                        memory_rss_bytes=row["memory_rss_bytes"], memory_pss_bytes=row["memory_pss_bytes"],
                        network_rx_bytes="", network_tx_bytes="", block_read_bytes=row["block_read_bytes"],
                        block_write_bytes=row["block_write_bytes"], interval_seconds=gap,
                        missed_intervals=max(0, round(gap) - 1) if gap else 0))
                    file.flush()
                    if len(self.seen) == 6: self.ready.set()
        except Exception as error:
            self.errors.append(type(error).__name__)

    def host_samples(self):
        process = psutil.Process(os.getpid()); process.cpu_percent(); psutil.cpu_percent()
        with (self.folder / "load-generator.csv").open("w", newline="", encoding="utf-8") as file:
            names = ["sample_epoch", "generator_cpu_percent", "generator_rss_bytes", "collector_cpu_percent", "collector_rss_bytes", "host_cpu_percent", "host_available_memory_bytes", "power_plugged", "battery_percent"]
            writer = csv.DictWriter(file, fieldnames=names); writer.writeheader()
            while not self.stop_event.is_set():
                battery=psutil.sensors_battery()
                writer.writerow(dict(sample_epoch=time.time(), generator_cpu_percent=process.cpu_percent(),
                    generator_rss_bytes=process.memory_info().rss, collector_cpu_percent=self.tool_cpu,
                    collector_rss_bytes=self.tool_rss, host_cpu_percent=psutil.cpu_percent(),
                    host_available_memory_bytes=psutil.virtual_memory().available,
                    power_plugged=battery.power_plugged if battery else '',battery_percent=battery.percent if battery else ''))
                file.flush(); self.stop_event.wait(1)

    def close(self):
        self.runtime.wsl("touch", self.stop_path)
        try: self.process.wait(timeout=10)
        except subprocess.TimeoutExpired: self.process.terminate()
        self.reader.join(timeout=5); self.stop_event.set(); self.host.join(timeout=5)
        self.error_file.close()
        data = dict(tool="Direct-process cgroup-v2 Java sampler + Windows psutil", target_interval_seconds=1,
            cpu_definition="delta cgroup usage_usec / monotonic elapsed seconds; 100%=one core",
            memory_definition="memory.current minus memory.stat inactive_file; RSS/PSS additionally recorded",
            timestamp_definition="Windows receipt epoch for request-window alignment; Linux source timestamp retained",
            network_definition="No per-service namespace counters in direct-process mode; unavailable fields left empty",
            errors=self.errors, intervals={name: dict(samples=len(v)+1, interval_mean=sum(v)/len(v), interval_max=max(v)) for name,v in self.intervals.items()})
        (self.folder / "collector.json").write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
