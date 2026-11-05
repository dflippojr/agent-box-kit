"""Tests for box/orchestrate/scripts: select.py and handoff_check.py. Host responses are invented
ones in GitHub's shape (tests/fixtures/orchestrate, see its README), served by a stand-in gh so the
scripts run as they would against the host. The no-hosted-VCS mode runs on real git repositories
built in temp folders."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import git, write

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "box" / "orchestrate" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "orchestrate"


def load(name, alias):
    """Import a script under another name: `select` would shadow the standard library module."""
    spec = importlib.util.spec_from_file_location(alias, str(SCRIPTS / name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selector = load("select.py", "orchestrate_select")
handoff = load("handoff_check.py", "orchestrate_handoff_check")


def script(name, *args, env=None, stdin=None):
    return subprocess.run([sys.executable, str(SCRIPTS / name)] + [str(a) for a in args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, input=stdin)


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# A stand-in gh: answers `gh api PATH` and `gh api graphql ...` from the routes of one PR case.
FAKE_GH = r'''
import json, os, sys
data = json.load(open(os.environ["FAKE_GH_FIXTURE"], encoding="utf-8"))
routes = dict(data["base"])
routes.update(data["cases"].get(os.environ.get("FAKE_GH_CASE", ""), {}))
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["api", "graphql"]:
    if "query=" not in " ".join(args) or "mutation" in " ".join(args):
        sys.exit(1)
    after = [a[6:] for a in args if a.startswith("after=")]
    key = "graphql" + (" after=" + after[0] if after else "")
elif args[:3] == ["api", "-X", "GET"]:
    key = args[-1]
else:
    sys.stderr.write("only read-only api calls are allowed\n")
    sys.exit(1)
if key not in routes:
    sys.stderr.write("gh: Not Found (HTTP 404)\n")
    sys.exit(1)
print(json.dumps(routes[key]))
'''


@pytest.fixture
def fake_gh(tmp_path):
    """The --gh command, and a function giving the environment for a case."""
    gh = tmp_path / "gh.py"
    gh.write_text(FAKE_GH, encoding="utf-8")
    log = tmp_path / "gh.log"
    command = '"%s" "%s"' % (Path(sys.executable).as_posix(), gh.as_posix())

    def env(case, fixture_file="pr_cases.json"):
        return dict(os.environ, FAKE_GH_FIXTURE=str(FIXTURES / fixture_file), FAKE_GH_CASE=case,
                    FAKE_GH_LOG=str(log))
    env.log = log
    return command, env


def stand_in_gh(tmp_path, routes):
    """The --gh command and environment for a stand-in gh serving `routes`, and its call log."""
    fixture_file = tmp_path / "routes.json"
    fixture_file.write_text(json.dumps({"base": routes, "cases": {}}), encoding="utf-8")
    gh = tmp_path / "gh.py"
    gh.write_text(FAKE_GH, encoding="utf-8")
    log = tmp_path / "gh.log"
    env = dict(os.environ, FAKE_GH_FIXTURE=str(fixture_file), FAKE_GH_LOG=str(log))
    return '"%s" "%s"' % (Path(sys.executable).as_posix(), gh.as_posix()), env, log


def runner(case):
    """The same routes as the stand-in gh, in-process."""
    data = fixture("pr_cases.json")
    routes = dict(data["base"], **data["cases"][case])

    def run(args):
        if args[:2] == ["api", "graphql"]:
            after = [a[6:] for a in args if a.startswith("after=")]
            key = "graphql" + (" after=" + after[0] if after else "")
        else:
            assert args[:3] == ["api", "-X", "GET"], args
            key = args[-1]
        return (routes[key], None) if key in routes else (None, "HTTP 404")
    return run


def test_fixtures_are_synthetic():
    """This repository is public: fixtures are invented, never recorded issues or PRs."""
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    assert "invented" in readme
    for path in sorted(FIXTURES.glob("*.json")):
        assert path.name in readme, path.name
        text = path.read_text(encoding="utf-8")
        for sha in re.findall(r"\b[0-9a-f]{40}\b", text):
            assert int(sha, 16) < 16 ** 12, "%s has a real-looking commit id" % path.name
        assert not re.search(r"https?://(?!example\.com)", text), path.name
        assert "owner/app" in text or path.name == "issues.json"


# ----- select.py -----------------------------------------------------------------------------

ISSUES = FIXTURES / "issues.json"


def plan(capacity=2, **kw):
    issues = selector.read_json(str(ISSUES))
    return selector.select(issues, capacity, **kw)


def reasons_for(result, number):
    return next(e["reasons"] for e in result["not_dispatchable"] if e["number"] == number)


def test_priority_order_then_oldest_first():
    result = plan(capacity=10)
    # P1 #7 is newer than unlabelled #8 but goes first; within P1, #7 is older than #3.
    assert [e["number"] for e in result["dispatch"]] == [7, 3, 8, 2]
    assert [e["number"] for e in result["not_dispatchable"]] == [10, 5, 4, 6, 9, 12]


def test_capacity_one_dispatches_only_the_top_issue():
    result = plan(capacity=1)
    assert [e["number"] for e in result["dispatch"]] == [7]
    assert [e["number"] for e in result["waiting"]] == [3, 8, 2]


def test_capacity_zero_dispatches_nothing():
    result = plan(capacity=0)
    assert result["dispatch"] == [] and len(result["waiting"]) == 4


def test_an_open_dependency_holds_the_issue():
    assert reasons_for(plan(), 4) == ["dependency #2 is open"]


def test_a_closed_dependency_does_not_hold_the_issue():
    assert 3 in [e["number"] for e in plan()["dispatch"]]


def test_a_dependency_missing_from_the_input_counts_as_open():
    assert reasons_for(plan(), 12) == ["dependency #40 not in the input; its state is unknown"]


def test_missing_and_double_tier_labels():
    result = plan()
    assert reasons_for(result, 5) == ["no tier label"]
    assert reasons_for(result, 6) == ["2 tier labels (tier:frontier, tier:standard); needs "
                                      "exactly one"]


def test_lifecycle_labels_hold_a_ready_issue():
    result = plan()
    assert reasons_for(result, 10) == ["labelled reserved: is reserved (a session holds it)"]
    assert "needs the owner at hand" in reasons_for(result, 9)[0]
    # #11 is not ready, so it is not listed at all; #1 is closed.
    listed = {e["number"] for k in ("dispatch", "waiting", "not_dispatchable") for e in result[k]}
    assert not listed & {1, 11}


def test_owner_present_releases_user_present_issues():
    assert 9 in [e["number"] for e in plan(capacity=10, owner_present=True)["dispatch"]]


def test_every_reason_is_listed():
    issues = [{"number": 1, "title": "t", "state": "OPEN", "createdAt": "", "labels":
               ["ready", "blocked", "parked"], "body": "Dependencies: #2, other/repo#3"},
              {"number": 2, "title": "u", "state": "OPEN", "createdAt": "", "labels": [],
               "body": ""}]
    result = selector.select(issues, 1)
    assert result["not_dispatchable"][0]["reasons"] == [
        "no tier label", "labelled blocked: is blocked", "labelled parked: is parked",
        "dependency #2 is open",
        "dependency other/repo#3 is in another repo; check it and drop the line"]


def test_dependency_lines_in_issue_shapes():
    assert selector.dependencies("## Dependencies\nDependencies: #32\n") == [(None, 32)]
    assert selector.dependencies("**Dependencies:** #3, #4") == [(None, 3), (None, 4)]
    assert selector.dependencies("**Dependencies**\nnone\n") == []
    assert selector.dependencies("Closes #5. No dependencies here.") == []
    assert selector.dependencies("Dependencies: https://example.com/owner/app/issues/1") == [
        ("owner/app", 1)]
    assert selector.dependencies("## Dependencies\n- #3 the schema, merged\n- #4\n") == [
        (None, 3), (None, 4)]
    for line in ("Dependencies: none", "Dependencies: None yet.", "**Dependencies**\nnone\n",
                 "## Dependencies\nnone\n\n## Next\nSee #9.",
                 "## Dependencies\n- none\n\n# Next\n#9", "**Dependencies**\nnone\n\nSee #9.",
                 "Dependencies: #3 (the schema), owner/app#4",
                 "Dependencies are pinned in the lock file. See #9."):
        assert selector.unread_dependencies(line) == [], line
        assert 9 not in [n for _, n in selector.dependencies(line)], line


# The key with its references on the lines below it, as a person editing an issue or a box-audit
# card (`**Dependencies**`, then `none`) writes them.
@pytest.mark.parametrize("body", [
    "Dependencies:\n- #1",
    "Dependencies:\n#1",
    "**Dependencies**\n#1",
    "**Dependencies**\n- #1",
    "**Dependencies:**\n- #1",
    "Dependencies\n#1",
    "Dependencies:\n\n1. #1",
    "**Dependencies**\n- [ ] #1",
    "## Dependencies\n- #1 the parser, not merged",
    "## Dependencies\n\n- #2\n\n- #1\n\n## Out of scope",
    "**Constraints**\n- none\n\n**Dependencies**\n#1\n\n**Out of scope**\nThe theme.",
    "**Dependencies**\n#1\n**Out of scope**\nThe theme.",
    "**Dependencies**\n**#1**",
    # A loose list (blank lines between items) under a key that is not a heading.
    "**Dependencies**\n\n- #2\n\n- #1",
    "Dependencies:\n- #2\n\n- #1",
    "**Dependencies**\n\n1. #2\n\n2. #1\n\n**Out of scope**\nThe theme.",
    # Under a heading, everything up to the next heading of the same or a higher level.
    "## Dependencies\n### Blocking\n- #1",
    "## Dependencies\n\n### Blocking\n\n- #2\n\n**Soft**\n\n- #1\n\n## Out of scope\nThe theme.",
    "### Dependencies\n- #2\n\n#### Later\n\n#1\n\n### Acceptance\n- [ ] passes",
    # A list under a key line that has a value of its own, as the list grows when someone edits it.
    "Dependencies: #2\n- #1",
    "Dependencies: #2\n\n- #1",
    "**Dependencies:** #2\n- #1",
    "- Dependencies: #2\n  - #1",
    "Dependencies: #2\n#1",
    "Dependencies: #2\n\u2022 #1",
    "Dependencies: #2\n\u2022 #1 the parser",
    "Dependencies: #2\n\u2013 #1 the parser",
    "- Tier: standard\n- Dependencies: #2\n- Blocked by: #1\n- Acceptance: passes",
    # The key's paragraph: a line directly below it that names an issue, even past prose. Markdown
    # renders `Dependencies: #2\nAlso #1` as one line.
    "Dependencies: #2\nAlso #1",
    "Dependencies: #2\nblocked by #1 too",
    "Dependencies: #2\n#1 parser",
    "Dependencies: #2\n<br>#1",
    "Dependencies: #2\nand the parser work\nin #1",
    "Dependencies: #2\n\n- #2\nalso #1",
    # A sub-label item with nothing after its colon, and a nested list under it.
    "Dependencies: #2\n- Hard:\n  - #1",
    "**Dependencies:** #2\n- **Blocking:**\n  - #1",
    "- Tier: standard\n- Dependencies: #2\n  - Hard:\n    - #1",
    "Dependencies: #2\n- Hard:\n  - #2\n- Soft:\n\n  - #1",
    "Dependencies: #2\nHard:\n\t- #1",
    "Dependencies: #2\n- Hard:\n  - #2\nAlso #1",
    "> Dependencies: #2\n> - Hard:\n>   Blocked by: #1",
    "Dependencies: #2\n\n#1, #2",
    # A sub-label with nothing after its colon and a list that is not indented under it: a label
    # line, a flat list of sub-labels, mixed tabs and spaces, a loose list.
    "Dependencies: #2\nHard:\n- #1",
    "Dependencies: #2\nBlocking:\n- #1",
    "Dependencies: #2\nHard:\n#1",
    "Dependencies: #2\nHard:\nAlso #1",
    "**Dependencies:** #2\nHard:\n- #1",
    "Dependencies: #2\nHard:\nSoft:\n- #1",
    "Dependencies: #2\n- Hard:\n- #1\n- Soft:\n- #2",
    "Dependencies: #2\n- Hard:\n\n- #1",
    "- Dependencies: #2\n  - Hard:\n\t- #1",
    "Dependencies: #2\n- Hard:\n  - #2\n\n- Soft:\n  - #1",
    # The key as any list item the parser reads: ordered, `+`, a bullet or dash, a checkbox.
    "1. Dependencies: #1",
    "1) Dependencies: #1",
    "1. Tier: standard\n2. Dependencies: #1",
    "1. Dependencies:\n   - #1",
    "+ Dependencies: #1",
    "• Dependencies: #1",
    "– Dependencies: #1",
    "- [ ] Dependencies: #1",
    "- [x] Dependencies: #1",
    "* [X] **Dependencies:** #2\n  - #1",
    "> 1. Dependencies: #1",
    # After a blank line under a bare key or label: a line of references, or a `\u2022` item.
    "**Dependencies**\n#2\n\n#1",
    "**Dependencies**\n- #2\n\n#1, #2",
    "Dependencies:\n- #2\n\n\u2022 #1",
    "Dependencies:\n- #2\n\n\u2022 #1 the parser",
    # Unicode space or a byte-order mark before the key.
    "\u2003Dependencies: #1",
    "\ufeffDependencies: #1",
    "\u3000Dependencies: #1",
    "##\u00a0Dependencies\n- #1",
])
def test_references_below_the_dependencies_key_hold_the_issue(body):
    issues = [{"number": 3, "title": "t", "state": "OPEN", "createdAt": "", "body": body,
               "labels": ["ready", "tier:standard"]},
              {"number": 1, "title": "u", "state": "OPEN", "createdAt": "", "labels": [],
               "body": ""},
              {"number": 2, "title": "v", "state": "CLOSED", "createdAt": "", "labels": [],
               "body": ""}]
    result = selector.select(issues, 1)
    assert result["dispatch"] == []
    assert reasons_for(result, 3) == ["dependency #1 is open"]


@pytest.mark.parametrize("line, reason", [
    ("Dependencies: 1", "dependency line not understood: 1 (write #n references, or none)"),
    ("Dependencies: #2, 1", "dependency line not understood: #2, 1 (write #n references, or "
                            "none)"),
    ("Dependencies: the schema issue", "dependency line not understood: the schema issue (write "
                                       "#n references, or none)"),
    ("Dependencies: https://example.com/owner/app/pull/1", "dependency line not understood: "
     "https://example.com/owner/app/pull/1 (write #n references, or none)"),
    ("Dependencies: https://example.com/owner/app/issues/1", "dependency #1 is open"),
    ("**Dependencies**\nthe schema issue", "dependency line not understood: the schema issue "
                                           "(write #n references, or none)"),
    ("Dependencies:\n- 1", "dependency line not understood: 1 (write #n references, or none)"),
    ("Dependencies: -", "dependency line not understood: - (write #n references, or none)"),
    ("Dependencies: ?", "dependency line not understood: ? (write #n references, or none)"),
    ("Dependencies: nonexistent", "dependency line not understood: nonexistent (write #n "
                                  "references, or none)"),
    # A line of the key's paragraph that names an issue without a `#`.
    ("Dependencies: #2\nAlso issue 1", "dependency line not understood: Also issue 1 (write #n "
                                       "references, or none)"),
    ("Dependencies: #2\nHard:\nAlso issue 1", "dependency line not understood: Also issue 1 "
                                              "(write #n references, or none)"),
])
def test_a_dependency_line_that_cannot_be_read_holds_the_issue(line, reason):
    """A link or a bare number is how a person writes a dependency too. Read as no dependency, it
    would dispatch an issue whose dependency #1 is still open."""
    issues = [{"number": 3, "title": "t", "state": "OPEN", "createdAt": "", "body": line,
               "labels": ["ready", "tier:standard"]},
              {"number": 1, "title": "u", "state": "OPEN", "createdAt": "", "labels": [],
               "body": ""}]
    result = selector.select(issues, 1, slug="owner/app")
    assert result["dispatch"] == []
    assert reason in reasons_for(result, 3)


