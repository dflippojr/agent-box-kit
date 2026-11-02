#!/usr/bin/env python3
"""Check a box-audit score card against card-format.md, or score a mark row. Stdlib only. CI runs
it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux).

Usage:
  card.py check CARD      Print CARD_OK, or CARD_INVALID and one problem per line.
  card.py score "ROW"     Print the overall score for a row such as
                          "G ✓ · R ~ · J ✗ · W ~ · P – · D ~".

Exit codes: 0 card valid or row scored; 1 card invalid; 2 usage error (unreadable card,
malformed row).

The overall rule is the one in box/STANDARD.md:
  10 every applicable dimension is ★;
   9 every applicable dimension is ✓ or ★, or exactly one ~ with a written external blocker;
  otherwise 3 + the dimensions marked ~, ✓, ★ or –, at most 8.
"""
import re
import sys
from pathlib import Path

DIMENSIONS = ["G", "R", "J", "W", "P", "D"]
NAMES = {"G": "Enforced gate", "R": "Real-thing tests", "J": "Outside judge",
         "W": "Worker-runnable proof", "P": "Real-use feedback", "D": "Defect ratchet"}
MARKS = "✗~✓★–"
NEVER_NA = {"G", "J", "W", "D"}
TIERS = {"tier:mechanical", "tier:standard", "tier:frontier"}
REVIEWS = {"review:security", "review:concurrency", "review:migration", "review:perf"}
OTHER_LABELS = {"ready", "needs-refinement", "P0", "P1", "P2"}
ISSUE_PARTS = ["**Problem**", "**Want**", "**Constraints**", "**Dependencies**", "**Out of scope**"]
HEADER = ["Repo", "Remote", "Host evidence", "Judge", "Score"]
ROW = re.compile(r"`((?:[A-Z] \S · ){5}[A-Z] \S) → (\d+)`")


def parse_row(row):
    """Marks in G R J W P D order from 'G ✓ · R ~ ...', or None if malformed."""
    cells = [c.split() for c in row.split(" · ")]
    if [c[0] for c in cells if c] != DIMENSIONS or any(len(c) != 2 or c[1] not in MARKS
                                                       for c in cells):
        return None
    return [c[1] for c in cells]


def overall(marks, blocker=False):
    """The standard's overall rule. `blocker`: the one ~ has a written external blocker."""
    applicable = [m for m in marks if m != "–"]
    if all(m == "★" for m in applicable):
        return 10
    if all(m in "✓★" for m in applicable):
        return 9
    if blocker and sum(m == "~" for m in applicable) == 1 and \
            all(m in "~✓★" for m in applicable):
        return 9
    return min(8, 3 + sum(m in "~✓★–" for m in marks))


def sections(text):
    """Map dimension letter to its `## X: Name` section text, in file order."""
    found = []
    for m in re.finditer(r"^## ([A-Z]): (.*?)$(.*?)(?=^## |\Z)", text, re.M | re.S):
        found.append((m.group(1), m.group(2).strip(), m.group(3)))
    return found


def listed(body, label):
    """Items under a `**label**` line up to the next bold label or heading; [] if `none`."""
    m = re.search(r"^\*\*%s\*\*\s*$(.*?)(?=^\*\*|^#|\Z)" % re.escape(label), body, re.M | re.S)
    if not m:
        return None
    text = m.group(1).strip()
    if re.match(r"^(none|- none)\.?$", text, re.I):
        return []
    return [l for l in text.splitlines() if l.strip().startswith("- ")]


def part(body, heading):
    m = re.search(r"^### %s\s*$(.*?)(?=^### |\Z)" % re.escape(heading), body, re.M | re.S)
    return m.group(1).strip() if m else None


def proposals(text):
    """(dimension, title, body) for every proposed issue under any mark. Filing reads this same
    list, so whatever it files has passed check_issue and the one-title rule."""
    for dim, _, body in sections(text):
        block = part(body, "Proposed issues") or ""
        for title, ibody in re.findall(r"^#### (.+?)\s*$(.*?)(?=^#### |\Z)", block, re.M | re.S):
            yield dim, title.strip(), ibody


def check_labels(where, labels, open_, known=TIERS | REVIEWS | OTHER_LABELS):
    """The label rules of the one issue shape, wherever the issue is written: a card's proposal
    or a host issue (queue-fill's issue_lint.py). `open_`: an open decision remains; None when
    the issue does not say, which skips the rules that depend on it."""
    out = []
    tiers = [l for l in labels if l in TIERS]
    if len(tiers) != 1:
        out.append("%s: needs exactly one tier label, has %s" % (where, tiers or "none"))
    unknown = [l for l in labels if l not in known]
    if unknown:
        out.append("%s: unknown labels %s" % (where, unknown))
    if len([l for l in labels if l in REVIEWS]) > 2:
        out.append("%s: at most two review labels" % where)
    if open_ is not None:
        if "ready" in labels and open_:
            out.append("%s: labelled ready with open decisions" % where)
        if "ready" in labels and "needs-refinement" in labels:
            out.append("%s: both ready and needs-refinement" % where)
        if open_ and "needs-refinement" not in labels:
            out.append("%s: open decisions need the needs-refinement label" % where)
    return out


def check_parts(where, names, positions, dependencies):
    """The part rules of the one issue shape: `names` are the five parts as the issue spells
    them, `positions` where each starts (-1 when absent), `dependencies` the Dependencies text."""
    missing = [p for p, pos in zip(names, positions) if pos < 0]
    if missing:
        return ["%s: missing %s" % (where, ", ".join(missing))]
    if positions != sorted(positions):
        return ["%s: parts out of order, want %s" % (where, " ".join(names))]
    if not re.match(r"^(none\.?|Dependencies: #\d+(, #\d+)*)$", dependencies, re.I):
        return ["%s: Dependencies must be `none` or `Dependencies: #N`, got %r"
                % (where, dependencies[:60])]
    return []


