#!/usr/bin/env python3
"""PR-body lint: the change description must carry its proof. Stdlib only; Python 3.8+.

Usage:
  python scripts/pr_body_lint.py FILE     Read the description from FILE, or stdin for `-`.

The description passes when it has, outside HTML comments, with no `<placeholder>` left in
these parts:
  - a `## Proof` section holding a table with at least one row: criterion, how verified,
    evidence, each filled in;
  - a `### Not verified` section that is not empty (say what you did not check and why);
  - a `### Gate changes` section that is not empty (`none` when there are none);
    a closing-reference line inside either section does not count as its content;
  - a closing reference: a line starting `Closes`, `Fixes` or `Resolves` and naming the issue
    (`#12`, `owner/repo#12`, `PROJ-12` or the issue's URL).

Exit codes: 0 the description passes; 1 it does not (a verdict; each problem is printed);
2 usage error, or FILE unreadable.
"""
import re
import sys

PLACEHOLDER = re.compile(r"<[^<>\n]+>")
# Closes #12, Closes owner/repo#12, Closes PROJ-12 or Closes <issue URL>.
CLOSING = re.compile(r"^[ \t]*(closes|fixes|resolves):?[ \t]+([\w./-]*#\d+|[A-Z][A-Z0-9]+-\d+|"
                     r"https?://\S+|#?<[^<>\n]+>)", re.I | re.M)


def section(text, heading):
    """The text under a heading, up to the next heading of the same or a higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    m = re.search(r"^%s\s*$(.*?)(?=^#{1,%d} |\Z)" % (re.escape(heading), level), text,
                  re.M | re.S | re.I)
    return m.group(1) if m else None


def table_rows(text):
    """Data rows of the first markdown table in text, each as a list of cell strings."""
    rows = []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            rows.append(line.strip())
        elif rows:
            break
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    if len(cells) < 2 or not all(re.match(r"^:?-+:?$", c) for c in cells[1]):
        return []
    return cells[2:]


def problems(body):
    text = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    found, checked = [], []
    proof = section(text, "## Proof")
    if proof is None:
        found.append("no `## Proof` section")
    else:
        rows = table_rows(proof)
        if not rows:
            found.append("`## Proof` has no table with a row per acceptance criterion")
        for row in rows:
            if len(row) < 3 or not all(row[:3]):
                found.append("proof row has an empty cell: | %s |" % " | ".join(row))
            checked += row
    for heading in ("### Not verified", "### Gate changes"):
        part = section(text, heading)
        if part is None:
            found.append("no `%s` section" % heading)
        elif not "".join(l for l in part.splitlines() if not CLOSING.match(l)).strip():
            found.append("`%s` is empty" % heading)
        else:
            checked.append(part)
    closing = [m.group(0) for m in CLOSING.finditer(text)]
    if not closing:
        found.append("no closing reference (`Closes ISSUE`)")
    for left in sorted(set(PLACEHOLDER.findall("\n".join(checked + closing)))):
        found.append("template placeholder left in: %s" % left)
    return found


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: pr_body_lint.py FILE (or - for stdin)", file=sys.stderr)
        return 2
    try:
        if argv[0] == "-":
            body = sys.stdin.read()
        else:
            with open(argv[0], encoding="utf-8") as f:
                body = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        print("pr_body_lint.py: cannot read %s: %s" % (argv[0], exc), file=sys.stderr)
        return 2
    found = problems(body)
    for line in found:
        print("PR BODY: %s" % line)
    print("PR_BODY_FAIL" if found else "PR_BODY_PASS")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
