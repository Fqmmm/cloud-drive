"""Cross-service JWT negative checks. Print only case names/statuses, never tokens."""
import base64
import hashlib
import hmac
import json
import time
from course_smoke import Environment, request


def encode(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")


def run(env):
    env.runtime_images = True
    env.start()
    payload = dict(accountName="jwt_contract", password="test-Pass-123", nickname="契约核验", email="jwt@example.test")
    assert request(env.auth, "/api/v1/auth/register", payload)[0] == 200
    login = request(env.auth, "/api/v1/auth/login", payload)[2]["data"]
    env.start_files()
    env.shares = env.service("share")
    now = int(time.time())
    baseline = dict(sub=login["userId"], accountId=login["accountId"], iat=now, exp=now + 7200,
                    iss=env.env["JWT_ISSUER"], aud=[env.env["JWT_AUDIENCE"]])
    cases = {"valid": {}, "future-iat": {"iat": now + 600},
             "exp-before-iat": {"iat": now + 600, "exp": now + 300},
             "expired": {"iat": now - 600, "exp": now - 1}, "wrong-issuer": {"iss": "wrong"},
             "wrong-audience": {"aud": ["wrong"]}, "missing-account": {"accountId": None},
             "missing-iat": {"iat": None}, "missing-exp": {"exp": None}, "negative-sub": {"sub": "-1"},
             "overflow-sub": {"sub": "9223372036854775808"}, "wrong-algorithm": {}}
    failures = []
    for name, changes in cases.items():
        claims = {key: value for key, value in {**baseline, **changes}.items() if value is not None}
        algorithm = "HS384" if name == "wrong-algorithm" else "HS256"
        body = encode({"alg": algorithm, "typ": "JWT"}) + b"." + encode(claims)
        signature = hmac.new(env.env["JWT_SECRET"].encode(), body,
                             hashlib.sha384 if algorithm == "HS384" else hashlib.sha256).digest()
        token = (body + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()
        statuses = [request(base, path, token=token)[0] for base, path in (
            (env.auth, "/api/v1/users/me"), (env.files, "/api/v1/quota"), (env.shares, "/api/v1/shares"))]
        expected = 200 if name == "valid" else 401
        print(f"JWT {name}: auth/file/share={statuses}, expected={expected}", flush=True)
        if statuses != [expected] * 3: failures.append(name)
    assert not failures, "JWT contract mismatches: " + ", ".join(failures)
    print("PASS JWT contract: all three services enforce matching identity, time, issuer, audience and algorithm rules", flush=True)


if __name__ == "__main__":
    environment = Environment()
    try: run(environment)
    finally: environment.close()
