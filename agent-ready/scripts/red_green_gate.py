#!/usr/bin/env python3
"""Objective red->green gate: does a test really reproduce a bug? Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux); other versions and distributions are not verified.

Usage:
  red_green_gate.py --fix FIX.patch [--dir REPO] [--timeout SECONDS] [--red-pattern REGEX]
                    [--tail N] -- <test command and arguments>

Example:
  red_green_gate.py --fix fix.patch -- python -m pytest tests/test_bug.py -q

What it does
  1. Preflight: the repo has no tracked changes (untracked files are allowed, because the
     test under evaluation is usually a new file) and the patch applies cleanly.
  2. RED:   run the test command on the current (buggy) tree. It must FAIL.
  3. Apply the fix patch and run the command again.
  4. GREEN: it must PASS.
  5. Always revert the patch, and verify the tree is back to how it started.

Verdicts and exit codes
  0  RED->GREEN: PASS   red on the buggy tree, green after the fix
  1  RED->GREEN: FAIL   the test is green before the fix (a false reproduction), still red after
                        the fix, or red for a reason that does not match --red-pattern
  2  harness error      preflight failed, command not found, timeout, or the tree could not be
                        restored. Never treated as red: a broken harness proves nothing.

The command is run without a shell (pass arguments after `--`). The model never decides the
verdict; only the exit code of your command does.
Python subprocesses inherit an empty temporary bytecode-cache location and disabled cache
writes, so same-size fixes in the same timestamp second cannot reuse stale bytecode (Python 3.8+).
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


class HarnessError(Exception):
    pass


def run_git(root, *args):
    return subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True)


def tracked_dirty(root):
    proc = run_git(root, "status", "--porcelain", "--untracked-files=no")
    if proc.returncode != 0:
        raise HarnessError("git status failed: %s" % proc.stderr.strip())
    return proc.stdout.strip()


def run_command(cmd, root, timeout):
    try:
        # Disabling writes alone still permits reading existing stale bytecode.
        with tempfile.TemporaryDirectory(prefix="red-green-pyc-") as cache:
            env = os.environ.copy()
            env["PYTHONPYCACHEPREFIX"] = cache
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                                  errors="replace", timeout=timeout, env=env)
    except FileNotFoundError:
        raise HarnessError("command not found: %s" % cmd[0])
    except subprocess.TimeoutExpired:
        raise HarnessError("command timed out after %ss" % timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def tail(text, n):
    lines = text.strip().splitlines()
    return "\n".join("    " + line for line in lines[-n:])


def gate(root, patch, cmd, timeout, red_pattern, tail_lines):
    root = Path(root).resolve()
    patch = Path(patch).resolve()
    if not patch.is_file():
        raise HarnessError("patch not found: %s" % patch)
    if run_git(root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        raise HarnessError("%s is not a git working tree" % root)
    dirty = tracked_dirty(root)
    if dirty:
        raise HarnessError("tracked files have uncommitted changes; commit or stash them first:\n"
                           + tail(dirty, 10))
    check = run_git(root, "apply", "--check", str(patch))
    if check.returncode != 0:
        raise HarnessError("fix patch does not apply to the current tree: %s" % check.stderr.strip())

    code, out = run_command(cmd, root, timeout)
    if code == 0:
        print("RED->GREEN: FAIL")
        print("  The test PASSED on the buggy tree, so it does not reproduce the bug "
              "(false reproduction).")
        return 1
    if red_pattern and not re.search(red_pattern, out):
        print("RED->GREEN: FAIL")
        print("  The test failed on the buggy tree, but its output does not match "
              "--red-pattern, so it may be red for the wrong reason:")
        print(tail(out, tail_lines))
        return 1
    print("  [red]   failed on the buggy tree, as expected (exit %d)" % code)

    applied = run_git(root, "apply", str(patch))
    if applied.returncode != 0:
        raise HarnessError("could not apply the fix patch: %s" % applied.stderr.strip())
    try:
        code, out = run_command(cmd, root, timeout)
    finally:
        reverted = run_git(root, "apply", "-R", str(patch))
        leftover = tracked_dirty(root)
        if reverted.returncode != 0 or leftover:
            print("RED->GREEN: harness error: the tree was NOT restored. Inspect with "
                  "'git status' and 'git diff' before doing anything else.", file=sys.stderr)
            if leftover:
                print(tail(leftover, 10), file=sys.stderr)
            # Do not mask an in-flight exception; the caller sees exit 2 either way.
            raise SystemExit(2)

    if code != 0:
        print("RED->GREEN: FAIL")
        print("  The test still FAILS after the fix (exit %d). Either the test asserts the wrong "
              "thing, it fails for an unrelated reason such as a compile error, or the patch is "
              "wrong:" % code)
        print(tail(out, tail_lines))
        return 1
    print("  [green] passed after the fix, as expected")
    print("RED->GREEN: PASS")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("red_green_gate: put the test command after '--'", file=sys.stderr)
        return 2
    split = argv.index("--")
    opts, cmd = argv[:split], argv[split + 1:]
    if not cmd:
        print("red_green_gate: empty test command", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fix", required=True, help="unified diff that fixes the bug")
    ap.add_argument("--dir", default=".", help="repository root (default: current directory)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per test run")
    ap.add_argument("--red-pattern", help="regex the failing output must match")
    ap.add_argument("--tail", type=int, default=20, help="output lines to show on failure")
    args = ap.parse_args(opts)
    try:
        return gate(args.dir, args.fix, cmd, args.timeout, args.red_pattern, args.tail)
    except HarnessError as exc:
        print("RED->GREEN: harness error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
