"""Tests for the queue-fill skill's scripts (box/skills/queue-fill/scripts). Inputs are built at
runtime. Host calls go to a stand-in gh that answers `gh api` GETs from invented routes in
GitHub's shape and logs every other command, so nothing reaches a network."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_box_audit import ISSUE, make_card

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "box" / "skills" / "queue-fill"
SCRIPTS = SKILL / "scripts"
AUDIT_SCRIPTS = ROOT / "box" / "skills" / "box-audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(AUDIT_SCRIPTS))

import card  # noqa: E402
import collect  # noqa: E402
import file_issues  # noqa: E402
import hunt  # noqa: E402
import issue_lint  # noqa: E402
import refine  # noqa: E402

select = issue_lint.select


def script(path, *args, env=None, stdin=None):
    return subprocess.run([sys.executable, str(path)] + [str(a) for a in args], env=env,
                          input=stdin, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def lint_cli(*args, **kw):
    return script(SCRIPTS / "issue_lint.py", *args, **kw)


GOOD = """\
## Problem
Invoice totals round half to even, so 2.5 becomes 2.

## Want
- `test_totals_round_half_up` passes: 2.5 rounds to 3.

## Constraints
- Tests go in tests/. Stdlib only.

## Dependencies
Dependencies: #3, #4

