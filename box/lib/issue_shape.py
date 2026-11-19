"""The one issue shape every queue-fill pass writes, as rules: lint(body, labels, known, where)
returns the problems with one issue, [] if it has the shape. Stdlib only; Python 3.8+. Not a
script: queue-fill's issue_lint.py (the CLI, whose docstring states the shape), hunt.py and
refine.py, and box-audit's file_issues.py import it from box/lib (issue #36). Sections are read
with box/lib's md.py; label and part rules are the score card's (scorecard).
"""
import html
import re
import unicodedata

import issue_folder
import scorecard
from md import HEADING, HTML, ONE_LINE_COMMENT, headings, lines

PARTS = ["Problem", "Want", "Constraints", "Dependencies", "Out of scope"]
KNOWN = (scorecard.TIERS | scorecard.REVIEWS | scorecard.OTHER_LABELS | set(issue_folder.HELD)
         | {issue_folder.PRESENT, "bug"})
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
MARKUP = re.compile(r"<!--.*?-->|<!--|-->|<[^<>]*>")
# `[text](dest)` and `[text][ref]` render as text; `[](dest)` renders as nothing. The
# destination and title may hold balanced parentheses, two levels deep.
LINK = re.compile(r"\[([^\[\]]*)\](?:\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)|\[[^\[\]]*\])")
# Python's splitlines() ends a line at these too; CommonMark does not, so a marker after one is
# paragraph text, not the clean fence opener it would look like.
SEPARATORS = {"\x85": "U+0085 NEXT LINE", "\u2028": "U+2028 LINE SEPARATOR",
              "\u2029": "U+2029 PARAGRAPH SEPARATOR"}
# Cyrillic and Greek look-alikes of the letters in "open question", folded to Latin after
# lowercasing. Over-flags text in those scripts, on purpose.
LOOK_ALIKES = str.maketrans("\u043e\u03bf\u0440\u03c1\u0435\u03b5\u0455\u0456\u03b9\u0442\u03c4"
                            "\u051b\u03c5\u03bd", "ooppeesiittqun")


def question_sections(body):
    """The text under each heading outside fenced code that starts with `Open question`."""
    return [text for _, title, _, text in headings(body)
            if title.lower().startswith("open question")]


def asks(text):
    """Whether text, read bluntly, says `open question`: with HTML comments and tags stripped
    or not, link destinations dropped or not, character references decoded, NFKC applied, all
    but letters and digits dropped, lowercased and look-alike letters folded to Latin."""
    seen = []
    for t in (text, MARKUP.sub("", text), MARKUP.sub("", html.unescape(text))):
        for u in (t, LINK.sub(r"\1", t)):
            u = unicodedata.normalize("NFKC", html.unescape(u))
            seen.append("".join(c for c in u if c.isalnum()).lower().translate(LOOK_ALIKES))
    return any("openquestion" in t for t in seen)


def open_questions(body):
    """Each open question, in order: the text under an `Open question` heading, or the line
    itself for any other line that says it, or two lines that say it across a line break.
    Fails closed: fences, comments and markup hide nothing here."""
    sections = {start: text for _, title, start, text in headings(body)
                if title.lower().startswith("open question")}
    found = [(pos, line, asks(line)) for pos, _, line, _, _ in lines(body)]
    out = []
    for i, (pos, line, hit) in enumerate(found):
        if hit:
            out.append(sections.get(pos, line.strip()))
        elif i + 1 < len(found) and not found[i + 1][2] and asks(line + " " + found[i + 1][1]):
            out.append((line + " " + found[i + 1][1]).strip())
    return out


def unmodelled(body, where="issue"):
    """Problems for Markdown the lint does not model and so cannot read safely."""
    out, previous = [], ""
    for _, n, line, fenced, problem in lines(body):
        for c in sorted(set(line) & set(SEPARATORS)):
            out.append("%s: line %d: a %s, which the host does not read as a line end; remove it"
                       % (where, n, SEPARATORS[c]))
        if problem:
            out.append("%s: line %d: %s" % (where, n, problem))
        elif fenced:
            previous = ""
            continue
        elif HTML.match(line) and not ONE_LINE_COMMENT.match(line):
            out.append("%s: line %d: an HTML %s; the lint does not read inside it, so remove it"
                       % (where, n, "comment" if line.lstrip().startswith("<!--") else "block"))
        elif SETEXT.match(line) and previous.strip() and not HEADING.match(previous):
            out.append("%s: line %d: a Setext heading (text underlined with = or -); use a `#` "
                       "heading, or a blank line before a `---` rule" % (where, n))
        previous = line
    return out


def lint(body, labels, known=KNOWN, where="issue"):
    """Problems with one issue, [] if it has the shape."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    out = unmodelled(body, where)
    questions = open_questions(body)
    asked = any(questions)
    out += scorecard.check_labels(where, labels, asked, known)
    if questions and not asked:
        out.append("%s: an `Open question` heading has nothing under it" % where)
    if "needs-refinement" in labels and not any(question_sections(body)):
        out.append("%s: needs-refinement without an `Open question` section holding the question"
                   % where)
    sections = {}
    for level, title, start, text in headings(body):
        if level == 2 and title in PARTS:
            if title in sections:
                out.append("%s: `## %s` appears more than once" % (where, title))
            sections.setdefault(title, (start, text))
    positions = [sections[p][0] if p in sections else -1 for p in PARTS]
    dependencies = re.sub(r"^Dependencies:[ \t]*(none\.?)$", r"\1",
                          sections.get("Dependencies", (0, ""))[1], flags=re.I)
    parts = scorecard.check_parts(where, ["## %s" % p for p in PARTS], positions, dependencies)
    if parts:
        return out + parts
    return out + ["%s: `## %s` is empty" % (where, p) for p in PARTS if not sections[p][1]]
