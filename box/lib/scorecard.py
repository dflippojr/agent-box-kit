"""The box-audit score card's rules: the mark row, the overall and Proven values, the Standard
hash, and the card and issue-shape checks. Stdlib only; Python 3.8+. Not a script: box-audit's
card.py (the CLI, whose docstring states the rules), audit.py, judge.py and file_issues.py,
box-crosspollinate's compare.py and queue-fill's issue_lint rules import it from box/lib
(issue #36). Sections and parts are read with md.py, outside fenced code.
"""
import hashlib
import re
from pathlib import Path

import md

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
KIT = Path(__file__).resolve().parents[1]  # box/: lib -> box
# Paths in the kit, in hashing order. Moving or renaming one changes the value too.
RUBRIC = ["STANDARD.md", "skills/box-audit/judge-prompt.md", "skills/box-audit/card-format.md",
          "skills/box-audit/scripts/collect.py"]
STANDARD_LINE = re.compile(r"^- Standard:[^\n]*\n?", re.M)


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


def proven(marks):
    """The standard's Proven value as text with one decimal, e.g. '5.0'. Integer arithmetic,
    so a half rounds up rather than to even."""
    applicable = [m for m in marks if m != "–"]
    if not applicable:  # only a malformed card marks G, J, W and D n/a; check reports it
        return "0.0"
    halves = sum(2 if m in "✓★" else 1 if m == "~" else 0 for m in applicable)
    tenths = (100 * halves + len(applicable)) // (2 * len(applicable))  # 50*halves/n, half up
    return "%d.%d" % divmod(tenths, 10)


PROVEN = re.compile(r"^- Proven:[^\n]*\n?", re.M)


def stamp_proven(text):
    """`text` with its `- Proven:` line computed from the score row, right after `- Score:`,
    replacing any Proven line the judge wrote. Unchanged when the score row is malformed."""
    score = re.search(r"^- Score: (.*)$", text, re.M)
    row = ROW.search(score.group(1)) if score else None
    marks = parse_row(row.group(1)) if row else None
    if not marks:
        return text
    text = PROVEN.sub("", text)
    score = re.search(r"^- Score: .*$", text, re.M)
    return "%s\n- Proven: %s%s" % (text[:score.end()], proven(marks), text[score.end():])


def standard_hash(kit=KIT, standard_text=None):
    """The Standard value of the rubric in `kit` (default: the kit this script sits in), as 12
    lowercase hex digits. `standard_text`, when given, is the text hashed in place of the kit's
    STANDARD.md: the text a caller already read and gave the judge. Raises OSError when a file
    cannot be read."""
    h = hashlib.sha256()
    for rel in RUBRIC:
        if standard_text is not None and rel == "STANDARD.md":
            data = standard_text.encode("utf-8")
        else:
            data = (Path(kit) / rel).read_bytes()
        data = data.replace(b"\r\n", b"\n")
        h.update(("%s\n%d\n" % (rel, len(data))).encode("utf-8"))
        h.update(data)
    return h.hexdigest()[:12]


def stamp_standard(text, value):
    """`text` with one `- Standard: value` line, right after `- Proven:` (or `- Score:`),
    replacing any Standard line the judge wrote. Unchanged when the card has no Score line."""
    if not re.search(r"^- Score: .*$", text, re.M):
        return text
    text = STANDARD_LINE.sub("", text)
    anchor = re.search(r"^- Proven: .*$", text, re.M) or re.search(r"^- Score: .*$", text, re.M)
    return "%s\n- Standard: %s%s" % (text[:anchor.end()], value, text[anchor.end():])


def card_standard(text):
    """The card's Standard value, or None when it has no `- Standard:` line."""
    m = re.search(r"^- Standard: (.*)$", text, re.M)
    return m.group(1).strip() if m else None


DIMENSION_HEADING = re.compile(r"([A-Z]): (.*)$")


def sections(text):
    """(letter, name, text) for each `## X: Name` section outside fenced code, in file order. A
    section runs to the next heading of level 1 or 2 (md.headings)."""
    found = []
    for level, title, _, body in md.headings(text):
        m = DIMENSION_HEADING.match(title) if level == 2 else None
        if m:
            found.append((m.group(1), m.group(2).strip(), body))
    return found


def subsections(body, level):
    """(title, text) for each heading of `level` in body outside fenced code, in order."""
    return [(title, text) for found, title, _, text in md.headings(body) if found == level]


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
    """The text under the first `### heading` in body outside fenced code, or None."""
    return next((text for title, text in subsections(body, 3) if title == heading), None)


def proposals(text):
    """(dimension, title, body) for every proposed issue under any mark. Filing reads this same
    list, so whatever it files has passed check_issue and the one-title rule."""
    for dim, _, body in sections(text):
        for title, ibody in subsections(part(body, "Proposed issues") or "", 4):
            yield dim, title, ibody


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


def check_proposed(filed):
    """The issue rules for a list of (dimension, title, body) proposals, as `proposals` yields
    them: each has the issue shape, and no title is proposed twice."""
    out, titles = [], {}
    for dim, title, body in filed:
        out += check_issue(dim, title, body)
        # Filing checks titles against open issues once, before creating any.
        if title in titles:
            out.append("%s: issue title %r is also proposed under %s; merge them into one issue"
                       % (dim, title, titles[title]))
        titles.setdefault(title, dim)
    return out


PROPOSAL_FILE = re.compile(r"^# Box crosspollinate: .+ \(\d{4}-\d{2}-\d{2}\)\s*$")


def check_proposal_file(text):
    """Problems in a box-crosspollinate proposal file: its first line, at least one proposal
    under a `## X: Name` section's `### Proposed issues`, and the issue rules for each."""
    out = []
    if not PROPOSAL_FILE.match(text.splitlines()[0] if text.strip() else ""):
        out.append("first line must be `# Box crosspollinate: <repo> (<YYYY-MM-DD>)`")
    for dim, name, _ in sections(text):
        if NAMES.get(dim) != name:
            out.append("section `## %s: %s` is not a dimension heading" % (dim, name))
    filed = list(proposals(text))
    if not filed:
        out.append("no proposed issues")
    return out + check_proposed(filed)


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
    given = re.search(r"^- Proven: (.*)$", text, re.M)
    if given and marks and given.group(1).strip() != proven(marks):
        out.append("Proven %s does not follow the standard: the score row gives %s" % (
            given.group(1).strip(), proven(marks)))
    standards = re.findall(r"^- Standard:(.*)$", text, re.M)
    if len(standards) > 1:
        out.append("more than one `- Standard:` line")
    elif standards and not re.match(r"^ [0-9a-f]{12}$", standards[0].rstrip()):
        out.append("Standard %r must be 12 lowercase hex digits, as `card.py standard` prints"
                   % standards[0].strip())
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
    out += check_proposed(filed)
    if marks and row:
        want = overall(marks, blocker)
        if int(row.group(2)) != want:
            out.append("overall score %s does not follow the rule: %s gives %d" % (
                row.group(2), row.group(1), want))
    return out
