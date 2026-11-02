#!/usr/bin/env python3
"""File the findings of one bug-hunt pass as issues. Dry run unless --apply. Stdlib only. CI runs
it on Python 3.10 and 3.8.

Usage:
  hunt.py DRAFTS (--repo OWNER/NAME | --folder DIR) [--apply] [--only TITLE]... [--gh CMD]
          [--offline] [--allow-label NAME]...

  DRAFTS         A folder of findings, one `.md` file each: a header between `---` lines with
                 `title:` and `labels:` lines, then the issue body (format in ../SKILL.md).
  --repo, --folder, --apply, --only, --gh, --offline
                 As for box-audit's file_issues.py, which does the filing: where to file (a
                 GitHub repository, or an issue folder for a project with no hosted VCS), create
                 only with --apply, only these titles, the gh command, a dry run without the host.
  --allow-label  Another label the findings may carry, as for issue_lint.py. Repeatable.

Every finding is checked before anything is filed, and one that fails stops the run:
  - it passes issue_lint.py with its labels;
  - its title starts with `Bug hunt: ` and its labels include `bug`, so box-audit's D collector
    counts it as a defect and its pass by day;
  - it carries no owner-only label (`gate-change-approved`, `findings-accepted`), even when
    --allow-label names one;
  - `## Problem` opens with the three lines
        Found by: bug hunt YYYY-MM-DD at <commit>
        Introducing change: <#N, a pull-request link, a commit, or unknown>
        CI-catchable: <yes or no>
  - every finding names the same `Found by:` line (one run files one dated pass) and a title
    no other finding has.
Filing then follows file_issues.py: each label must exist on the repo, an open issue with the
same title is skipped, and nothing is created without --apply.

Exit codes: 0 dry run printed or every finding filed (or skipped as a duplicate); 1 a finding
fails its checks, a label is missing, or a create failed; 2 usage error (unreadable drafts, bad
--repo or --folder, host unreachable, --offline with --apply or --folder).
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "box-audit" / "scripts"))

import collect  # noqa: E402
import file_issues  # noqa: E402
import issue_lint  # noqa: E402

FOUND = re.compile(r"^Found by: bug hunt (\d{4}-\d{2}-\d{2}) at ([0-9a-f]{7,40})$")
INTRODUCING = re.compile(r"^Introducing change: (unknown|%s)$" % collect.CHANGE_REF)
CATCHABLE = re.compile(r"^CI-catchable: (yes|no)$")
OWNER_ONLY = {"gate-change-approved", "findings-accepted"}


class DraftError(Exception):
    """An unreadable draft: exit 2."""


def read_draft(path):
    """A finding: a header of `key: value` lines between `---` lines, then the body."""
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as e:
        raise DraftError("%s: %s" % (path.name, e))
    m = re.match(r"---\n(.*?)\n---\n?(.*)\Z", text, re.S)
    if not m:
        raise DraftError("%s: no header between --- lines" % path.name)
    fields = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if line.strip() and not sep:
            raise DraftError("%s: header line without a colon: %s" % (path.name, line))
        fields[key.strip()] = value.strip()
    if not fields.get("title"):
        raise DraftError("%s: no title: line" % path.name)
    return {"dimension": "D", "file": path.name, "title": fields["title"],
            "labels": [l.strip() for l in fields.get("labels", "").split(",") if l.strip()],
            "body": m.group(2).strip() + "\n"}


def check(finding, known=issue_lint.KNOWN):
    """Problems with one finding, and its `Found by:` line (None if it has none)."""
    where = finding["file"]
    out = issue_lint.lint(finding["body"], finding["labels"], known, where)
    if not finding["title"].startswith("Bug hunt: "):
        out.append("%s: the title must start with `Bug hunt: `" % where)
    owner_only = [l for l in finding["labels"] if l in OWNER_ONLY]
    if owner_only:
        out.append("%s: %s only the owner applies" % (where, ", ".join(owner_only)))
    if "bug" not in finding["labels"]:
        out.append("%s: needs the bug label" % where)
    problem = next((text for level, title, _, text in issue_lint.headings(finding["body"])
                    if level == 2 and title == "Problem"), "")
    lines = [l.strip() for l in problem.splitlines() if l.strip()][:3] + ["", "", ""]
    found = FOUND.match(lines[0])
    for line, pattern, want in ((lines[0], FOUND, "Found by: bug hunt YYYY-MM-DD at <commit>"),
                                (lines[1], INTRODUCING, "Introducing change: <#N, a link, a "
                                                        "commit, or unknown>"),
                                (lines[2], CATCHABLE, "CI-catchable: yes|no")):
        if not pattern.match(line):
            out.append("%s: ## Problem must open with `%s`, got %r" % (where, want, line[:60]))
    return out, found.group(0) if found else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("drafts")
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo")
    target.add_argument("--folder")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--gh")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--allow-label", action="append", default=[])
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    error = file_issues.target_error(args.repo, args.folder, args.apply, args.offline)
    if error:
        print("hunt: %s" % error, file=sys.stderr)
        return 2
    folder = Path(args.drafts)
    try:
        if not folder.is_dir():
            raise DraftError("%s: not a folder" % folder)
        findings = [read_draft(p) for p in sorted(folder.glob("*.md"))]
    except DraftError as e:
        print("hunt: %s" % e, file=sys.stderr)
        return 2
    problems, passes, titles = [], set(), {}
    for f in findings:
        out, found = check(f, issue_lint.KNOWN | set(args.allow_label))
        problems += out
        passes.add(found)
        if f["title"] in titles:
            problems.append("%s: title %r is also in %s" % (f["file"], f["title"],
                                                             titles[f["title"]]))
        titles.setdefault(f["title"], f["file"])
    if len(passes - {None}) > 1:
        problems.append("findings name more than one pass: %s" % ", ".join(
            sorted(passes - {None})))
    if problems:
        print("FINDINGS_INVALID: fix the drafts first")
        for p in problems:
            print("- " + p)
        return 1
    issues = [f for f in findings if not args.only or f["title"] in args.only]
    if args.only and len(issues) != len(set(args.only)):
        print("hunt: --only names a title no finding has", file=sys.stderr)
        return 2
    return file_issues.file_all(issues, args.repo, args.folder, args.apply, args.gh, args.offline,
                                "hunt")


if __name__ == "__main__":
    sys.exit(main())
