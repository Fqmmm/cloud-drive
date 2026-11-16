"""Experiment-only API setup and scoped cleanup; credentials stay in artifacts/."""
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import secrets
import subprocess
import threading
import time

import requests

ROOT = Path(__file__).resolve().parents[2]
MIB = 1024 * 1024


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def command(args, input_text=None, timeout=180):
    result = subprocess.run(args, cwd=ROOT, input=input_text, capture_output=True,
                            text=True, encoding="utf-8", timeout=timeout)
    if result.returncode:
        # Never echo docker env, request payloads, mc aliases or SQL error text.
        raise RuntimeError("Command failed: " + args[0] + " (exit " + str(result.returncode) + ")")
    return result.stdout.strip()


def compose(*args, input_text=None, timeout=180):
    return command(["docker", "compose", *args], input_text, timeout)


def sql(statement):
    return compose("exec", "-T", "mysql", "bash", "-c",
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --protocol=socket -u root -N -B file_db', input_text=statement)


def payload(size):
    return random.Random(20261116 + size).randbytes(size)


class Client:
    def __init__(self, base, token=None):
        self.base, self.token = base.rstrip("/"), token
        self.session = requests.Session()
        self.session.trust_env = False
        adapter = requests.adapters.HTTPAdapter(max_retries=0, pool_connections=2, pool_maxsize=2)
        self.session.mount("http://", adapter)

    def request(self, path, method="GET", data=None, files=None, anonymous=False):
        headers = {"Authorization": "Bearer " + self.token} if self.token and not anonymous else {}
        prepared = self.session.prepare_request(requests.Request(method, self.base + "/api/v1" + path,
                                                                json=data, files=files, headers=headers))
        started = time.time()
        clock = time.perf_counter()
        response = self.session.send(prepared, timeout=(3, 30), allow_redirects=False)
        return response, started, time.time(), (time.perf_counter() - clock) * 1000

    def data(self, path, method="GET", data=None, files=None):
        response = self.request(path, method, data, files)[0]
        if response.status_code != 200:
            raise RuntimeError("Setup/cleanup HTTP status " + str(response.status_code))
        result = response.json()
        if result.get("code") != "00000":
            raise RuntimeError("Setup/cleanup business validation failed")
        return result["data"]

    def login(self, fixture, required_seconds=600, refresh=False):
        cached = fixture.get("_token")
        if cached and not refresh:
            claims = json.loads(base64.urlsafe_b64decode(cached.split(".")[1] + "=="))
            if claims["exp"] - time.time() >= required_seconds:
                self.token = cached
                return claims["exp"] - time.time()
        result = self.data("/auth/login", "POST", dict(accountName=fixture["account"], password=fixture["password"]))
        self.token = result["token"]
        fixture["_token"] = self.token
        claims = json.loads(base64.urlsafe_b64decode(self.token.split(".")[1] + "=="))
        if claims["exp"] - time.time() < required_seconds:
            raise RuntimeError("JWT lifetime insufficient; product default was not extended")
        return claims["exp"] - time.time()


def prepare(base, secret_path, users=20, progress=print):
    fixtures = []
    prefix = "e1_" + secrets.token_hex(4)

    def user(index):
        account = prefix + f"_v{index:02}"
        fixture = dict(vu=index, account=account, password=secrets.token_hex(16))
        client = Client(base)
        client.data("/auth/register", "POST", dict(accountName=account, password=fixture["password"],
                    nickname=f"E1 VU {index:02}", email=account + "@example.test", accountType="personal"))
        client.login(fixture)
        fixture["userId"] = client.data("/users/me")["userId"]
        fixture["listDirectory"] = client.data("/directories", "POST", dict(name="E1-list", parentId="0"))["id"]
        fixture["uploadDirectory"] = client.data("/directories", "POST", dict(name="E1-uploads", parentId="0"))["id"]
        fixture["largeDirectory"] = client.data("/directories", "POST", dict(name="E1-large", parentId="0"))["id"]
        ids = []
        for item in range(99):
            ids.append(client.data("/directories", "POST", dict(name=f"entry-{item:03}", parentId=fixture["listDirectory"]))["id"])
        fixture["fileId"] = client.data("/files?parentId=" + fixture["listDirectory"], "POST",
            files={"file": ("seed-1MiB.bin", payload(MIB), "application/octet-stream")})["id"]
        ids.append(fixture["fileId"])
        fixture["baselineIds"] = ids
        fixture["largeFileId"] = None
        if index <= 5:
            fixture["largeFileId"] = client.data("/files?parentId=" + fixture["largeDirectory"], "POST",
                files={"file": ("seed-20MiB.bin", payload(20 * MIB), "application/octet-stream")})["id"]
        share = client.data("/shares", "POST", dict(fileId=fixture["fileId"], accessType=1, expireDays=7))
        fixture["shareId"], fixture["shareToken"], fixture["extractCode"] = share["id"], share["shareToken"], share["extractCode"]
        fixture["baselineBytes"] = client.data("/quota")["usedBytes"]
        if len(client.data("/files?parentId=" + fixture["listDirectory"])["items"]) != 100:
            raise RuntimeError("Fixture must contain exactly 100 list entries")
        return fixture

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(user, index) for index in range(1, users + 1)]
        for future in as_completed(futures):
            fixtures.append(future.result())
            fixtures.sort(key=lambda value: value["vu"])
            save(secret_path, fixtures)
            progress(f"Prepared VU {len(fixtures)}/{users}: 100 entries and independent storage")
    return fixtures