@pytest.mark.parametrize("body, line", [
    ("**Dependencies**\n**Blocking**\n- #1", "**Dependencies**"),
    ("Dependencies:\n\n## Acceptance\n- #1 passes", "Dependencies:"),
    ("**Dependencies**\n**Out of scope**\n- #1", "**Dependencies**"),
    ("## Dependencies\n\n## Acceptance\n- #1 passes", "## Dependencies"),
    ("## Dependencies\n\n### Blocking\n", "## Dependencies"),
    ("Dependencies:", "Dependencies:"),
    ("Dependencies:\n", "Dependencies:"),
    ("Dependencies (blocking): #1", "Dependencies (blocking): #1"),
    ("Dependencies - #1", "Dependencies - #1"),
    ("Dependencies \u2014 #1", "Dependencies \u2014 #1"),
    ("Dependencies\u00a0: #1", "Dependencies\u00a0: #1"),
    ("**Dependencies (blocking)**\n- #1", "**Dependencies (blocking)**"),
    ("Dependency: #1", "Dependency: #1"),
    ("**Dependency**\n- #1", "**Dependency**"),
    # A key in a shape the parser does not read: a table row, HTML, inline code.
    ("| Dependencies | #1 |", "| Dependencies | #1 |"),
    ("<b>Dependencies:</b> #1", "<b>Dependencies:</b> #1"),
    ("`Dependencies:` #1", "`Dependencies:` #1"),
    ("- <strong>Dependencies</strong>: #1", "- <strong>Dependencies</strong>: #1"),
    ("<td>Dependencies</td><td>1</td>", "<td>Dependencies</td><td>1</td>"),
])
def test_a_dependencies_key_with_nothing_readable_holds_the_issue(body, line):
    """A key with no reference and no `none` under it, or a key written in a shape this script does
    not know, may still name a dependency. Read as none, it would dispatch the issue with #1
    open."""
    issues = [{"number": 3, "title": "t", "state": "OPEN", "createdAt": "", "body": body,
               "labels": ["ready", "tier:standard"]},
              {"number": 1, "title": "u", "state": "OPEN", "createdAt": "", "labels": [],
               "body": ""}]
    result = selector.select(issues, 1)
    assert result["dispatch"] == []
    assert "dependency line not understood: %s (write #n references, or none)" % line \
        in reasons_for(result, 3)