def check_issue(dim, title, body):
    out = []
    where = "%s issue %r" % (dim, title)
    m = re.search(r"^Labels:\s*(.+)$", body, re.M)
    labels = [l.strip() for l in m.group(1).split(",")] if m else []
    if not m:
        out.append("%s: no Labels: line" % where)
    d = re.search(r"^Open decisions:\s*(.*)$", body, re.M)
    open_ = not re.match(r"^none\.?$", d.group(1).strip(), re.I) if d else None
    out += check_labels(where, labels, open_)
    if not d:
        out.append("%s: no Open decisions: line" % where)
    positions = [body.find(p) for p in ISSUE_PARTS]
    dep = body[positions[3] + len(ISSUE_PARTS[3]):positions[4]].strip()
    return out + check_parts(where, ISSUE_PARTS, positions, dep)


def check(text):
    out = []
    if not re.match(r"^# Box audit: .+ \(\d{4}-\d{2}-\d{2}\)\s*$", text.splitlines()[0]
                    if text.strip() else ""):
        out.append("first line must be `# Box audit: <repo> (<YYYY-MM-DD>)`")
    for field in HEADER:
        if not re.search(r"^- %s: \S" % re.escape(field), text, re.M):
            out.append("header line `- %s:` missing" % field)
    score = re.search(r"^- Score: (.*)$", text, re.M)
    row = ROW.search(score.group(1)) if score else None
    marks = parse_row(row.group(1)) if row else None
    if score and not marks:
        out.append("Score must look like `G ✓ · R ~ · J ✗ · W ~ · P – · D ~ → 8`")
    if not re.search(r"^## Summary[ \t]*\n(?:[ \t]*\n)*(?!#)\S", text, re.M):
        out.append("## Summary missing or empty")
    found = sections(text)
    if [d for d, _, _ in found] != DIMENSIONS:
        out.append("dimension sections must be ## G, ## R, ## J, ## W, ## P, ## D in that order; "
                   "found %s" % [d for d, _, _ in found])
    blocker, filed = False, list(proposals(text))
    for dim, name, body in found:
        if dim not in DIMENSIONS:
            continue
        mark = marks[DIMENSIONS.index(dim)] if marks else None
        if name != NAMES[dim]:
            out.append("%s: heading should be `## %s: %s`" % (dim, dim, NAMES[dim]))
        m = re.search(r"^\*\*Mark:\*\*\s*(\S+)", body, re.M)
        if not m or m.group(1) not in MARKS:
            out.append("%s: `**Mark:**` line missing or not one of %s" % (dim, " ".join(MARKS)))
        elif mark and m.group(1) != mark:
            out.append("%s: Mark %s differs from the score row's %s" % (dim, m.group(1), mark))
        if mark == "–":
            if dim in NEVER_NA:
                out.append("%s is never n/a" % dim)
            if not re.search(r"^\*\*Reason:\*\*\s*\S", body, re.M):
                out.append("%s: n/a needs a `**Reason:**` line" % dim)
            continue
        if mark == "~" and re.search(r"^\*\*Blocker:\*\*\s*\S", body, re.M):
            blocker = True
        evidence = part(body, "Evidence")
        if evidence is None:
            out.append("%s: ### Evidence missing" % dim)
        else:
            verified, read_only = listed(evidence, "Verified"), listed(evidence, "Read only")
            if verified is None or read_only is None:
                out.append("%s: Evidence needs both **Verified** and **Read only** (a list or "
                           "`none`)" % dim)
            elif not verified and mark in ("✓", "★"):
                out.append("%s: marked %s with no verified evidence; read-only evidence is "
                           "partial at best" % (dim, mark))
            elif not verified and not read_only:
                out.append("%s: no evidence at all" % dim)
        gap = part(body, "Gap")
        if not gap:
            out.append("%s: ### Gap missing or empty" % dim)
        issues = part(body, "Proposed issues")
        if issues is None:
            out.append("%s: ### Proposed issues missing" % dim)
            continue
        if mark != "★" and not any(d == dim for d, _, _ in filed) and \
                not re.search(r"^No issue:\s*\S", issues, re.M):
            out.append("%s: below ★ needs a proposed issue or a `No issue:` line" % dim)
    titles = {}
    for dim, title, body in filed:
        out += check_issue(dim, title, body)
        # Filing checks titles against open issues once, before creating any.
        if title in titles:
            out.append("%s: issue title %r is also proposed under %s; merge them into one issue"
                       % (dim, title, titles[title]))
        titles.setdefault(title, dim)
    if marks and row:
        want = overall(marks, blocker)
        if int(row.group(2)) != want:
            out.append("overall score %s does not follow the rule: %s gives %d" % (
                row.group(2), row.group(1), want))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) != 2 or argv[0] not in ("check", "score"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    if argv[0] == "score":
        marks = parse_row(argv[1].split("→")[0].strip().strip("`"))
        if not marks:
            print("card: malformed row %r" % argv[1], file=sys.stderr)
            return 2
        print(overall(marks))
        return 0
    try:
        text = Path(argv[1]).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print("card: cannot read %s: %s" % (argv[1], e), file=sys.stderr)
        return 2
    problems = check(text)
    if problems:
        print("CARD_INVALID")
        for p in problems:
            print("- " + p)
        return 1
    print("CARD_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