## Out of scope
Currency conversion.
"""

QUESTION = "\n## Open question\nRound per line or per invoice?\n"


def write(path, text):
    path.write_bytes(text.encode("utf-8"))
    return path


# ----- issue_lint ----------------------------------------------------------------------------

def test_a_good_issue_passes(tmp_path):
    r = lint_cli(write(tmp_path / "body.md", GOOD), "--labels", "tier:standard, ready, P1")
    assert r.returncode == 0 and r.stdout == "ISSUE_OK\n", r.stdout + r.stderr


def test_a_missing_section_fails(tmp_path):
    body = GOOD.replace("## Want\n- `test_totals_round_half_up` passes: 2.5 rounds to 3.\n\n", "")
    r = lint_cli(write(tmp_path / "body.md", body), "--labels", "tier:standard, ready")
    assert r.returncode == 1 and r.stdout.startswith("ISSUE_INVALID\n"), r.stdout
    assert "- issue: missing ## Want" in r.stdout


def test_two_tier_labels_fail(tmp_path):
    r = lint_cli(write(tmp_path / "body.md", GOOD), "--labels",
                 "tier:standard, tier:frontier, ready")
    assert r.returncode == 1
    assert "needs exactly one tier label, has ['tier:standard', 'tier:frontier']" in r.stdout


def test_needs_refinement_without_a_question_fails(tmp_path):
    r = lint_cli(write(tmp_path / "body.md", GOOD), "--labels", "tier:standard, needs-refinement")
    assert r.returncode == 1
    assert "needs-refinement without an `Open question` section" in r.stdout
    r = lint_cli(write(tmp_path / "body.md", GOOD + QUESTION), "--labels",
                 "tier:standard, needs-refinement")
    assert r.returncode == 0, r.stdout


def test_ready_with_an_open_question_fails(tmp_path):
    r = lint_cli(write(tmp_path / "body.md", GOOD + QUESTION), "--labels", "tier:standard, ready")
    assert r.returncode == 1
    assert "labelled ready with open decisions" in r.stdout
    assert "open decisions need the needs-refinement label" in r.stdout


@pytest.mark.parametrize("body, labels, problem", [
    (GOOD + "\n## Open questions\n\n## Notes\nx\n", "tier:standard, needs-refinement",
     "an `Open question` heading has nothing under it"),
    (GOOD.replace("## Want\n- `test", "## Want\n\n## Wanted\n- `test"), "tier:standard, ready",
     "`## Want` is empty"),
    (GOOD + "\n## Problem\nAgain.\n", "tier:standard, ready", "`## Problem` appears more than once"),
    (GOOD.replace("## Problem", "## Out of scope", 1).replace("## Out of scope\nCurrency",
                                                              "## Problem\nCurrency"),
     "tier:standard, ready", "parts out of order"),
    (GOOD.replace("Dependencies: #3, #4", "Dependencies: #3 #4"), "tier:standard, ready",
     "Dependencies must be `none` or `Dependencies: #N`"),
    (GOOD.replace("#3, #4\n", "#3, #4\n\nBoth land the money type first.\n"),
     "tier:standard, ready", "Dependencies must be `none` or `Dependencies: #N`"),
    (GOOD, "tier:standard, ready, gate-change-approved", "unknown labels ['gate-change-approved']"),
    (GOOD, "tier:standard, ready, review:perf, review:security, review:migration",
     "at most two review labels"),
])
def test_shape_problems(body, labels, problem):
    found = issue_lint.lint(body, [l.strip() for l in labels.split(",")])
    assert any(problem in p for p in found), found


def test_what_the_shape_allows():
    lint = issue_lint.lint
    assert lint(GOOD.replace("Dependencies: #3, #4", "Dependencies: none"), ["tier:mechanical"]) \
        == []
    assert lint(GOOD.replace("Dependencies: #3, #4", "none"), ["tier:mechanical"]) == []
    # Extra sections between the parts, holding labels, and a heading in a code block.
    extra = GOOD.replace("## Want", "## Context\nSee the parser.\n\n```\n## Problem\n```\n\n"
                                    "## Want")
    assert lint(extra, ["tier:standard", "ready", "user-present", "bug"]) == []
    assert lint(GOOD, ["tier:standard", "ready", "topic"]) != []
    assert lint(GOOD, ["tier:standard", "ready", "topic"], issue_lint.KNOWN | {"topic"}) == []
    assert lint(GOOD.replace("\n", "\r\n"), ["tier:standard"]) == []


# A fence closes only on the same character, at least as long, with nothing after it (CommonMark).
# A heading inside a fence is no section.
@pytest.mark.parametrize("fenced", [
    "\n## Example\n````markdown\n```\n## Problem\n```\n````\n",
    "\n## Example\n~~~~\n~~~\n## Problem\nx\n~~~\n~~~~\n",
    "\n## Example\n```\n~~~\n## Problem\nx\n```\n",
    "\n## Example\n```\n``` not a closer\n## Problem\nx\n```\n",
    "\n## Example\n```\n## Problem\nNever closed.\n",
])
def test_headings_inside_fences_are_no_sections(fenced):
    assert issue_lint.lint(GOOD + fenced, ["tier:standard", "ready"]) == []


def test_ordinary_fenced_code_passes():
    code = ("\n## Example\n```python\nx = 1  # <!-- not a comment here -->\nTitle\n---\n```\n"
            "\n~~~\nplain\n~~~\n")
    assert issue_lint.lint(GOOD + code, ["tier:standard", "ready"]) == []


# Fail closed: a line that starts with `Open question`, once whitespace, list, quote and heading
# markers are stripped, is an open question wherever it is, fences and comments included.
VISIBLE = "\n## Open question\nWhich format should be kept?\n"
HIDING = {
    # r1: a four-backtick fence holding a three-backtick line.
    "nested fence": "\n## Example\n````\n```\n````\n" + VISIBLE,
    # r2: a fence opened in a list item, then a visible question.
    "list fence": "\n- ```text\n  example\n  ```\n" + VISIBLE,
    "ordered list fence": "\n1. ```text\n   example\n   ```\n" + VISIBLE,
    # r2: a fence inside an HTML comment, then a visible question.
    "comment fence": "\n<!--\n```\n-->\n" + VISIBLE,
    # r2: Setext headings.
    "setext -": "\nOpen question\n-------------\nWhich format should be kept?\n",
    "setext =": "\nOpen question\n=============\nWhich format should be kept?\n",
    # Questions the old parser hid outright.
    "in a fence": "\n## Example\n```\n## Open question\nWhich one?\n```\n",
    "in a comment": "\n<!--\n## Open question\nWhich one?\n-->\n",
    "in a list": "\n- **Open question:** which one?\n",
    "in a quote": "\n> open questions: which one?\n",
    "in a one-line comment": "\n<!-- Open question: which one? -->\n",
    "in a task list": "\n- [ ] Open question: which one?\n",
    # r3: inline markup or a character reference in the heading.
    "comment before": "\n## <!-- marker -->Open question\nWhich format should be kept?\n",
    "comment inside": "\n## Open<!-- marker --> question\nWhich format should be kept?\n",
    "emphasis": "\n## **Open** question\nWhich format should be kept?\n",
    "entity": "\n## &#79;pen question\nWhich format should be kept?\n",
    # Further forms of the same class: a tag, code span, invisible or wide characters, a soft
    # line break.
    "tag": "\n## <span>Open</span> question\nWhich one?\n",
    "code span": "\n## `Open` question\nWhich one?\n",
    "zero-width space": "\n## Open​ question\nWhich one?\n",
    "fullwidth": "\n## Ｏpen question\nWhich one?\n",
    "soft break": "\nThere is one\nOpen\nquestion: which one?\n",
}


@pytest.mark.parametrize("case", sorted(HIDING))
def test_a_question_anywhere_blocks_ready(case):
    body = GOOD + HIDING[case]
    assert issue_lint.open_questions(body), case
    found = issue_lint.lint(body, ["tier:standard", "ready"])
    assert any("labelled ready with open decisions" in p for p in found), found
    before = ["tier:standard", "needs-refinement"]
    assert refine.new_labels(before, body) == before


@pytest.mark.parametrize("extra, problem", [
    ("\n<!-- a\nnote -->\n", "HTML comment"),
    ("\n<!--\n```\n-->\n", "HTML comment"),
    ("\n<pre>\n## Notes\n</pre>\n", "HTML block"),
    ("\nNotes\n-----\nx\n", "Setext"),
    ("\nNotes\n=\nx\n", "Setext"),
    ("\n- ```text\n  example\n  ```\n", "fence"),
    ("\n1. ```text\n   example\n   ```\n", "fence"),
    ("\n> ```\n> code\n> ```\n", "fence"),
    ("\n  ```\n  code\n  ```\n", "fence"),
    # Fence lines are strict: column 0, ASCII space or tab only.
    ("\n```\ncode\n  ```\n```\n", "fence"),
    ("\n``` text\ncode\n```\n", "fence"),
    ("\n ```\ncode\n```\n", "fence"),
    ("\n```a`b\n", "fence"),
])
def test_unmodelled_structure_fails(extra, problem):
    found = issue_lint.lint(GOOD + extra, ["tier:standard", "ready"])
    assert any(problem in p for p in found), found


# r3: a closer ending in non-ASCII whitespace keeps a CommonMark fence open, hiding every section
# after it. The lint rejects the line instead of guessing.
HIDDEN_BY_FENCE = {
    "nbsp closer": GOOD.replace("## Want", "```text\nexample\n``` \n\n## Want", 1),
    "em space closer": GOOD.replace("## Want", "```text\nexample\n``` \n\n## Want", 1),
}
R3 = dict(HIDDEN_BY_FENCE, **{k: GOOD + HIDING[k] for k in
                               ("comment before", "comment inside", "emphasis", "entity")})


@pytest.mark.parametrize("case", sorted(HIDDEN_BY_FENCE))
def test_a_fence_closer_with_unicode_whitespace_fails(case):
    found = issue_lint.lint(HIDDEN_BY_FENCE[case], ["tier:standard", "ready"])
    assert any("fence" in p for p in found), found
    before = ["tier:standard", "needs-refinement"]
    assert refine.new_labels(before, HIDDEN_BY_FENCE[case]) == before


# r4 (#80): CommonMark ends a line only at LF, CR or CRLF. Split at U+0085, U+2028 or U+2029
# too, and a marker after one reads as a clean fence opener while the renderer reads paragraph
# text, so its closer opens a fence that hides `## Want` onward.
SEPARATORS = {"U+0085": "\x85", "U+2028": " ", "U+2029": " "}
HIDDEN_BY_SEPARATOR = {
    "%s before %s" % (name, fence): GOOD.replace(
        "## Want", "%s%stext\nexample\n%s\n\n## Want" % (sep, fence * 3, fence * 3), 1)
    for name, sep in SEPARATORS.items() for fence in "`~"}
# r4: a look-alike letter or a link in the heading still renders "Open question".
HIDDEN_IN_HEADING = {
    "cyrillic O": "\n## Оpen question\nWhich one?\n",
    "greek letters": "\n## Ορεn questiοn\nWhich one?\n",
    "empty link": "\n## Open[](x) question\nWhich one?\n",
    "link": "\n## [Open](https://x) question\nWhich one?\n",
    "link with parens": "\n## [Open](x(y)) question\nWhich one?\n",
    "link with a title": "\n## [Open](x \"a (b)\") question\nWhich one?\n",
    "reference link": "\n## [Open][1] question\nWhich one?\n\n[1]: https://x\n",
}
R4 = dict(HIDDEN_BY_SEPARATOR, **{k: GOOD + v for k, v in HIDDEN_IN_HEADING.items()})


@pytest.mark.parametrize("case", sorted(HIDDEN_BY_SEPARATOR))
def test_a_unicode_line_separator_fails(case):
    body = HIDDEN_BY_SEPARATOR[case]
    name = case.split()[0]
    found = issue_lint.lint(body, ["tier:standard", "ready"])
    assert any(name in p and "line 4" in p for p in found), found
    before = ["tier:standard", "needs-refinement"]
    assert refine.new_labels(before, body) == before


@pytest.mark.parametrize("case", sorted(HIDDEN_IN_HEADING))
def test_a_disguised_question_heading_blocks_ready(case):
    body = GOOD + HIDDEN_IN_HEADING[case]
    found = issue_lint.lint(body, ["tier:standard", "ready"])
    assert any("labelled ready with open decisions" in p for p in found), found
    before = ["tier:standard", "needs-refinement"]
    assert refine.new_labels(before, body) == before


def test_cr_and_crlf_line_ends_still_read():
    for end in ("\r", "\r\n"):
        assert issue_lint.lint(GOOD.replace("\n", end), ["tier:standard", "ready"]) == []
        found = issue_lint.lint((GOOD + QUESTION).replace("\n", end), ["tier:standard", "ready"])
        assert any("labelled ready with open decisions" in p for p in found), found


NOT_PROMOTED = dict(R3, **R4)


@pytest.mark.parametrize("case", sorted(NOT_PROMOTED))
def test_refine_never_promotes_an_r3_body(tmp_path, case):
    folder = tmp_path / "issues"
    folder.mkdir()
    write(folder / "5.md", file_issues.issue_file(
        5, "Round totals", ["tier:standard", "needs-refinement"], GOOD + QUESTION +
        "\n## Owner answer\nPer invoice.\n", "2026-10-01T00:00:00Z", "open"))
    before = (folder / "5.md").read_bytes()
    r = script(SCRIPTS / "refine.py", "apply", "5", write(tmp_path / "new.md", NOT_PROMOTED[case]),
               "--folder", folder, "--apply")
    assert "now ready" not in r.stdout, r.stdout
    issue = select.parse_issue_file(folder / "5.md")
    assert "ready" not in issue["labels"], issue["labels"]
    assert r.returncode == 1 or "needs-refinement" in issue["labels"], r.stdout
    if r.returncode == 1:
        assert (folder / "5.md").read_bytes() == before


def test_a_one_line_marker_comment_passes():
    """Tools leave markers such as `<!-- reservation:start -->`; one that closes on its own line
    hides nothing. Anything after the close does not count as closed."""
    marked = "<!-- reservation:start -->\n" + GOOD + "<!-- reservation:end -->\n"
    assert issue_lint.lint(marked, ["tier:standard", "ready"]) == []
    found = issue_lint.lint(GOOD + "<!-- x --> ## Notes\n", ["tier:standard", "ready"])
    assert any("HTML comment" in p for p in found), found


def test_a_required_section_hidden_in_a_comment_fails():
    body = GOOD.replace("## Want\n- `test_totals_round_half_up` passes: 2.5 rounds to 3.\n",
                        "<!--\n## Want\n- `test_totals_round_half_up` passes.\n-->\n")
    found = issue_lint.lint(body, ["tier:standard", "ready"])
    assert any("HTML comment" in p for p in found), found


def test_needs_refinement_still_needs_an_open_question_heading():
    """The loose scan only blocks `ready`; `needs-refinement` needs a real `## Open question`."""
    body = GOOD + "\nOpen question: which one?\n"
    found = issue_lint.lint(body, ["tier:standard", "needs-refinement"])
    assert any("needs-refinement without an `Open question` section" in p for p in found), found
    assert issue_lint.lint(GOOD + QUESTION, ["tier:standard", "needs-refinement"]) == []


def test_refinement_never_promotes_a_body_the_lint_rejects(tmp_path):
    folder = tmp_path / "issues"
    folder.mkdir()
    write(folder / "5.md", file_issues.issue_file(
        5, "Round totals", ["tier:standard", "needs-refinement"], GOOD + QUESTION +
        "\n## Owner answer\nPer invoice.\n", "2026-10-01T00:00:00Z", "open"))
    body = GOOD + "\n<!--\nkept for later\n-->\n"
    assert refine.new_labels(["tier:standard", "needs-refinement"], body) == \
        ["tier:standard", "needs-refinement"]
    r = script(SCRIPTS / "refine.py", "apply", "5", write(tmp_path / "new.md", body),
               "--folder", folder, "--apply")
    assert r.returncode == 1 and "NOT REFINED" in r.stdout, r.stdout + r.stderr
    assert "needs-refinement" in (folder / "5.md").read_text(encoding="utf-8")


def test_the_lint_reuses_card_checks_not_a_copy(monkeypatch):
    """The label and part rules live once, in card.py."""
    source = (SCRIPTS / "issue_lint.py").read_text(encoding="utf-8")
    assert "card.check_labels(" in source and "card.check_parts(" in source
    assert "exactly one tier label" not in source.split('"""', 2)[2]
    calls = []
    monkeypatch.setattr(card, "check_labels", lambda *a: calls.append(a) or ["from card"])
    assert "from card" in issue_lint.lint(GOOD, ["tier:standard"])
    assert calls