@pytest.mark.parametrize("body, line", [
    ("Dependencies: none\n- #2", "Dependencies: none"),
    ("**Dependencies**: none\n- #2", "**Dependencies**: none"),
    ("## Dependencies: none\n- #2", "## Dependencies: none"),
    ("* Dependencies: none\n* #2", "* Dependencies: none"),
    ("Dependencies: none\n\n- #2", "Dependencies: none"),
    ("Dependencies:\n- none\n- #2", "Dependencies:"),
    ("**Dependencies**\nnone\n\n#2", "**Dependencies**"),
    ("Dependencies: none\nbut actually #2", "Dependencies: none"),
    ("Dependencies: none\n- Blocked by:\n  - #2", "Dependencies: none"),
    ("Dependencies: none\nHard:\n- #2", "Dependencies: none"),
    ("- [ ] Dependencies: none\n- #2", "- [ ] Dependencies: none"),
])
def test_none_with_a_reference_under_it_holds_the_issue(body, line):
    """`none` and a reference under the same key contradict each other. Read either way, the issue
    may go out while its dependency is open, so a person has to rewrite it. #2 is closed here, so
    the contradiction is the only reason; with #1 open the issue is held for #1 as well."""
    issues = [{"number": 3, "title": "t", "state": "OPEN", "createdAt": "", "body": body,
               "labels": ["ready", "tier:standard"]},
              {"number": 1, "title": "u", "state": "OPEN", "createdAt": "", "labels": [],
               "body": ""},
              {"number": 2, "title": "v", "state": "CLOSED", "createdAt": "", "labels": [],
               "body": ""}]
    result = selector.select(issues, 1)
    assert result["dispatch"] == []
    assert reasons_for(result, 3) == [
        "dependency line not understood: %s (write #n references, or none)" % line]
    issues[0]["body"] = body.replace("#2", "#1")
    result = selector.select(issues, 1)
    assert result["dispatch"] == []
    assert "dependency #1 is open" in reasons_for(result, 3)


@pytest.mark.parametrize("body", [
    "Dependencies: none",
    "Dependencies: #2",
    "Dependencies: none\n\n- Add the flag\n- Test it",
    "Dependencies: #2\nTier: standard\n- #1 is not a dependency here",
    "- Tier: standard\n- Dependencies: none\n- Acceptance: tests pass",
    "**Dependencies:** none\n**Acceptance:** #1 passes",
    "Dependencies: #2\n\n## Acceptance\n- #1 passes",
    "Dependencies: none\n\nSee #1 for the background.",
    "Dependencies: #2\nThe parser work is done.",
    "Dependencies: none\n- Acceptance:\n  - tests pass",
    "Dependencies: none\nTier: standard\nSee #1 for the background.",
    "Dependencies: none\n- Notes: see below\n  - #1 has the background",
    "Dependencies: none\n## Tasks\n- Add the flag",
    "## Dependencies\nNone",
    "**Dependencies**\n- None",
    "**Problem**\nIt breaks.\n\n**Dependencies**\nnone\n\n**Out of scope**\nThe theme.",
    "1. Dependencies: none\n2. Acceptance: tests pass",
    "- [x] Dependencies: #2\n- [ ] Acceptance: tests pass",
    "Dependencies: none\n- Acceptance:\n  - tests pass\n- Docs:\n  - updated",
    "Dependencies: none\n\nAcceptance:\n- tests pass",
    "Dependencies: none\n\nNotes:\nSee #1 for the background.",
    "Dependencies: none\nNotes:\n\nSee #1 for the background.",
    "Dependencies: none\n\n- `Dependencies: #N` or `none`;",
    "| Key | Value |\n|---|---|\n| Dependencies | none |",
])
def test_a_line_after_an_inline_value_that_is_not_part_of_it_ends_the_key(body):
    """Templates that put one key on each line keep dispatching: a line that is not a list item, an
    item that starts another key, or, after a blank line, a line that names no issue ends it."""
    issues = [{"number": 3, "title": "t", "state": "OPEN", "createdAt": "", "body": body,
               "labels": ["ready", "tier:standard"]},
              {"number": 1, "title": "u", "state": "OPEN", "createdAt": "", "labels": [],
               "body": ""},
              {"number": 2, "title": "v", "state": "CLOSED", "createdAt": "", "labels": [],
               "body": ""}]
    result = selector.select(issues, 1)
    assert [e["number"] for e in result["dispatch"]] == [3], reasons_for(result, 3)


@pytest.mark.parametrize("body, unread", [
    ("Dependencies: #2\n- https://example.com/notes\n- #1", "https://example.com/notes"),
    ("Dependencies: #2\n- See https://example.com/notes\n- #1",
     "See https://example.com/notes"),
    ("Dependencies: #2\n- Hard:\n  - the schema work\n  - #1", "the schema work"),
    ("> Dependencies: #2\n> - Hard:\n>   - the schema work\n>   - #1", "the schema work"),
    ("> Dependencies: #2\n> - Hard:\n>   - Tier: standard\n>   - #1", "Tier: standard"),
    ("- Dependencies: #2\n  - Hard:\n\t- Tier: standard\n\t- #1", "Tier: standard"),
    ("Dependencies: #2\n- Hard:\n- the schema work\n- #1", "the schema work"),
    # `none` under a sub-label with a reference nested under it contradicts itself.
    ("Dependencies: #2\n- Hard: none\n  - #1", "Hard: none"),
    ("Dependencies: #2\n**Hard:** none\n  - #1", "**Hard:** none"),
    ("Dependencies: #2\n- Acceptance:\n  - tests pass\n- #1", "tests pass"),
])
def test_a_line_below_an_inline_value_that_is_not_a_reference_holds_the_issue(body, unread):
    """A link is not a key (`https:`), and a nested list under a sub-label is part of the key, so
    the list goes on to `- #1`. The line with no reference holds the issue too."""
    issues = [{"number": 3, "title": "t", "state": "OPEN", "createdAt": "", "body": body,
               "labels": ["ready", "tier:standard"]},
              {"number": 1, "title": "u", "state": "OPEN", "createdAt": "", "labels": [],
               "body": ""},
              {"number": 2, "title": "v", "state": "CLOSED", "createdAt": "", "labels": [],
               "body": ""}]
    result = selector.select(issues, 1)
    assert result["dispatch"] == []
    assert reasons_for(result, 3) == [
        "dependency line not understood: %s (write #n references, or none)" % unread,
        "dependency #1 is open"]


def test_cli_text_output_and_exit_code():
    r = script("select.py", "--json", ISSUES, "--capacity", "2")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("Dispatch now (capacity 2):\n  #7 ")
    assert "Waiting for capacity:" in r.stdout and "- dependency #2 is open" in r.stdout


def test_cli_reads_stdin_and_reports_nothing_dispatchable_as_success():
    r = script("select.py", "--json", "-", stdin="[]")
    assert r.returncode == 0 and "  none" in r.stdout


@pytest.mark.parametrize("args, stdin", [
    (["--json", "-"], "{not json"),
    (["--json", "-"], '[{"title": "no number"}]'),
    (["--json", "-", "--capacity", "-1"], "[]"),
    (["--repo", "not-a-slug"], None),
    ([], None),
])
def test_cli_usage_and_input_errors_exit_2(args, stdin):
    assert script("select.py", *args, stdin=stdin).returncode == 2


def issue_file(issue):
    """The issue-folder form of one host issue, field for field (README: Issue folder)."""
    return "---\nnumber: %d\ntitle: %s\nstate: %s\nlabels: %s\ncreatedAt: %s\n---\n%s" % (
        issue["number"], issue["title"], issue["state"].lower(),
        ", ".join(l["name"] for l in issue["labels"]), issue["createdAt"], issue["body"])


def test_issue_folder_maps_one_to_one_onto_host_json(tmp_path):
    folder = tmp_path / "issues"
    folder.mkdir()
    for issue in fixture("issues.json"):
        (folder / ("%d.md" % issue["number"])).write_bytes(issue_file(issue).encode("utf-8"))
    from_folder = script("select.py", "--folder", folder, "--format", "json", "--capacity", "2")
    from_json = script("select.py", "--json", ISSUES, "--format", "json", "--capacity", "2")
    assert from_folder.returncode == 0, from_folder.stderr
    assert json.loads(from_folder.stdout) == json.loads(from_json.stdout)


def test_issue_file_whose_number_differs_from_its_name_is_an_input_error(tmp_path):
    (tmp_path / "3.md").write_text("---\nnumber: 4\ntitle: t\nstate: open\n---\n",
                                   encoding="utf-8")
    r = script("select.py", "--folder", tmp_path)
    assert r.returncode == 2 and "does not match the file name" in r.stderr


