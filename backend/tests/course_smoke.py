"""Disposable A/AB development checks, separate from C/D's formal experiments."""
import concurrent.futures
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

BACKEND = Path(__file__).resolve().parents[1]


class Environment:
    def __init__(self):
        self.prefix = "course-a-" + secrets.token_hex(5)
        self.network = self.prefix + "-net"
        self.containers = []
        self.env = os.environ.copy()
        for name in ("MYSQL_ROOT_PASSWORD", "AUTH_DB_PASSWORD", "FILE_DB_PASSWORD", "SHARE_DB_PASSWORD",
                     "JWT_SECRET", "INTERNAL_API_TOKEN", "MINIO_ROOT_PASSWORD"):
            self.env[name] = secrets.token_hex(24)
        self.env.update(JWT_ISSUER="course-drive", JWT_AUDIENCE="course-drive-api", MINIO_ROOT_USER="course-test")

    def docker(self, *args):
        result = subprocess.run(["docker", *map(str, args)], env=self.env, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Docker command failed: " + result.stderr[:500])
        return result.stdout.strip()

    def start(self):
        self.docker("network", "create", self.network)
        name = self.prefix + "-mysql"
        self.containers.append(name)
        self.database = name
        self.docker("run", "-d", "--name", name, "--network", self.network, "--network-alias", "mysql",
                    "--tmpfs", "/var/lib/mysql:rw", "-e", "MYSQL_ROOT_PASSWORD", "-e", "AUTH_DB_PASSWORD",
                    "-e", "FILE_DB_PASSWORD", "-e", "SHARE_DB_PASSWORD",
                    "--mount", f"type=bind,source={BACKEND / 'sql/course-mysql/init'},target=/docker-entrypoint-initdb.d,readonly",
                    "--mount", f"type=bind,source={BACKEND / 'sql/course-mysql/schema'},target=/opt/course-schema,readonly",
                    "mysql:8.0.29", "--default-time-zone=+00:00")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if self.sql("SELECT version FROM file_db.schema_version") == "1":
                    break
            except RuntimeError:
                pass
            time.sleep(2)
        else:
            raise AssertionError("Fresh course MySQL did not initialize")
        self.auth = self.service("auth")

    def service(self, kind, extra=()):
        name = self.prefix + "-" + kind
        self.containers.append(name)
        jar = BACKEND / (kind + "-service") / "target" / (kind + "-service.jar")
        assert jar.exists(), "Build " + kind + "-service first"
        args = ["run", "-d", "--name", name, "--network", self.network, "--network-alias", kind + "-service",
                "-p", "127.0.0.1::8080", "-e", kind.upper() + "_DB_PASSWORD"]
        for variable in ("JWT_SECRET", "JWT_ISSUER", "JWT_AUDIENCE", "INTERNAL_API_TOKEN", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
            args += ["-e", variable]
        args += list(extra)
        args += ["--mount", f"type=bind,source={jar},target=/app/app.jar,readonly",
                 "eclipse-temurin:17-jre", "java", "-jar", "/app/app.jar"]
        self.docker(*args)
        base = "http://" + self.docker("port", name, "8080/tcp").splitlines()[0]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if request(base, "/health/ready")[0] == 200:
                    return base
            except (OSError, ValueError):
                pass
            time.sleep(1)
        raise AssertionError(kind + " service not ready")

    def start_files(self):
        name = self.prefix + "-minio"
        self.containers.append(name)
        self.docker("run", "-d", "--name", name, "--network", self.network, "--network-alias", "minio",
                    "--tmpfs", "/data:rw", "-e", "MINIO_ROOT_USER", "-e", "MINIO_ROOT_PASSWORD",
                    "minio/minio:latest", "server", "/data")
        self.files = self.service("file", ("-e", "DEFAULT_QUOTA_BYTES=1048576", "-e", "MAX_FILE_BYTES=524288"))

    def sql(self, query, user="root", database=None):
        password_variable = {"root": "MYSQL_ROOT_PASSWORD", "auth_user": "AUTH_DB_PASSWORD"}[user]
        command = f'MYSQL_PWD="${password_variable}" mysql --protocol=TCP -h 127.0.0.1 -u {user} -Nse "$1"'
        return self.docker("exec", self.database, "sh", "-c", command, "sh", query)

    def close(self):
        for name in reversed(self.containers):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", self.network], capture_output=True)


def request(base, path, data=None, token=None, method=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(base + path, payload, headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as failure:
        response = failure
    with response:
        body = response.read()
        return response.status, dict(response.headers), json.loads(body) if body else None


def registration(env):
    def register(name, email, **overrides):
        payload = dict(accountName=name, email=email, password="test-Pass-123", nickname="课程用户", accountType="personal")
        payload.update(overrides)
        return request(env.auth, "/api/v1/auth/register", payload)

    assert register("Alice", "alice@example.test")[0] == 200
    status, _, body = register("ALICE", "other@example.test")
    assert status == 409 and body["code"] == "ACCOUNT_EXISTS"
    status, _, body = register("other", "ALICE@example.test")
    assert status == 409 and body["code"] == "EMAIL_EXISTS"
    for overrides in (dict(accountName="ab"), dict(accountName="a b"), dict(accountName="a" * 33),
                      dict(password="short"), dict(password="a" * 65), dict(nickname=""),
                      dict(email="invalid"), dict(accountType="team")):
        payload = dict(accountName="valid_user", email="valid@example.test", password="test-Pass-123", nickname="有效")
        payload.update(overrides)
        assert request(env.auth, "/api/v1/auth/register", payload)[0] == 400
    assert request(env.auth, "/api/v1/auth/register", {})[0] == 400
    # Same account with different emails forces account conflicts after inserting sys_user.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda i: register("parallel", f"p{i}@example.test"), range(4)))
    assert sorted(response[0] for response in responses) == [200, 409, 409, 409]
    assert env.sql("SELECT COUNT(*) FROM auth_db.sys_user") == "2", "rollback left orphan users"
    assert env.sql("SELECT COUNT(*) FROM auth_db.sys_account") == "2"
    assert env.sql("SELECT account_name FROM auth_db.sys_account WHERE account_name='alice'") == "alice"
    stored = env.sql("SELECT password FROM auth_db.sys_account WHERE account_name='alice'")
    assert stored.startswith("{bcrypt-sha256}$2a$12$") and "test-Pass-123" not in stored
    for foreign in ("file_db.user_quota", "share_db.sys_share"):
        try:
            env.sql("SELECT COUNT(*) FROM " + foreign, user="auth_user")
        except RuntimeError:
            pass
        else:
            raise AssertionError("auth_user unexpectedly accessed another service database")
    print("PASS registration: validation, normalization, salted hash, duplicate email/account, concurrent rollback, DB isolation")


def authentication(env):
    status, _, result = request(env.auth, "/api/v1/auth/login", dict(accountName="ALICE", password="test-Pass-123"))
    assert status == 200
    env.token = result["data"]["token"]
    assert isinstance(result["data"]["userId"], str)
    status, _, result = request(env.auth, "/api/v1/users/me", token=env.token)
    assert status == 200 and result["data"]["accountName"] == "alice"
    assert set(result["data"]) == {"userId", "accountId", "nickname", "accountName", "email"}
    for name, password in (("alice", "incorrect-pass"), ("missing_user", "test-Pass-123")):
        status, _, result = request(env.auth, "/api/v1/auth/login", dict(accountName=name, password=password))
        assert status == 401 and result["code"] == "INVALID_CREDENTIALS"
    assert request(env.auth, "/api/v1/users/me")[0] == 401
    assert request(env.auth, "/api/v1/users/me", token=env.token + "x")[0] == 401
    env.sql("UPDATE auth_db.sys_account SET status=0 WHERE account_name='alice'")
    assert request(env.auth, "/api/v1/auth/login", dict(accountName="alice", password="test-Pass-123"))[0] == 401
    env.sql("UPDATE auth_db.sys_account SET status=1 WHERE account_name='alice'")
    env.start_files()
    status, _, result = request(env.files, "/api/v1/quota", token=env.token)
    assert status == 200 and result["data"]["usedBytes"] == 0
    assert request(env.files, "/api/v1/quota", token=env.token + "x")[0] == 401
    env.docker("stop", env.prefix + "-auth")
    assert request(env.files, "/api/v1/quota", token=env.token)[0] == 200
    env.docker("start", env.prefix + "-auth")
    print("PASS login/JWT/profile: normalized login, credential/disabled checks, minimal profile, real JWT accepted by B without auth process")


if __name__ == "__main__":
    environment = Environment()
    try:
        environment.start()
        registration(environment)
        if "--auth" in sys.argv:
            authentication(environment)
    finally:
        environment.close()
