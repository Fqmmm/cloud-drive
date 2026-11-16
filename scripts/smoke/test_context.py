"""SQL and runtime checks must target the explicitly selected Compose project."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from functional import Acceptance


class ContextTests(unittest.TestCase):
    def test_selected_environment_and_project_are_used_for_compose(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / "test.env"
            env.write_text("JWT_ISSUER=isolated-test\n", encoding="utf-8")
            suite = Acceptance("http://127.0.0.1:8080", env_file=env, project="isolated-e2")
            self.assertEqual(suite.settings["JWT_ISSUER"], "isolated-test")
            with patch("functional.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "ok")) as run:
                self.assertEqual(suite.compose("ps", "-q"), "ok")
                self.assertEqual(run.call_args.args[0], ["docker", "compose", "--env-file", str(env.resolve()),
                                                        "-p", "isolated-e2", "ps", "-q"])
            suite.http.close()


if __name__ == "__main__":
    unittest.main()