SELECT_ROUTES = {
    "repos/owner/app/issues?state=open&per_page=100&page=1": [
        {"number": 3, "title": "Round totals", "state": "open", "created_at": "2026-09-05",
         "body": "Dependencies: #1, #2", "labels": [{"name": "ready"}, {"name": "tier:standard"}]},
        {"number": 4, "title": "A pull request", "state": "open", "created_at": "2026-09-01",
         "body": "", "labels": [{"name": "ready"}], "pull_request": {}},
        {"number": 5, "title": "Rename a key", "state": "open", "created_at": "2026-09-06",
         "body": "Dependencies: #1", "labels": [{"name": "ready"}, {"name": "tier:mechanical"}]}],
    "repos/owner/app/issues/1": {"number": 1, "state": "closed"},
}


def test_host_mode_reads_open_issues_and_looks_up_dependencies(tmp_path):
    command, env, log = stand_in_gh(tmp_path, SELECT_ROUTES)
    r = script("select.py", "--repo", "owner/app", "--format", "json", "--gh", command, env=env)
    assert r.returncode == 0, r.stderr
    result = json.loads(r.stdout)
    assert [e["number"] for e in result["dispatch"]] == [5]
    # #2 is not on the host (404): its state is unreadable, so it counts as open.
    assert result["not_dispatchable"][0]["reasons"] == ["dependency #2 is unreadable (http 404)"]
    calls = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert all(c[:3] == ["api", "-X", "GET"] for c in calls)
    # #1 is looked up once, though two issues name it.
    assert sum(c[-1] == "repos/owner/app/issues/1" for c in calls) == 1


def test_host_mode_errors_exit_3(tmp_path):
    r = script("select.py", "--repo", "owner/app", "--gh", '"%s" -c "import sys; sys.exit(1)"'
               % Path(sys.executable).as_posix())
    assert r.returncode == 3 and "host error" in r.stderr



def paged(full_pages, last):
    """A host list of `full_pages` pages of 100, then a page of `last` entries, then nothing.
    Each page is called for at most once."""
    calls = []

    def page_of(n):
        assert n not in calls, "page %d read twice" % n
        calls.append(n)
        size = 100 if n <= full_pages else last if n == full_pages + 1 else 0
        return [{"number": n * 1000 + i, "title": "Issue", "state": "open",
                 "created_at": "2026-09-01", "body": "", "labels": []} for i in range(size)]
    page_of.calls = calls
    return page_of


def page_number(path):
    return int(re.search(r"[?&]page=(\d+)", path).group(1))


def test_select_exactly_ten_full_pages_is_a_complete_list():
    """Issue #64: 1000 open issues, page 11 empty, is read whole."""
    pages = paged(10, 0)
    host = selector.Host("owner/app", runner=lambda path: (pages(page_number(path)), None))
    assert len(selector.read_host(host)) == 1000
    assert pages.calls == list(range(1, 12))


def test_select_more_than_ten_full_pages_is_incomplete():
    pages = paged(10, 1)
    host = selector.Host("owner/app", runner=lambda path: (pages(page_number(path)), None))
    with pytest.raises(selector.HostError, match="more than 10 pages"):
        selector.read_host(host)


def test_select_an_unreadable_page_past_the_bound_is_a_host_error():
    pages = paged(10, 0)

    def run(path):
        n = page_number(path)
        return (None, "HTTP 502") if n == 11 else (pages(n), None)
    with pytest.raises(selector.HostError, match="issues page 11: HTTP 502"):
        selector.read_host(selector.Host("owner/app", runner=run))


def test_select_a_short_first_page_is_the_whole_list():
    pages = paged(0, 7)
    host = selector.Host("owner/app", runner=lambda path: (pages(page_number(path)), None))
    assert len(selector.read_host(host)) == 7
    assert pages.calls == [1]


def test_select_pull_requests_count_toward_a_full_page():
    """A page of 100 entries is full though some are pull requests, so the next page is read."""
    pages = paged(1, 0)

    def run(path):
        batch = pages(page_number(path))
        return [dict(i, pull_request={}) if i["number"] % 2 else i for i in batch], None
    assert len(selector.read_host(selector.Host("owner/app", runner=run))) == 50
    assert pages.calls == [1, 2]


def test_select_overflow_error_text():
    pages = paged(10, 1)
    host = selector.Host("owner/app", runner=lambda path: (pages(page_number(path)), None))
    with pytest.raises(selector.HostError) as e:
        selector.read_host(host)
    assert str(e.value) == "more than 10 pages of open issues; list incomplete"


@pytest.mark.parametrize("response, expected", [
    ((None, "HTTP 502"), "issues page 2: HTTP 502"),
    (({"message": "x"}, None), "issues page 2: not a list"),
    (([{"number": 7, "title": "No state"}], None), "issues page 2: #7: missing or bad field "
                                                   "'state'"),
])
def test_select_page_two_error_text(response, expected):
    pages = paged(1, 0)

    def run(path):
        n = page_number(path)
        return response if n == 2 else (pages(n), None)
    with pytest.raises(selector.HostError) as e:
        selector.read_host(selector.Host("owner/app", runner=run))
    assert str(e.value) == expected


def test_select_a_bad_issue_on_page_one_stops_before_page_two():
    """A full page 1 with a malformed issue is reported before page 2 is asked for."""
    calls = []

    def run(path):
        n = page_number(path)
        calls.append(n)
        if n == 2:
            return None, "HTTP 502"
        batch = paged(1, 0)(n)
        batch[0] = {"number": 7, "title": "No state"}
        return batch, None
    with pytest.raises(selector.HostError) as e:
        selector.read_host(selector.Host("owner/app", runner=run))
    assert str(e.value) == "issues page 1: #7: missing or bad field 'state'"
    assert calls == [1]


def test_select_a_bad_issue_past_the_bound_is_still_the_overflow():
    pages = paged(10, 1)

    def run(path):
        n = page_number(path)
        batch = pages(n)
        return ([{"number": 7, "title": "No state"}] if n == 11 else batch), None
    with pytest.raises(selector.HostError) as e:
        selector.read_host(selector.Host("owner/app", runner=run))
    assert str(e.value) == "more than 10 pages of open issues; list incomplete"


# Run a script as the interpreter would, but find `select` on the path before the built-in one,
# as on interpreters that build it as a separate file (CI's Linux Python does).
SHADOW_PROBE = """
import importlib.machinery, runpy, sys
class PathFirst:
    def find_spec(self, name, path=None, target=None):
        if name == "select":
            return importlib.machinery.PathFinder.find_spec(name, sys.path)
sys.meta_path.insert(0, PathFirst())
sys.argv = sys.argv[1:]
sys.path.insert(0, %r)
runpy.run_path(sys.argv[0], run_name="__main__")
"""


@pytest.mark.parametrize("name", ["select.py", "handoff_check.py"])
def test_scripts_do_not_import_select_py_as_the_standard_select_module(name, repo, tmp_path):
    """subprocess imports `select` on POSIX. Where it is not built in, the scripts' folder, first
    on the path, would hand subprocess select.py instead, and every git or gh call would fail.
    Each run starts a process, since only subprocess.run breaks: select.py runs a stand-in gh and
    handoff_check.py runs git."""
    command, env, log = stand_in_gh(tmp_path, {
        "repos/owner/app/issues?state=open&per_page=100&page=1": []})
    args = {"select.py": ["--repo", "owner/app", "--gh", command],
            "handoff_check.py": ["--local", repo, "--branch", "no-such-branch", "--gate-result",
                                 tmp_path / "gate.txt", "--body", tmp_path / "body.md"]}[name]
    r = subprocess.run([sys.executable, "-c", SHADOW_PROBE % str(SCRIPTS), str(SCRIPTS / name)]
                       + [str(a) for a in args], capture_output=True, text=True, env=env)
    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == {"select.py": 0, "handoff_check.py": 3}[name], r.stderr
    if name == "select.py":
        assert log.read_text(encoding="utf-8").strip(), "the stand-in gh was never run"


# ----- handoff_check.py: host mode -----------------------------------------------------------

def verdict(case):
    return handoff.check_pr("owner/app", 12, runner=runner(case))


def failed(result):
    return {i["name"]: i["problems"] for i in result["items"] if not i["ok"]}


def test_all_green_is_ready():
    result = verdict("all green")
    assert result["ready"] and failed(result) == {}
    assert result["head"] == "%040x" % 0x12


@pytest.mark.parametrize("case, problem", [
    ("pending check", "pending: tests (in_progress)"),
    ("failed check", "failed: tests (failure)"),
    ("cancelled check", "cancelled: tests (cancelled)"),
    ("failed status", "failed: lint (error)"),
    ("no checks", "no checks reported on the head commit"),
])
def test_checks_must_be_green_on_the_head_commit(case, problem):
    result = verdict(case)
    assert not result["ready"] and failed(result) == {"checks": [problem]}


def test_a_rerun_that_passed_replaces_the_failure():
    assert verdict("rerun passed")["ready"]


@pytest.mark.parametrize("case", ["unresolved thread", "unresolved thread on page 2"])
def test_unresolved_threads_block(case):
    problems = failed(verdict(case))
    assert list(problems) == ["review"]
    assert problems["review"][0].startswith("1 unresolved review thread (app/invoice.ext:")


