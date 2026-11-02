#!/usr/bin/env python3
"""Run agent-ready/scripts/red_green_gate.py on every candidate of every case. Stdlib only.

Usage:
  run_gates.py [--cases DIR] [--log FILE]

For each cases/NN-slug/ it builds a throwaway git repo holding target.py (committed, buggy),
copies one candidate in as an untracked test_candidate.py, and runs the gate with that case's
fix.patch and pytest. Prints one line per candidate and writes the full gate output to --log.

Exit codes:
  0  every candidate of every case is RED->GREEN: PASS
  1  at least one candidate is not (the gate rejected it)
  2  harness error (git or pytest missing, gate exit 2)
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE.parent.parent / "agent-ready" / "scripts" / "red_green_gate.py"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True)


def gate_candidate(case_dir, cand):
    work = Path(tempfile.mkdtemp(prefix="evalgate-"))
    try:
        shutil.copyfile(case_dir / "target.py", work / "target.py")
        for cmd in (["init", "-q"], ["config", "user.email", "x@example.com"],
                    ["config", "user.name", "x"], ["config", "commit.gpgsign", "false"],
                    ["config", "core.autocrlf", "false"], ["add", "-A"], ["commit", "-qm", "buggy"]):
            if git(work, *cmd).returncode != 0:
                return 2, "git %s failed" % cmd[0]
        shutil.copyfile(cand, work / "test_candidate.py")
        proc = subprocess.run(
            [sys.executable, str(GATE), "--fix", str(case_dir / "fix.patch"), "--dir", str(work),
             "--red-pattern", "AssertionError", "--", sys.executable, "-B", "-m", "pytest",
             "test_candidate.py", "-q", "-p", "no:cacheprovider"],
            capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default=str(HERE / "cases"))
    ap.add_argument("--log", default=str(HERE / "gate-log.txt"))
    args = ap.parse_args(argv)
    lines, worst = [], 0
    for case_dir in sorted(p for p in Path(args.cases).iterdir() if p.is_dir()):
        for cand in sorted((case_dir / "candidates").glob("test_*.py")):
            code, out = gate_candidate(case_dir, cand)
            verdict = {0: "PASS", 1: "FAIL"}.get(code, "ERROR")
            lines.append("%s %s exit=%d RED->GREEN: %s" % (case_dir.name, cand.stem[5:], code, verdict))
            if code != 0:
                lines.extend("    " + ln for ln in out.strip().splitlines()[-10:])
            worst = max(worst, code)
    text = "\n".join(lines) + "\n"
    print(text, end="")
    Path(args.log).write_bytes(text.encode("utf-8"))
    return worst


if __name__ == "__main__":
    sys.exit(main())