def test_lint_cli_issue_file_stdin_and_usage(tmp_path):
    path = write(tmp_path / "3.md", "---\nnumber: 3\ntitle: Round half up\nstate: open\n"
                                    "labels: tier:standard, ready\ncreatedAt: 2026-09-05T09:00:00Z"
                                    "\n---\n" + GOOD)
    assert lint_cli("--issue-file", path).returncode == 0
    write(path, path.read_text(encoding="utf-8").replace("ready", "needs-refinement"))
    r = lint_cli("--issue-file", path)
    assert r.returncode == 1 and "- #3: needs-refinement without" in r.stdout, r.stdout
    assert lint_cli("-", "--labels", "tier:standard", stdin=GOOD).returncode == 0
    assert lint_cli("--issue-file", path, "--labels", "x").returncode == 2
    assert lint_cli(path).returncode == 2
    assert lint_cli(tmp_path / "missing.md", "--labels", "tier:standard").returncode == 2
    assert lint_cli("--issue-file", write(tmp_path / "4.md", "no header")).returncode == 2
    r = lint_cli("--bogus")
    assert r.returncode == 2 and "Traceback" not in r.stderr


# ----- gap pass: box-audit's proposals in the same shape -------------------------------------

def card_with_open_decision():
    """The test card with a second issue under G: an open decision and a dependency."""
    open_issue = ISSUE.format(title="Pick a store").replace(
        "Labels: tier:standard, ready, P1", "Labels: tier:frontier, needs-refinement").replace(
        "Open decisions: none", "Open decisions: SQLite or files?").replace(
        "**Dependencies**\nnone", "**Dependencies**\nDependencies: #2")
    return make_card(["✓", "~", "✗", "~", "–", "~"]).replace(
        "## R: Real-thing tests", open_issue + "\n## R: Real-thing tests")