def test_owner_accept_label_after_the_head_commit_accepts_findings():
    assert verdict("accepted by owner")["ready"]


def test_accept_label_applied_by_a_non_owner_does_not_count():
    problems = failed(verdict("accept label by non-owner"))
    assert "findings-accepted was applied by worker-bot, not the owner" in problems["review"][0]
    assert problems["owner-only labels"] == ["findings-accepted applied by worker-bot, not the "
                                             "owner"]


def test_accept_label_applied_before_the_last_push_does_not_count():
    problems = failed(verdict("accept label before push"))
    assert list(problems) == ["review"]
    assert "before the head commit was pushed at 2026-10-05T10:00:00Z" in problems["review"][0]


def test_a_removed_accept_label_does_not_count():
    assert "findings-accepted is not on the PR" in failed(verdict("accept label removed"))[
        "review"][0]


def test_an_owner_only_label_applied_by_a_worker_is_named():
    assert failed(verdict("gate label by non-owner")) == {
        "owner-only labels": ["gate-change-approved applied by worker-bot, not the owner"]}


def test_missing_proof_table():
    assert failed(verdict("missing proof table")) == {"proof": ["no '## Proof' section"]}


def test_proof_table_with_an_empty_cell():
    assert failed(verdict("proof table with an empty cell")) == {
        "proof": ["proof table row 1 has an empty or missing cell"]}


def test_missing_closing_reference():
    assert failed(verdict("missing closing reference")) == {
        "closing reference": ["no closing reference (Closes #n) in the PR body"]}


def test_proof_rule_details():
    good = fixture("pr_cases.json")["base"]["repos/owner/app/pulls/12"]["body"]
    assert handoff.proof_problems(good) == []
    no_sections = good.split("### Not verified")[0]
    assert handoff.proof_problems(no_sections) == [
        "no '### Not verified' section under '## Proof'",
        "no '### Gate changes' section under '## Proof'"]
    assert handoff.proof_problems(good.replace("None.", "")) == [
        "'### Gate changes' is empty (write 'none' if there is nothing)"]
    assert handoff.proof_problems(good.replace("How verified", "Notes")) == [
        "proof table header needs Criterion, How verified and Evidence columns"]
    commented = "<!--\n" + good + "\n-->"
    assert handoff.proof_problems(commented) == ["no '## Proof' section"]
    assert handoff.closing_refs(commented) == []
    assert handoff.closing_refs("Fixes: owner/app#9 and resolves #3") == ["Fixes: owner/app#9",
                                                                          "resolves #3"]


@pytest.mark.parametrize("case, code, first", [
    ("all green", 0, "READY: owner/app#12 at "),
    ("pending check", 1, "NOT READY: owner/app#12 at "),
    ("accept label by non-owner", 1, "NOT READY: owner/app#12 at "),
])
def test_cli_verdicts_and_read_only_calls(fake_gh, case, code, first):
    command, env = fake_gh
    r = script("handoff_check.py", "--repo", "owner/app", "--pr", "12", "--gh", command,
               env=env(case))
    assert r.returncode == code, r.stdout + r.stderr
    assert r.stdout.startswith(first)
    for line in env.log.read_text(encoding="utf-8").splitlines():
        args = json.loads(line)
        assert args[:3] == ["api", "-X", "GET"] or (
            args[:2] == ["api", "graphql"] and "mutation" not in " ".join(args))


def test_cli_names_each_failed_item(fake_gh):
    command, env = fake_gh
    r = script("handoff_check.py", "--repo", "owner/app", "--pr", "12", "--gh", command,
               "--format", "json", env=env("accept label by non-owner"))
    assert r.returncode == 1
    assert [i["name"] for i in json.loads(r.stdout)["items"] if not i["ok"]] == [
        "review", "owner-only labels"]


def test_cli_host_error_exits_3(fake_gh):
    command, env = fake_gh
    r = script("handoff_check.py", "--repo", "owner/app", "--pr", "99", "--gh", command,
               env=env("all green"))
    assert r.returncode == 3 and "pull request: HTTP 404" in r.stderr



@pytest.mark.parametrize("key", [None, "check_runs"])
def test_handoff_exactly_ten_full_pages_is_a_complete_list(key):
    """Issue #64: a list of exactly 1000 entries, page 11 empty, is read whole."""
    pages = paged(10, 0)

    def run(args):
        batch = pages(page_number(args[-1]))
        return ({key: batch} if key else batch), None
    assert len(handoff.Host(runner=run).pages("repos/owner/app/x?per_page=100", "x", key)) == 1000
    assert pages.calls == list(range(1, 12))


def test_handoff_more_than_ten_full_pages_is_incomplete():
    pages = paged(10, 1)
    host = handoff.Host(runner=lambda args: (pages(page_number(args[-1])), None))
    with pytest.raises(handoff.HostError, match="x: more than 10 pages"):
        host.pages("repos/owner/app/x?per_page=100", "x")


def test_handoff_overflow_error_text():
    pages = paged(10, 1)
    host = handoff.Host(runner=lambda args: (pages(page_number(args[-1])), None))
    with pytest.raises(handoff.HostError) as e:
        host.pages("repos/owner/app/x?per_page=100", "x")
    assert str(e.value) == "x: more than 10 pages"


@pytest.mark.parametrize("key", [None, "check_runs"])
def test_handoff_a_short_first_page_is_the_whole_list(key):
    pages = paged(0, 7)

    def run(args):
        batch = pages(page_number(args[-1]))
        return ({key: batch} if key else batch), None
    assert len(handoff.Host(runner=run).pages("repos/owner/app/x?per_page=100", "x", key)) == 7
    assert pages.calls == [1]


def test_handoff_page_two_error_text():
    pages = paged(1, 0)

    def run(args):
        n = page_number(args[-1])
        return (None, "HTTP 502") if n == 2 else (pages(n), None)
    with pytest.raises(handoff.HostError) as e:
        handoff.Host(runner=run).pages("repos/owner/app/x?per_page=100", "x")
    assert str(e.value) == "x: HTTP 502"


@pytest.mark.parametrize("args", [
    [], ["--repo", "owner/app"], ["--repo", "owner/app", "--pr", "1", "--local", "."],
    ["--local", "."], ["--repo", "nope", "--pr", "1"],
])
def test_cli_usage_errors_exit_2(args):
    assert script("handoff_check.py", *args).returncode == 2


@pytest.mark.parametrize("name, args", [
    ("select.py", ["--repo", "owner/app"]),
    ("handoff_check.py", ["--repo", "owner/app", "--pr", "1"]),
])
def test_unbalanced_gh_command_exits_2(name, args):
    r = script(name, *args, "--gh", "gh '")
    assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr


# ----- handoff_check.py: no-hosted-VCS mode on a real git repository -------------------------

@pytest.fixture
def branch(repo, tmp_path):
    """A worker branch with one commit, its handoff note and a passing gate result."""
    git(repo, "checkout", "-q", "-b", "worker/issue-7")
    write(repo, "invoice.txt", "rounds half up\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Round totals")
    head = git(repo, "rev-parse", "HEAD").strip()
    body = fixture("pr_cases.json")["base"]["repos/owner/app/pulls/12"]["body"]
    note = write(tmp_path, "handoff.md", body)
    gate = write(tmp_path, "gate.txt", "command: make check\ncommit: %s\nexit: 0\n" % head)
    return repo, head, note, gate


ACCEPT = "findings-accepted/worker/issue-7"


