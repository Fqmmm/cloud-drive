"""Continue E3 without discarding compatible rounds, then run E4 and reports."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

from support import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if any(not re.fullmatch(r"[a-z0-9-]{1,24}", value) for value in (args.source_run_id, args.run_id)):
        parser.error("Invalid run ID")
    env = ROOT / "artifacts" / "liu" / args.source_run_id / ".env"
    commands = [
        [sys.executable, "-u", "scripts/failure/run.py", "--env-file", str(env), "--run-id", args.run_id,
         "--continue-from", args.source_run_id],
        [sys.executable, "-u", "scripts/persistence/run.py", "--env-file", str(env), "--run-id", args.run_id],
        [sys.executable, "scripts/experiments/analyze.py", "--run-id", args.run_id, "--context-run-id", args.source_run_id]]
    if args.restore:
        commands[1].append("--restore")
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
