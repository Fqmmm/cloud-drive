"""Launch an isolated six-container development stack and run the real browser flow."""
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from course_smoke import Environment, request, raw_request, upload


def run(env):
    env.runtime_images = True
    env.file_runtime_image = True
    env.start()
    env.sql("ALTER TABLE auth_db.sys_user AUTO_INCREMENT=9007199254740993")
    env.sql("ALTER TABLE auth_db.sys_account AUTO_INCREMENT=9007199254740993")
    env.sql("ALTER TABLE file_db.sys_file AUTO_INCREMENT=9007199254740993")
    env.start_files()
    name = env.prefix + "-frontend"
    env.containers.append(name)
    env.docker("run", "-d", "--name", name, "--network", env.network, "-p", "127.0.0.1::80", "cloud-drive-frontend:course")
    env.frontend = "http://" + env.docker("port", name, "80/tcp").splitlines()[0]
    env.env["PUBLIC_BASE_URL"] = env.frontend
    env.shares = env.service("share")
    browser_env = env.env.copy()
    browser_env["COURSE_BASE_URL"] = env.frontend
    browser_env["COURSE_TEST_PASSWORD"] = secrets.token_hex(12)
    browser_env["COURSE_TEST_SUFFIX"] = secrets.token_hex(4)
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    command = ["pnpm.cmd" if os.name == "nt" else "pnpm", "exec", "playwright", "test", "--config", "playwright.live.config.ts"]
    result = subprocess.run(command, cwd=frontend, env=browser_env, capture_output=True, text=True, encoding="utf-8")
    output = result.stdout + result.stderr
    output = output.replace(browser_env["COURSE_TEST_PASSWORD"], "<redacted-password>")
    output = re.sub(r"(/(?:api/v1/)?s/)[A-Za-z0-9_-]{22}", r"\1<redacted-share-token>", output)
    output = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted-jwt>", output)
    output = re.sub(r"(?<![0-9])[0-9]{6}(?![0-9])", "<redacted-six-digits>", output)
    print(output, flush=True)
    assert result.returncode == 0, "Real browser acceptance failed; see redacted output above"
    assert env.sql("SELECT COUNT(*) FROM auth_db.sys_user") == "2"
    assert env.sql("SELECT SUM(used_space) FROM file_db.user_quota") == "0"
    assert env.sql("SELECT COUNT(*) FROM file_db.sys_file WHERE is_deleted=0") == "0"
    assert env.sql("SELECT COUNT(*) FROM share_db.sys_share") == "2"
    print("PASS AB browser: two accounts, anonymous public/protected access, SHA-256, BIGINT identities, isolation, rename snapshot, cancellation, permanent deletion and final quota", flush=True)
    tables = {"auth_user": "auth_db.sys_user", "file_user": "file_db.sys_file", "share_user": "share_db.sys_share"}
    for user, own_table in tables.items():
        assert env.sql("SELECT COUNT(*) FROM " + own_table, user=user).isdigit()
        for foreign_table in tables.values():
            if foreign_table == own_table: continue
            try: env.sql("SELECT COUNT(*) FROM " + foreign_table, user=user)
            except RuntimeError: pass
            else: raise AssertionError("Cross-database access was unexpectedly granted")
    print("PASS database isolation: all three service accounts read only their own database", flush=True)
    login = request(env.frontend, "/api/v1/auth/login", {"accountName": "owner_" + browser_env["COURSE_TEST_SUFFIX"],
                    "password": browser_env["COURSE_TEST_PASSWORD"]})
    assert login[0] == 200
    env.token = login[2]["data"]["token"]
    env.directory = "0"
    content = b"storage recovery sample"
    status, _, result = upload(env, "storage-recovery.bin", content)
    assert status == 200
    file_id = result["data"]["id"]
    env.docker("stop", env.prefix + "-minio")
    assert raw_request(env.files, "/api/v1/files/" + file_id + "/download", token=env.token)[0] == 503
    assert upload(env, "storage-failure.bin", content)[0] == 503
    assert request(env.files, "/api/v1/quota", token=env.token)[2]["data"]["usedBytes"] == len(content)
    assert request(env.files, "/api/v1/files/" + file_id, token=env.token, method="DELETE")[0] == 200
    assert request(env.files, "/api/v1/quota", token=env.token)[2]["data"]["usedBytes"] == 0
    assert int(env.sql("SELECT COUNT(*) FROM file_db.object_cleanup")) > 0
    env.docker("start", env.prefix + "-minio")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        # B's documented retry operation, applied only to the disposable test database.
        env.sql("UPDATE file_db.object_cleanup SET next_attempt_at=UTC_TIMESTAMP()")
        if env.sql("SELECT COUNT(*) FROM file_db.object_cleanup") == "0": break
        time.sleep(2)
    assert env.sql("SELECT COUNT(*) FROM file_db.object_cleanup") == "0"
    assert env.sql("SELECT SUM(used_space) FROM file_db.user_quota") == "0"
    print("PASS storage outage: download/upload 503, failed upload quota unchanged, delete immediate, persistent cleanup recovers", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    environment = Environment()
    try: run(environment)
    finally: environment.close()
