"""Markdown sections, read one way for every box script (issue #36). Stdlib only; Python 3.8+.
Not a script: queue-fill's issue_lint rules (issue_shape), box-audit's score card rules
(scorecard) and orchestrate's handoff_check.py import it from box/lib.

A heading is `#` to `######` after at most three spaces, outside fenced code. A fence is read
only at column 0, as CommonMark reads it there: three or more backticks (with no backtick after
them) or tildes, closed by a run of the same character at least as long with nothing but spaces
or tabs after it. A line that looks like a fence but is not one read exactly (indented, in a list
item or quote, with non-ASCII whitespace, or with a backtick after its opening run) is reported
by lines() and opens nothing, so a fenced example of a heading is never read as the section.

lines(body) yields (start, line number, line, fenced, problem) per line. headings(body) lists the
headings with their sections. section(text, heading, level) is the text under the first `level`
heading named `heading` (case-insensitive), or None.
"""
import re

# Only the marker: headings() strips the closing `#`s in Python. A lazy `(.*?)[ \t#]*$` here
# rescanned the rest of the line for each character it took.
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]")
# A fence line the lint reads: at column 0, three or more backticks (with no backtick after
# them) or tildes. A closer has only ASCII spaces or tabs after its run.
FENCE = re.compile(r"^(`{3,}(?=[^`]*$)|~{3,})(.*)$")
# Anything that looks like a fence: a run of three after whitespace, list or quote markers.
FENCE_LIKE = re.compile(r"^[\s>]*(?:(?:[-*+]|\d{1,9}[.)])\s[\s>]*)*(?:`{3}|~{3})")


def lines(body):
    """(start, line number, line, fenced, problem) for each line. `fenced`: the line opens,
    closes or sits in a fence. `problem`: why a line that looks like a fence is not one the lint
    reads exactly; such a line leaves the fence as it was."""
    fence, pos = None, 0
    for n, raw in enumerate(re.findall(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$", body), 1):
        line, problem = raw.rstrip("\r\n"), None
        f = FENCE.match(line)
        if FENCE_LIKE.match(line):
            if any(c.isspace() and c not in " \t" for c in line):
                problem = "non-ASCII whitespace on a code fence line; use plain spaces"
            elif not line.startswith(("`", "~")):
                problem = "a code fence in a list item, a quote or indented; start it at column 0"
            elif fence is None and not f:
                problem = "a code fence with a backtick after its opening run"
        fenced = fence is not None
        if problem is None and f:
            if fence is None:
                fence, fenced = f.group(1), True
            # CommonMark: the closing fence repeats the opening character at least as many
            # times and has nothing but spaces or tabs after it.
            elif f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence) \
                    and not f.group(2).strip(" \t"):
                fence = None
        yield pos, n, line, fenced, problem
        pos += len(raw)


def headings(body):
    """(level, text, start of the heading line, its section's text, stripped) for each heading
    outside fenced code. A section runs to the next such heading of the same or a higher
    level."""
    found = []
    for pos, _, line, fenced, problem in lines(body):
        m = not fenced and not problem and HEADING.match(line)
        if m:
            text = line[m.end():].rstrip(" \t#").strip()
            found.append([len(m.group(1)), text, pos, pos + len(line) + 1])
    out = []
    for i, (level, text, start, after) in enumerate(found):
        end = next((h[2] for h in found[i + 1:] if h[0] <= level), len(body))
        out.append((level, text, start, body[after:end].strip()))
    return out


def section(text, heading, level):
    for found_level, title, _, body in headings(text):
        if found_level == level and title.lower() == heading.lower():
            return body
    return None