def test_every_gap_proposal_passes_the_lint():
    text = card_with_open_decision()
    assert card.check(text) == []
    issues = file_issues.proposed(text)
    assert len(issues) == 6
    for i in issues:
        assert issue_lint.lint(i["body"], i["labels"], where=i["title"]) == [], i["body"]
    store = next(i for i in issues if i["title"] == "Pick a store")
    assert "## Open questions\nSQLite or files?" in store["body"]
    assert select.dependencies(store["body"]) == [(None, 2)]


@pytest.mark.parametrize("mutate, problem", [
    (lambda t: t.replace("Labels: tier:standard, ready, P1", "Labels: tier:standard, "
                         "needs-refinement", 1), "needs-refinement without an `Open question`"),
    (lambda t: t.replace("**Want**\n- It works.", "**Want**", 1), "`## Want` is empty"),
])
def test_the_gap_pass_files_nothing_the_lint_rejects(tmp_path, mutate, problem):
    """The card check is looser than the lint; filing runs both."""
    text = mutate(make_card(["✓", "~", "✗", "~", "–", "~"]))
    assert card.check(text) == []
    path = write(tmp_path / "card.md", text)
    fi = AUDIT_SCRIPTS / "file_issues.py"
    r = script(fi, path, "--repo", "o/r", "--offline")
    assert r.returncode == 1 and "PROPOSALS_INVALID" in r.stdout and problem in r.stdout, r.stdout
    gh, env, calls = stand_in(tmp_path, {
        "repos/o/r/labels?per_page=100": REPO_LABELS,
        "repos/o/r/issues?state=open&per_page=100": []})
    r = script(fi, path, "--repo", "o/r", "--gh", gh, "--apply", env=env)
    assert r.returncode == 1 and "PROPOSALS_INVALID" in r.stdout and calls() == []
    folder = tmp_path / "issues"
    folder.mkdir()
    assert script(fi, path, "--folder", folder, "--apply").returncode == 1
    assert list(folder.iterdir()) == []


def folder_issue(folder, number, title, labels, body=GOOD, state="open"):
    write(folder / ("%d.md" % number), file_issues.issue_file(
        number, title, labels, body, "2026-09-0%dT09:00:00Z" % number, state))