def tag(repo, email, *args, env=None, name=ACCEPT, message="Findings accepted for #7"):
    """Tag as `email`: the tagger is the committer identity, which GIT_COMMITTER_* overrides."""
    env = dict(env or os.environ, GIT_COMMITTER_NAME="Tagger", GIT_COMMITTER_EMAIL=email)
    r = subprocess.run(["git", "-C", str(repo), "tag", "-a", "-m", message] + list(args) +
                       [name], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def tag_object(repo, head, signature, name=ACCEPT, message="Findings accepted for #7\n"):
    """Write a tag object by hand, `signature` appended, and point the acceptance ref at it."""
    payload = "object %s\ntype commit\ntag %s\ntagger Owner <owner@example.com> 1792000000 " \
              "+0000\n\n%s" % (head, name, message)
    r = subprocess.run(["git", "-C", str(repo), "hash-object", "-t", "tag", "-w", "--stdin"],
                       input=(payload + signature).encode("utf-8"), capture_output=True)
    assert r.returncode == 0, r.stderr
    git(repo, "update-ref", "refs/tags/" + ACCEPT, r.stdout.decode("ascii").strip())
    return payload


def local(repo, note, gate, *extra):
    return script("handoff_check.py", "--local", repo, "--branch", "worker/issue-7",
                  "--gate-result", gate, "--body", note, *extra)


def test_local_mode_ready(branch):
    repo, head, note, gate = branch
    r = local(repo, note, gate)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("READY: worker/issue-7 at %s" % head)


def test_local_mode_gate_result_must_name_the_head(branch, tmp_path):
    repo, head, note, gate = branch
    write(repo, "invoice.txt", "rounds half even\n")
    git(repo, "commit", "-q", "-am", "Later push")
    r = local(repo, note, gate)
    assert r.returncode == 1
    assert "the gate result is for commit %s, not the head" % head in r.stdout
    gate.write_text("commit: %s\nexit: 1\n" % git(repo, "rev-parse", "HEAD").strip(),
                    encoding="utf-8")
    assert "the gate exited 1" in local(repo, note, gate).stdout


def test_local_mode_findings_need_the_owners_tag_on_the_head(branch, tmp_path):
    repo, head, note, gate = branch
    findings = write(tmp_path, "findings.md", "- [x] rename the helper\n- [ ] guard empty "
                                              "invoices\n")
    r = local(repo, note, gate, "--findings", findings, "--owner", "owner@example.com")
    assert r.returncode == 1 and "1 open review finding and not owner-accepted: no tag" \
        in r.stdout
    tag(repo, "worker@example.com")
    r = local(repo, note, gate, "--findings", findings, "--owner", "owner@example.com",
              "--trust-unsigned")
    assert r.returncode == 1 and "was made by <worker@example.com>, not the owner" in r.stdout
    tag(repo, "owner@example.com", "-f")
    r = local(repo, note, gate, "--findings", findings, "--owner", "owner@example.com")
    assert r.returncode == 1 and "no --owner-key given" in r.stdout
    r = local(repo, note, gate, "--findings", findings, "--owner", "owner@example.com",
              "--owner-key", "AB" * 20)
    assert r.returncode == 1 and "has no good signature git can verify" in r.stdout
    r = local(repo, note, gate, "--findings", findings, "--owner", "owner@example.com",
              "--trust-unsigned")
    assert r.returncode == 0, r.stdout


def test_local_mode_git_runs_with_trace2_off(branch, tmp_path):
    """Trace2 targets named by the caller's environment, or by the global git config (read from
    the home), receive nothing while the tag is verified."""
    repo, head, note, gate = branch
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")
    tag(repo, "owner@example.com")
    home = tmp_path / "home"
    traces = tmp_path / "traces"
    traces.mkdir()
    write(home, ".gitconfig", "[trace2]\n" + "".join(
        "\t%sTarget = %s\n" % (kind, (traces / ("%s.log" % kind)).as_posix())
        for kind in ("event", "normal", "perf")))
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
               GIT_TRACE2_EVENT=str(traces / "env-event.json"))
    r = script("handoff_check.py", "--local", repo, "--branch", "worker/issue-7",
               "--gate-result", gate, "--body", note, "--findings", findings, "--owner",
               "owner@example.com", "--owner-key", "AB" * 20, env=env)
    assert r.returncode == 1 and "has no good signature git can verify" in r.stdout, \
        r.stdout + r.stderr
    assert sorted(p.name for p in traces.iterdir()) == []


def test_local_mode_tag_on_an_older_commit_does_not_count(branch, tmp_path):
    repo, head, note, gate = branch
    tag(repo, "owner@example.com")
    write(repo, "invoice.txt", "rounds half even\n")
    git(repo, "commit", "-q", "-am", "Later push")
    new_head = git(repo, "rev-parse", "HEAD").strip()
    gate.write_text("commit: %s\nexit: 0\n" % new_head, encoding="utf-8")
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")
    r = local(repo, note, gate, "--findings", findings, "--owner", "owner@example.com",
              "--trust-unsigned")
    assert r.returncode == 1 and "names %s, not the head" % head[:12] in r.stdout


@pytest.mark.parametrize("message", ["ok", "Findings accepted for #8", "Accepted for #77"])
def test_local_mode_tag_message_must_name_the_issue_the_note_closes(branch, tmp_path, message):
    """The tag binds the owner's acceptance to the work: its message names the issue the handoff
    note closes (#7), so a tag the owner signed for other work does not count here."""
    repo, head, note, gate = branch
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")
    tag(repo, "owner@example.com", message=message)
    r = local(repo, note, gate, "--findings", findings, "--owner", "owner@example.com",
              "--trust-unsigned")
    assert r.returncode == 1, r.stdout
    assert "message does not name #7, the issue the handoff note closes" in r.stdout


def test_local_mode_errors(branch, tmp_path):
    repo, head, note, gate = branch
    r = script("handoff_check.py", "--local", repo, "--branch", "no-such-branch",
               "--gate-result", gate, "--body", note)
    assert r.returncode == 3 and "branch no-such-branch not found" in r.stderr
    r = local(repo, tmp_path / "missing.md", gate)
    assert r.returncode == 2 and "--body" in r.stderr


def test_local_mode_git_not_runnable_is_exit_3_not_a_verdict(branch, tmp_path):
    repo, head, note, gate = branch
    empty = tmp_path / "empty-path"
    empty.mkdir()
    r = script("handoff_check.py", "--local", repo, "--branch", "worker/issue-7",
               "--gate-result", gate, "--body", note, env=dict(os.environ, PATH=str(empty)))
    assert r.returncode == 3 and "git not runnable" in r.stderr, r.stdout + r.stderr


def gpg_path(path, form="-u"):
    """`path` in the form the gpg on PATH reads. Git for Windows ships an MSYS gpg, which takes
    `C:\\...` for a relative path and prepends its working directory; it needs `/c/...`. The
    cygpath beside it converts. A native gpg has no cygpath beside it and gets the path as is.
    `form` "-w" converts back, for a path Python opens."""
    cygpath = Path(shutil.which("gpg")).parent / "cygpath.exe"
    if os.name != "nt" or not cygpath.exists():
        return path
    return subprocess.run([str(cygpath), form, path], capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def gpg_home():
    """A throwaway keyring holding an owner key and a worker key, made at run time. A short path:
    gpg-agent's socket lives in it on some systems, and socket paths are limited in length."""
    if not shutil.which("gpg"):
        pytest.skip("gpg is not installed")
    home = tempfile.mkdtemp(prefix="gpg")
    env = dict(os.environ, GNUPGHOME=gpg_path(home))
    keys = {}
    for who in ("owner", "worker"):
        r = subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
                            "--quick-gen-key", "%s <%s@example.com>" % (who.title(), who),
                            "ed25519", "sign", "never"], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        listing = subprocess.run(["gpg", "--with-colons", "--list-keys", who + "@example.com"],
                                 env=env, capture_output=True, text=True).stdout
        keys[who] = re.search(r"^fpr:+([0-9A-F]{40}):", listing, re.M).group(1)
    yield env, keys
    subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=env, capture_output=True)
    shutil.rmtree(home, ignore_errors=True)