def cleanup_uploads(base, fixtures):
    """Delete only this fixture's upload directory children, then verify physical removal.

    mc batch removal and queue acknowledgements are maintenance after measurement.
    No active object, other account or uncommitted upload queue is touched.
    """
    objects, deleted = [], 0
    for fixture in fixtures:
        client = Client(base)
        client.login(fixture)
        owner = int(fixture["userId"])
        directory = int(fixture["uploadDirectory"])
        pending = sql("SELECT f.object_key FROM file_db.sys_file f LEFT JOIN file_db.object_cleanup c ON c.object_key=f.object_key "
                      f"WHERE f.user_id={owner} AND f.parent_id={directory} AND f.is_directory=0 AND (f.is_deleted=0 OR c.object_key IS NOT NULL)")
        objects.extend(key for key in pending.splitlines() if re.fullmatch(r"[0-9a-f-]{36}", key))
        for item in client.data("/files?parentId=" + str(directory))["items"]:
            client.data("/files/" + item["id"], "DELETE")
            deleted += 1
        quota = client.data("/quota")
        if quota["usedBytes"] != fixture["baselineBytes"]:
            raise RuntimeError("Experiment upload quota did not return to baseline")
    objects = sorted(set(objects))
    if objects:
        alias = 'mc alias set e1 http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" </dev/null >/dev/null && '
        removal = subprocess.run(["docker", "compose", "exec", "-T", "minio", "sh", "-c", alias + "mc rm --force --stdin --json"],
            cwd=ROOT, input="\n".join("e1/cloud-drive/" + key for key in objects) + "\n", capture_output=True, text=True,
            encoding="utf-8", timeout=300)
        listing = compose("exec", "-T", "minio", "sh", "-c", alias + "mc ls --recursive --json e1/cloud-drive", timeout=120)
        remaining = {json.loads(line).get("key") for line in listing.splitlines() if line.startswith("{")}
        if remaining.intersection(objects):
            raise RuntimeError("Physical experiment objects remain after batch cleanup")
        for offset in range(0, len(objects), 500):
            keys = ",".join("'" + key + "'" for key in objects[offset:offset + 500])
            sql("DELETE c FROM file_db.object_cleanup c JOIN file_db.sys_file f ON c.object_key=f.object_key "
                f"WHERE f.is_deleted=1 AND c.object_key IN ({keys})")
        quoted = ",".join(str(int(fixture["userId"])) for fixture in fixtures)
        left = sql("SELECT COUNT(*) FROM file_db.object_cleanup c JOIN file_db.sys_file f ON c.object_key=f.object_key "
                   f"WHERE f.user_id IN ({quoted}) AND f.parent_id IN (" + ",".join(str(int(f["uploadDirectory"])) for f in fixtures) + ")")
        if left != "0":
            raise RuntimeError("Experiment cleanup queue not empty")
    return dict(logical_files_deleted=deleted, scoped_object_keys_checked=len(objects), remaining_objects=0,
                removal_exit_code=removal.returncode if objects else 0,
                quota_restored=True, maintenance_outside_measurement=True)


def checksum(base, fixtures, large=False):
    expected = hashlib.sha256(payload(20 * MIB if large else MIB)).hexdigest()
    records = []
    for fixture in fixtures:
        client = Client(base)
        client.login(fixture)
        file_id = fixture["largeFileId"] if large else fixture["fileId"]
        response = client.request("/files/" + file_id + "/download")[0]
        actual = hashlib.sha256(response.content).hexdigest()
        records.append(dict(vu=fixture["vu"], bytes=len(response.content), sha256=actual, match=response.status_code == 200 and actual == expected))
    if not all(row["match"] for row in records):
        raise RuntimeError("Pre/post-round source checksum failed")
    return records
