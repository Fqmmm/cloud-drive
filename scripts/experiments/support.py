"""Shared E3/E4 context: isolated projects, public evidence, private credentials.

All Docker commands use the supplied env/project explicitly. Raw credentials,
database dumps and sample bytes stay in ignored artifacts/, never in reports.
"""
import base64
import codecs
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import secrets
import subprocess
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("mysql", "minio", "auth-service", "file-service", "share-service", "frontend")


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def csv_write(path, rows, fields=None):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]) if rows else fields or [])
        writer.writeheader()
        writer.writerows(rows)


def digest(content):
    return hashlib.sha256(content).hexdigest()


def sample(size):
    return random.Random(20261117 + size).randbytes(size)


def sanitize(text, sensitive=()):
    for value in sorted(set(str(v) for v in sensitive if v), key=len, reverse=True):
        text = text.replace(value, "<redacted>")
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted-jwt>", text)
    return re.sub(r"(/s/)[A-Za-z0-9_-]{22,}", r"\1<redacted>", text)


def validate_project(project):
    if not re.fullmatch(r"cloud-drive-liu-[a-z0-9-]{1,32}", project):
        raise ValueError("Experiments require a dedicated cloud-drive-liu-* project")
    return project


def retained_volumes(before, after, service):
    left = next(r for r in before if r["service"] == service)
    right = next(r for r in after if r["service"] == service)
    volumes = lambda r: sorted((m["Name"], m["Destination"]) for m in r["mounts"] if m["Type"] == "volume")
    return left["id"] != right["id"] and bool(volumes(left)) and volumes(left) == volumes(right)


