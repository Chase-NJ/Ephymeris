#!/usr/bin/env python3
"""Stop hook: a session that changed the sidecar, firmware or protocol cannot
finish while the gate tests fail.

Exit 2 with the failure on stderr blocks the stop and hands Claude the output;
pytest's own exit 1 would let the session finish. Stdlib only.
"""

import json
import subprocess
import sys
from pathlib import Path

WATCHED = ("sidecar", "firmware", "protocol")
GATE = (
    "tests/test_golden.py",
    "tests/test_structure.py",
    "tests/test_legacy_pin.py",
    "tests/test_analytics_stream_is_pure.py",
    "tests/test_recovery.py",
    "tests/test_writer.py",
    "tests/test_run_document.py",
)
TAIL = 60


def git(cwd, *args):
    out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=30)
    return out.stdout.strip() if out.returncode == 0 else ""


def venv_python(*checkouts):
    for checkout in checkouts:
        for relative in (".venv/bin/python", ".venv/Scripts/python.exe"):
            candidate = checkout / "sidecar" / relative
            if candidate.exists():
                return candidate
    return None


def main():
    try:
        cwd = json.load(sys.stdin).get("cwd") or "."
    except ValueError:
        cwd = "."
    top = git(cwd, "rev-parse", "--show-toplevel")
    if not top or not git(top, "status", "--porcelain", "--", *WATCHED):
        return 0
    root = Path(top)
    main_checkout = Path(git(top, "rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    python = venv_python(root, main_checkout)
    if python is None:
        print("stop_gate: no sidecar venv found, gate tests not run", file=sys.stderr)
        return 0
    run = subprocess.run(
        [str(python), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *GATE],
        cwd=root / "sidecar", capture_output=True, text=True,
    )
    if run.returncode == 0:
        return 0
    lines = (run.stdout + run.stderr).splitlines()
    print("stop_gate: the gate tests fail; fix the code, not the tests or their fixtures.", file=sys.stderr)
    print("\n".join(lines[-TAIL:]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
