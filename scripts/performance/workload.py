"""Closed VU workload, with raw request/iteration cohorts and no credential output."""
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import re
import threading
import time

import requests

from common import Client, MIB, payload


class Workload:
    def __init__(self, base, fixtures, folder, run_id, scenario, upload_cap=150):
        self.base, self.fixtures, self.folder, self.scenario = base, fixtures, folder, scenario
        self.run_id, self.upload_cap = run_id, upload_cap
        self.size = 20 * MIB if scenario.startswith("P5") else MIB
        self.content = payload(self.size)
        self.sha256 = hashlib.sha256(self.content).hexdigest()
        self.clients = [Client(base) for _ in fixtures]
        self.jwt_remaining = [client.login(fixture, refresh=True) for client, fixture in zip(self.clients, fixtures)]
        self.upload_counts = [0] * len(fixtures)
        self.cap_hits = [False] * len(fixtures)
        self.lock = threading.Lock()
        self.totals = {}
        self.files = []
        self.writers = {}
        definitions = {
            "requests": ["phase", "vu", "iteration", "operation", "start_epoch", "end_epoch", "latency_ms", "status", "success", "error_category", "error_code", "payload_bytes"],
            "iterations": ["phase", "vu", "iteration", "start_epoch", "end_epoch", "latency_ms", "success"],
            "errors": ["phase", "vu", "iteration", "operation", "start_epoch", "status", "error_category", "error_code"],
        }
        for name, fields in definitions.items():
            file = (folder / (name + ".csv")).open("w", newline="", encoding="utf-8")
            self.files.append(file)
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            self.writers[name] = writer

    def request(self, index, phase, iteration, operation, path, deadline, method="GET", data=None, files=None, anonymous=False):
        began, clock = time.time(), time.perf_counter()
        success, category, code, status, byte_count = False, "", "", 0, 0
        try:
            response, began, ended, latency = self.clients[index].request(path, method, data, files, anonymous)
            status = response.status_code
            if status != 200:
                category = {400: "parameter", 401: "authentication", 403: "authorization", 409: "conflict_or_quota",
                            413: "size", 429: "rate_limit", 502: "dependency", 503: "dependency", 504: "timeout"}.get(status, "http")
                try:
                    actual = response.json().get("code", "")
                    code = actual if isinstance(actual, str) and re.fullmatch(r"[A-Z0-9_]{1,64}", actual) else "HTTP_ERROR"
                except ValueError:
                    code = "NON_JSON_ERROR"
            elif operation in ("download", "share_download"):
                byte_count = len(response.content)
                success = byte_count == self.size
                if operation == "share_download":
                    success = success and hashlib.sha256(response.content).hexdigest() == self.sha256
            else:
                root = response.json()
                value = root.get("data")
                success = root.get("code") == "00000" and isinstance(value, dict)
                if success and operation == "list":
                    success = isinstance(value.get("breadcrumb"), list) and isinstance(value.get("items"), list)
                    success = success and {item.get("id") for item in value["items"]} == set(self.fixtures[index]["baselineIds"])
                    success = success and len(value["items"]) == 100
                elif success and operation == "upload":
                    success = isinstance(value.get("id"), str) and bool(re.fullmatch(r"[1-9][0-9]*", value["id"])) and value.get("fileSize") == self.size
                    byte_count = self.size if success else 0
                elif success and operation == "share_verify":
                    success = value.get("fileSize") == self.size and value.get("requiresCode") is True
            if not success and not category:
                category, code = "validation", "RESPONSE_VALIDATION_FAILED"
        except requests.Timeout:
            ended, latency, category, code = time.time(), (time.perf_counter() - clock) * 1000, "timeout", "CLIENT_TIMEOUT"
        except requests.RequestException:
            ended, latency, category, code = time.time(), (time.perf_counter() - clock) * 1000, "network", "CLIENT_NETWORK_ERROR"
        except (ValueError, KeyError, TypeError, AttributeError):
            ended, latency, category, code = time.time(), (time.perf_counter() - clock) * 1000, "validation", "INVALID_RESPONSE_STRUCTURE"
        cohort = phase if began < deadline else phase + "_drain"
        row = dict(phase=cohort, vu=index + 1, iteration=iteration, operation=operation, start_epoch=began,
                   end_epoch=ended, latency_ms=latency, status=status, success=int(success),
                   error_category=category, error_code=code, payload_bytes=byte_count if success else 0)
        with self.lock:
            self.writers["requests"].writerow(row)
            count, failures = self.totals.get(cohort, (0, 0))
            self.totals[cohort] = (count + 1, failures + int(not success))
            if not success:
                self.writers["errors"].writerow({key: row[key] for key in ["phase", "vu", "iteration", "operation", "start_epoch", "status", "error_category", "error_code"]})
        return success

    def phase(self, name, seconds, progress):
        starts = time.time() + 0.25
        deadline = starts + seconds
        progress(f"{name}: started; duration={seconds}s; VUs={len(self.fixtures)}")

        def user(index):
            fixture = self.fixtures[index]
            time.sleep(max(0, starts + index / len(self.fixtures) - time.time()))
            iteration = 0
            while time.time() < deadline:
                if self.scenario in ("P2", "P5U") and self.upload_counts[index] >= self.upload_cap:
                    self.cap_hits[index] = True
                    time.sleep(min(1, max(0, deadline - time.time())))
                    continue
                iteration += 1
                began, clock = time.time(), time.perf_counter()
                if self.scenario == "P1":
                    success = self.request(index, name, iteration, "list", "/files?parentId=" + fixture["listDirectory"], deadline)
                elif self.scenario in ("P2", "P5U"):
                    self.upload_counts[index] += 1
                    filename = f"{self.run_id[-30:]}-v{index + 1}-{name}-{iteration}.bin"
                    success = self.request(index, name, iteration, "upload", "/files?parentId=" + fixture["uploadDirectory"], deadline,
                        method="POST", files={"file": (filename, self.content, "application/octet-stream")})
                elif self.scenario in ("P3", "P5D"):
                    file_id = fixture["largeFileId"] if self.scenario == "P5D" else fixture["fileId"]
                    success = self.request(index, name, iteration, "download", "/files/" + file_id + "/download", deadline)
                else:
                    path = "/s/" + fixture["shareToken"]
                    data = dict(extractCode=fixture["extractCode"])
                    success = self.request(index, name, iteration, "share_verify", path + "/verify", deadline,
                                           method="POST", data=data, anonymous=True)
                    if success:
                        success = self.request(index, name, iteration, "share_download", path + "/download", deadline,
                                               method="POST", data=data, anonymous=True)
                with self.lock:
                    self.writers["iterations"].writerow(dict(phase=name, vu=index + 1, iteration=iteration,
                        start_epoch=began, end_epoch=time.time(), latency_ms=(time.perf_counter() - clock) * 1000, success=int(success)))
                time.sleep(min(1, max(0, deadline - time.time())))

        with ThreadPoolExecutor(max_workers=len(self.fixtures)) as pool:
            futures = [pool.submit(user, index) for index in range(len(self.fixtures))]
            heartbeat = time.time() + 30
            while any(not future.done() for future in futures):
                time.sleep(min(5, max(0.1, deadline - time.time())))
                if time.time() >= heartbeat:
                    with self.lock:
                        count, failures = self.totals.get(name, (0, 0))
                    progress(f"{name}: elapsed={time.time() - starts:.0f}s requests={count} failed={failures}")
                    heartbeat = time.time() + 30
            for future in futures:
                future.result()
        for file in self.files:
            file.flush()
        progress(f"{name}: finished; drain={max(0, time.time() - deadline):.3f}s")
        return dict(start_epoch=starts, end_epoch=deadline, actual_drain_seconds=max(0, time.time() - deadline))

    def close(self):
        for client in self.clients:
            client.session.close()
        for file in self.files:
            file.close()
