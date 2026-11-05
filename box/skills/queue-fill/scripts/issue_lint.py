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
import argparse
import html
import importlib.util
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOX = HERE.parent.parent.parent
sys.path.insert(0, str(BOX / "skills" / "box-audit" / "scripts"))

import card  # noqa: E402


def load_select():
    """box/orchestrate's select.py, loaded under another name: `import select` finds the
    standard library's module of that name."""
    spec = importlib.util.spec_from_file_location("orchestrate_select",
                                                  str(BOX / "orchestrate" / "scripts" / "select.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


select = load_select()

PARTS = ["Problem", "Want", "Constraints", "Dependencies", "Out of scope"]
KNOWN = card.TIERS | card.REVIEWS | card.OTHER_LABELS | set(select.HELD) | {select.PRESENT, "bug"}
# The text ends at its last character that is not a space, tab or `#`: one greedy pass, where a
# lazy `(.*?)` rescanned the rest of the line for each character it took.
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+((?:.*[^ \t#])?)[ \t#]*$")
# A fence line the lint reads: at column 0, three or more backticks (with no backtick after
# them) or tildes. A closer has only ASCII spaces or tabs after its run.
FENCE = re.compile(r"^(`{3,}(?=[^`]*$)|~{3,})(.*)$")
# Anything that looks like a fence: a run of three after whitespace, list or quote markers.
FENCE_LIKE = re.compile(r"^[\s>]*(?:(?:[-*+]|\d{1,9}[.)])\s[\s>]*)*(?:`{3}|~{3})")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
HTML = re.compile(r"^ {0,3}<(?:!--|[!?]|/?[A-Za-z][A-Za-z0-9-]*(?:[ \t/>]|$))")
# A comment that closes on its own line, such as a tool's marker, hides nothing: CommonMark ends
# that HTML block on the same line.
ONE_LINE_COMMENT = re.compile(r"^ {0,3}<!--(?:(?!-->).)*-->[ \t]*$")
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
    """(level, text, start of the heading line, end of its section) for each heading outside
    fenced code. A section runs to the next heading of the same or a higher level."""
    found = []
    for pos, _, line, fenced, problem in lines(body):
        m = not fenced and not problem and HEADING.match(line)
        if m:
            found.append([len(m.group(1)), m.group(2).strip(), pos, pos + len(line) + 1])
    out = []
    for i, (level, text, start, after) in enumerate(found):
        end = next((h[2] for h in found[i + 1:] if h[0] <= level), len(body))
        out.append((level, text, start, body[after:end].strip()))
    return out


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
    out += card.check_labels(where, labels, asked, known)
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
    parts = card.check_parts(where, ["## %s" % p for p in PARTS], positions, dependencies)
    if parts:
        return out + parts
    return out + ["%s: `## %s` is empty" % (where, p) for p in PARTS if not sections[p][1]]


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
            issue = select.parse_issue_file(Path(args.issue_file))
        except (OSError, UnicodeDecodeError, select.InputError) as e:
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
