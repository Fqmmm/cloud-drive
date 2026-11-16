"""Scoped Compose operations and credential-free evidence for E2."""
from contextlib import redirect_stdout
import csv
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "performance"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))
from common import Client, MIB, checksum, payload, prepare, save, utc
from resources import engine
from functional import Acceptance


def validate_project(project):
    if not re.fullmatch(r"cloud-drive-e2-[a-z0-9_-]{1,40}", project):
        raise ValueError("E2 mutations require a dedicated cloud-drive-e2-* project")
    return project


def sanitize(text, secrets=()):
    for secret in sorted(set(secrets), key=len, reverse=True):
        if len(secret) >= 6:
            text = text.replace(secret, "<redacted>")
    text = re.sub(r"(/s/)[A-Za-z0-9_-]{22}", r"\1<redacted>", text)
    return re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted-jwt>", text)


def changed_services(before, after):
    def group(rows):
        return {name: sorted((r["id"], r["started"], r["image_id"]) for r in rows if r["service"] == name)
                for name in {r["service"] for r in rows}}
    left, right = group(before), group(after)
    return {name for name in left.keys() | right.keys() if left.get(name) != right.get(name)}


def settings(path):
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
                if line and not line.startswith("#") and "=" in line)


def api_engine(path):
    with engine(path) as response:
        return json.load(response)


def inventory(project):
    from urllib.parse import quote
    filters = quote(json.dumps({"label": ["com.docker.compose.project=" + project]}))
    result = []
    for item in api_engine("/containers/json?all=1&filters=" + filters):
        raw = api_engine("/containers/" + item["Id"] + "/json")
        labels, state = raw["Config"]["Labels"], raw["State"]
        result.append(dict(service=labels["com.docker.compose.service"], number=labels["com.docker.compose.container-number"],
            id=raw["Id"], image_id=raw["Image"], image_reference=raw["Config"]["Image"],
            version=next((x.split("=", 1)[1] for x in raw["Config"]["Env"] if x.startswith("APP_VERSION=")), None),
            image_version_label=labels.get("org.opencontainers.image.version"),
            started=state["StartedAt"], status=state["Status"], health=state.get("Health", {}).get("Status"),
            restart_count=raw["RestartCount"], oom_killed=state["OOMKilled"],
            limits={k: raw["HostConfig"].get(k) for k in ["NanoCpus", "CpuQuota", "CpuPeriod", "Memory", "MemorySwap"]},
            mounts=[{k: m.get(k) for k in ["Type", "Name", "Source", "Destination"]} for m in raw["Mounts"]],
            networks={k: dict(ip=v["IPAddress"], aliases=v["Aliases"]) for k, v in raw["NetworkSettings"]["Networks"].items()}))
    return sorted(result, key=lambda r: (r["service"], r["number"]))


class Context:
    def __init__(self, project, env_file):
        self.project, self.env_file = validate_project(project), env_file.resolve()
        self.values = settings(self.env_file)
        if self.values["COMPOSE_PROJECT_NAME"] != self.project:
            raise ValueError("Private environment and requested project differ")
        self.base = "http://127.0.0.1:" + self.values["HTTP_PORT"]
        self.secrets = [v for k, v in self.values.items() if any(s in k for s in ["PASSWORD", "SECRET", "TOKEN", "MINIO_ROOT_USER"])]

    def run(self, args, log=None, timeout=900):
        began = time.time()
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        output = sanitize(result.stdout + result.stderr, self.secrets)
        if log:
            log.write_text(output, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("E2 command failed (exit " + str(result.returncode) + "); see redacted log")
        return result.stdout.strip(), time.time() - began

    def compose(self, *args, log=None, timeout=900):
        if args[0] == "down" and any(x in args for x in ["-v", "--volumes"]):
            raise ValueError("E2 must preserve volumes")
        return self.run(["docker", "compose", "--env-file", str(self.env_file), "-p", self.project,
                         "--progress", "plain", *args], log, timeout)

    def reload(self, folder):
        return self.run(["pwsh", "-NoProfile", "-File", "scripts/deployment/reload-nginx.ps1",
                         "-EnvFile", str(self.env_file), "-ProjectName", self.project], folder / "nginx-reload.log")

    def snapshot(self, folder, name="containers.json"):
        rows = inventory(self.project)
        save(folder / name, rows)
        return rows

    def topology(self, folder):
        networks = json.loads(self.compose("config", "--format", "json")[0])["networks"]
        save(folder / "networks.json", [api_engine("/networks/" + x["name"]) for x in networks.values()])
        volumes = []
        for suffix in ["mysql_data", "minio_data"]:
            name = self.project + "_" + suffix
            volumes.append(api_engine("/volumes/" + name))
        save(folder / "volumes.json", volumes)

    def ready(self, count=6, timeout=300):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = inventory(self.project)
            if len(rows) == count and all(r["health"] == "healthy" and r["status"] == "running" for r in rows):
                return rows
            time.sleep(1)
        raise RuntimeError("E2 services did not become healthy")


class StartupObserver:
    def __init__(self, project):
        self.project, self.stop = project, threading.Event()
        self.transitions, self.errors, self.seen = [], [], {}
        self.thread = threading.Thread(target=self.collect, daemon=True)

    def collect(self):
        while not self.stop.is_set():
            try:
                for row in inventory(self.project):
                    value = (row["status"], row["health"])
                    if self.seen.get(row["id"]) != value:
                        self.transitions.append(dict(observed_epoch=time.time(), observed_utc=utc(), **row))
                        self.seen[row["id"]] = value
            except Exception as error:
                self.errors.append(dict(utc=utc(), type=type(error).__name__))
            self.stop.wait(.5)

    def finish(self, folder):
        self.stop.set()
        self.thread.join(timeout=5)
        save(folder / "startup-observations.json", dict(poll_interval_seconds=.5, transitions=self.transitions, errors=self.errors))


def full_smoke(ctx, folder, name="smoke"):
    suite = Acceptance(ctx.base, ctx.env_file, ctx.project)
    output, fatal, passed_epoch = io.StringIO(), None, None
    began = time.time()
    try:
        with redirect_stdout(output):
            suite.accounts()
            suite.directories_and_files()
            suite.sharing()
            suite.deletion()
        if not all(r["status"] == "PASS" for r in suite.results):
            raise AssertionError("Functional acceptance failed")
        passed_epoch = time.time()
    except Exception as error:
        fatal = type(error).__name__
    finally:
        try:
            suite.cleanup()
        except Exception as error:
            fatal = fatal or "Cleanup:" + type(error).__name__
        suite.http.close()
    report = dict(start_epoch=began, passed_epoch=passed_epoch, cleanup_finished_epoch=time.time(),
        total=len(suite.results), passed=sum(r["status"] == "PASS" for r in suite.results), fatal=fatal, results=suite.results,
        scope="FR-01..FR-12 API acceptance, no outages; does not replace browser acceptance")
    save(folder / (name + ".json"), report)
    (folder / (name + ".log")).write_text(sanitize(output.getvalue(), [*ctx.secrets, *suite.sensitive]), encoding="utf-8")
    if fatal:
        raise RuntimeError("Full API smoke did not pass; see " + name + ".json")
    return report
