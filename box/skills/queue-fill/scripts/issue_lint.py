#!/usr/bin/env python3
"""Check an issue against the one shape every queue-fill pass writes. Stdlib only. CI runs it on
Python 3.10 and 3.8.

Usage:
  issue_lint.py BODY --labels LABELS [--allow-label NAME]...
  issue_lint.py --issue-file FILE [--allow-label NAME]...

  BODY           The issue body as the host shows it, Markdown with `## Problem`-style headings;
                 `-` reads stdin.
  --labels       The issue's labels, comma-separated (`tier:standard, ready`).
  --issue-file   An issue file in box/orchestrate's issue-folder format instead: the labels come
                 from its header and the body follows it.
  --allow-label  Another label the repo uses, such as a topic label. Repeatable. Known without
                 it: the tier, review, priority, `ready` and `needs-refinement` labels box-audit's
                 card.py knows, the holding labels select.py knows, and `bug`.

The shape, checked with card.py's own label and part rules (`check_labels`, `check_parts`):
  - `## Problem`, `## Want`, `## Constraints`, `## Dependencies` and `## Out of scope`, in that
    order, each once and none empty. Other sections may sit between them.
  - `## Dependencies` holds one line, `Dependencies: #N` (`Dependencies: #3, #4`) or
    `Dependencies: none`, and nothing else: select.py reads every line under that heading, and a
    note there holds the issue from dispatch.
  - Exactly one tier label, at most two review labels, only known labels.
  - A `## Open question` heading (any level), with the question under it, if the issue is
    labelled `needs-refinement`.
  - No open question with `ready`. This check fails closed: each line is normalized (HTML
    comments and tags stripped, link destinations dropped, character references decoded, NFKC,
    only letters and digits kept, lowercased, Cyrillic and Greek look-alikes folded to Latin),
    and a line, or two adjacent lines, containing `openquestion` in any of those forms is open,
    wherever it is, fenced code and HTML comments included.
  - Only Markdown the lint models: no HTML block (a comment that closes on its own line, such as
    a tool's marker, is fine), no Setext heading (a line of only `=` or `-` under a text line)
    and no line that looks like a code fence but is not exact: a fence starts at column 0 and
    has only ASCII spaces or tabs on its line (none in a list item, a quote or indented).
    Lines end only at LF, CR or CRLF, as on the host; a U+0085, U+2028 or U+2029 anywhere
    fails. Required sections are `##` headings outside fenced code.
The lint over-flags on purpose: rather than guess how a renderer reads unusual Markdown, it
rejects it. To pass, delete an answered question and rewrite flagged structures plainly.

Prints ISSUE_OK, or ISSUE_INVALID and one problem per line.

Exit codes: 0 the issue passes; 1 the lint found problems; 2 usage error (bad options, unreadable
body or issue file).
"""
import sys
# Before any other import: box/lib gets no bytecode beside the helpers.
sys.dont_write_bytecode = True

from pathlib import Path  # noqa: E402

# box/lib, in the checkout this file sits in, holds the helpers box scripts share (issue #36).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

import argparse  # noqa: E402

import issue_folder  # noqa: E402
from issue_shape import KNOWN, lint  # noqa: E402


def report(problems):
    if problems:
        print("ISSUE_INVALID")
        for p in problems:
            print("- " + p)
        return 1
    print("ISSUE_OK")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("body", nargs="?")
    ap.add_argument("--labels")
    ap.add_argument("--issue-file")
    ap.add_argument("--allow-label", action="append", default=[])
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    known = KNOWN | set(args.allow_label)
    if args.issue_file:
        if args.body is not None or args.labels is not None:
            print("issue_lint: --issue-file takes no BODY or --labels", file=sys.stderr)
            return 2
        try:
            issue = issue_folder.parse_issue_file(Path(args.issue_file))
        except (OSError, UnicodeDecodeError, issue_folder.InputError) as e:
            print("issue_lint: %s" % e, file=sys.stderr)
            return 2
        return report(lint(issue["body"], issue["labels"], known, "#%d" % issue["number"]))
    if args.body is None or args.labels is None:
        print("issue_lint: give BODY and --labels, or --issue-file", file=sys.stderr)
        return 2
    try:
        body = sys.stdin.read() if args.body == "-" else \
            Path(args.body).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print("issue_lint: cannot read %s: %s" % (args.body, e), file=sys.stderr)
        return 2
    labels = [l.strip() for l in args.labels.split(",") if l.strip()]
    return report(lint(body, labels, known))


if __name__ == "__main__":
    sys.exit(main())
