"""1 Hz independent HTTP probes, with absolute request deadlines.

Each scheduled probe gets its own subprocess. A hung/slow trickle download is
killed at its wall-clock deadline. Scheduling never waits for an HTTP response;
the maximum concurrency is bounded by probes * (deadline + one tick).
"""
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import multiprocessing as mp
import threading
import time

import requests

from support import digest, utc

FIELDS = ["probe", "tick", "planned_epoch", "sent_epoch", "returned_epoch", "http_status", "business_code",
          "category", "elapsed_ms", "schedule_lag_ms", "bytes", "sha256"]


def http_worker(connection, spec):
    sent = time.time()
    connection.send(dict(event="sent", sent_epoch=sent))
    row = dict(sent_epoch=sent, http_status="", business_code="", category="transport", bytes=0, sha256="")
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.request(spec.get("method", "GET"), spec["url"], json=spec.get("data"),
                headers=spec.get("headers", {}), timeout=spec["timeout"], allow_redirects=False) as response:
                body = response.content
                row.update(http_status=response.status_code, bytes=len(body))
                if spec.get("sha256"):
                    row["sha256"] = digest(body)
                    ok = response.status_code == 200 and row["sha256"] == spec["sha256"]
                    row["category"] = "ok" if ok else "http" if response.status_code != 200 else "checksum"
                    if response.status_code != 200:
                        try:
                            row["business_code"] = response.json().get("code", "")
                        except (ValueError, AttributeError):
                            pass
                elif spec.get("html"):
                    row["category"] = "ok" if response.status_code == 200 and b"<html" in body.lower() else "http"
                else:
                    try:
                        result = response.json()
                        row["business_code"] = result.get("code", "")
                        row["category"] = "ok" if response.status_code == 200 and result.get("code") == "00000" else "http-business"
                    except (ValueError, AttributeError):
                        row["category"] = "invalid-json"
    except requests.Timeout:
        row["category"] = "timeout"
    except requests.RequestException:
        row["category"] = "transport"
    except Exception:
        row["category"] = "worker-error"
    row.update(returned_epoch=time.time())
    try:
        connection.send(row)
    finally:
        connection.close()


def execute(spec):
    context = mp.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=http_worker, args=(send, spec), daemon=True)
    began = time.time()
    deadline = time.monotonic() + spec["timeout"]
    process.start()
    send.close()
    sent = ""
    try:
        row = None
        while receive.poll(max(0, deadline - time.monotonic())):
            try:
                message = receive.recv()
            except EOFError:
                row = dict(category="worker-error", sent_epoch="", returned_epoch=time.time())
                break
            if message.get("event") == "sent":
                sent = message["sent_epoch"]
            else:
                row = message
                break
        if row is None:
            row = dict(category="deadline", sent_epoch=sent, returned_epoch=time.time())
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        row.setdefault("http_status", "")
        row.setdefault("business_code", "")
        row.setdefault("bytes", 0)
        row.setdefault("sha256", "")
        row["elapsed_ms"] = (row["returned_epoch"] - (row["sent_epoch"] or began)) * 1000
        return row
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        receive.close()


def specifications(ctx):
    user = ctx.fixtures[0]
    item = user["files"][1]  # 1 MiB; protected and public shares use the same bytes.
    base = ctx.base + "/api/v1"
    auth = {"Authorization": "Bearer " + user["jwt"]}
    probes = dict(
        login=dict(url=base + "/auth/login", method="POST", data=dict(accountName=user["account"], password=user["password"])),
        files=dict(url=base + "/files?parentId=" + user["directory"], headers=auth),
        personal_download=dict(url=base + "/files/" + item["id"] + "/download", headers=auth, sha256=item["sha256"]),
        share_list=dict(url=base + "/shares", headers=auth),
        frontend=dict(url=ctx.base + "/", html=True))
    for index, share in enumerate(item["shares"]):
        for action in ("verify", "download"):
            probes[f"share_{index}_{action}"] = dict(url=base + "/s/" + share["shareToken"] + "/" + action,
                method="POST", data={"extractCode": share.get("extractCode")})
            if action == "download":
                probes[f"share_{index}_{action}"]["sha256"] = item["sha256"]
    for spec in probes.values():
        spec["timeout"] = 15 if spec.get("sha256") else 5
    return probes


class Scheduler:
    def __init__(self, specs, path):
        self.specs, self.path = specs, path
        self.rows, self.pending, self.stop = [], [], threading.Event()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.pool = ThreadPoolExecutor(max_workers=len(specs) * 17)

    def start(self):
        self.thread.start()
        return self

    def dispatch(self, name, spec, tick, planned):
        began = time.time()
        row = dict(probe=name, tick=tick, planned_epoch=planned, **execute(spec))
        row["schedule_lag_ms"] = ((row["sent_epoch"] or began) - planned) * 1000
        with self.lock:
            self.rows.append(row)

    def loop(self):
        epoch, anchor, tick = time.time(), time.monotonic(), 0
        with self.path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            written = set()
            while not self.stop.is_set():
                for name, spec in self.specs.items():
                    self.pending.append(self.pool.submit(self.dispatch, name, spec, tick, epoch + tick))
                self.flush(writer, written)
                stream.flush()
                tick += 1
                self.stop.wait(max(0, anchor + tick - time.monotonic()))
            self.pool.shutdown(wait=True)
            self.flush(writer, written)

    def flush(self, writer, written):
        with self.lock:
            for row in self.rows:
                key = (row["probe"], row["tick"])
                if key not in written:
                    writer.writerow(row)
                    written.add(key)

    def stable(self, since, count=3):
        with self.lock:
            for name in self.specs:
                rows = sorted((r for r in self.rows if r["probe"] == name and r["planned_epoch"] >= since),
                              key=lambda r: r["tick"])
                if len(rows) < count or any(r["category"] != "ok" for r in rows[-count:]):
                    return False
                if rows[-1]["tick"] - rows[-count]["tick"] != count - 1:
                    return False
        return True

    def finish(self):
        self.stop.set()
        self.thread.join()
        for future in self.pending:
            future.result()


def recovery(rows, after, probes, count=3):
    """First tick of a complete run of successes; late completions retain sent order."""
    recovered = {}
    for name in probes:
        records = sorted((r for r in rows if r["probe"] == name and float(r["planned_epoch"]) >= after),
                         key=lambda r: int(r["tick"]))
        for index in range(len(records) - count + 1):
            window = records[index:index + count]
            if all(r["category"] == "ok" for r in window) and int(window[-1]["tick"]) - int(window[0]["tick"]) == count - 1:
                recovered[name] = float(window[0]["sent_epoch"])
                break
    return recovered