def test_local_mode_acceptance_needs_the_owners_key_not_the_tagger_email(branch, tmp_path,
                                                                          gpg_home):
    """A worker can sign a tag with its own key and name the owner as tagger; `git verify-tag`
    passes for any key in the keyring. Only a signature by --owner-key counts."""
    repo, head, note, gate = branch
    env, keys = gpg_home
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")

    def run(*extra):
        return script("handoff_check.py", "--local", repo, "--branch", "worker/issue-7",
                      "--gate-result", gate, "--body", note, "--findings", findings, "--owner",
                      "owner@example.com", *extra, env=env)

    tag(repo, "owner@example.com", "-s", "-u", keys["worker"], env=env)
    r = run()
    assert r.returncode == 1 and "no --owner-key given" in r.stdout, r.stdout + r.stderr
    r = run("--owner-key", keys["owner"])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "is signed with %s, not the owner's key" % keys["worker"] in r.stdout

    tag(repo, "owner@example.com", "-f", "-s", "-u", keys["owner"], env=env)
    spaced = " ".join(keys["owner"][i:i + 4] for i in range(0, 40, 4)).lower()
    for key in (keys["owner"], spaced):
        r = run("--owner-key", key)
        assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("name, message", [
    ("gate-change-approved/worker/issue-7", "Gate change approved for #7"),
    ("v1", "Release 1, closes #7"),
])
def test_local_mode_an_owner_tag_made_for_something_else_does_not_count(branch, tmp_path,
                                                                        gpg_home, name, message):
    """The owner signs other tags on the same head: a gate-change approval, a release. A worker can
    point the acceptance ref at one of them. The name inside the signed object says what the owner
    signed it for; the ref name does not."""
    repo, head, note, gate = branch
    env, keys = gpg_home
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")
    tag(repo, "owner@example.com", "-s", "-u", keys["owner"], env=env, name=name,
        message=message)
    git(repo, "update-ref", "refs/tags/" + ACCEPT, git(repo, "rev-parse", name).strip())
    r = script("handoff_check.py", "--local", repo, "--branch", "worker/issue-7", "--gate-result",
               gate, "--body", note, "--findings", findings, "--owner", "owner@example.com",
               "--owner-key", keys["owner"], env=env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "tag %s is named %s inside the signed object" % (ACCEPT, name) in r.stdout


def test_local_mode_text_after_the_signature_does_not_name_the_issue(branch, tmp_path, gpg_home):
    """`git verify-tag` still passes when text is appended after the signature block, which the
    signature does not cover. A worker could append `Closes #7` to an owner-signed tag made for
    other work; only the signed part of the message counts."""
    repo, head, note, gate = branch
    env, keys = gpg_home
    tag(repo, "owner@example.com", "-s", "-u", keys["owner"], env=env, message="Accepted")
    raw = subprocess.run(["git", "-C", str(repo), "cat-file", "tag", ACCEPT],
                         capture_output=True).stdout + b"Closes #7\n"
    r = subprocess.run(["git", "-C", str(repo), "hash-object", "-t", "tag", "-w", "--stdin"],
                       input=raw, capture_output=True)
    assert r.returncode == 0, r.stderr
    git(repo, "update-ref", "refs/tags/" + ACCEPT, r.stdout.decode("ascii").strip())
    plain = subprocess.run(["git", "-C", str(repo), "verify-tag", ACCEPT], env=env,
                           capture_output=True, text=True)
    assert plain.returncode == 0, plain.stderr
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")
    r = script("handoff_check.py", "--local", repo, "--branch", "worker/issue-7", "--gate-result",
               gate, "--body", note, "--findings", findings, "--owner", "owner@example.com",
               "--owner-key", keys["owner"], env=env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "message does not name #7, the issue the handoff note closes" in r.stdout


def gpg_signed_tag(repo, head, env, key, *extra):
    """Sign the acceptance tag object with `key` by hand (`extra` passes options to gpg) and
    return `git verify-tag --raw` for it."""
    payload = tag_object(repo, head, "")
    # Bytes, not text: text mode on Windows writes \r\n, and gpg would sign other bytes.
    sign = subprocess.run(["gpg", "--batch", "--armor", "--detach-sign", "-u", key] + list(extra),
                          input=payload.encode("utf-8"), env=env, capture_output=True)
    assert sign.returncode == 0, sign.stderr
    tag_object(repo, head, sign.stdout.decode("ascii"))
    return subprocess.run(["git", "-C", str(repo), "verify-tag", "--raw", ACCEPT], env=env,
                          capture_output=True, text=True)


def owner_key_check(repo, note, gate, tmp_path, env, key):
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")
    return script("handoff_check.py", "--local", repo, "--branch", "worker/issue-7",
                  "--gate-result", gate, "--body", note, "--findings", findings, "--owner",
                  "owner@example.com", "--owner-key", key, env=env)


def test_local_mode_an_expired_owner_key_does_not_count(branch, tmp_path, gpg_home):
    """gpg reports EXPKEYSIG, and still VALIDSIG with the owner's fingerprint, for a signature by
    an expired key. `git verify-tag` exits 1 for it on Linux and macOS but 0 on Git for Windows
    2.56, so the status lines decide, not the exit code."""
    repo, head, note, gate = branch
    env, keys = gpg_home
    then = ["--faked-system-time", "20200101T000000"]
    r = subprocess.run(["gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase",
                        ""] + then + ["--quick-gen-key", "Owner <owner@example.com>", "ed25519",
                                      "sign", "1d"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    listing = subprocess.run(["gpg", "--with-colons", "--list-keys", "owner@example.com"],
                             env=env, capture_output=True, text=True).stdout
    expired = [k for k in re.findall(r"^fpr:+([0-9A-F]{40}):", listing, re.M)
               if k != keys["owner"]][0]
    raw = gpg_signed_tag(repo, head, env, expired, *then)
    assert "] EXPKEYSIG " in raw.stderr and "VALIDSIG " + expired in raw.stderr, raw.stderr
    r = owner_key_check(repo, note, gate, tmp_path, env, expired)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "has no good signature" in r.stdout


def test_local_mode_a_revoked_owner_key_does_not_count(branch, tmp_path, gpg_home):
    """The same for a key revoked after it signed: gpg reports REVKEYSIG and VALIDSIG."""
    repo, head, note, gate = branch
    env, keys = gpg_home
    raw = gpg_signed_tag(repo, head, env, keys["owner"])
    assert raw.returncode == 0 and "] GOODSIG " in raw.stderr, raw.stderr
    # gpg writes a revocation certificate for each key it makes, its armor line commented out.
    cert = Path(gpg_path(env["GNUPGHOME"], "-w"), "openpgp-revocs.d", keys["owner"] + ".rev")
    imported = subprocess.run(["gpg", "--batch", "--import"], env=env, capture_output=True,
                              input=cert.read_bytes().replace(b":-----BEGIN", b"-----BEGIN"))
    assert imported.returncode == 0, imported.stderr
    raw = subprocess.run(["git", "-C", str(repo), "verify-tag", "--raw", ACCEPT], env=env,
                         capture_output=True, text=True)
    assert "] REVKEYSIG " in raw.stderr and "VALIDSIG " + keys["owner"] in raw.stderr, raw.stderr
    r = owner_key_check(repo, note, gate, tmp_path, env, keys["owner"])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "has no good signature" in r.stdout


FPR = "AB" * 20
VALIDSIG = "VALIDSIG %s 2026-10-26 1793044300 0 4 0 22 10 00 %s" % (FPR, FPR)
GOOD = ["NEWSIG", "KEY_CONSIDERED %s 0" % FPR, "GOODSIG %s Owner <owner@example.com>" % FPR[-16:],
        VALIDSIG, "TRUST_ULTIMATE 0 pgp"]


def status(*lines):
    return "".join("[GNUPG:] %s\n" % l for l in lines)


@pytest.mark.parametrize("lines", [
    ["NEWSIG", "KEYEXPIRED 1577923200", "EXPKEYSIG %s Owner" % FPR[-16:], VALIDSIG],
    ["NEWSIG", "EXPSIG %s Owner" % FPR[-16:], VALIDSIG],
    ["NEWSIG", "REVKEYSIG %s Owner" % FPR[-16:], VALIDSIG, "KEYREVOKED"],
    ["NEWSIG", "BADSIG %s Owner" % FPR[-16:]],
    ["NEWSIG", "BADSIG %s Owner" % FPR[-16:], VALIDSIG],
    ["NEWSIG", "ERRSIG %s 22 10 00 1793044300 9 %s" % (FPR[-16:], FPR), "NO_PUBKEY " + FPR[-16:]],
    ["NEWSIG", "GOODSIG %s Owner" % FPR[-16:]],
    ["NEWSIG", VALIDSIG, "TRUST_ULTIMATE 0 pgp"],
    ["NEWSIG", "GOODSIG %s Owner" % FPR[-16:], "EXPKEYSIG %s Owner" % FPR[-16:], VALIDSIG],
    GOOD + ["NEWSIG", "EXPKEYSIG %s Owner" % FPR[-16:], VALIDSIG],
    GOOD + ["NEWSIG"],
    GOOD + [VALIDSIG],
    [],
], ids=["EXPKEYSIG", "EXPSIG", "REVKEYSIG", "BADSIG", "BADSIG+VALIDSIG", "ERRSIG",
        "GOODSIG alone", "VALIDSIG alone", "GOODSIG+EXPKEYSIG", "a second signature",
        "a second NEWSIG", "two VALIDSIG", "no status"])
def test_only_goodsig_with_validsig_counts_whatever_git_exits(monkeypatch, lines):
    """Git for Windows 2.56 exits 0 for some signatures gpg does not call good, so the status
    lines decide: one signature, GOODSIG and VALIDSIG, nothing else."""
    def verify_tag(args, **kw):
        return subprocess.CompletedProcess(args, 0, "", status(*lines))
    monkeypatch.setattr(handoff.subprocess, "run", verify_tag)
    assert handoff.signing_keys("repo", "oid") == set()


def test_a_good_signature_counts_only_when_git_also_exits_0(monkeypatch):
    for code, keys in ((0, {FPR}), (1, set())):
        monkeypatch.setattr(handoff.subprocess, "run", lambda args, code=code, **kw:
                            subprocess.CompletedProcess(args, code, "", status(*GOOD)))
        assert handoff.signing_keys("repo", "oid") == keys


def forging_gpg(tmp_path, key):
    """A stand-in signing program that reports a good signature by `key` for anything. It reads
    the payload git writes to it first: if it exits before git has written, git fails with EPIPE
    and the tag does not verify (seen on CI with git 2.34)."""
    fake = write(tmp_path, "fake-gpg", "#!/bin/sh\ncat >/dev/null\necho '[GNUPG:] NEWSIG'\n"
                 "echo '[GNUPG:] GOODSIG %s Owner'\n"
                 "echo '[GNUPG:] VALIDSIG %s 2026-10-23 0 0 4 0 22 10 00 %s'\n" % (
                     key[-16:], key, key))
    fake.chmod(0o755)
    return fake


@pytest.mark.skipif(os.name == "nt", reason="the stand-in signer is a shell script")
def test_local_mode_ignores_an_x509_program_set_in_the_checkout(branch, tmp_path):
    """The same for gpg.x509.program, which git runs for a tag whose signature block is X.509."""
    repo, head, note, gate = branch
    owner_key = "AB" * 20
    tag_object(repo, head, "-----BEGIN SIGNED MESSAGE-----\nMIAGCSqGSIb3DQEHAqCAMIACAQEx\n"
                           "-----END SIGNED MESSAGE-----\n")
    git(repo, "config", "gpg.x509.program", str(forging_gpg(tmp_path, owner_key)))
    forged = subprocess.run(["git", "-C", str(repo), "verify-tag", "--raw", ACCEPT],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert forged.returncode == 0 and "VALIDSIG " + owner_key in forged.stderr, forged.stderr
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")
    r = local(repo, note, gate, "--findings", findings, "--owner", "owner@example.com",
              "--owner-key", owner_key)
    assert r.returncode == 1 and "has no good signature git can verify" in r.stdout, r.stdout


@pytest.mark.skipif(os.name == "nt", reason="the stand-in signer is a shell script")
def test_local_mode_ignores_a_signing_program_set_in_the_checkout(branch, tmp_path, gpg_home):
    """Worker worktrees share the checkout's config. A gpg.program there that always reports the
    owner's key must not be the one that verifies the tag."""
    repo, head, note, gate = branch
    env, keys = gpg_home
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")
    tag(repo, "owner@example.com", "-s", "-u", keys["worker"], env=env)
    fake = forging_gpg(tmp_path, keys["owner"])
    for name in ("gpg.program", "gpg.openpgp.program"):
        git(repo, "config", name, str(fake))
    forged = subprocess.run(["git", "-C", str(repo), "verify-tag", "--raw",
                             "findings-accepted/worker/issue-7"], env=env, capture_output=True,
                            stdin=subprocess.DEVNULL, text=True)
    assert forged.returncode == 0 and "VALIDSIG " + keys["owner"] in forged.stderr
    r = script("handoff_check.py", "--local", repo, "--branch", "worker/issue-7", "--gate-result",
               gate, "--body", note, "--findings", findings, "--owner", "owner@example.com",
               "--owner-key", keys["owner"], env=env)
    assert r.returncode == 1 and "not the owner's key" in r.stdout, r.stdout + r.stderr


@pytest.fixture
def ssh_signing(branch, tmp_path):
    """Owner and worker SSH keys made at run time, both mapped to the owner's email in the
    allowed-signers file the checkout's config names, and a run of the check with the owner's
    key fingerprint as --owner-key."""
    if not shutil.which("ssh-keygen"):
        pytest.skip("ssh-keygen is not installed")
    repo, head, note, gate = branch
    keys, signers = {}, []
    for who in ("owner", "worker"):
        path = tmp_path / ("%s_key" % who)
        r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", who, "-f",
                            str(path)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        keys[who] = path
        public = path.with_name(path.name + ".pub").read_text(encoding="utf-8").split()
        signers.append("owner@example.com %s %s" % (public[0], public[1]))
    allowed = write(tmp_path, "allowed_signers", "\n".join(signers) + "\n")
    git(repo, "config", "gpg.ssh.allowedSignersFile", str(allowed))
    git(repo, "config", "gpg.format", "ssh")
    owner_fpr = subprocess.run(["ssh-keygen", "-lf", str(keys["owner"]) + ".pub"],
                               capture_output=True, text=True).stdout.split()[1]
    findings = write(tmp_path, "findings.md", "- [ ] guard empty invoices\n")

    def signed(who, *extra):
        git(repo, "config", "user.signingkey", str(keys[who]))
        tag(repo, "owner@example.com", *extra, "-s")

    def check():
        return script("handoff_check.py", "--local", repo, "--branch", "worker/issue-7",
                      "--gate-result", gate, "--body", note, "--findings", findings, "--owner",
                      "owner@example.com", "--owner-key", owner_fpr)
    return repo, owner_fpr, signed, check


def test_local_mode_ssh_signed_acceptance(ssh_signing):
    """The same rule for SSH signatures: the key's SHA256 fingerprint, not the allowed-signers
    principal, which the checkout's config names."""
    repo, owner_fpr, signed, check = ssh_signing
    signed("worker")
    r = check()
    assert r.returncode == 1 and "not the owner's key" in r.stdout, r.stdout + r.stderr
    signed("owner", "-f")
    r = check()
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(os.name == "nt", reason="the stand-in signer is a shell script")
def test_local_mode_ignores_an_ssh_program_set_in_the_checkout(ssh_signing, tmp_path):
    """A gpg.ssh.program in the checkout that reports the owner's key for a worker-signed tag."""
    repo, owner_fpr, signed, check = ssh_signing
    signed("worker")
    fake = write(tmp_path, "fake-ssh-keygen", "#!/bin/sh\ncat >/dev/null\necho 'Good \"git\" "
                 "signature for owner@example.com with ED25519 key %s'\n" % owner_fpr)
    fake.chmod(0o755)
    git(repo, "config", "gpg.ssh.program", str(fake))
    forged = subprocess.run(["git", "-C", str(repo), "verify-tag", "--raw", ACCEPT],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert forged.returncode == 0 and owner_fpr in forged.stdout + forged.stderr, forged.stderr
    r = check()
    assert r.returncode == 1 and "not the owner's key" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("extra", [
    ["--owner-key", "not-a-key"],
    ["--owner-key", "AB" * 20, "--trust-unsigned"],
])
def test_local_mode_owner_key_usage_errors(branch, extra):
    repo, head, note, gate = branch
    assert local(repo, note, gate, *extra).returncode == 2


# Issue bodies are untrusted. Before the fix each of these took over 5 s on 64 KB: REF retried
# `[\w.-]+/` from every letter of a long word, and LABEL's lazy run and its trailing `[*_]*` could
# split a run of underscores many ways. A child process with a timeout keeps a regression from
# hanging the suite.
@pytest.mark.parametrize("call", [
    "s.REF.search('a' * 200000)",
    "s.REF.search('a' * 100000 + '/' + 'a' * 100000)",
    "s.LABEL.match('a' + '_' * 200000)",
    "s.unread_dependencies('Dependencies: ' + 'a' * 200000)",
    "s.unread_dependencies('Dependencies: #1\\n- a' + '_' * 200000)",
    # The key's start: the leading run and the space after the key's prefix both took spaces,
    # `*` and `_`, and the value's lazy run retried `[ \t]*$` at every space.
    "s.read_dependencies('_' * 200000 + 'x')",
    "s.read_dependencies(' ' * 200000 + 'x')",
    "s.read_dependencies('_*' * 100000 + 'x')",
    "s.read_dependencies('+' + ' ' * 200000 + 'x')",
    "s.read_dependencies('[ ]' + ' ' * 200000 + 'x')",
    "s.read_dependencies('Dependencies' + ' ' * 200000 + 'x')",
    "s.read_dependencies('Dependencies: a' + ' ' * 200000 + 'b')",
])
def test_select_patterns_stay_fast_on_hostile_issue_bodies(call):
    code = ("import importlib.util; spec = importlib.util.spec_from_file_location('s', %r); "
            "s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s); %s"
            % (str(SCRIPTS / "select.py"), call))
    subprocess.run([sys.executable, "-c", code], check=True, timeout=5)


@pytest.mark.parametrize("body, lines, keys", [
    ("Dependencies: #1  ", ["#1"], []),
    ("> - [x] ## **Dependencies**: #2\t", ["#2"], []),
    ("1. [ ] Dependencies:** _#3_", ["_#3_"], []),
    ("\ufeff  __Dependencies__ \n- #4\n- #5", ["#4", "#5"], []),
    ("## Dependencies\n#6\n## Next\n#7", ["#6"], []),
    ("+ \u00a0Dependencies: #8", ["#8"], []),
    ("Dependencies:*  ** #10 ", ["** #10"], []),
    ("#  \t*Dependencies*: none", ["none"], []),
    ("- [ ]\u00a0Dependencies: #9", [], ["- [ ]\u00a0Dependencies: #9"]),
    ("Dependencies (blocking): #1", [], ["Dependencies (blocking): #1"]),
    ("\u2022 Dependency: #2", [], ["\u2022 Dependency: #2"]),
    ("Dependencies", [], ["Dependencies"]),
    ("1234567890. Dependencies: #1", [], []),
])
def test_dependency_keys_still_read_the_same(body, lines, keys):
    assert selector.read_dependencies(body) == (lines, keys)


@pytest.mark.parametrize("item, end", [
    ("Hard: #1", 5), ("**Hard**: #1", 9), ("Soft_*: x", 7), ("a__*_: x", 6), ("Hard*_*:", 8),
    ("Hard (later): #2", 13), ("see https://example.com", None), ("1st: x", None), ("a*b:", None),
])
def test_label_still_ends_at_the_first_colon(item, end):
    m = selector.LABEL.match(item)
    assert (m.end() if m else None) == end


@pytest.mark.parametrize("text, found", [
    ("#12", [(None, "12", None, None)]),
    ("owner/app#7 and #8", [("owner/app", "7", None, None), (None, "8", None, None)]),
    ("x.y/a-b/c#3", [("a-b/c", "3", None, None)]),
    ("word#4", [(None, "4", None, None)]),
    ("https://example.com/owner/app/issues/9", [(None, None, "owner/app", "9")]),
    ("a/b #5", [(None, "5", None, None)]),
    ("no reference here / at all", []),
])
def test_ref_still_finds_the_same_references(text, found):
    assert [m.groups() for m in selector.REF.finditer(text)] == found
