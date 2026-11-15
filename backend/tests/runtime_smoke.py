"""A image/proxy development acceptance. No formal C/D experiment data is collected."""
import hashlib
import json
from http.client import RemoteDisconnected
import time
from course_smoke import Environment, request, raw_request, upload


def ready(env, name):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        state = env.docker("inspect", "--format", "{{.State.Health.Status}}", name)
        if state == "healthy": return
        time.sleep(1)
    raise AssertionError("Image health command did not become healthy")


def run(env):
    env.runtime_images = True
    env.env["APP_VERSION"] = "runtime-selftest"
    env.start()
    env.start_files()
    name = env.prefix + "-frontend"
    env.containers.append(name)
    env.docker("run", "-d", "--name", name, "--network", env.network, "-p", "127.0.0.1::80", "cloud-drive-frontend:course")
    env.frontend = "http://" + env.docker("port", name, "80/tcp").splitlines()[0]
    env.env["PUBLIC_BASE_URL"] = env.frontend
    env.shares = env.service("share")
    for kind in ("auth", "share", "frontend"):
        ready(env, env.prefix + "-" + kind)
    assert raw_request(env.frontend, "/healthz")[0] == 200
    status, _, html = raw_request(env.frontend, "/")
    assert status == 200 and b'id="app"' in html
    for path in ("/api", "/api/v1/unknown", "/health/live", "/health/ready", "/internal/test/exit", "/api/v1/health/live"):
        status, _, body = raw_request(env.frontend, path)
        assert status == 404 and b'id="app"' not in body
    assert raw_request(env.frontend, "/internal/test/exit", b"{}", "application/json", method="POST", internal=env.env["INTERNAL_API_TOKEN"])[0] == 404
    payload = dict(accountName="runtime_user", password="test-Pass-123", nickname="运行核验", email="runtime@example.test")
    assert request(env.frontend, "/api/v1/auth/register", payload)[0] == 200
    status, headers, result = request(env.frontend, "/api/v1/auth/login", payload)
    assert status == 200 and headers["X-App-Version"] == "runtime-selftest"
    assert headers.get("X-Instance-Id") and headers.get("X-Request-Id")
    env.token = result["data"]["token"]
    assert request(env.frontend, "/api/v1/users/me", token=env.token)[0] == 200
    assert request(env.frontend, "/api/v1/files?parentId=0", token=env.token)[0] == 200
    assert request(env.frontend, "/api/v1/quota", token=env.token)[0] == 200
    env.directory = "0"
    env.content = b"runtime image SHA-256\n" * 100
    result = upload(env, "runtime sample.txt", env.content)
    assert result[0] == 200
    env.file_id = result[2]["data"]["id"]
    status, _, result = request(env.frontend, "/api/v1/shares", dict(fileId=env.file_id, accessType=1, expireDays=7), env.token)
    assert status == 200
    share = result["data"]
    assert share["shareUrl"].startswith(env.frontend + "/#/s/")
    endpoint = "/api/v1/s/" + share["shareToken"]
    assert request(env.frontend, endpoint)[2]["data"]["fileName"] is None
    assert request(env.frontend, endpoint + "/verify", {"extractCode": share["extractCode"]})[0] == 200
    status, _, body = raw_request(env.frontend, endpoint + "/download", json.dumps({"extractCode": share["extractCode"]}).encode(), "application/json")
    assert status == 200 and hashlib.sha256(body).digest() == hashlib.sha256(env.content).digest()
    assert request(env.frontend, "/api/v1/shares", token=env.token)[0] == 200
    for kind, package in (("auth", "auth"), ("share", "shares")):
        env.docker("exec", env.prefix + "-" + kind, "java", "-cp", "/app/probe", "com.jiayuan.drive." + package + ".HealthProbe")
    assert request(env.shares, "/internal/test/exit", {}, method="POST")[0] == 404

    # This is a one-time hook contract check, not the formal restart/recovery experiment.
    fault_url = env.service("share", ("-e", "EXPERIMENT_FAULTS_ENABLED=true"), label="fault")
    assert raw_request(fault_url, "/internal/test/exit", b"{}", "application/json", method="POST", internal="wrong")[0] == 403
    try:
        raw_request(fault_url, "/internal/test/exit", b"{}", "application/json", method="POST", internal=env.env["INTERNAL_API_TOKEN"])
    except (OSError, RemoteDisconnected):
        pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        exit_code = env.docker("inspect", "--format", "{{.State.ExitCode}}", env.prefix + "-fault")
        if exit_code == "17": break
        time.sleep(0.5)
    assert exit_code == "17"

    # Avoid dumping logs: assert sensitive values in memory and report only the verdict.
    sensitive = [env.env[key] for key in ("JWT_SECRET", "INTERNAL_API_TOKEN", "AUTH_DB_PASSWORD", "SHARE_DB_PASSWORD")]
    sensitive += [env.token, share["shareToken"], share["extractCode"], payload["password"]]
    for kind in ("auth", "share", "frontend", "fault"):
        logs = env.docker("logs", env.prefix + "-" + kind)
        assert all(value not in logs for value in sensitive), "Sensitive data appeared in runtime logs"
    print("PASS runtime images: built health commands, path-preserving proxy, internal/health/unknown API rejection, headers, POST SHA-256, disabled/enabled authenticated exit hook, log redaction", flush=True)


if __name__ == "__main__":
    environment = Environment()
    try: run(environment)
    finally: environment.close()
