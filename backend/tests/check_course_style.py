"""Run legacy rules with an explicit independent-service root; report parser limits."""
import importlib.util
import os
from pathlib import Path
import sys

backend = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("course_checker", backend / "script/code_check.py")
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)
checker.BackendLinter._discover_project_root = staticmethod(lambda start: os.path.abspath(start))
root = backend / sys.argv[1]
files = list((root / "src").rglob("*.java"))
print("Explicit source root:", root, "Java files:", len(files))
linter = checker.BackendLinter(str(root), checker.load_config(str(root)))
defects = linter.scan()
checker.print_report_eslint(defects, False)
print("Legacy javalang cannot parse Java records; any parse warnings above mean skipped files.")
sys.exit(bool(defects))
