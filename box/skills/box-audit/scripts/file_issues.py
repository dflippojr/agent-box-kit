#!/usr/bin/env python3
"""File a score card's proposed issues on GitHub, or into an issue folder. Dry run unless --apply.
It files a box-crosspollinate proposal file the same way.
Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux).

Usage:
  file_issues.py CARD (--repo OWNER/NAME | --folder DIR) [--apply] [--only TITLE]... [--gh CMD]
                 [--offline]

  CARD        A score card that passes `card.py check`, or a proposal file box-crosspollinate's
              compare.py wrote (first line `# Box crosspollinate: <repo> (<date>)`), whose
              proposals pass the same issue rules (`card.check_proposal_file`).
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

Exit codes: 0 dry run printed or every issue created (or skipped as a duplicate); 1 the card or
proposal file is invalid, a proposal fails issue_lint.py, a label is missing, or a create failed; 2 usage error (unreadable card, bad --repo,
unreadable --folder, host unreachable, --offline with --apply or --folder).
"""
import sys
# Before any other import: box/lib sits in the kit, which may be the audited checkout.
sys.dont_write_bytecode = True

from pathlib import Path  # noqa: E402

# box/lib, in the checkout this file sits in, holds the helpers box scripts share (issue #36).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

import argparse  # noqa: E402
import re  # noqa: E402

import scorecard  # noqa: E402
from filing import file_all, target_error  # noqa: E402
from issue_shape import lint  # noqa: E402

PARTS = ["Problem", "Want", "Constraints", "Dependencies", "Out of scope"]


def proposed(text, source="a box audit"):
    """Proposed issues as dicts: dimension, title, labels, body (Markdown for the host).
    `source` names what proposed them in each body's last line."""
    issues = []
    for dim, title, ibody in scorecard.proposals(text):
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
        out.append("_Proposed by %s (dimension %s)._" % (source, dim))
        issues.append({"dimension": dim, "title": title,
                       "labels": [l.strip() for l in labels.group(1).split(",")]
                       if labels else [], "body": "\n".join(out).strip() + "\n"})
    return issues


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
    crosspollinate = text.startswith("# Box crosspollinate:")
    problems = scorecard.check_proposal_file(text) if crosspollinate else scorecard.check(text)
    if problems:
        print("PROPOSAL_FILE_INVALID: fix the proposal file first" if crosspollinate
              else "CARD_INVALID: fix the card first")
        for p in problems:
            print("- " + p)
        return 1
    source = "box-crosspollinate" if crosspollinate else "a box audit"
    issues = [i for i in proposed(text, source) if not args.only or i["title"] in args.only]
    if args.only and len(issues) != len(set(args.only)):
        print("file_issues: --only names a title the file does not have", file=sys.stderr)
        return 2
    problems = [p for i in issues for p in lint(i["body"], i["labels"], where=i["title"])]
    if problems:
        print("PROPOSALS_INVALID: these proposals would not have the issue shape; fix the card")
        for p in problems:
            print("- " + p)
        return 1
    return file_all(issues, args.repo, args.folder, args.apply, args.gh, args.offline)


if __name__ == "__main__":
    sys.exit(main())