def test_gap_pass_into_a_folder_select_reads(tmp_path):
    folder = tmp_path / "issues"
    folder.mkdir()
    folder_issue(folder, 3, "Fix G gap 0", ["tier:standard", "ready"])
    folder_issue(folder, 7, "Old work", ["tier:standard"], state="closed")
    path = write(tmp_path / "card.md", make_card(["✓", "~", "✗", "~", "–", "~"]))
    fi = AUDIT_SCRIPTS / "file_issues.py"
    r = script(fi, path, "--folder", folder)
    assert r.returncode == 0 and "labels not checked" in r.stdout, r.stdout + r.stderr
    assert "SKIP: an open issue has this title" in r.stdout
    assert sorted(p.name for p in folder.iterdir()) == ["3.md", "7.md"]
    r = script(fi, path, "--folder", folder, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(p.name for p in folder.iterdir()) == ["%d.md" % n for n in (10, 11, 3, 7, 8, 9)]
    issues = sorted(select.read_folder(folder), key=lambda i: i["number"])
    assert [i["title"] for i in issues if i["number"] >= 8] == \
        ["Fix %s gap 0" % d for d in "RJWD"]
    for i in issues:
        assert issue_lint.lint(i["body"], i["labels"]) == [] or i["number"] == 7
    plan = select.select(issues, 10)
    assert {i["number"] for i in plan["dispatch"]} == {8, 9, 10, 11}  # #3 waits on #4
    r = script(fi, path, "--folder", folder, "--apply")
    assert r.returncode == 0 and len(list(folder.iterdir())) == 6, "a second run files nothing"
    assert script(fi, path, "--folder", folder, "--offline").returncode == 2
    assert script(fi, path, "--folder", tmp_path / "nope").returncode == 2
    assert script(fi, path, "--repo", "o/r", "--folder", folder).returncode == 2
    assert script(fi, path).returncode == 2


# ----- stand-in host -------------------------------------------------------------------------

FAKE_GH = r'''
import json, os, re, sys
args = sys.argv[1:]
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
if args[0] == "api":
    page = re.search(r"&page=(\d+)$", args[1])
    if page and page.group(1) != "1":
        print("[]")
        sys.exit(0)
    routes = json.load(open(os.environ["GH_ROUTES"], encoding="utf-8"))
    path = re.sub(r"&page=1$", "", args[1])
    if path in routes:
        print(json.dumps(routes[path]))
        sys.exit(0)
    sys.stderr.write("gh: Not Found (HTTP 404)\n")
    sys.exit(1)
if args[:2] in (["issue", "create"], ["issue", "edit"]):
    print("https://example.com/o/r/issues/1")
    sys.exit(0)
sys.exit(1)
'''


def stand_in(tmp_path, routes):
    """The --gh command, its environment, and a function returning the commands it was given."""
    gh = write(tmp_path / "gh.py", FAKE_GH)
    write(tmp_path / "routes.json", json.dumps(routes))
    log = tmp_path / "gh.log"
    env = dict(os.environ, GH_ROUTES=str(tmp_path / "routes.json"), GH_LOG=str(log))

    def calls():
        text = log.read_text(encoding="utf-8") if log.exists() else ""
        return [json.loads(l) for l in text.splitlines()]
    return '"%s" "%s"' % (Path(sys.executable).as_posix(), gh.as_posix()), env, calls


def labels(*names):
    return [{"name": n} for n in names]


REPO_LABELS = labels("bug", "ready", "needs-refinement", "tier:mechanical", "tier:standard",
                     "tier:frontier", "P1", "gate-change-approved")


# ----- bug-hunt pass -------------------------------------------------------------------------

FINDING = """\
---
title: Bug hunt: {title}
labels: bug, tier:mechanical, ready
---
## Problem
Found by: bug hunt 2026-10-27 at 0123456789ab
Introducing change: {change}
CI-catchable: yes

`parse` drops the last line of a file without a final newline.

## Want
- `test_parse_keeps_a_last_line_without_newline` passes.

## Constraints
- Tests in tests/.

## Dependencies
Dependencies: none

## Out of scope
Other parsers.
"""


def drafts(tmp_path, *findings):
    folder = tmp_path / "drafts"
    folder.mkdir(exist_ok=True)
    for n, (title, change) in enumerate(findings, 1):
        write(folder / ("%d.md" % n), FINDING.format(title=title, change=change))
    return folder


def test_bug_hunt_findings_feed_the_d_collector():
    """A finding that names its change counts as traced; `unknown` does not; both count as a
    defect and as a hunt."""
    traced = FINDING.format(title="x", change="#57")
    assert collect.INTRODUCED.search(traced)
    assert collect.INTRODUCED.search(FINDING.format(title="x", change="0123456789ab"))
    assert not collect.INTRODUCED.search(FINDING.format(title="x", change="unknown"))
    assert collect.BUGGY_LABEL.search("bug") and re.search(r"hunt", "Bug hunt: x", re.I)


def test_bug_hunt_dry_run_then_apply_on_the_host(tmp_path):
    folder = drafts(tmp_path, ("parse drops a line", "#57"), ("already filed", "unknown"))
    gh, env, calls = stand_in(tmp_path, {
        "repos/o/r/labels?per_page=100": REPO_LABELS,
        "repos/o/r/issues?state=open&per_page=100": [{"title": "Bug hunt: already filed"},
                                                     {"title": "a PR", "pull_request": {}}]})
    h = SCRIPTS / "hunt.py"
    r = script(h, folder, "--repo", "o/r", "--gh", gh, env=env)
    assert r.returncode == 0 and r.stdout.startswith("DRY RUN: 2 proposed issues"), r.stdout
    assert "Bug hunt: already filed  (SKIP: an open issue has this title)" in r.stdout
    assert all(c[0] == "api" for c in calls())
    r = script(h, folder, "--repo", "o/r", "--gh", gh, "--apply", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    created = [c for c in calls() if c[:2] == ["issue", "create"]]
    assert len(created) == 1 and created[0][created[0].index("--title") + 1] == \
        "Bug hunt: parse drops a line"
    assert created[0].count("--label") == 3 and "Introducing change: #57" in \
        created[0][created[0].index("--body") + 1]


def test_bug_hunt_stops_on_a_missing_label(tmp_path):
    folder = drafts(tmp_path, ("parse drops a line", "#57"))
    gh, env, calls = stand_in(tmp_path, {
        "repos/o/r/labels?per_page=100": labels("ready", "tier:mechanical"),
        "repos/o/r/issues?state=open&per_page=100": []})
    r = script(SCRIPTS / "hunt.py", folder, "--repo", "o/r", "--gh", gh, "--apply", env=env)
    assert r.returncode == 1 and "MISSING LABELS on o/r: bug" in r.stdout
    assert not [c for c in calls() if c[0] != "api"]


@pytest.mark.parametrize("mutate, problem", [
    (lambda t: t.replace("Introducing change: #57\n", ""), "must open with `Introducing change"),
    (lambda t: t.replace("Introducing change: #57", "Introducing change: last week"),
     "must open with `Introducing change"),
    (lambda t: t.replace("CI-catchable: yes", "CI-catchable: maybe"), "CI-catchable: yes|no"),
    (lambda t: t.replace("Found by: bug hunt 2026-10-27", "Found by: a hunch"), "Found by:"),
    (lambda t: t.replace("title: Bug hunt: ", "title: "), "must start with `Bug hunt: `"),
    (lambda t: t.replace("labels: bug, ", "labels: "), "needs the bug label"),
    (lambda t: t.replace("ready", "ready, findings-accepted"), "unknown labels"),
    (lambda t: t.replace("## Want", "## Wish"), "missing ## Want"),
])
def test_a_bad_finding_stops_the_run(tmp_path, mutate, problem):
    folder = drafts(tmp_path, ("parse drops a line", "#57"))
    path = folder / "1.md"
    write(path, mutate(path.read_text(encoding="utf-8")))
    r = script(SCRIPTS / "hunt.py", folder, "--repo", "o/r", "--offline")
    assert r.returncode == 1 and "FINDINGS_INVALID" in r.stdout and problem in r.stdout, r.stdout


def test_a_finding_never_carries_an_owner_only_label(tmp_path):
    folder = drafts(tmp_path, ("a", "#1"))
    write(folder / "1.md", FINDING.format(title="a", change="#1").replace("ready",
                                                                          "gate-change-approved"))
    r = script(SCRIPTS / "hunt.py", folder, "--repo", "o/r", "--offline", "--allow-label",
               "gate-change-approved")
    assert r.returncode == 1 and "gate-change-approved only the owner applies" in r.stdout


def test_one_run_is_one_pass_with_distinct_titles(tmp_path):
    folder = drafts(tmp_path, ("a", "#1"), ("a", "#2"))
    r = script(SCRIPTS / "hunt.py", folder, "--repo", "o/r", "--offline")
    assert r.returncode == 1 and "title 'Bug hunt: a' is also in 1.md" in r.stdout
    write(folder / "2.md", FINDING.format(title="b", change="#2").replace("2026-10-27",
                                                                          "2026-10-28"))
    r = script(SCRIPTS / "hunt.py", folder, "--repo", "o/r", "--offline")
    assert r.returncode == 1 and "more than one pass" in r.stdout


def test_bug_hunt_into_a_folder(tmp_path):
    folder = drafts(tmp_path, ("parse drops a line", "unknown"), ("b", "#2"))
    issues = tmp_path / "issues"
    issues.mkdir()
    r = script(SCRIPTS / "hunt.py", folder, "--folder", issues, "--only",
               "Bug hunt: parse drops a line", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    [issue] = select.read_folder(issues)
    assert issue["number"] == 1 and issue["labels"] == ["bug", "tier:mechanical", "ready"]
    assert select.select([issue], 1)["dispatch"][0]["number"] == 1


def test_bug_hunt_usage(tmp_path):
    folder = drafts(tmp_path, ("a", "#1"))
    h = SCRIPTS / "hunt.py"
    assert script(h, folder, "--repo", "o/r", "--offline", "--apply").returncode == 2
    assert script(h, folder, "--repo", "bad", "--offline").returncode == 2
    assert script(h, tmp_path / "nope", "--repo", "o/r", "--offline").returncode == 2
    assert script(h, folder, "--repo", "o/r", "--offline", "--only", "nope").returncode == 2
    assert script(h, folder, "--repo", "o/r", "--gh", "gh '").returncode == 2
    write(folder / "2.md", "no header\n")
    assert script(h, folder, "--repo", "o/r", "--offline").returncode == 2
    write(folder / "2.md", "---\nlabels: bug\n---\nbody\n")
    assert script(h, folder, "--repo", "o/r", "--offline").returncode == 2
    write(folder / "2.md", "---\ntitle: x\nnot a field\n---\nbody\n")
    assert script(h, folder, "--repo", "o/r", "--offline").returncode == 2


# ----- refinement pass -----------------------------------------------------------------------

REFINED = GOOD.replace("Dependencies: #3, #4", "Dependencies: none") + "\n## Decision (owner, 2026-10-26)\nRound per line.\n"
WAITING = GOOD + QUESTION


# Windows has no descriptor-relative writes, so refine refuses to write into a folder there
# (test_refine_refuses_folder_writes_where_it_cannot_anchor_them); tests of a write skip.
needs_safe_writes = pytest.mark.skipif(
    not refine.SAFE_WRITES, reason="refine refuses folder writes where it cannot anchor them")


def refine_folder(tmp_path):
    folder = tmp_path / "issues"
    folder.mkdir()
    folder_issue(folder, 1, "Round half up", ["tier:standard", "needs-refinement", "P1"],
                 WAITING + "\n## Owner answer\nPer line.\n")
    folder_issue(folder, 2, "Not answered", ["tier:standard", "needs-refinement"], WAITING)
    folder_issue(folder, 3, "Ready already", ["tier:standard", "ready"])
    return folder


def refine_cli(*args, **kw):
    return script(SCRIPTS / "refine.py", *args, **kw)


def test_refine_lists_answered_issues_first(tmp_path):
    folder = refine_folder(tmp_path)
    r = refine_cli("list", "--folder", folder)
    assert r.returncode == 0, r.stderr
    answered, waiting = r.stdout.split("Waiting for the owner")
    assert "#1     Round half up" in answered and "Per line." in answered
    assert "#2     Not answered" in waiting and "#3" not in r.stdout


@needs_safe_writes
def test_refine_makes_an_answered_issue_ready(tmp_path):
    folder = refine_folder(tmp_path)
    body = write(tmp_path / "new.md", REFINED)
    before = (folder / "1.md").read_text(encoding="utf-8")
    r = refine_cli("apply", 1, body, "--folder", folder)
    assert r.returncode == 0 and "DRY RUN: refine #1" in r.stdout, r.stdout + r.stderr
    assert "Labels: tier:standard, needs-refinement, P1 -> tier:standard, P1, ready" in r.stdout
    assert (folder / "1.md").read_text(encoding="utf-8") == before
    r = refine_cli("apply", 1, body, "--folder", folder, "--apply")
    assert r.returncode == 0 and "REFINED #1 (now ready)" in r.stdout, r.stdout
    issue = select.parse_issue_file(folder / "1.md")
    assert issue["labels"] == ["tier:standard", "P1", "ready"] and issue["body"] == REFINED
    assert issue["title"] == "Round half up" and issue["createdAt"] == "2026-09-01T09:00:00Z"
    plan = select.select(select.read_folder(folder), 5)
    assert 1 in {i["number"] for i in plan["dispatch"]}


@needs_safe_writes
def test_refine_keeps_needs_refinement_while_a_question_is_open(tmp_path):
    folder = refine_folder(tmp_path)
    body = write(tmp_path / "new.md", REFINED + "\n## Open question\nWhich rounding mode?\n")
    r = refine_cli("apply", 1, body, "--folder", folder, "--apply")
    assert r.returncode == 0 and "REFINED #1\n" in r.stdout, r.stdout
    issue = select.parse_issue_file(folder / "1.md")
    assert issue["labels"] == ["tier:standard", "needs-refinement", "P1"]
    assert "Which rounding mode?" in issue["body"]


@pytest.mark.parametrize("number, body, message", [
    (1, GOOD.replace("## Want", "## Wish"), "fails the lint"),
    (2, REFINED, "has no answer from the owner yet"),
    (3, REFINED, "is not an open needs-refinement issue"),
])
def test_refine_changes_nothing_when_it_cannot_refine(tmp_path, number, body, message):
    folder = refine_folder(tmp_path)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    r = refine_cli("apply", number, write(tmp_path / "new.md", body), "--folder", folder,
                   "--apply")
    assert r.returncode == 1 and message in r.stdout, r.stdout + r.stderr
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


def link_or_skip(make, target, link):
    try:
        make(str(target), str(link))
    except (OSError, NotImplementedError) as e:
        pytest.skip("cannot make a link here: %s" % e)


# The issue folder is the owner's, but its entries are untrusted: `issues/1.md` may be a link to a
# file elsewhere. Before the fix, refine followed it and rewrote the outside file.
@pytest.mark.parametrize("make", [os.symlink, os.link], ids=["symlink", "hard link"])
def test_refine_never_writes_through_a_linked_issue_file(tmp_path, make):
    folder = refine_folder(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (folder / "1.md").replace(outside / "1.md")
    before = (outside / "1.md").read_bytes()
    link_or_skip(make, outside / "1.md", folder / "1.md")
    r = refine_cli("apply", 1, write(tmp_path / "new.md", REFINED), "--folder", folder, "--apply")
    assert r.returncode == 2 and "link" in r.stderr, r.stdout + r.stderr
    assert "REFINED" not in r.stdout
    assert (outside / "1.md").read_bytes() == before


def test_select_refuses_a_symlinked_issue_file(tmp_path):
    folder = refine_folder(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (folder / "3.md").replace(outside / "3.md")
    link_or_skip(os.symlink, outside / "3.md", folder / "3.md")
    with pytest.raises(select.InputError, match="link"):
        select.read_folder(folder)


@needs_safe_writes
def test_refine_keeps_the_issue_file_mode(tmp_path):
    folder = refine_folder(tmp_path)
    os.chmod(str(folder / "1.md"), 0o640)
    mode = os.stat(str(folder / "1.md")).st_mode & 0o777
    r = refine_cli("apply", 1, write(tmp_path / "new.md", REFINED), "--folder", folder, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.stat(str(folder / "1.md")).st_mode & 0o777 == mode
    assert sorted(p.name for p in folder.iterdir()) == ["1.md", "2.md", "3.md"]


# ----- races: an entry swapped for a link between a check and the open or write ----------------
# Each test swaps the entry at the exact step, from a hook on the call the code makes there, so
# the interleaving is deterministic: no threads, no timing loops.

def dir_link_or_skip(target, link):
    """A link to a folder: a symlink, or on Windows a junction, which needs no privilege."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link_or_skip(os.symlink, target, link)


def is_entry(path, folder, name=None):
    """Whether a path argument (with or without a dir_fd) names folder/name."""
    want = os.path.normcase(os.path.abspath(str(folder / name) if name else str(folder)))
    return os.path.normcase(os.path.abspath(str(path))) == want


def swap_once(swap):
    done = []

    def run():
        if not done:
            done.append(True)
            swap()
    return run


def outside_issue(tmp_path, number):
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    folder_issue(outside, number, "QZJ-9047-WVX outside title", ["tier:standard", "ready"],
                 GOOD + "\n## Owner answer\nQZJ-9047-WVX outside answer.\n")
    path = outside / ("%d.md" % number)
    os.chmod(str(path), 0o600)
    return path


def outside_state(path):
    return {p.name: (p.read_bytes(), os.stat(str(p)).st_mode) for p in path.parent.iterdir()}


def test_select_never_reads_an_issue_file_swapped_for_a_link_after_its_check(tmp_path,
                                                                            monkeypatch):
    folder = refine_folder(tmp_path)
    outside = outside_issue(tmp_path, 3)
    swap = swap_once(lambda: ((folder / "3.md").unlink(),
                              link_or_skip(os.symlink, outside, folder / "3.md")))
    real_lstat, real_open = os.lstat, os.open

    def lstat(path, *a, **kw):
        st = real_lstat(path, *a, **kw)
        if is_entry(path, folder, "3.md"):
            swap()  # checked: a plain file; now it is a link
        return st

    def open_(path, flags, *a, dir_fd=None, **kw):
        if (path == "3.md" and dir_fd is not None) or is_entry(path, folder, "3.md"):
            swap()
        return real_open(path, flags, *a, dir_fd=dir_fd, **kw)

    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setattr(os, "open", open_)
    with pytest.raises(select.InputError, match="link") as e:
        issues = select.read_folder(folder)
        assert "QZJ" not in repr(issues)
    assert "QZJ" not in str(e.value)


def test_select_refuses_an_issue_file_with_other_hard_links(tmp_path):
    folder = refine_folder(tmp_path)
    outside = outside_issue(tmp_path, 3)
    (folder / "3.md").unlink()
    link_or_skip(os.link, outside, folder / "3.md")
    with pytest.raises(select.InputError, match="hard links"):
        select.read_folder(folder)


def refine_in_process(capsys, folder, body, *extra):
    code = refine.main(["apply", "1", str(body), "--folder", str(folder), "--apply"]
                       + list(extra))
    out = capsys.readouterr()
    return code, out.out + out.err


@needs_safe_writes
def test_refine_writes_only_into_the_folder_it_read(tmp_path, monkeypatch, capsys):
    """The folder is replaced by a link to another folder after refine checks the issue file
    and before it writes. The write must still land in the folder it read."""
    folder = refine_folder(tmp_path)
    outside = outside_issue(tmp_path, 1)
    before = outside_state(outside)
    body = write(tmp_path / "new.md", REFINED)
    moved = tmp_path / "moved"
    swap = swap_once(lambda: (folder.rename(moved), dir_link_or_skip(outside.parent, folder)))
    real_samestat = os.path.samestat

    def samestat(a, b):
        same = real_samestat(a, b)
        swap()  # after the identity check, before the temp file and the move
        return same

    monkeypatch.setattr(os.path, "samestat", samestat)
    code, out = refine_in_process(capsys, folder, body)
    assert outside_state(outside) == before, out
    assert code == 0 and "REFINED #1" in out, out
    assert select.parse_issue_file(moved / "1.md")["body"] == REFINED


def test_refine_refuses_a_folder_reached_through_a_link(tmp_path, capsys):
    real = tmp_path / "elsewhere"
    real.mkdir()
    outside = outside_issue(tmp_path, 1)
    before = outside_state(outside)
    dir_link_or_skip(outside.parent, real / "issues")
    body = write(tmp_path / "new.md", REFINED)
    code, out = refine_in_process(capsys, real / "issues", body)
    assert code == 2 and "link" in out, out
    assert outside_state(outside) == before


@needs_safe_writes
def test_refine_never_follows_a_swapped_temp_file(tmp_path, monkeypatch, capsys):
    """The new file is swapped for a link to an outside file after it is written and before it
    is moved over the issue file: no outside mode may change, and refine must not report
    success with a link as the issue file."""
    folder = refine_folder(tmp_path)
    outside = outside_issue(tmp_path, 7)
    before = outside_state(outside)
    body = write(tmp_path / "new.md", REFINED)

    def swap_temp(path, dir_fd=None):
        if os.path.basename(str(path)) == "1.md":
            return
        os.unlink(path, dir_fd=dir_fd)
        os.symlink(str(outside), path, dir_fd=dir_fd)

    real_chmod, real_replace = os.chmod, os.replace
    swapped = []

    def chmod(path, mode, *a, **kw):
        if not swapped and str(path).endswith(".tmp"):
            swapped.append(path)
            swap_temp(path, kw.get("dir_fd"))
        return real_chmod(path, mode, *a, **kw)

    def replace(src, dst, *a, src_dir_fd=None, dst_dir_fd=None, **kw):
        if not swapped:
            swapped.append(src)
            swap_temp(src, src_dir_fd)
        return real_replace(src, dst, *a, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, **kw)

    monkeypatch.setattr(os, "chmod", chmod)
    monkeypatch.setattr(os, "replace", replace)
    code, out = refine_in_process(capsys, folder, body)
    assert swapped, "the hook never ran"
    assert outside_state(outside) == before, out
    assert code == 1 and "REFINED" not in out, out


def test_refine_refuses_folder_writes_where_it_cannot_anchor_them(tmp_path, monkeypatch, capsys):
    folder = refine_folder(tmp_path)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    monkeypatch.setattr(refine, "SAFE_WRITES", False, raising=False)
    code, out = refine_in_process(capsys, folder, write(tmp_path / "new.md", REFINED))
    assert code == 1 and "REFINED" not in out and "cannot" in out, out
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


def host_routes(issue_labels, comments, repo_labels=REPO_LABELS):
    issue = {"number": 7, "title": "Round half up", "state": "open", "body": WAITING,
             "created_at": "2026-09-05T09:00:00Z", "labels": labels(*issue_labels)}
    return {"repos/o/r/issues/7": issue,
            "repos/o/r/issues/7/comments?per_page=100": comments,
            "repos/o/r/labels?per_page=100": repo_labels,
            "repos/o/r/issues?state=open&labels=needs-refinement&per_page=100": [
                issue, {"number": 8, "title": "a PR", "pull_request": {}, "state": "open"}]}


OWNER_ANSWER = [{"user": {"login": "someone"}, "created_at": "2026-10-25T10:00:00Z",
                 "body": "Per invoice?"},
                {"user": {"login": "Owner"}, "created_at": "2026-10-26T10:00:00Z",
                 "body": "Per line."}]


def test_refine_on_the_host_touches_only_ready_and_needs_refinement(tmp_path):
    """The issue also carries an owner-only label: refinement leaves it where it is."""
    gh, env, calls = stand_in(tmp_path, host_routes(
        ["tier:standard", "needs-refinement", "gate-change-approved"], OWNER_ANSWER))
    body = write(tmp_path / "new.md", REFINED)
    r = refine_cli("list", "--repo", "o/r", "--owner", "owner", "--gh", gh, env=env)
    assert r.returncode == 0 and "2026-10-26: Per line." in r.stdout, r.stdout + r.stderr
    assert "Per invoice" not in r.stdout and "a PR" not in r.stdout
    r = refine_cli("apply", 7, body, "--repo", "o/r", "--owner", "owner", "--gh", gh, env=env)
    assert r.returncode == 0 and not [c for c in calls() if c[0] != "api"], r.stdout
    r = refine_cli("apply", 7, body, "--repo", "o/r", "--owner", "owner", "--gh", gh, "--apply",
                   env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    [edit] = [c for c in calls() if c[0] != "api"]
    assert edit[:5] == ["issue", "edit", "7", "-R", "o/r"]
    assert edit[edit.index("--body") + 1] == REFINED
    flags = [a for a in edit if a.startswith("--")]
    assert flags == ["--body", "--add-label", "--remove-label"]
    assert edit[edit.index("--add-label") + 1] == "ready"
    assert edit[edit.index("--remove-label") + 1] == "needs-refinement"


def test_refine_on_the_host_needs_the_owner_and_the_ready_label(tmp_path):
    body = write(tmp_path / "new.md", REFINED)
    gh, env, calls = stand_in(tmp_path, host_routes(["tier:standard", "needs-refinement"],
                                                    OWNER_ANSWER[:1]))
    r = refine_cli("apply", 7, body, "--repo", "o/r", "--gh", gh, "--apply", env=env)
    assert r.returncode == 1 and "no answer from the owner" in r.stdout, r.stdout
    gh, env, calls = stand_in(tmp_path, host_routes(["tier:standard", "needs-refinement"],
                                                    OWNER_ANSWER, labels("bug")))
    r = refine_cli("apply", 7, body, "--repo", "o/r", "--owner", "OWNER", "--gh", gh, "--apply",
                   env=env)
    assert r.returncode == 1 and "MISSING LABELS: ready" in r.stdout, r.stdout
    assert not [c for c in calls() if c[0] != "api"]


def test_refine_usage_and_host_errors(tmp_path):
    folder = refine_folder(tmp_path)
    body = write(tmp_path / "new.md", REFINED)
    assert refine_cli("list", 1, "--folder", folder).returncode == 2
    assert refine_cli("apply", 1, "--folder", folder).returncode == 2
    assert refine_cli("list", "--folder", folder, "--apply").returncode == 2
    assert refine_cli("apply", 9, body, "--folder", folder).returncode == 2
    assert refine_cli("apply", 1, tmp_path / "nope.md", "--folder", folder).returncode == 2
    assert refine_cli("list", "--repo", "bad").returncode == 2
    assert refine_cli("list", "--repo", "o/r", "--gh", "gh '").returncode == 2
    gh, env, _ = stand_in(tmp_path, {})
    r = refine_cli("list", "--repo", "o/r", "--gh", gh, env=env)
    assert r.returncode == 2 and "HTTP 404" in r.stderr and "Traceback" not in r.stderr
    r = refine_cli("apply", 7, body, "--repo", "o/r", "--gh", gh, env=env)
    assert r.returncode == 2 and "Traceback" not in r.stderr
    assert refine_cli("apply", 1, "-", "--folder", folder, stdin=REFINED).returncode == 0


def test_new_labels_never_touch_other_labels():
    for extra in (["gate-change-approved"], ["findings-accepted", "P0"], []):
        before = ["tier:standard", "needs-refinement"] + extra
        assert refine.new_labels(before, REFINED) == ["tier:standard"] + extra + ["ready"]
        assert refine.new_labels(before, WAITING) == before


# ----- docs ----------------------------------------------------------------------------------

def test_skill_front_matter_names_every_script_and_headers():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: queue-fill\ndescription: ")
    for name in ("issue_lint.py", "hunt.py", "refine.py", "file_issues.py"):
        assert name in text, name
    for path in sorted(SCRIPTS.glob("*.py")):
        assert path.name in text, path.name
        header = path.read_text(encoding="utf-8").split('"""')[1]
        assert "Exit codes:" in header and "Stdlib only" in header, path.name
    for target in re.findall(r"\]\(([^)#\s]+)", text):
        assert (SKILL / target).resolve().exists(), target
    assert "skills/queue-fill/" in (ROOT / "box" / "README.md").read_text(encoding="utf-8")


def test_skill_is_vendor_neutral():
    names = ["Claude", "Codex", "Cursor", "OpenAI", "Anthropic", "GPT", "Copilot", "Gemini"]
    for path in sorted(SKILL.rglob("*")):
        if path.suffix in (".md", ".py", ".json"):
            text = path.read_text(encoding="utf-8")
            for name in names:
                assert not re.search(r"\b%s\b" % name, text), (path, name)


@pytest.mark.parametrize("unit", ["-  ", "-   ", "1.  ", "* \t "])
def test_fence_like_does_not_backtrack_on_a_long_list_marker_line(unit):
    """`\\s+[\\s>]*` could split each marker's spaces many ways, so one line of about 80 characters
    took seconds and each few more doubled it. A child process keeps a regression from hanging the
    suite."""
    line = unit * 200 + "x"
    code = ("import sys; sys.path[:0] = %r; import issue_lint; "
            "assert issue_lint.FENCE_LIKE.match(%r) is None" % (sys.path, line))
    subprocess.run([sys.executable, "-c", code], check=True, timeout=20)


@pytest.mark.parametrize("line", ["```", "- ```", "-  ```", "-   > ~~~", "1.  ```", " > * \t ```"])
def test_fence_like_still_finds_a_fence_after_markers(line):
    assert issue_lint.FENCE_LIKE.match(line)


@pytest.mark.parametrize("line", ["'# ' + '#' * 200000 + 'x'", "'# ' + ' #\\t' * 70000 + 'x'"])
def test_heading_does_not_backtrack_on_a_long_run_of_closing_hashes(line):
    """`(.*?)[ \\t#]*$` rescanned the rest of the line for each character the lazy text took, so
    one heading line of 64 KB took over 5 s. Issue bodies are untrusted."""
    code = ("import sys; sys.path[:0] = %r; import issue_lint; "
            "assert issue_lint.headings(%s)[0][1].endswith('x')" % (sys.path, line))
    subprocess.run([sys.executable, "-c", code], check=True, timeout=5)


@pytest.mark.parametrize("line, heading", [
    ("# Title", (1, "Title")), ("## Title ##", (2, "Title")), ("#  a # b #  ", (1, "a # b")),
    ("### C# \t#", (3, "C")), ("# #", (1, "")), ("#\t", (1, "")), ("   ###### x", (6, "x")),
    ("    # x", None), ("####### x", None), ("#x", None),
])
def test_heading_still_strips_the_closing_sequence(line, heading):
    found = [h[:2] for h in issue_lint.headings(line)]
    assert found == ([heading] if heading else [])
    assert bool(issue_lint.HEADING.match(line)) == bool(heading)
