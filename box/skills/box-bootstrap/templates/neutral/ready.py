#!/usr/bin/env python3
"""Ready check: the merge gate where the host cannot enforce required checks. Stdlib only;
Python 3.8+.

Usage:
  python scripts/ready.py --body FILE [--base REF]

  --body FILE   The change description (from the PR template), checked by pr_body_lint.py.
  --base REF    The branch the change merges into (default: @@DEFAULT_BRANCH@@).

It judges the commit checked out, and refuses a working tree with uncommitted or untracked
files (Python bytecode aside), since those are not part of that commit: keep FILE outside the
checkout. In order it runs:
  1. the gate, `python scripts/check.py`;
  2. the tamper guard, `python scripts/tamper_guard.py --base REF`. A gate change passes only
     when the owner's approval tag `gate-change-approved/<full head commit id>` exists and
     points at the head commit. Only the owner creates that tag;
  3. the PR-body lint, `python scripts/pr_body_lint.py FILE`.
The head commit must be the same at the end as at the start.

Merge only on exit 0, and only the commit it printed.

Exit codes: 0 ready; 1 not ready (a verdict; the failed steps are printed); 2 usage error;
3 git error.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APPROVAL_TAG = "gate-change-approved/%s"
BYTECODE = re.compile(r"(^|/)__pycache__/|\.py[co]$")


def git(*args):
    p = subprocess.run(["git"] + list(args), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.stdout.strip() if p.returncode == 0 else None


def step(name, cmd):
    print("== %s" % name, flush=True)
    return subprocess.call([sys.executable] + cmd) == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the merge gate on the head commit.")
    ap.add_argument("--body", required=True, help="the change description file")
    ap.add_argument("--base", default="@@DEFAULT_BRANCH@@")
    args = ap.parse_args(argv)
    if not Path(args.body).is_file():
        print("ready.py: --body %s is not a file" % args.body, file=sys.stderr)
        return 2
    head = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=all")
    if status:
        # Bytecode from an earlier run is not part of any commit and changes no result.
        status = "\n".join(l for l in status.splitlines()
                           if not (l.startswith("?? ") and BYTECODE.search(l[3:])))
    if head is None or status is None or git("rev-parse", "--verify", "-q", args.base) is None:
        print("ready.py: cannot read HEAD, the working tree or base %s" % args.base,
              file=sys.stderr)
        return 3
    print("Judging head commit %s against %s" % (head, args.base))
    failed = []
    if status:
        print("NOT_READY: the working tree has changes that are not in the head commit:\n%s"
              % status)
        return 1
    if not step("gate", [str(HERE / "check.py")]):
        failed.append("gate")
    guard = [str(HERE / "tamper_guard.py"), "--base", args.base]
    if git("rev-parse", "-q", "--verify", "refs/tags/%s^{commit}" % (APPROVAL_TAG % head)) == head:
        print("owner approval tag %s found" % (APPROVAL_TAG % head))
        guard.append("--approved")
    if not step("tamper guard", guard):
        failed.append("tamper guard")
    if not step("PR-body lint", [str(HERE / "pr_body_lint.py"), args.body]):
        failed.append("PR-body lint")
    if git("rev-parse", "HEAD") != head:
        failed.append("head moved during the run")
    if failed:
        print("NOT_READY at %s: %s" % (head, ", ".join(failed)))
        return 1
    print("READY: merge %s and nothing else" % head)
    return 0


if __name__ == "__main__":
    sys.exit(main())
