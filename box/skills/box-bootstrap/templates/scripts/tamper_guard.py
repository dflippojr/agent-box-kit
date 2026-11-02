#!/usr/bin/env python3
"""Tamper guard: flag a change that weakens the gate, so it cannot merge without the owner's
explicit approval. Stdlib only; Python 3.8+.

Usage:
  python scripts/tamper_guard.py --base REF [--head REF] [--approved]

  --base REF    The commit the change is judged against (the target branch, or its commit).
  --head REF    The change's commit (default: HEAD).
  --approved    The owner approved the gate change on this head commit. The caller decides
                who may say so: CI passes it when the owner-only approval label is on the
                change; the `ready` script passes it when the owner's approval tag names the
                head commit.

What counts as weakening the gate, in the diff from the merge base of REF and HEAD:
  - a test file deleted or moved out of the tests, or a test function removed;
  - a skip, xfail or retry added to a test file or to test configuration;
  - an edit to gate config: CI workflows, these gate scripts, coverage, pytest or lint config
    (including those sections of pyproject.toml), CODEOWNERS, the PR template, `.box-profile`.

Exit codes: 0 nothing flagged, or flagged and approved; 1 flagged and not approved (a
verdict); 2 usage error; 3 git error.
"""
import argparse
import re
import subprocess
import sys

TEST_FILE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")
TEST_CONFIG = re.compile(r"^(pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml|noxfile\.py)$")
WEAKENS = re.compile(
    r"pytest\.mark\.(skip|skipif|xfail|flaky)|pytest\.(skip|xfail|importorskip)\(|"
    r"unittest\.(skip|skipIf|skipUnless|expectedFailure)|@skip\b|\.skipTest\(|@flaky\b|"
    r"\breruns?\b|rerunfailures|pytest[-_]retry|@retry\b|--deselect|--ignore\b")
TEST_DEF = re.compile(r"^\s*(async\s+)?def\s+(test\w*)\s*\(")
GATE_FILES = {"scripts/check.py", "scripts/ready.py", "scripts/tamper_guard.py",
              "scripts/pr_body_lint.py", ".box-profile", ".coveragerc", "pytest.ini", "tox.ini",
              "setup.cfg", "noxfile.py", "sonar-project.properties", ".pre-commit-config.yaml",
              "CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS",
              ".github/pull_request_template.md", "docs/pull_request_template.md"}
GATE_PREFIXES = (".github/workflows/",)
GATE_SECTION = re.compile(r"^\[+\s*tool\.(pytest|coverage|mypy|ruff|pyright|tox)\b")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class GitError(Exception):
    pass


def git(*args):
    p = subprocess.run(["git", "-c", "core.quotePath=false"] + list(args), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise GitError("git %s: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout


def show(ref, path):
    try:
        return git("show", "%s:%s" % (ref, path))
    except GitError:
        return ""


def section_at(text, line):
    """The TOML table header in force at 1-based `line` of text, or ''."""
    current = ""
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("["):
            current = raw.strip()
        if n >= line:
            break
    return current


def changes(base, head):
    """(status, old path, new path) for each changed file, renames detected."""
    out = git("diff", "--name-status", "-z", "-M", "%s...%s" % (base, head)).split("\0")
    found, i = [], 0
    while i < len(out) - 1:
        status = out[i]
        if status[:1] in "RC":
            found.append((status[0], out[i + 1], out[i + 2]))
            i += 3
        else:
            found.append((status[0], out[i + 1], out[i + 1]))
            i += 2
    return found


def hunks(base, head, old, new):
    """(removed [(old line, text)], added [(new line, text)]) for one file, renamed or not."""
    patch = git("diff", "-U0", "-M", "--no-color", "%s...%s" % (base, head), "--",
                *sorted({old, new}))
    removed, added, old, new = [], [], 0, 0
    for line in patch.splitlines():
        m = HUNK.match(line)
        if m:
            old, new = int(m.group(1)), int(m.group(3))
        elif line.startswith("-") and not line.startswith("---"):
            removed.append((old, line[1:]))
            old += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added.append((new, line[1:]))
            new += 1
    return removed, added


def findings(base, head):
    merge_base = git("merge-base", base, head).strip()
    flagged = []
    for status, old, new in changes(base, head):
        if TEST_FILE.search(old) and (status == "D" or (status == "R" and
                                                        not TEST_FILE.search(new))):
            flagged.append("deletes test file %s" % old)
        if new in GATE_FILES or old in GATE_FILES or new.startswith(GATE_PREFIXES):
            flagged.append("edits gate config %s" % new)
            continue
        if status == "D":
            continue
        if not (TEST_FILE.search(new) or TEST_CONFIG.match(new)):
            continue
        removed, added = hunks(base, head, old, new)
        if new == "pyproject.toml":
            before, after = show(merge_base, old), show(head, new)
            touched = [section_at(before, n) for n, _ in removed]
            touched += [section_at(after, n) for n, _ in added]
            touched += [text.strip() for _, text in removed + added]
            if any(GATE_SECTION.match(s) for s in touched):
                flagged.append("edits gate config pyproject.toml (pytest, coverage or lint)")
                continue
        for n, text in added:
            if WEAKENS.search(text):
                flagged.append("adds a skip, xfail or retry at %s:%d: %s" % (new, n, text.strip()))
        gone = {m.group(2) for _, t in removed for m in [TEST_DEF.match(t)] if m}
        back = {m.group(2) for _, t in added for m in [TEST_DEF.match(t)] if m}
        for name in sorted(gone - back):
            flagged.append("removes test %s from %s" % (name, new))
    return flagged


def main(argv=None):
    ap = argparse.ArgumentParser(description="Flag changes that weaken the gate.")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--approved", action="store_true")
    args = ap.parse_args(argv)
    try:
        flagged = findings(args.base, args.head)
    except GitError as exc:
        print("tamper_guard.py: %s" % exc, file=sys.stderr)
        return 3
    for line in flagged:
        print("GATE CHANGE: %s" % line)
    if not flagged:
        print("TAMPER_GUARD_PASS: no gate change")
        return 0
    if args.approved:
        print("TAMPER_GUARD_PASS: %d gate change(s), approved by the owner" % len(flagged))
        return 0
    print("TAMPER_GUARD_FAIL: %d gate change(s) need the owner's explicit approval" % len(flagged))
    return 1


if __name__ == "__main__":
    sys.exit(main())
