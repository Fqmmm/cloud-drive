"""FR-01..FR-12 acceptance against the running root Compose project.

Uses new random test accounts. SQL fault/limit changes target only those accounts
and shares. --with-outages briefly stops this project's storage/file service and
always starts them again. Never deletes volumes or uses A's disposable stack.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
from threading import Thread
import time

import requests

ROOT = Path(__file__).resolve().parents[2]


class Acceptance:
    def __init__(self, base, env_file=None, project=None):
        self.base = base.rstrip("/")
        self.env_file = Path(env_file or ROOT / ".env").resolve()
        self.project = project
        self.http = requests.Session()
        self.http.trust_env = False
        self.settings = dict(line.split("=", 1) for line in self.env_file.read_text(
            encoding="utf-8").splitlines() if line and not line.startswith("#") and "=" in line)
        self.suffix = secrets.token_hex(5)
        self.password = secrets.token_hex(16)
        self.results = []
        self.sensitive = [self.password]
        self.stopped = set()
        self.files = []
        self.shares = []

    def check(self, requirement, label, condition):
        status = "PASS" if condition else "FAIL"
        self.results.append(dict(requirement=requirement, case=label, status=status))
        print(f"{status} {requirement}: {label}", flush=True)
        if not condition:
            raise AssertionError(f"{requirement}: {label}")

    def api(self, path, method="GET", data=None, token=None, files=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        response = self.http.request(method, self.base + "/api/v1" + path,
                                     json=data, files=files, headers=headers,
                                     timeout=150, allow_redirects=False)
        return response

    def data(self, response):
        if response.status_code != 200 or response.json().get("code") != "00000":
            raise AssertionError("Expected successful API response")
        return response.json()["data"]

    def compose(self, *args, sql=None):
        context = ["--env-file", str(self.env_file)]
        if self.project:
            context.extend(["-p", self.project])
        result = subprocess.run(["docker", "compose", *context, *args], cwd=ROOT, input=sql,
                                capture_output=True, text=True, encoding="utf-8", timeout=90)
        if result.returncode:
            raise RuntimeError("Compose acceptance operation failed")
        return result.stdout.strip()

    def sql(self, statement):
        return self.compose("exec", "-T", "mysql", "bash", "-c",
                            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --protocol=socket -u root -N -B',
                            sql=statement)

    def upload(self, name, content, token=None, parent=None):
        return self.api("/files?parentId=" + (parent or self.directory), "POST", token=token or self.token,
                        files={"file": (name, content, "application/octet-stream")})

    def quota(self):
        return self.data(self.api("/quota", token=self.token))

    def share(self, kind=0, days=7):
        created = self.data(self.api("/shares", "POST", dict(fileId=self.file, accessType=kind,
                            expireDays=days), self.token))
        self.shares.append(created["id"])
        self.sensitive.extend([created["shareToken"], created.get("extractCode") or "<none>"])
        return created

    def signed_expired_token(self, user, account):
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
        now = int(time.time())
        header = encode(dict(alg="HS256", typ="JWT"))
        payload = encode(dict(sub=user, accountId=account, iat=now - 600, exp=now - 1,
                              iss=self.settings["JWT_ISSUER"], aud=[self.settings["JWT_AUDIENCE"]]))
        body = header + b"." + payload
        signature = base64.urlsafe_b64encode(hmac.new(self.settings["JWT_SECRET"].encode(), body,
                                                     hashlib.sha256).digest()).rstrip(b"=")
        token = (body + b"." + signature).decode()
        self.sensitive.append(token)
        return token

    def accounts(self):
        owner = dict(accountName="Owner_" + self.suffix, password=self.password,
                     nickname="课程验收用户", email="owner_" + self.suffix + "@example.test", accountType="personal")
        other = dict(owner, accountName="other_" + self.suffix, email="other_" + self.suffix + "@example.test")
        for payload in [owner, other]:
            self.check("FR-01", "valid personal registration", self.api("/auth/register", "POST", payload).status_code == 200)
        self.check("FR-01", "case-insensitive duplicate account rejected", self.api("/auth/register", "POST",
                   dict(owner, accountName=owner["accountName"].lower(), email="duplicate_" + self.suffix + "@example.test")).status_code == 409)
        self.check("FR-01", "duplicate email rejected", self.api("/auth/register", "POST",
                   dict(owner, accountName="new_" + self.suffix)).status_code == 409)
        for field, value in [("accountName", "ab"), ("accountName", "x" * 33), ("accountName", "bad-name"),
                             ("password", "short"), ("password", "x" * 65), ("nickname", ""),
                             ("nickname", "x" * 33), ("email", "invalid"), ("accountType", "team")]:
            invalid = dict(owner, **{field: value})
            self.check("FR-01", "invalid registration " + field + " rejected",
                       self.api("/auth/register", "POST", invalid).status_code == 400)
        self.check("FR-01", "missing required fields rejected", self.api("/auth/register", "POST", {}).status_code == 400)
        self.check("FR-02", "wrong credentials rejected", self.api("/auth/login", "POST",
                   dict(accountName=owner["accountName"], password="wrong-password")).status_code == 401)
        login = self.data(self.api("/auth/login", "POST", dict(accountName=owner["accountName"].lower(), password=self.password)))
        other_login = self.data(self.api("/auth/login", "POST", dict(accountName=other["accountName"], password=self.password)))
        self.token, self.other_token = login["token"], other_login["token"]
        self.owner_id = int(login["userId"])
        self.sensitive.extend([self.token, self.other_token])
        profile = self.data(self.api("/users/me", token=self.token))
        self.check("FR-02", "normalized login and minimal string-ID profile", profile["accountName"] == owner["accountName"].lower()
                   and isinstance(profile["userId"], str) and set(profile) == {"userId", "accountId", "nickname", "accountName", "email"})
        self.expired = self.signed_expired_token(login["userId"], login["accountId"])
        for token in [None, self.token + "x", self.expired]:
            self.check("FR-02", "missing forged or expired credentials rejected", self.api("/quota", token=token).status_code == 401)
        self.check("FR-01", "password stored only as a strong hash", self.sql(
            f"SELECT password LIKE '{{bcrypt-sha256}}$2a$12$%' FROM auth_db.sys_account WHERE id={int(login['accountId'])}") == "1")

    def directories_and_files(self):
        self.directory = self.data(self.api("/directories", "POST", dict(name="  课程 资料  ", parentId="0"), self.token))["id"]
        listing = self.data(self.api("/files?parentId=" + self.directory, token=self.token))
        self.check("FR-03", "empty directory and breadcrumb", listing["items"] == [] and listing["breadcrumb"][-1]["name"] == "课程 资料")
        self.check("FR-03", "other user cannot browse private directory", self.api("/files?parentId=" + self.directory, token=self.other_token).status_code == 404)
        for name in [" ", ".", "..", "bad/name", "bad\\name", "bad\nname", "x" * 256]:
            self.check("FR-04", "invalid directory name rejected", self.api("/directories", "POST", dict(name=name, parentId=self.directory), self.token).status_code == 400)
        for name in ["Case", "case", "x" * 255]:
            item = self.data(self.api("/directories", "POST", dict(name=name, parentId=self.directory), self.token))
            self.check("FR-04", "case-sensitive names and 255-character boundary accepted", isinstance(item["id"], str))
            self.api("/directories/" + item["id"], "DELETE", token=self.token)
        renamed = self.data(self.api("/directories/" + self.directory + "/rename", "PUT", dict(name="归档 资料"), self.token))
        self.check("FR-04", "directory rename keeps identity", renamed["id"] == self.directory and renamed["originalName"] == "归档 资料")
        self.original_quota = self.quota()["totalBytes"]
        self.check("FR-08", "default total quota and zero directory usage", self.original_quota == int(self.settings["DEFAULT_QUOTA_BYTES"]) and self.quota()["usedBytes"] == 0)
        self.content = bytes(index % 251 for index in range(65536))
        self.file = self.data(self.upload("课程 文件.bin", self.content))["id"]
        self.files.append(self.file)
        self.check("FR-05", "upload increases usage by actual bytes", self.quota()["usedBytes"] == len(self.content))
        self.check("FR-05", "duplicate upload rejected", self.upload("课程 文件.bin", self.content).status_code == 409)
        self.check("FR-04", "file and directory share a name space", self.api("/directories", "POST", dict(name="课程 文件.bin", parentId=self.directory), self.token).status_code == 409)
        self.check("FR-04", "nonempty directory cannot be deleted", self.api("/directories/" + self.directory, "DELETE", token=self.token).status_code == 409)
        occupied = self.data(self.api("/directories", "POST", dict(name="occupied", parentId=self.directory), self.token))["id"]
        self.check("FR-06", "file rename cannot conflict with a directory", self.api("/files/" + self.file + "/rename", "PUT", dict(name="occupied"), self.token).status_code == 409)
        self.api("/directories/" + occupied, "DELETE", token=self.token)
        downloaded = self.api("/files/" + self.file + "/download", token=self.token)
        self.check("FR-06", "owner download SHA-256 matches", downloaded.status_code == 200 and hashlib.sha256(downloaded.content).digest() == hashlib.sha256(self.content).digest())
        self.check("FR-06", "download supplies a filename", "filename" in downloaded.headers.get("Content-Disposition", ""))
        for path, method, data in [("/files/" + self.file + "/download", "GET", None),
                                   ("/files/" + self.file + "/rename", "PUT", dict(name="越权")),
                                   ("/files/" + self.file, "DELETE", None),
                                   ("/shares", "POST", dict(fileId=self.file, accessType=0, expireDays=7))]:
            self.check("FR-03", "cross-user file operation rejected", self.api(path, method, data, self.other_token).status_code == 404)
        other_root = self.data(self.api("/files", token=self.other_token))
        self.check("FR-03", "other user's root contains no owner entries", not other_root["items"])
        self.check("FR-05", "single-file limit enforced", self.upload("too-large.bin", bytes(int(self.settings["MAX_FILE_BYTES"]) + 1)).status_code == 413)
        self.check("FR-05", "failed uploads leave quota unchanged", self.quota()["usedBytes"] == len(self.content))
        self.sql(f"UPDATE file_db.user_quota SET total_quota={len(self.content) + 800000} WHERE user_id={self.owner_id}")
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                uploaded = list(pool.map(lambda i: self.upload(f"concurrent-{i}.bin", bytes(400000)), range(3)))
            self.check("FR-08", "three concurrent uploads cannot exceed quota", sorted(r.status_code for r in uploaded) == [200, 200, 409])
            for response in uploaded:
                if response.status_code == 200:
                    item = self.data(response)["id"]
                    self.files.append(item)
                    self.api("/files/" + item, "DELETE", token=self.token)
        finally:
            self.sql(f"UPDATE file_db.user_quota SET total_quota={self.original_quota} WHERE user_id={self.owner_id}")
        self.check("FR-08", "delete restores usage even before physical cleanup", self.quota()["usedBytes"] == len(self.content))

    def sharing(self):
        for request in [dict(fileId=self.directory, accessType=0, expireDays=7),
                        dict(fileId=self.file, accessType=2, expireDays=7),
                        dict(fileId=self.file, accessType=0, expireDays=2)]:
            self.check("FR-09", "directory or invalid share settings rejected", self.api("/shares", "POST", request, self.token).status_code == 400)
        for days in [1, 7, 30, None]:
            created = self.share(days=days)
            expiry = created["expireTime"]
            valid = expiry is None if days is None else abs((datetime.fromisoformat(expiry.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() - days * 86400) < 15
            self.check("FR-09", "supported share expiration", valid)
        self.public = self.share()
        self.protected = self.share(kind=1)
        # Exercise a real generated leading-zero code, without changing the stored hash.
        for _ in range(100):
            if self.protected["extractCode"].startswith("0"):
                break
            self.protected = self.share(kind=1)
        code = self.protected["extractCode"]
        self.check("FR-09", "generated six-digit code preserves leading zero", isinstance(code, str) and bool(re.fullmatch("0[0-9]{5}", code)))
        self.check("FR-09", "share URL points to frontend", self.protected["shareUrl"].startswith(self.base + "/#/s/"))
        public_path = "/s/" + self.public["shareToken"]
        path = "/s/" + self.protected["shareToken"]
        details = self.data(self.api(path))
        self.check("FR-10", "protected metadata is hidden before verification", details["requiresCode"] and details["fileName"] is None and details["fileSize"] is None)
        for bad in [None, 123456, "bad"]:
            self.check("FR-10", "missing numeric or malformed code rejected", self.api(path + "/download", "POST", dict(extractCode=bad)).status_code == 403)
        limit = int(self.settings["SHARE_CODE_MAX_FAILURES"])
        wrong = "999999" if code != "999999" else "888888"
        statuses = [self.api(path + "/verify", "POST", dict(extractCode=wrong)).status_code for _ in range(limit + 1)]
        self.check("FR-10", "wrong-code rate limit applies", 429 in statuses)
        verified = self.data(self.api(path + "/verify", "POST", dict(extractCode=code)))
        self.check("FR-10", "correct code bypasses wrong-attempt limit", verified["fileSize"] == len(self.content))
        for endpoint, data in [(public_path, {}), (path, dict(extractCode=code))]:
            downloaded = self.api(endpoint + "/download?fileId=999999", "POST", data)
            self.check("FR-10", "anonymous download is restricted to shared bytes", downloaded.status_code == 200 and downloaded.content == self.content)
        self.check("FR-10", "download rechecks code after verify", self.api(path + "/download", "POST", dict(extractCode=wrong)).status_code == 429)
        self.api("/files/" + self.file + "/rename", "PUT", dict(name="当前 名称.bin"), self.token)
        self.check("FR-06", "rename keeps file parent content and usage", self.quota()["usedBytes"] == len(self.content) and self.api("/files/" + self.file + "/download", token=self.token).content == self.content)
        self.check("FR-06", "old share uses current filename", self.data(self.api(public_path))["fileName"] == "当前 名称.bin")
        entries = self.data(self.api("/shares", token=self.token))
        self.check("FR-11", "share list retains original name and hides plaintext code", all(e["fileName"] == "课程 文件.bin" and "extractCode" not in e for e in entries))
        self.check("FR-11", "other user's share list is isolated", self.data(self.api("/shares", token=self.other_token)) == [])
        self.check("FR-11", "other user cannot cancel owner share", self.api("/shares/" + self.public["id"], "DELETE", token=self.other_token).status_code == 404)
        for _ in range(2):
            self.check("FR-11", "share cancellation is idempotent", self.api("/shares/" + self.public["id"], "DELETE", token=self.token).status_code == 200)
        self.check("FR-12", "cancelled share has distinct error", self.api(public_path).json()["code"] == "SHARE_CANCELLED")
        self.check("FR-11", "cancelling one share leaves another usable", self.api(path + "/download", "POST", dict(extractCode=code)).status_code == 200)
        self.expiring = self.share()
        self.sql(f"UPDATE share_db.sys_share SET expire_time=UTC_TIMESTAMP()-INTERVAL 1 SECOND WHERE id={int(self.expiring['id'])}")
        self.check("FR-12", "expired share is rejected by server", self.api("/s/" + self.expiring["shareToken"]).json()["code"] == "SHARE_EXPIRED")
        entries = self.data(self.api("/shares", token=self.token))
        self.check("FR-11", "history lists active cancelled and expired shares", {"ACTIVE", "CANCELLED", "EXPIRED"} <= {e["status"] for e in entries})
        self.check("FR-12", "nonexistent share has distinct error", self.api("/s/" + secrets.token_urlsafe(16)).json()["code"] == "SHARE_NOT_FOUND")

    def outage(self):
        path = "/s/" + self.protected["shareToken"]
        code = dict(extractCode=self.protected["extractCode"])
        for service in ["file-service", "minio"]:
            before = self.quota()["usedBytes"]
            self.stopped.add(service)
            self.compose("stop", service)
            try:
                if service == "minio":
                    self.check("FR-05", "storage outage rejects upload", self.upload("unavailable.bin", b"not saved").status_code == 503)
                    self.check("FR-05", "storage outage preserves usage and list", self.quota()["usedBytes"] == before and self.api("/files", token=self.token).status_code == 200)
                self.check("FR-12", service + " outage returns dependency error", self.api(path + "/download", "POST", code).status_code == 503)
            finally:
                self.compose("start", service)
                self.stopped.discard(service)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if self.api(path + "/download", "POST", code).status_code == 200:
                    break
                time.sleep(2)
            self.check("FR-10", service + " recovery restores original link", self.api(path + "/download", "POST", code).content == self.content)

    def deletion(self):
        self.check("FR-07", "permanent delete succeeds", self.api("/files/" + self.file, "DELETE", token=self.token).status_code == 200)
        self.check("FR-07", "repeated delete cannot decrement usage twice", self.api("/files/" + self.file, "DELETE", token=self.token).status_code == 404 and self.quota()["usedBytes"] == 0)
        self.check("FR-07", "deleted file cannot be downloaded", self.api("/files/" + self.file + "/download", token=self.token).status_code == 404)
        protected = "/s/" + self.protected["shareToken"]
        self.check("FR-12", "deleted source invalidates protected download", self.api(protected + "/download", "POST", dict(extractCode=self.protected["extractCode"])).json()["code"] == "SHARE_FILE_UNAVAILABLE")
        replacement = self.data(self.upload("当前 名称.bin", b"replacement"))["id"]
        self.files.append(replacement)
        self.check("FR-07", "replacement cannot revive old share", replacement != self.file and self.api(protected + "/verify", "POST", dict(extractCode=self.protected["extractCode"])).status_code == 404)
        self.api("/files/" + replacement, "DELETE", token=self.token)
        self.check("FR-04", "empty directory can be deleted", self.api("/directories/" + self.directory, "DELETE", token=self.token).status_code == 200)

    def browser(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            owner_context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            other_context = browser.new_context()
            anonymous_context = browser.new_context()
            page, other, anonymous = [context.new_page() for context in [owner_context, other_context, anonymous_context]]
            origins = []
            for current in [page, other, anonymous]:
                current.on("request", lambda request: origins.append(request.url.split("/api/")[0]) if "/api/" in request.url else None)

            def register(current, name):
                current.goto(self.base + "/#/login")
                current.get_by_role("button", name="创建个人账户", exact=True).click()
                current.get_by_label("账户名", exact=True).fill(name)
                current.get_by_label("密码", exact=True).fill(self.password)
                self.check("FR-01", "browser password input is masked", current.get_by_label("密码", exact=True).get_attribute("type") == "password")
                current.get_by_label("昵称", exact=True).fill("浏览器验收")
                current.get_by_label("邮箱", exact=True).fill(name + "@example.test")
                current.get_by_role("button", name="注册", exact=True).click()
                expect(current.get_by_text("注册成功，请登录", exact=True)).to_be_visible()
                self.check("FR-01", "browser successful registration clears password", current.get_by_label("密码", exact=True).input_value() == "")
                current.get_by_role("button", name="创建个人账户", exact=True).click()
                current.get_by_label("密码", exact=True).fill(self.password)
                current.get_by_role("button", name="注册", exact=True).click()
                expect(current.get_by_text("邮箱已注册", exact=True)).to_be_visible()
                self.check("FR-01", "browser duplicate registration retains non-sensitive fields", current.get_by_label("账户名", exact=True).input_value() == name)
                current.get_by_role("button", name="已有账户，去登录", exact=True).click()
                current.get_by_label("密码", exact=True).fill("wrong-password")
                current.get_by_role("button", name="登录", exact=True).click()
                expect(current.get_by_text("账户或密码错误", exact=True)).to_be_visible()
                current.get_by_label("密码", exact=True).fill(self.password)
                current.get_by_role("button", name="登录", exact=True).click()
                expect(current.get_by_role("heading", name="个人文件", exact=True)).to_be_visible()

            def download(current, button, filename):
                with current.expect_download() as pending:
                    current.get_by_role("button", name=button, exact=True).click()
                saved = pending.value
                self.check("FR-06", "browser download filename and SHA-256", saved.suggested_filename == filename and Path(saved.path()).read_bytes() == self.content)

            try:
                register(page, "uiowner_" + self.suffix)
                self.check("FR-01", "browser registration enters personal files", page.url.endswith("#/files"))
                page.reload()
                expect(page.get_by_text("浏览器验收", exact=True)).to_be_visible()
                expect(page.get_by_text("已用 0 B", exact=False)).to_be_visible()
                self.check("FR-02", "browser refresh preserves login and profile", True)
                expect(page.get_by_text("当前目录为空，可以新建目录或上传文件", exact=True)).to_be_visible()
                page.get_by_label("新目录名称").fill("浏览器 目录")
                page.get_by_role("button", name="新建目录", exact=True).click()
                page.get_by_role("button", name="浏览器 目录 /", exact=True).click()
                expect(page.get_by_role("navigation", name="文件路径").get_by_text("浏览器 目录", exact=True)).to_be_visible()
                self.check("FR-03", "browser empty state directory navigation and breadcrumb", True)
                page.get_by_label("选择上传文件").set_input_files(dict(name="界面 文件.bin", mimeType="application/octet-stream", buffer=self.content))
                page.route("**/api/v1/files?parentId=*", lambda route: route.abort("internetdisconnected") if route.request.method == "POST" else route.continue_())
                page.get_by_role("button", name="上传文件", exact=True).click()
                expect(page.get_by_text("连接失败，请检查网络后重试", exact=True)).to_be_visible()
                page.unroute("**/api/v1/files?parentId=*")
                pending_upload = []
                page.route("**/api/v1/files?parentId=*", lambda route: pending_upload.append(route) if route.request.method == "POST" else route.continue_())
                page.get_by_role("button", name="上传文件", exact=True).click()
                expect(page.get_by_role("button", name="上传文件", exact=True)).to_be_disabled()
                expect(page.get_by_text("正在上传，请稍候…", exact=True)).to_be_visible()
                self.check("FR-05", "browser upload shows progress and blocks duplicate click", True)
                pending_upload[0].continue_()
                page.unroute("**/api/v1/files?parentId=*")
                expect(page.get_by_text("界面 文件.bin", exact=True)).to_be_visible()
                expect(page.get_by_text("已用 64.0 KiB", exact=False)).to_be_visible()
                self.check("FR-08", "browser upload refreshes used and available capacity", True)
                self.check("FR-05", "browser upload failure is visible and retry succeeds", True)
                content, origin = self.content, self.base
                class InterruptedDownload(BaseHTTPRequestHandler):
                    def log_message(self, *args):
                        pass

                    def do_OPTIONS(self):
                        self.send_response(204)
                        self.send_header("Access-Control-Allow-Origin", origin)
                        self.send_header("Access-Control-Allow-Headers", "authorization,content-type")
                        self.end_headers()

                    def do_GET(self):
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Access-Control-Allow-Origin", origin)
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content[:1024])
                        self.wfile.flush()
                        self.close_connection = True

                fault = ThreadingHTTPServer(("127.0.0.1", 0), InterruptedDownload)
                worker = Thread(target=fault.serve_forever, daemon=True)
                worker.start()
                try:
                    page.route("**/api/v1/files/*/download", lambda route: route.continue_(url=f"http://127.0.0.1:{fault.server_port}/interrupted"))
                    page.get_by_role("button", name="下载", exact=True).click()
                    expect(page.get_by_text("下载中断，请重试", exact=True)).to_be_visible()
                    self.check("FR-06", "browser detects a truncated transfer and discards it", True)
                finally:
                    page.unroute("**/api/v1/files/*/download")
                    fault.shutdown()
                    fault.server_close()
                    worker.join(timeout=2)
                download(page, "下载", "界面 文件.bin")
                self.check("FR-06", "browser failed download can be retried", True)
                page.once("dialog", lambda dialog: dialog.accept("改名 文件.bin"))
                page.get_by_role("button", name="重命名", exact=True).click()
                expect(page.get_by_text("改名 文件.bin", exact=True)).to_be_visible()
                page.get_by_role("button", name="分享", exact=True).click()
                page.get_by_role("button", name="创建分享", exact=True).click()
                public_url = page.get_by_label("分享地址", exact=True).input_value()
                page.get_by_role("button", name="复制链接及提取码", exact=True).click()
                self.check("FR-09", "browser clipboard contains public URL", page.evaluate("navigator.clipboard.readText()") == public_url)
                page.get_by_label("访问方式").select_option("1")
                page.route("**/api/v1/shares", lambda route: route.abort("internetdisconnected") if route.request.method == "POST" else route.continue_())
                page.get_by_role("button", name="创建分享", exact=True).click()
                expect(page.get_by_text("连接失败，请检查网络后重试", exact=True)).to_be_visible()
                expect(page.get_by_label("分享地址", exact=True)).to_have_count(0)
                self.check("FR-09", "browser failed creation clears stale success URL", True)
                page.unroute("**/api/v1/shares")
                page.get_by_role("button", name="创建分享", exact=True).click()
                expect(page.locator("[aria-label='新分享结果'] strong")).to_be_visible()
                code = page.locator("[aria-label='新分享结果'] strong").inner_text()
                protected_url = page.get_by_label("分享地址", exact=True).input_value()
                self.sensitive.extend([code, public_url.split("/s/")[-1], protected_url.split("/s/")[-1]])
                page.get_by_role("button", name="复制链接及提取码", exact=True).click()
                self.check("FR-09", "browser clipboard preserves protected URL and code", page.evaluate("navigator.clipboard.readText()") == protected_url + " 提取码：" + code)
                register(other, "uiother_" + self.suffix)
                expect(other.get_by_text("当前目录为空，可以新建目录或上传文件", exact=True)).to_be_visible()
                self.check("FR-03", "second browser user has separate empty space", True)
                anonymous.goto(public_url)
                expect(anonymous.get_by_text("改名 文件.bin", exact=True)).to_be_visible()
                download(anonymous, "下载文件", "改名 文件.bin")
                anonymous.goto(protected_url)
                expect(anonymous.get_by_text("改名 文件.bin", exact=True)).to_have_count(0)
                anonymous.get_by_label("提取码", exact=True).fill("999999" if code != "999999" else "888888")
                anonymous.get_by_role("button", name="验证提取码", exact=True).click()
                expect(anonymous.get_by_text("请输入正确提取码", exact=True)).to_be_visible()
                self.check("FR-10", "browser wrong code stays on anonymous page without details", "/#/s/" in anonymous.url)
                anonymous.get_by_label("提取码", exact=True).fill(code)
                anonymous.get_by_role("button", name="验证提取码", exact=True).click()
                expect(anonymous.get_by_text("改名 文件.bin", exact=True)).to_be_visible()
                download(anonymous, "下载文件", "改名 文件.bin")
                public_row = page.get_by_role("row").filter(has_text="公开").filter(has_text="改名 文件.bin")
                page.once("dialog", lambda dialog: dialog.accept())
                public_row.get_by_role("button", name="取消分享", exact=True).click()
                expect(public_row.get_by_text("已取消", exact=True)).to_be_visible()
                anonymous.goto(public_url)
                expect(anonymous.get_by_text("分享已取消", exact=True)).to_be_visible()
                anonymous.goto(self.base + "/#/s/" + self.expiring["shareToken"])
                expect(anonymous.get_by_text("分享已过期", exact=True)).to_be_visible()
                anonymous.goto(self.base + "/#/s/" + secrets.token_urlsafe(16))
                expect(anonymous.get_by_text("分享不存在", exact=True)).to_be_visible()
                self.check("FR-12", "browser distinguishes cancelled expired and missing links", True)
                page.get_by_role("link", name="个人文件", exact=True).click()
                page.get_by_role("button", name="浏览器 目录 /", exact=True).click()
                confirmation = []
                def confirm_delete(dialog):
                    confirmation.append(dialog.message)
                    dialog.accept()
                page.once("dialog", confirm_delete)
                page.get_by_role("button", name="永久删除", exact=True).click()
                expect(page.get_by_text("改名 文件.bin", exact=True)).to_have_count(0)
                expect(page.get_by_text("已用 0 B", exact=False)).to_be_visible()
                self.check("FR-07", "browser permanent-delete confirmation includes filename and recovery warning", bool(confirmation) and "改名 文件.bin" in confirmation[0] and "无法在网盘中恢复" in confirmation[0])
                anonymous.goto(protected_url)
                anonymous.get_by_label("提取码", exact=True).fill(code)
                anonymous.get_by_role("button", name="验证提取码", exact=True).click()
                expect(anonymous.get_by_text("文件已失效", exact=True)).to_be_visible()
                expect(anonymous.get_by_role("button", name="下载文件", exact=True)).to_have_count(0)
                self.check("FR-12", "browser deleted-source page removes download", True)
                page.get_by_role("button", name="根目录", exact=True).click()
                page.once("dialog", lambda dialog: dialog.accept("改名 目录"))
                page.get_by_role("button", name="重命名", exact=True).click()
                expect(page.get_by_role("button", name="改名 目录 /", exact=True)).to_be_visible()
                page.once("dialog", lambda dialog: dialog.accept())
                page.get_by_role("button", name="永久删除", exact=True).click()
                expect(page.get_by_role("button", name="改名 目录 /", exact=True)).to_have_count(0)
                self.check("FR-04", "browser directory rename and empty delete", True)
                page.get_by_role("button", name="退出登录", exact=True).click()
                expect(page.get_by_text("浏览器验收", exact=True)).to_have_count(0)
                self.check("FR-02", "browser logout clears credential and profile", page.evaluate("localStorage.getItem('course-token')") is None)
                page.evaluate("token => localStorage.setItem('course-token', token)", self.expired)
                page.goto(self.base + "/#/files")
                # A hash-only navigation does not recreate the in-memory session.
                page.reload()
                expect(page.get_by_role("button", name="登录", exact=True)).to_be_visible()
                page.wait_for_function("localStorage.getItem('course-token') === null")
                self.check("FR-02", "browser expired credential redirects to login", page.evaluate("localStorage.getItem('course-token')") is None)
                self.check("FR-10", "all browser API calls use one origin", bool(origins) and all(origin == self.base for origin in origins))
            finally:
                browser.close()

    def cleanup(self):
        for service in self.stopped.copy():
            self.compose("start", service)
        if hasattr(self, "token"):
            for item in self.files:
                self.api("/files/" + item, "DELETE", token=self.token)
            for share in self.shares:
                self.api("/shares/" + share, "DELETE", token=self.token)
            if hasattr(self, "directory"):
                self.api("/directories/" + self.directory, "DELETE", token=self.token)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--project-name")
    parser.add_argument("--with-outages", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--api-only", action="store_true")
    mode.add_argument("--browser-only", action="store_true")
    args = parser.parse_args()
    suite = Acceptance(args.base_url, args.env_file, args.project_name)
    fatal = None
    try:
        if args.browser_only:
            fixture = dict(accountName="fixture_" + suite.suffix, password=suite.password,
                           nickname="浏览器前置样本", email="fixture_" + suite.suffix + "@example.test")
            suite.data(suite.api("/auth/register", "POST", fixture))
            login = suite.data(suite.api("/auth/login", "POST", dict(accountName=fixture["accountName"], password=suite.password)))
            suite.token = login["token"]
            suite.sensitive.append(suite.token)
            suite.expired = suite.signed_expired_token(login["userId"], login["accountId"])
            suite.directory = suite.data(suite.api("/directories", "POST", dict(name="浏览器前置样本", parentId="0"), suite.token))["id"]
            suite.content = bytes(index % 251 for index in range(65536))
            suite.file = suite.data(suite.upload("fixture.bin", suite.content))["id"]
            suite.files.append(suite.file)
            suite.expiring = suite.share()
            suite.sql(f"UPDATE share_db.sys_share SET expire_time=UTC_TIMESTAMP()-INTERVAL 1 SECOND WHERE id={int(suite.expiring['id'])}")
        else:
            suite.accounts()
            suite.directories_and_files()
            suite.sharing()
            if args.with_outages:
                suite.outage()
            suite.deletion()
        if not args.api_only:
            suite.browser()
    except Exception as error:
        # Browser exceptions can contain tokens/typed values; emit a redacted diagnostic.
        fatal = type(error).__name__ + ": " + str(error)
        for secret in [*suite.sensitive, *suite.settings.values()]:
            if len(secret) >= 6:
                fatal = fatal.replace(secret, "<redacted>")
        fatal = re.sub(r"(/s/)[A-Za-z0-9_-]{22}", r"\1<redacted>", fatal)
        print("FAIL: " + fatal, flush=True)
    finally:
        try:
            suite.cleanup()
        except Exception as error:
            fatal = fatal or "Cleanup failed: " + type(error).__name__
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        folder = ROOT / "artifacts" / "functional" / timestamp
        folder.mkdir(parents=True, exist_ok=True)
        report = dict(timestamp=timestamp, base_url=args.base_url, source_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), with_outages=args.with_outages,
            api_only=args.api_only, browser_only=args.browser_only, results=suite.results, fatal=fatal,
            compose_project=args.project_name or suite.settings.get("COMPOSE_PROJECT_NAME"),
            limits=["Browser upload interruption and truncated-download responses are injected faults.",
                    "This is functional acceptance, not formal E1-E4 experiment data."])
        (folder / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        passed = sum(result["status"] == "PASS" for result in suite.results)
        print(f"Checks passed: {passed}/{len(suite.results)}; report: {folder.relative_to(ROOT)}", flush=True)
    return 1 if fatal or any(result["status"] == "FAIL" for result in suite.results) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