def run_live(args, public_log, raw_log, sensitive, timeout, cwd, env=None):
    """Spool child output without pipe backpressure; publish redacted lines live.

    Raw bytes stay private. Decode incrementally so UTF-8 text and credentials
    split across file reads are not damaged or leaked by partial redaction.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending = ""
    deadline = time.monotonic() + timeout
    with raw_log.open("wb") as destination, public_log.open("w", encoding="utf-8") as public:
        process = subprocess.Popen(args, cwd=cwd, env=env, stdout=destination, stderr=subprocess.STDOUT)
        try:
            with raw_log.open("rb") as source:
                while True:
                    if process.poll() is None and time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(args, timeout)
                    chunk = source.read(65536)
                    if chunk:
                        pending += decoder.decode(chunk).replace("\r", "\n")
                        lines = pending.split("\n")
                        pending = lines.pop()
                        for line in lines:
                            if line:
                                public.write(sanitize(line, sensitive) + "\n")
                        public.flush()
                    elif process.poll() is not None:
                        pending += decoder.decode(b"", final=True)
                        if pending:
                            public.write(sanitize(pending, sensitive) + "\n")
                            public.flush()
                        break
                    else:
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(args, timeout)
                        time.sleep(.2)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
    return subprocess.CompletedProcess(args, process.returncode,
        raw_log.read_text(encoding="utf-8", errors="replace"), "")


class Context:
    def __init__(self, env_file):
        self.env_file = Path(env_file).resolve()
        self.values = dict(line.split("=", 1) for line in self.env_file.read_text(encoding="utf-8").splitlines()
                           if line and not line.startswith("#") and "=" in line)
        self.project = validate_project(self.values["COMPOSE_PROJECT_NAME"])
        self.base = "http://127.0.0.1:" + self.values["HTTP_PORT"]
        self.private = self.env_file.parent
        self.sensitive = [v for k, v in self.values.items() if any(x in k for x in ("PASSWORD", "SECRET", "TOKEN"))]
        self.audit = None
        self.fixtures = []
        fixtures = self.private / "fixtures.json"
        if fixtures.exists():
            self.fixtures = json.loads(fixtures.read_text(encoding="utf-8"))
            self.remember()

    def remember(self):
        for user in self.fixtures:
            self.sensitive.extend([user["password"], user.get("jwt")])
            for item in user.get("files", []):
                for share in item.get("shares", []):
                    self.sensitive.extend([share["shareToken"], share.get("extractCode")])

    def run(self, args, input_text=None, timeout=300, check=True, private_output=None, record_output=True, env=None, live_log=None):
        began = time.time()
        if live_log:
            if input_text is not None:
                raise ValueError("Live command input is not supported")
            result = run_live(args, live_log, self.private / f"command-{time.time_ns()}.raw.log",
                              self.sensitive, timeout, ROOT, env)
        else:
            result = subprocess.run(args, cwd=ROOT, input=input_text, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
        if private_output:
            private_output.write_text(result.stdout, encoding="utf-8")
        if self.audit:
            # SQL stdin and secret environment values are deliberately omitted.
            with self.audit.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(utc=utc(), start_epoch=began, end_epoch=time.time(),
                    command=sanitize(" ".join(args), self.sensitive), exit_code=result.returncode,
                    output="<private-output>" if private_output or not record_output else sanitize(result.stdout + result.stderr, self.sensitive)),
                    ensure_ascii=False) + "\n")
        if check and result.returncode:
            raise RuntimeError(f"{args[0]} exited {result.returncode}; see execution.jsonl")
        return result

    def compose(self, *args, overrides=None, **kwargs):
        if args[0] in ("down", "rm"):
            raise ValueError("Experiment tools never remove projects or volumes")
        # Compose gives exported shell variables priority over --env-file.
        # Pin our private values, rather than silently using another project's
        # passwords/ports. Only the explicit fault-switch override is allowed.
        environment = os.environ.copy()
        environment.update(self.values)
        if overrides:
            if set(overrides) != {"EXPERIMENT_FAULTS_ENABLED"}:
                raise ValueError("Only the fault switch can override experiment configuration")
            environment.update(overrides)
        return self.run(["docker", "compose", "--env-file", str(self.env_file), "-p", self.project, *args], env=environment, **kwargs)

    def sql(self, statement):
        return self.compose("exec", "-T", "mysql", "bash", "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --protocol=socket -u root -N -B --default-character-set=utf8mb4',
            input_text=statement).stdout.strip()

    def inventory(self):
        ids = self.compose("ps", "-a", "-q").stdout.split()
        if not ids:
            return []
        # Inspect contains secrets; only an explicit projection is public.
        raw = json.loads(self.run(["docker", "inspect", *ids], record_output=False).stdout)
        rows = []
        for item in raw:
            state = item["State"]
            rows.append(dict(service=item["Config"]["Labels"]["com.docker.compose.service"], id=item["Id"],
                image=item["Image"], image_reference=item["Config"]["Image"], path=item["Path"], args=item["Args"],
                started=state["StartedAt"], finished=state["FinishedAt"], status=state["Status"],
                health=state.get("Health", {}).get("Status"), exit_code=state["ExitCode"],
                restart_count=item["RestartCount"], restart_policy=item["HostConfig"]["RestartPolicy"],
                mounts=[{k: m.get(k) for k in ("Type", "Name", "Source", "Destination")} for m in item["Mounts"]]))
        return sorted(rows, key=lambda r: r["service"])

    def ready(self, timeout=300):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = self.inventory()
            if {r["service"] for r in rows} == set(SERVICES) and all(
                    r["status"] == "running" and r["health"] == "healthy" for r in rows):
                return rows
            time.sleep(1)
        raise RuntimeError("Six services did not become healthy")

    def reload(self):
        self.compose("exec", "-T", "frontend", "nginx", "-t")
        self.compose("exec", "-T", "frontend", "nginx", "-s", "reload")

    def snapshot(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        rows = self.inventory()
        save(folder / "containers.json", rows)
        context = self.run(["docker", "context", "show"]).stdout.strip()
        info = self.run(["docker", "info", "--format", "{{json .}}"])
        raw = json.loads(info.stdout)
        info_fields = ("ServerVersion", "OperatingSystem", "OSType", "Architecture", "NCPU", "MemTotal", "DockerRootDir")
        save(folder / "environment.json", dict(utc=utc(), docker_context=context, project=self.project,
            source_commit=self.run(["git", "rev-parse", "HEAD"]).stdout.strip(),
            worktree_status=self.run(["git", "status", "--porcelain=v1"]).stdout,
            python=sys.version, platform=platform.platform(), host_cpu=platform.processor(), host_logical_cpus=os.cpu_count(),
            engine={k: raw.get(k) for k in info_fields},
            compose_version=self.run(["docker", "compose", "version"]).stdout.strip(),
            parameters={k: v for k, v in self.values.items() if not any(x in k for x in ("PASSWORD", "SECRET", "TOKEN"))}))
        source_paths = [ROOT / "compose.yaml", ROOT / ".env.example"]
        for directory in ("scripts", "backend/auth-service", "backend/file-service", "backend/share-service", "frontend/src/course", "frontend/nginx"):
            source_paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file()
                and "target" not in path.parts and "__pycache__" not in path.parts
                and (path.suffix in (".py", ".ps1", ".java", ".yaml", ".yml", ".xml", ".ts", ".vue", ".css", ".conf") or path.name == "Dockerfile"))
        source_paths.extend([ROOT / "frontend/Dockerfile", ROOT / "frontend/package.json", ROOT / "frontend/pnpm-lock.yaml"])
        save(folder / "source-sha256.json", [dict(path=str(path.relative_to(ROOT)), sha256=digest(path.read_bytes()))
             for path in sorted(set(source_paths)) if path.is_file()])
        config = self.compose("config", "--format", "json").stdout
        (folder / "compose.redacted.json").write_text(sanitize(config, self.sensitive), encoding="utf-8")
        return rows

    def logs(self, folder):
        for service in SERVICES:
            result = self.compose("logs", "--no-color", "--timestamps", service, check=False)
            (folder / (service + ".log")).write_text(sanitize(result.stdout + result.stderr, self.sensitive), encoding="utf-8")

    def api(self, path, method="GET", user=None, data=None, files=None, timeout=30):
        with requests.Session() as session:
            session.trust_env = False
            return session.request(method, self.base + "/api/v1" + path, json=data, files=files,
                headers={"Authorization": "Bearer " + user["jwt"]} if user else {}, timeout=timeout, allow_redirects=False)

    def data(self, *args, **kwargs):
        response = self.api(*args, **kwargs)
        if response.status_code != 200 or response.json().get("code") != "00000":
            raise RuntimeError(f"Fixture operation failed: HTTP {response.status_code}")
        return response.json()["data"]

    def login(self, user, minimum=600):
        result = self.data("/auth/login", "POST", data=dict(accountName=user["account"], password=user["password"]))
        user["jwt"] = result["token"]
        claims = json.loads(base64.urlsafe_b64decode(user["jwt"].split(".")[1] + "=="))
        user["exp"] = claims["exp"]
        self.sensitive.append(user["jwt"])
        if user["exp"] - time.time() < minimum:
            raise RuntimeError("JWT does not cover the planned round")
        return result

    def checkpoint(self):
        self.remember()
        save(self.private / "fixtures.json", self.fixtures)

    def prepare(self, folder):
        if self.fixtures:
            raise RuntimeError("Use a new private environment for a new dataset")
        for index in (1, 2):
            account = "liu_" + secrets.token_hex(5) + f"_{index}"
            user = dict(account=account, password=secrets.token_hex(16), files=[])
            self.data("/auth/register", "POST", data=dict(accountName=account, password=user["password"],
                nickname=f"刘骐语实验用户{index}", email=account + "@example.test", accountType="personal"))
            login = self.login(user)
            user.update(userId=login["userId"], accountId=login["accountId"])
            self.fixtures.append(user)
            self.checkpoint()
            user["directory"] = self.data("/directories", "POST", user=user,
                                          data=dict(name="实验 数据", parentId="0"))["id"]
            for size in (1024, 1024 * 1024, 20 * 1024 * 1024):
                content = sample(size)
                name = f"中文 样本 {size}.bin"
                source = self.private / f"source-{size}.bin"
                if not source.exists():
                    source.write_bytes(content)
                item = self.data("/files?parentId=" + user["directory"], "POST", user=user,
                                 files={"file": (name, content, "application/octet-stream")})
                record = dict(id=item["id"], name=name, size=size, sha256=digest(content), shares=[])
                user["files"].append(record)
                for kind in (0, 1):
                    share = self.data("/shares", "POST", user=user,
                        data=dict(fileId=item["id"], accessType=kind, expireDays=7))
                    # Created intentionally omits accessType; retain the input.
                    share["accessType"] = kind
                    record["shares"].append(share)
                self.checkpoint()
        self.wait_cleanup()
        self.verify(folder)
        self.metadata(folder)

    def wait_cleanup(self, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.sql("SELECT COUNT(*) FROM file_db.object_cleanup;") == "0":
                return
            time.sleep(2)
        raise RuntimeError("Object cleanup queue did not drain")

    def verify(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        rows = []
        for user in self.fixtures:
            self.login(user)
            listing = self.data("/files?parentId=" + user["directory"], user=user)["items"]
            if {v["id"] for v in listing} != {v["id"] for v in user["files"]}:
                raise AssertionError("Directory/file identity changed")
            quota = self.data("/quota", user=user)
            if quota["usedBytes"] != sum(item["size"] for item in user["files"]):
                raise AssertionError("Quota differs from fixture")
            for item in user["files"]:
                routes = [("personal", "/files/" + item["id"] + "/download", "GET", user, None)]
                for share in item["shares"]:
                    routes.append(("share-" + str(share["accessType"]), "/s/" + share["shareToken"] + "/download",
                                   "POST", None, {"extractCode": share.get("extractCode")}))
                for kind, path, method, owner, body in routes:
                    response = self.api(path, method, user=owner, data=body)
                    actual = digest(response.content)
                    rows.append(dict(user_id=user["userId"], file_id=item["id"], route=kind,
                        source_bytes=item["size"], download_bytes=len(response.content), source_sha256=item["sha256"],
                        download_sha256=actual, http_status=response.status_code,
                        passed=response.status_code == 200 and actual == item["sha256"] and len(response.content) == item["size"]))
        csv_write(folder / "checksums.csv", rows)
        permissions = []
        for index, user in enumerate(self.fixtures):
            other = self.fixtures[1 - index]
            item = user["files"][0]
            protected = item["shares"][1]
            actual_code = protected["extractCode"]
            wrong = "000000" if actual_code != "000000" else "999999"
            for label, path, method, owner, body in [
                ("cross-user-download", "/files/" + item["id"] + "/download", "GET", other, None),
                ("cross-user-directory", "/files?parentId=" + user["directory"], "GET", other, None),
                ("wrong-extract-code", "/s/" + protected["shareToken"] + "/download", "POST", None, {"extractCode": wrong})]:
                status = self.api(path, method, user=owner, data=body).status_code
                permissions.append(dict(case=label, owner=user["userId"], http_status=status,
                                        passed=status in ((403, 429) if label == "wrong-extract-code" else (403, 404))))
        save(folder / "permissions.json", permissions)
        if not all(r["passed"] for r in rows + permissions):
            raise AssertionError("Download or authorization verification failed")
        return rows

    def metadata(self, folder):
        owners = ",".join(str(int(u["userId"])) for u in self.fixtures)
        queries = dict(
            users=f"SELECT id,nickname,email,status,is_deleted FROM auth_db.sys_user WHERE id IN ({owners}) ORDER BY id;",
            accounts=f"SELECT id,user_id,account_name,account_type,status,is_deleted FROM auth_db.sys_account WHERE user_id IN ({owners}) ORDER BY id;",
            files=f"SELECT id,user_id,parent_id,original_name,file_size,IFNULL(object_key,''),is_directory,is_deleted FROM file_db.sys_file WHERE user_id IN ({owners}) ORDER BY id;",
            quota=f"SELECT user_id,total_quota,used_space FROM file_db.user_quota WHERE user_id IN ({owners}) ORDER BY user_id;",
            shares=f"SELECT id,user_id,file_id,file_name,access_type,expire_time,status FROM share_db.sys_share WHERE user_id IN ({owners}) ORDER BY id;",
            counts="SELECT 'users',COUNT(*) FROM auth_db.sys_user UNION ALL SELECT 'accounts',COUNT(*) FROM auth_db.sys_account UNION ALL SELECT 'files',COUNT(*) FROM file_db.sys_file UNION ALL SELECT 'shares',COUNT(*) FROM share_db.sys_share;",
            cleanup="SELECT object_key,reason,attempts,next_attempt_at FROM file_db.object_cleanup ORDER BY object_key;")
        result = {name: self.sql(query).splitlines() for name, query in queries.items()}
        save(folder / "metadata.json", result)
        baseline = []
        for user in self.fixtures:
            for item in user["files"]:
                key = self.sql(f"SELECT object_key FROM file_db.sys_file WHERE id={int(item['id'])};")
                for share in item["shares"]:
                    baseline.append(dict(user_id=user["userId"], account_id=user["accountId"], directory_id=user["directory"],
                        file_id=item["id"], parent_id=user["directory"], file_name=item["name"], source_bytes=item["size"],
                        source_sha256=item["sha256"], object_key=key, share_id=share["id"], access_type=share["accessType"],
                        expires=share.get("expireTime"), status="ACTIVE"))
        csv_write(folder / "baseline.csv", baseline)
        alias = 'mc alias set liu http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && '
        objects = self.compose("exec", "-T", "minio", "sh", "-c", alias + "mc ls --recursive --json liu/cloud-drive").stdout
        save(folder / "objects.json", [json.loads(line) for line in objects.splitlines() if line.startswith("{")])
        policy = self.compose("exec", "-T", "minio", "sh", "-c", alias + "mc anonymous get-json liu/cloud-drive", check=False).stdout.strip()
        (folder / "bucket-policy.log").write_text(policy, encoding="utf-8")
        private = self.compose("exec", "-T", "minio", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                               "http://127.0.0.1:9000/cloud-drive").stdout.strip()
        if private != "403":
            raise AssertionError("Bucket permits anonymous listing")
        # A denied list operation alone does not prove known object keys private.
        key = self.sql(f"SELECT object_key FROM file_db.sys_file WHERE user_id IN ({owners}) AND is_directory=0 AND is_deleted=0 LIMIT 1;")
        status = self.compose("exec", "-T", "minio", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                              "http://127.0.0.1:9000/cloud-drive/" + key).stdout.strip()
        if status != "403":
            raise AssertionError("Bucket permits anonymous direct object access")
        return result

    def backup(self, label):
        target = self.private / (label + ".sql")
        self.compose("exec", "-T", "mysql", "bash", "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -u root --single-transaction --routines --triggers --set-gtid-purged=OFF --databases auth_db file_db share_db',
            private_output=target)
        return dict(file=target.name, bytes=target.stat().st_size, sha256=digest(target.read_bytes()), private=True)


def init_env(path, project, port, npm_registry=None):
    validate_project(project)
    if npm_registry and not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?/?", npm_registry):
        raise ValueError("Use an HTTPS registry without credentials or query parameters")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Private environment exists; refusing to replace volume credentials")
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    replacements = dict(COMPOSE_PROJECT_NAME=project, HTTP_PORT=str(port), PUBLIC_BASE_URL=f"http://127.0.0.1:{port}",
                        APP_IMAGE_TAG="liu-e3-e4", EXPERIMENT_FAULTS_ENABLED="false")
    if npm_registry:
        replacements["NPM_REGISTRY"] = npm_registry.rstrip("/")
    replacements.update({key: secrets.token_hex(32) for key in
        ("MYSQL_ROOT_PASSWORD", "AUTH_DB_PASSWORD", "FILE_DB_PASSWORD", "SHARE_DB_PASSWORD", "MINIO_ROOT_PASSWORD", "JWT_SECRET", "INTERNAL_API_TOKEN")})
    for key, value in replacements.items():
        text = re.sub(r"(?m)^" + key + r"=.*$", key + "=" + value, text)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
