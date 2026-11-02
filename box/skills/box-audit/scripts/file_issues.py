#!/usr/bin/env python3
"""File a score card's proposed issues on GitHub, or into an issue folder. Dry run unless --apply.
Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux).

Usage:
  file_issues.py CARD (--repo OWNER/NAME | --folder DIR) [--apply] [--only TITLE]... [--gh CMD]
                 [--offline]

  CARD        A score card that passes `card.py check`.
  --repo      Where to file. One of --repo and --folder is required: a card can be filed
              somewhere other than its remote.
  --folder    File into DIR instead, an issue folder in box/orchestrate's format for a project
              with no hosted VCS: each issue becomes `<number>.md`, numbered after the highest
              number already there, open, with its labels and today's time. A folder has no
              label list, so labels are not checked there.
  --apply     Create the issues. Without it, print what would be created and change nothing.
  --only      File only the issue with this exact title. Repeatable.
  --gh CMD    The command that runs gh, split like a shell would (default: `gh` on PATH).
  --offline   Dry run without reading the host: skips the label and duplicate checks, and says so.
              Not allowed with --apply.

Each issue body has the `## Problem`, `## Want`, `## Constraints`, `## Dependencies` and
`## Out of scope` sections, and `## Open questions` when a decision is open: the shape
queue-fill's issue_lint.py checks. Every proposal must pass it before anything is filed: the card
check alone allows, for one, `needs-refinement` with `Open decisions: none`.

Before creating anything, every label the issues use must already exist on the repo, and an
open issue with the same title is skipped as a duplicate; both lists are read to the last page.
In a folder, an open issue file with the same title is skipped.
A missing label stops the whole run: creating labels is the owner's call. Every proposal, under
any mark including n/a, passes `card.py check`, and a card that proposes one title twice fails
it, so one run never files a title twice.

Exit codes: 0 dry run printed or every issue created (or skipped as a duplicate); 1 the card is
invalid, a proposal fails issue_lint.py, a label is missing, or a create failed; 2 usage error (unreadable card, bad --repo,
unreadable --folder, host unreachable, --offline with --apply or --folder).
"""
import argparse
import importlib.util
import itertools
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "queue-fill" / "scripts"))

import card  # noqa: E402
import issue_lint  # noqa: E402

select = issue_lint.select  # box/orchestrate's select.py, which reads issue folders

# gh's read handling, one implementation for every host reader, loaded by path from box/lib in the
# checkout this file sits in, as collect.py does. Its timeout and error text apply to every read.
GH_READ = HERE.parents[2] / "lib" / "gh_read.py"
_spec = importlib.util.spec_from_file_location("box_gh_read", str(GH_READ))
gh_read = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gh_read)

PARTS = ["Problem", "Want", "Constraints", "Dependencies", "Out of scope"]


def proposed(text):
    """Proposed issues as dicts: dimension, title, labels, body (Markdown for the host)."""
    issues = []
    for dim, title, ibody in card.proposals(text):
        labels = re.search(r"^Labels:\s*(.+)$", ibody, re.M)
        decisions = re.search(r"^Open decisions:\s*(.*)$", ibody, re.M)
        out = []
        for name in PARTS:
            m = re.search(r"^\*\*%s\*\*\s*$(.*?)(?=^\*\*(%s)\*\*|\Z)" % (
                re.escape(name), "|".join(re.escape(p) for p in PARTS)), ibody, re.M | re.S)
            content = m.group(1).strip() if m else ""
            if name == "Dependencies":
                content = content if content.lower().startswith("dependencies:") \
                    else "Dependencies: none"
            out += ["## %s" % name, content, ""]
        if decisions and not re.match(r"^none\.?$", decisions.group(1).strip(), re.I):
            out += ["## Open questions", decisions.group(1).strip(), ""]
        out.append("_Proposed by a box audit (dimension %s)._" % dim)
        issues.append({"dimension": dim, "title": title,
                       "labels": [l.strip() for l in labels.group(1).split(",")]
                       if labels else [], "body": "\n".join(out).strip() + "\n"})
    return issues


def gh_json(gh, args):
    """One read-only gh call: (body, error), as gh_read.read returns them."""
    return gh_read.read(gh + args)


def read_all(gh, what, path):
    """Every item of a paged host list, to the last page: a label or title missed on a later page
    would be reported missing or filed twice. Raises RuntimeError."""
    items = []
    for page in itertools.count(1):
        body, error = gh_json(gh, ["api", "%s&page=%d" % (path, page)])
        if error:
            raise RuntimeError("%s: %s" % (what, error))
        items += body or []
        if len(body or []) < 100:
            return items


def host_state(gh, repo):
    """(label names, open issue titles) or raise RuntimeError."""
    labels = read_all(gh, "labels", "repos/%s/labels?per_page=100" % repo)
    issues = read_all(gh, "issues", "repos/%s/issues?state=open&per_page=100" % repo)
    return ({l["name"] for l in labels},
            {i["title"] for i in issues if "pull_request" not in i})


