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
heading named `heading` (case-insensitive), or None. unread(text, end) lists the lines before
`end` that may render otherwise than they are read here: odd fences and HTML blocks.
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
# An HTML block's first line. A comment that closes on its own line, such as a tool's marker,
# hides nothing: CommonMark ends that HTML block on the same line.
HTML = re.compile(r"^ {0,3}<(?:!--|[!?]|/?[A-Za-z][A-Za-z0-9-]*(?:[ \t/>]|$))")
ONE_LINE_COMMENT = re.compile(r"^ {0,3}<!--(?:(?!-->).)*-->[ \t]*$")


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


def unread(text, end=None):
    """(line number, why) for each line before position `end` (default: all) that this module
    does not read the way a host renders it: a line that looks like a fence but is not one read
    exactly, or the first line of an HTML block outside fenced code (a comment closed on its own
    line excepted). What follows such a line may render as code or raw HTML though it is read
    here as Markdown, so a caller that must read what the host shows fails closed on it."""
    out = []
    for pos, n, line, fenced, problem in lines(text):
        if end is not None and pos >= end:
            break
        if problem:
            out.append((n, problem))
        elif not fenced and HTML.match(line) and not ONE_LINE_COMMENT.match(line):
            out.append((n, "an HTML block, which the host renders as HTML, not Markdown"))
    return out
