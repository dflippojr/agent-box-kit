"""box-audit's workflow reader (collect.parse_workflow) against a real YAML parser. The script is
stdlib-only and line-based, so these tests hold it to PyYAML's reading of the triggers and job
names: for this repo's workflows, box-bootstrap's workflow templates and a synthetic corpus
(tests/fixtures/box_audit/workflows), and for each of them re-indented by 2, 4 and 8 spaces."""
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "box" / "skills" / "box-audit" / "scripts"))

import collect  # noqa: E402

CORPUS = sorted(
    list((ROOT / ".github" / "workflows").glob("*.yml")) +
    [ROOT / "box" / "skills" / "box-bootstrap" / "templates" / "github" / name
     for name in ("gate.yml", "pr-checks.yml")] +
    list((ROOT / "tests" / "fixtures" / "box_audit" / "workflows").glob("*.yml")))


def text_of(path):
    # The bootstrap fills its placeholders before the workflow is used; `@` cannot start a YAML
    # scalar, so the template does not parse until then.
    return path.read_text(encoding="utf-8").replace("@@DEFAULT_BRANCH@@", "main")


def yaml_facts(text):
    """Triggers (sorted) and job names (in order) as a YAML parser reads them. YAML 1.1 reads a
    bare `on` key as true, which is how PyYAML returns it."""
    data = yaml.safe_load(text)
    on = data.get("on", data.get(True))
    if isinstance(on, str):
        on = [on]
    return sorted(on or []), list(data.get("jobs") or {})


def line_facts(text):
    facts = collect.parse_workflow(text)
    return facts["triggers"], facts["jobs"]


def reindent(text, width):
    """The same YAML with each nesting level `width` spaces deep. A line deeper than the one
    above opens a level; a `- ` entry opens one for the keys after it, which sit at its
    content's column. Block scalar bodies keep their lines but not their inner spacing."""
    out, stack = [], [(0, 0)]  # (old column, new column)
    for line in text.splitlines():
        body = line.lstrip(" ")
        if not body:
            out.append("")
            continue
        old = len(line) - len(body)
        if body.startswith("#"):
            # A comment, or a `#` line in a block scalar: it moves with the level it sits in,
            # and opens or closes none.
            col, new = next(e for e in reversed(stack) if e[0] <= old)
            out.append(" " * (new + old - col) + body)
            continue
        while stack[-1][0] > old:
            stack.pop()
        if stack[-1][0] < old:
            stack.append((old, stack[-1][1] + width))
        new = stack[-1][1]
        out.append(" " * new + body)
        dash = re.match(r"-( +)", body)
        if dash:
            stack.append((old + 1 + len(dash.group(1)), new + 1 + len(dash.group(1))))
    return "\n".join(out) + "\n"


def run_pairs(text):
    return [(job, cmd) for _, job, cmd in collect.parse_workflow(text)["runs"]]


def test_the_corpus_covers_the_cases_the_issue_names():
    names = {p.name for p in CORPUS}
    assert {"tests.yml", "sonar.yml", "gate.yml", "pr-checks.yml", "indent4.yml", "indent8.yml",
            "quoted_keys.yml", "flow_on.yml", "on_mapping_filters.yml",
            "block_run.yml"} <= names


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_triggers_and_jobs_match_a_yaml_parser(path):
    text = text_of(path)
    triggers, jobs = yaml_facts(text)
    assert triggers and jobs, "a corpus file with no triggers or jobs tests nothing"
    assert line_facts(text) == (triggers, jobs)


@pytest.mark.parametrize("width", [2, 4, 8])
@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_reindenting_leaves_the_facts_unchanged(path, width):
    text = text_of(path)
    moved = reindent(text, width)
    # The re-indented file is the same workflow to a YAML parser, so the property is not vacuous.
    assert yaml_facts(moved) == yaml_facts(text)
    assert line_facts(moved) == line_facts(text)
    assert run_pairs(moved) == run_pairs(text)


PROBE = """\
name: ci
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
"""


@pytest.mark.parametrize("text, triggers", [
    (PROBE, ["pull_request", "push"]),
    (reindent(PROBE, 4), ["pull_request", "push"]),
    (PROBE.replace("  test:", '  "test":').replace("  push:\n  pull_request:\n", "  push:\n"),
     ["push"]),
    ("name: ci\non: push, pull_request\njobs:\n    test:\n        steps:\n"
     "            - run: pytest\n", ["pull_request", "push"]),
], ids=["2-space", "4-space", "quoted-job-key", "4-space-flow-on"])
def test_the_issues_probe_inputs(text, triggers):
    f = collect.parse_workflow(text)
    assert f["triggers"] == triggers
    assert f["jobs"] == ["test"]
    assert [job for _, job, cmd in f["runs"] if cmd == "pytest"] == ["test"]
