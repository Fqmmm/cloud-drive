"""Offline regression tests for evidence integrity, isolation and bounded probes.

Local HTTP fixtures are synthetic and are never exported to experiments/.
"""
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from support import Context, SERVICES, csv_write, digest, init_env, object_is_absent, retained_volumes, run_live, sanitize, validate_project, validate_resume_environment
from probes import execute, recovery, Scheduler
from analyze import audit_public, normalize_public, report_e3, report_e4, summarize_round

GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.is_file() else shutil.which("bash")


@unittest.skipUnless(BASH, "Maven wrapper checks require Bash")
class MavenBuildTests(unittest.TestCase):
    def invoke(self, failures, build_exit):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bin").mkdir()
            (root / "bin" / "mvn").write_text('''#!/bin/sh
case "$*" in
  *go-offline*)
    count=0
    if [ -f "$CASE_DIR/count" ]; then count=$(cat "$CASE_DIR/count"); fi
    count=$((count + 1))
    printf '%s' "$count" > "$CASE_DIR/count"
    echo prepare >> "$CASE_DIR/calls"
    if [ "$count" -le "$PREP_FAILURES" ]; then exit 1; fi
    exit 0
    ;;
  *) echo build >> "$CASE_DIR/calls"; exit "$BUILD_EXIT" ;;
esac
''', encoding="utf-8", newline="\n")
            (root / "bin" / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
            for path in (root / "bin").iterdir():
                path.chmod(0o755)
            environment = os.environ.copy()
            environment.update(PREP_FAILURES=str(failures), BUILD_EXIT=str(build_exit), MAVEN_MIRROR_URL="https://maven.aliyun.com/repository/public")
            script = Path(__file__).resolve().parents[2] / "backend/docker/maven-build.sh"
            result = subprocess.run([BASH, "-c", 'export CASE_DIR="$PWD" TMPDIR="$PWD"; export PATH="$PWD/bin:$PATH"; sh "$1" verify',
                "wrapper-test", str(script)], cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            calls = (root / "calls").read_text().splitlines() if (root / "calls").exists() else []
            return result, calls

    def test_dependency_download_retries_then_build_runs_once(self):
        result, calls = self.invoke(failures=2, build_exit=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["prepare", "prepare", "prepare", "build"])

    def test_exhausted_dependency_retries_do_not_start_build(self):
        result, calls = self.invoke(failures=9, build_exit=0)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(calls, ["prepare", "prepare", "prepare"])

    def test_compile_or_test_failure_is_returned_without_retry(self):
        result, calls = self.invoke(failures=0, build_exit=23)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(calls, ["prepare", "build"])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/hang":
            time.sleep(5)
            return
        body = b"sample" if self.path == "/bytes" else b'{"code":"00000","data":{}}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-Id", "server-test-id")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class ContextTests(unittest.TestCase):
    def test_offline_recomputation_does_not_require_private_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "metrics.json").write_text('{"median":7.0}', encoding="utf-8")
            result = audit_public([path], path / "missing-private-context")
            self.assertFalse(result["exact_secret_values_checked"])
            self.assertTrue(result["generic_patterns_checked"])
            self.assertEqual(result["files_checked"], 1)

    def test_offline_scan_still_rejects_jwt_and_extraction_code_patterns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for content in ('eyJabcdefghijk.abcdefghijklmn.abcdefghijklmn', '{"extractCode":"001234"}'):
                (path / "bad.log").write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    audit_public([path], path / "missing-private-context")
    def test_mc_object_missing_accepts_the_observed_structured_error(self):
        observed = dict(status="error", error=dict(message="Unable to stat object", cause=dict(message="Object does not exist", error={})))
        self.assertTrue(object_is_absent(1, json.dumps(observed)))
        observed["error"]["cause"]["error"] = {"Code": "NoSuchKey"}
        self.assertTrue(object_is_absent(1, json.dumps(observed)))

    def test_mc_network_auth_bucket_and_parse_errors_are_not_missing_objects(self):
        for code, message in (("AccessDenied", "Object does not exist"), ("NoSuchBucket", "Object does not exist"),
                              (None, "Connection refused"), (None, "Access denied")):
            value = dict(status="error", error=dict(cause=dict(message=message, error={"Code": code} if code else {})))
            self.assertFalse(object_is_absent(1, json.dumps(value)))
        for text in ("not found", "{}", "[]", '"error"', '{"status":"error","error":null}'):
            self.assertFalse(object_is_absent(1, text))
        self.assertFalse(object_is_absent(0, json.dumps(dict(status="success"))))

    def test_continuation_requires_original_project_images_and_probe(self):
        rows = [dict(service=name, image="sha256:" + name) for name in SERVICES]
        args = (dict(project="cloud-drive-liu-original"), rows, rows, "a" * 64, "a" * 64, "cloud-drive-liu-original")
        validate_resume_environment(*args)
        changed = [dict(row) for row in rows]
        changed[0]["image"] = "different"
        for current, old_hash, new_hash, project in ((changed, "a"*64, "a"*64, args[-1]),
            (rows, "a"*64, "b"*64, args[-1]), (rows, "a"*64, "a"*64, "cloud-drive-liu-other"),
            (rows + [rows[0]], "a"*64, "a"*64, args[-1])):
            with self.assertRaises(ValueError):
                validate_resume_environment(args[0], rows, current, old_hash, new_hash, project)
    def test_live_log_is_visible_before_command_exits_and_is_redacted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            results = []
            command = [sys.executable, "-u", "-c", "import time; print('secret-abcdef first',flush=True); time.sleep(2); print('last',flush=True)"]
            thread = threading.Thread(target=lambda: results.append(run_live(command, path / "public.log", path / "private.log",
                ["secret-abcdef"], 10, path)))
            thread.start()
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                if (path / "public.log").exists() and "first" in (path / "public.log").read_text():
                    break
                time.sleep(.05)
            visible_while_running = thread.is_alive() and "first" in (path / "public.log").read_text()
            thread.join()
            self.assertTrue(visible_while_running)
            self.assertEqual(results[0].returncode, 0)
            self.assertNotIn("secret-abcdef", (path / "public.log").read_text())
            self.assertIn("secret-abcdef", (path / "private.log").read_text())
            self.assertIn("last", (path / "public.log").read_text())

    def test_live_log_preserves_nonzero_command_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            result = run_live([sys.executable, "-c", "print('build failed'); raise SystemExit(7)"],
                path / "public.log", path / "private.log", [], 10, path)
            self.assertEqual(result.returncode, 7)
            self.assertIn("build failed", (path / "public.log").read_text())

    def test_project_isolation_and_input_validation(self):
        for project in ("cloud-drive-course", "cloud-drive-e2-old", "x;docker", "cloud-drive-liu-../escape"):
            with self.assertRaises(ValueError):
                validate_project(project)
        self.assertEqual(validate_project("cloud-drive-liu-20261117"), "cloud-drive-liu-20261117")

    def test_context_and_credentials_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            init_env(env, "cloud-drive-liu-test", 8088)
            original = env.read_bytes()
            with self.assertRaises(FileExistsError):
                init_env(env, "cloud-drive-liu-test", 8088)
            self.assertEqual(original, env.read_bytes())
            ctx = Context(env)
            with patch("support.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as run:
                ctx.compose("stop", "share-service")
                command = run.call_args.args[0]
                self.assertEqual(command[:7], ["docker", "compose", "--env-file", str(env.resolve()), "-p", "cloud-drive-liu-test", "stop"])
            for operation in (("down",), ("down", "-v"), ("rm", "mysql")):
                with self.assertRaises(ValueError):
                    ctx.compose(*operation)

    def test_registry_is_recorded_and_rejects_credentials_or_injection(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            init_env(env, "cloud-drive-liu-test", 8088, npm_registry="https://registry.npmmirror.com/")
            self.assertEqual(Context(env).values["NPM_REGISTRY"], "https://registry.npmmirror.com")
            for value in ("http://insecure.test", "https://user:password@registry.test", "https://x.test\nSECRET=value"):
                with self.assertRaises(ValueError):
                    init_env(Path(folder) / "new.env", "cloud-drive-liu-test", 8088, npm_registry=value)

    def test_maven_mirror_is_recorded_and_xml_injection_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            init_env(env, "cloud-drive-liu-test", 8088, maven_mirror="https://maven.aliyun.com/repository/public")
            self.assertEqual(Context(env).values["MAVEN_MIRROR_URL"], "https://maven.aliyun.com/repository/public")
            for value in ("https://x.test/?secret=1", "https://x.test/<evil>", "http://x.test/public", "https://user:pass@x.test"):
                with self.assertRaises(ValueError):
                    init_env(Path(folder) / "new.env", "cloud-drive-liu-test", 8088, maven_mirror=value)

    def test_redaction_including_short_extraction_codes_and_jwt(self):
        text = 'code=001234 password=password-long /s/' + 'a' * 22 + ' eyJabc.abcdef.abcdef elapsed=19'
        result = sanitize(text, ["001234", "password-long"])
        for secret in ("001234", "password-long", "a" * 22, "eyJabc.abcdef.abcdef"):
            self.assertNotIn(secret, result)
        self.assertIn("elapsed=19", result)

    def test_private_dump_not_echoed_in_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            init_env(env, "cloud-drive-liu-test", 8088)
            ctx = Context(env)
            ctx.audit = Path(folder) / "execution.jsonl"
            target = Path(folder) / "dump.sql"
            with patch("support.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "password_hash_and_tokens", "")):
                ctx.run(["docker", "test"], private_output=target)
            self.assertIn("password_hash_and_tokens", target.read_text())
            self.assertNotIn("password_hash_and_tokens", ctx.audit.read_text())

    def test_shell_environment_cannot_replace_private_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            init_env(env, "cloud-drive-liu-test", 8088)
            ctx = Context(env)
            with patch.dict("os.environ", {"HTTP_PORT": "9999", "EXPERIMENT_FAULTS_ENABLED": "true"}), \
                    patch("support.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as run:
                ctx.compose("config", "--quiet")
                self.assertEqual(run.call_args.kwargs["env"]["HTTP_PORT"], "8088")
                self.assertEqual(run.call_args.kwargs["env"]["EXPERIMENT_FAULTS_ENABLED"], "false")
                ctx.compose("up", "-d", "share-service", overrides={"EXPERIMENT_FAULTS_ENABLED": "true"})
                self.assertEqual(run.call_args.kwargs["env"]["EXPERIMENT_FAULTS_ENABLED"], "true")

    def test_container_changed_and_same_volume_required(self):
        before = [dict(service="mysql", id="old", mounts=[dict(Type="volume", Name="original", Destination="/var/lib/mysql")])]
        after = [dict(service="mysql", id="new", mounts=[dict(Type="volume", Name="original", Destination="/var/lib/mysql")])]
        self.assertTrue(retained_volumes(before, after, "mysql"))
        after[0]["mounts"][0]["Name"] = "empty-new-volume"
        self.assertFalse(retained_volumes(before, after, "mysql"))
        after[0]["mounts"][0]["Name"] = "original"
        after[0]["id"] = "old"
        self.assertFalse(retained_volumes(before, after, "mysql"))

    def test_csv_unicode_and_exact_hash_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "baseline.csv"
            row = dict(name="中文 文件.bin", sha256=digest(b"sample"), bytes=6)
            csv_write(path, [row])
            with path.open(encoding="utf-8", newline="") as stream:
                actual = list(csv.DictReader(stream))[0]
            self.assertEqual(actual["name"], row["name"])
            self.assertEqual(actual["sha256"], row["sha256"])


class RecoveryTests(unittest.TestCase):
    def test_windows_evidence_is_normalized_before_hashing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            text = "中文,sha256\r\n文件,abc\r\n".encode("utf-8")
            (path / "checksums.csv").write_bytes(text)
            (path / "private.bin").write_bytes(b"\x00\r\n\xff")
            normalize_public([path])
            self.assertEqual((path / "checksums.csv").read_bytes(), text.replace(b"\r\n", b"\n"))
            self.assertEqual((path / "private.bin").read_bytes(), b"\x00\r\n\xff")

    def test_automatic_recovery_uses_die_event_and_business_probes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for stage, restart, started in (("before", 0, "1970-01-01T00:01:00Z"), ("after", 1, "1970-01-01T00:01:40.400Z")):
                (path / stage).mkdir()
                (path / stage / "containers.json").write_text(json.dumps([dict(service="share-service", id="same-id", restart_count=restart, started=started)]))
            (path / "result.json").write_text(json.dumps(dict(completed=True, fault="F5", repeat=1)))
            (path / "events.json").write_text(json.dumps([dict(name="t0-inject", epoch=100, service="share-service")]))
            (path / "docker-events.jsonl").write_text(json.dumps(dict(Action="die", timeNano=100200000000,
                Actor=dict(ID="same-id", Attributes=dict(exitCode="17")))) + "\n")
            rows = [dict(probe="download", tick=i, planned_epoch=100 + i, sent_epoch=100.1 + i,
                returned_epoch=100.2 + i, category="timeout" if i == 0 else "ok", schedule_lag_ms=100, elapsed_ms=1) for i in range(4)]
            rows[0]["planned_epoch"] = 99.9  # Queued before fault, actually sent after it.
            csv_write(path / "probe.csv", rows)
            impact, timeline = summarize_round(path)
            self.assertAlmostEqual(timeline["recovery_seconds"], 1.1)
            self.assertAlmostEqual(timeline["exit_to_start_seconds"], .2)
            self.assertAlmostEqual(timeline["t1"], 100.2)
            self.assertAlmostEqual(impact[0]["failure_window_seconds"], 1.0)
            (path / "docker-events.jsonl").write_text("")
            with self.assertRaises(ValueError):
                summarize_round(path)

    def test_incomplete_or_pilot_e3_cannot_publish_formal_report(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for status, kind in (("failed", "formal"), ("complete", "pilot")):
                (path / "manifest.json").write_text(json.dumps(dict(status=status, kind=kind, repeats=3)))
                with self.assertRaises(ValueError):
                    report_e3(path, path / "report.md")
                self.assertFalse((path / "report.md").exists())

    def test_missing_e4_round_cannot_publish_formal_report(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "manifest.json").write_text(json.dumps(dict(status="complete", completed=["mysql-r1"])))
            with self.assertRaises(ValueError):
                report_e4(path, path / "report.md")
            self.assertFalse((path / "report.md").exists())

    def test_requires_three_consecutive_ticks_and_does_not_sort_by_completion(self):
        rows = [dict(probe="files", tick=tick, planned_epoch=100 + tick, sent_epoch=100.1 + tick, category=category)
                for tick, category in ((0, "ok"), (1, "timeout"), (2, "ok"), (3, "ok"), (4, "ok"))]
        self.assertEqual(recovery(list(reversed(rows)), 101, ["files"]), {"files": 102.1})
        self.assertEqual(recovery([rows[2], rows[4]], 101, ["files"]), {})
        rows[3]["tick"] = 10
        self.assertEqual(recovery(rows, 101, ["files"]), {})

    def test_missing_probe_cannot_be_treated_as_recovered(self):
        rows = [dict(probe="a", tick=i, planned_epoch=i, sent_epoch=i + .1, category="ok") for i in range(3)]
        self.assertEqual(set(recovery(rows, 0, ["a", "b"])), {"a"})


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_content_corruption_not_success(self):
        correct = execute(dict(url=self.base + "/bytes", timeout=5, sha256=digest(b"sample")))
        wrong = execute(dict(url=self.base + "/bytes", timeout=5, sha256=digest(b"different")))
        self.assertEqual(correct["category"], "ok")
        self.assertEqual(wrong["category"], "checksum")

    def test_actual_server_request_id_is_retained_for_log_correlation(self):
        row = execute(dict(url=self.base + "/bytes", timeout=5, sha256=digest(b"sample")))
        self.assertEqual(row["request_id"], "server-test-id")

    def test_wall_clock_deadline_kills_hung_worker(self):
        began = time.monotonic()
        row = execute(dict(url=self.base + "/hang", timeout=1))
        self.assertIn(row["category"], ("deadline", "timeout"))
        self.assertLess(time.monotonic() - began, 3)

    def test_one_slow_probe_does_not_block_other_ticks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "probe.csv"
            scheduler = Scheduler(dict(slow=dict(url=self.base + "/hang", timeout=2),
                                       fast=dict(url=self.base + "/ok", timeout=5)), path).start()
            time.sleep(3.2)
            scheduler.finish()
            fast = sorted((r for r in scheduler.rows if r["probe"] == "fast"), key=lambda r: r["tick"])
            self.assertGreaterEqual(len(fast), 3)
            self.assertTrue(all(r["category"] == "ok" for r in fast))
            self.assertLess(fast[2]["planned_epoch"] - fast[0]["planned_epoch"], 2.1)
            with path.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), len(scheduler.rows))


if __name__ == "__main__":
    unittest.main()