def target_error(repo, folder, apply, offline):
    """The usage error in a filing target, or None. Checked before the issues are read."""
    if repo is not None and not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        return "--repo must be OWNER/NAME"
    if offline and folder is not None:
        return "--offline is for --repo dry runs; a folder is read anyway"
    if offline and apply:
        return "--offline is for dry runs only"
    return None


def issue_file(number, title, labels, body, created, state="open"):
    """An issue file in box/orchestrate's issue-folder format."""
    if "\n" in title or "\n" in created:
        raise ValueError("a header value spans lines")
    return "---\nnumber: %d\ntitle: %s\nstate: %s\nlabels: %s\ncreatedAt: %s\n---\n%s" % (
        number, title, state, ", ".join(labels), created, body)


def file_all(issues, repo, folder, apply, gh_spec, offline, name="file_issues"):
    """Print what would be filed and, with `apply`, file it: on the GitHub repository `repo`, or
    into the issue folder `folder`. Each issue is a dict with dimension, title, labels and body.
    Returns the exit code."""
    labels, titles, existing = None, set(), []
    if folder is not None:
        try:
            existing = select.read_folder(folder)
        except select.InputError as e:
            print("%s: cannot read %s: %s" % (name, folder, e), file=sys.stderr)
            return 2
        titles = {i["title"] for i in existing if i["state"] == "OPEN"}
    try:
        gh = shlex.split(gh_spec) if gh_spec else ([shutil.which("gh")] if shutil.which("gh")
                                                   else None)
    except ValueError as e:
        print("%s: --gh: %s" % (name, e), file=sys.stderr)
        return 2
    if folder is None and not offline:
        if not gh:
            print("%s: gh CLI not found" % name, file=sys.stderr)
            return 2
        try:
            labels, titles = host_state(gh, repo)
        except RuntimeError as e:
            print("%s: cannot read %s: %s" % (name, repo, e), file=sys.stderr)
            return 2
    missing = sorted({l for i in issues for l in i["labels"]} - labels) if labels is not None \
        else []
    mode = "APPLY" if apply else "DRY RUN"
    note = " (offline: labels and duplicates not checked)" if offline else \
        " (a folder has no label list: labels not checked)" if folder is not None else ""
    print("%s: %d proposed issues for %s%s" % (mode, len(issues), repo or folder, note))
    for i in issues:
        dup = i["title"] in titles
        print("\n=== [%s] %s%s\nLabels: %s\n\n%s" % (
            i["dimension"], i["title"], "  (SKIP: an open issue has this title)" if dup else "",
            ", ".join(i["labels"]), i["body"]))
    if missing:
        print("MISSING LABELS on %s: %s. Nothing was created; ask the owner to add them."
              % (repo, ", ".join(missing)))
        return 1
    if not apply:
        return 0
    failed = 0
    number = max([i["number"] for i in existing] or [0])
    for i in issues:
        if i["title"] in titles:
            continue
        if folder is not None:
            number += 1
            path = Path(folder) / ("%d.md" % number)
            try:
                with open(str(path), "x", encoding="utf-8", newline="\n") as f:
                    f.write(issue_file(number, i["title"], i["labels"], i["body"],
                                       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
            except (OSError, ValueError) as e:
                failed += 1
                print("FAILED %r: %s" % (i["title"], e))
                continue
            titles.add(i["title"])
            print("CREATED %s" % path)
            continue
        cmd = ["issue", "create", "-R", repo, "--title", i["title"], "--body", i["body"]]
        for label in i["labels"]:
            cmd += ["--label", label]
        p = subprocess.run(gh + cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if p.returncode == 0:
            titles.add(i["title"])
            print("CREATED %s" % p.stdout.strip())
        else:
            failed += 1
            print("FAILED %r: %s" % (i["title"], p.stderr.strip()[:200]))
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("card")
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo")
    target.add_argument("--folder")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--gh")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    error = target_error(args.repo, args.folder, args.apply, args.offline)
    if error:
        print("file_issues: %s" % error, file=sys.stderr)
        return 2
    try:
        text = Path(args.card).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print("file_issues: cannot read %s: %s" % (args.card, e), file=sys.stderr)
        return 2
    problems = card.check(text)
    if problems:
        print("CARD_INVALID: fix the card first")
        for p in problems:
            print("- " + p)
        return 1
    issues = [i for i in proposed(text) if not args.only or i["title"] in args.only]
    if args.only and len(issues) != len(set(args.only)):
        print("file_issues: --only names a title the card does not have", file=sys.stderr)
        return 2
    problems = [p for i in issues for p in issue_lint.lint(i["body"], i["labels"],
                                                           where=i["title"])]
    if problems:
        print("PROPOSALS_INVALID: these proposals would not have the issue shape; fix the card")
        for p in problems:
            print("- " + p)
        return 1
    return file_all(issues, args.repo, args.folder, args.apply, args.gh, args.offline)


if __name__ == "__main__":
    sys.exit(main())
