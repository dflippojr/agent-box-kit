#!/usr/bin/env python3
"""The one-command gate: every step CI runs, run the same way locally. Stdlib only.

Usage:
  python scripts/check.py

CI runs this file and nothing else, so the local run and CI cannot drift. Add a step (lint,
type check, coverage floor) to STEPS, never to the CI config alone.

A gate that runs nothing is not a gate: pytest finding no tests (its exit 5) fails the gate.

Exit codes: 0 every step passed; 1 a step failed; 2 usage error.
"""
import subprocess
import sys

STEPS = [
    ("tests", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]),
]
NO_TESTS = 5  # pytest's exit code when it collected nothing


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print("check.py takes no arguments", file=sys.stderr)
        return 2
    failed = []
    for name, cmd in STEPS:
        print("== %s: %s" % (name, " ".join(cmd)), flush=True)
        code = subprocess.call(cmd)
        if code == NO_TESTS and name == "tests":
            print("== %s: no tests collected; a gate that runs nothing fails" % name)
        if code != 0:
            failed.append(name)
    print("GATE_FAIL: %s" % ", ".join(failed) if failed else "GATE_PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
