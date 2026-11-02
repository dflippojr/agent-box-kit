"""Tests for the box-audit skill's scripts (box/skills/box-audit/scripts). Collectors run on real
git repositories built in temp folders. Host collectors read invented responses shaped like
GitHub's (tests/fixtures/box_audit, see its README). Judges are small Python programs standing in
for an agent CLI: they read the prompt on stdin like one, so the launcher and its isolation are
tested as they run, not mocked."""
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from conftest import git, run, write
from test_box_standard import overall as standard_overall

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "box" / "skills" / "box-audit"
SCRIPTS = SKILL / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "box_audit"
sys.path.insert(0, str(SCRIPTS))

import audit  # noqa: E402
import card  # noqa: E402
import collect  # noqa: E402
import file_issues  # noqa: E402
import judge  # noqa: E402

MARKER = "BOX_AUDIT_TEST_INSTRUCTIONS.md"


def script(name, *args, cwd=None, env=None):
    return subprocess.run([sys.executable, str(SCRIPTS / name)] + [str(a) for a in args],
                          cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


WORKFLOW = """\
name: ci
on:
  pull_request:
  push:
    branches: [main]
  schedule:
    - cron: "0 3 * * *"
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        include:
          - {os: ubuntu-latest, python: "3.12"}
    services:
      db:
        image: postgres:16
    steps:
      - uses: actions/checkout@v4
      - run: make check
      - name: scan
        if: secrets.SCAN_TOKEN != ''
        run: |
          scanner --all || true
      - run: gh issue create --title nightly-failed
"""


@pytest.fixture
def box_repo(repo):
    """A small repo with one of each thing the collectors look for, and a fix history."""
    write(repo, ".github/workflows/ci.yml", WORKFLOW)
    write(repo, ".github/workflows/deploy.yml", "on:\n  push:\njobs:\n  ship:\n    runs-on: x\n"
                                                "    steps:\n      - run: ./deploy.sh\n")
    write(repo, ".github/pull_request_template.md", "## Proof\n\n### Not verified\n\nCloses #\n")
    write(repo, "Makefile", "check:\n\tpytest\n\nbuild:\n\techo\n")
    write(repo, "AGENTS.md", "# Agents\n\n## Layout\n\nsrc/\n\n## Proving a change\n\n"
                             "Run `make check` and attach its output.\n")
    write(repo, "docs/ui-testing.md", "contract\n")
    write(repo, "docs/architecture.md", "arch\n")
    write(repo, "docker-compose.yml", "services:\n  db:\n    image: postgres:18\n")
    write(repo, "app.py", "ROUTES = ['/healthz']\nimport sentry_sdk\n")
    write(repo, "vendor/lib.js", "x\n")
    write(repo, "finance/reconcile_balances.py", "def run():\n    pass\n")
    write(repo, "scripts/vendor-into-site", "cp -r build \"$1\"\n")
    write(repo, "tests/test_unit.py", "def test_add():\n    assert 1 + 1 == 2\n")
    write(repo, "tests/test_mocked.py", "from unittest.mock import MagicMock\n")
    write(repo, "tests/test_db.py", "import psycopg\n")
    write(repo, "tests/test_props.py", "from hypothesis import given\n")
    write(repo, "tests/golden/expected.json", "{}\n")
    write(repo, "e2e/home.spec.ts", "import { test } from '@playwright/test'\n")
    write(repo, ".github/ISSUE_TEMPLATE/bug.md", "Which PR introduced it?\n")
    commit(repo, "Add the app")
    write(repo, "app.py", "ROUTES = ['/healthz', '/version']\nimport sentry_sdk\n")
    write(repo, "tests/test_unit.py", "def test_add():\n    assert 2 + 2 == 4\n")
    commit(repo, "fix: version route (#2)")
    write(repo, "README.md", "hello again\n")
    commit(repo, "fix: typo in readme")
    git(repo, "revert", "--no-edit", "HEAD")
    git(repo, "branch", "-M", "main")
    return repo


def snapshot(root):
    """Root and every path under it with its size, modification time, file id and link count:
    any write shows up, including one through a hard link and a file created then deleted (its
    folder's time changes), also directly in root."""
    st = os.stat(str(root))
    out = {".": (st.st_size, st.st_mtime_ns, st.st_ino, st.st_nlink)}
    for dirpath, dirnames, filenames in os.walk(str(root)):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            st = os.stat(p)
            out[os.path.relpath(p, str(root))] = (st.st_size, st.st_mtime_ns, st.st_ino,
                                                  st.st_nlink)
    return out


def test_snapshot_sees_a_file_created_and_deleted_in_the_root(repo):
    os.utime(str(repo), (1e9, 1e9))
    before = snapshot(repo)
    (repo / "transient").write_text("x")
    (repo / "transient").unlink()
    assert snapshot(repo) != before


def hard_link(target, at):
    at.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(str(target), str(at))
    except OSError:
        pytest.skip("cannot create a hard link here")


def by_name(evidence):
    return {c["name"]: c for c in evidence["collectors"]}


def claims(collector):
    return "\n".join(i["claim"] for i in collector["items"])


# ----- collect: local evidence ---------------------------------------------------------------

def test_collect_writes_nothing_inside_the_repo(box_repo, tmp_path):
    before = snapshot(box_repo)
    out = tmp_path / "evidence.json"
    r = script("collect.py", box_repo, "--no-remote", "--out", out)
    assert r.returncode == 0, r.stderr
    assert snapshot(box_repo) == before
    assert json.loads(out.read_text(encoding="utf-8"))["collectors"]


def test_collect_refuses_out_inside_repo_and_non_repos(box_repo, tmp_path):
    r = script("collect.py", box_repo, "--no-remote", "--out", box_repo / "evidence.json")
    assert r.returncode == 2 and "outside" in r.stderr
    assert not (box_repo / "evidence.json").exists()
    plain = tmp_path / "plain"
    plain.mkdir()
    assert script("collect.py", plain).returncode == 2
    assert script("collect.py", box_repo, "--remote", "not a slug").returncode == 2


def test_collect_refuses_out_hard_linked_into_the_repo(box_repo, tmp_path):
    out = tmp_path / "evidence.json"
    hard_link(box_repo / "README.md", out)
    before = snapshot(box_repo)
    r = script("collect.py", box_repo, "--no-remote", "--out", out)
    assert r.returncode == 2 and "other hard links" in r.stderr
    assert snapshot(box_repo) == before  # content and link count
    assert (box_repo / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_collect_from_a_subdirectory_covers_and_guards_the_whole_checkout(box_repo, tmp_path):
    before = snapshot(box_repo)
    r = script("collect.py", box_repo / "tests", "--no-remote", "--out", box_repo / "ev.json")
    assert r.returncode == 2 and "outside" in r.stderr
    assert snapshot(box_repo) == before
    out = tmp_path / "evidence.json"
    r = script("collect.py", box_repo / "tests", "--no-remote", "--out", out)
    assert r.returncode == 0, r.stderr
    evidence = json.loads(out.read_text(encoding="utf-8"))
    assert evidence["repo"] == "repo"
    assert "AGENTS.md: " in claims(by_name(evidence)["proof_rules"])


def test_repo_without_remote_still_gets_a_full_report(box_repo):
    ev = collect.collect(box_repo)
    c = by_name(ev)
    assert ev["remote"] is None and ev["host_evidence"] == "unavailable (no remote)"
    for name in ("ci_runs", "merged_prs"):
        assert c[name]["status"] == "unavailable" and c[name]["reason"] == "no remote"
    for name in ("repo", "ci_config", "tests", "oracles", "proof_rules", "production"):
        assert c[name]["status"] == "ok" and c[name]["items"], name
    # Local parts of host collectors are still reported.
    assert "1 reverts" in claims(c["defects"])
    md = collect.render_md(ev)
    assert "## ci_runs (unavailable: no remote)" in md


def test_non_github_remote_is_named_as_the_reason(box_repo):
    git(box_repo, "remote", "add", "origin", "https://gitlab.example.com/team/app.git")
    ev = collect.collect(box_repo)
    assert "not on GitHub" in ev["host_evidence"]


def test_parse_workflow_facts():
    f = collect.parse_workflow(WORKFLOW)
    assert f["triggers"] == ["pull_request", "push", "schedule"]
    assert f["jobs"] == ["test"]
    assert [c for _, _, c in f["runs"]] == ["make check", "scanner --all || true",
                                            "gh issue create --title nightly-failed"]
    assert f["cancel_in_progress"] == [(10, "true")]
    assert f["secret_conditions"] and "SCAN_TOKEN" in f["secret_conditions"][0][1]
    assert f["soft_fail"] and "|| true" in f["soft_fail"][0][1]
    assert f["schedules"] == ["0 3 * * *"] and f["opens_issues"]
    assert ("postgres:16" in [i for _, i in f["images"]])
    assert any("ubuntu-latest" in r for _, r in f["runners"])


@pytest.mark.parametrize("text", [
    "    - run: npm test; exit 0\n",
    "    - run: >+\n        npm test || true\n",
    "    - run: |2\n        npm test || true\n",
    "    - run: >-2  # folded\n        npm test; exit 0\n",
    "    - run: |2-\n        npm test || true\n",
])
def test_parse_workflow_soft_fail_in_any_run_form(text):
    f = collect.parse_workflow("jobs:\n  test:\n    steps:\n" + text)
    command = text.splitlines()[-1].split("run: ")[-1].strip()
    assert [c for _, _, c in f["runs"]] == [command]
    assert [line for _, line in f["soft_fail"]] == [command]


@pytest.mark.parametrize("header", ["|", ">+", "|2", ">-2  # folded", "|2-"])
def test_parse_workflow_block_run_ends_at_sibling_step_keys(header):
    f = collect.parse_workflow("jobs:\n  test:\n    steps:\n    - run: " + header + "\n"
                               "        npm test\n"
                               "      if: secrets.SCAN_TOKEN != ''\n"
                               "      continue-on-error: true\n")
    assert [c for _, _, c in f["runs"]] == ["npm test"]
    assert f["continue_on_error"] == 1
    assert [c for _, c in f["secret_conditions"]] == ["secrets.SCAN_TOKEN != ''"]


@pytest.mark.parametrize("run, flagged", [
    ("npm test; exit 0", True),
    ("npm test # do not add ; exit 0", False),
    ("npm test # never || true", False),
    ("echo '# not a comment' || true", True),
    ("\"npm test # quoted || true\"  # note", False),
    ("'npm test # do not add ; exit 0'", False),
    ("\"npm test # do not add ; exit 0\"", False),
    ("'npm test; exit 0'", True),
    ("\"npm test; exit 0\"", True),
    ("'echo \"# not a comment\" || true'", True),
    ("\"echo '# not a comment' || true\"", True),
    ("'echo ''#'' || true'", True),
    ("echo \\# || true", True),
    ("echo a#b || true", True),
])
def test_parse_workflow_soft_fail_ignores_yaml_comments(run, flagged):
    f = collect.parse_workflow("jobs:\n  test:\n    steps:\n    - run: " + run + "\n")
    assert bool(f["soft_fail"]) == flagged


def test_ci_config_items(box_repo):
    c = by_name(collect.collect(box_repo))["ci_config"]
    text = claims(c)
    assert "cancel-in-progress: true" in text
    assert "may pass green while skipping" in text
    assert "soft-fail command" in text
    assert "local gate candidate `make check`" in text
    assert "make build" not in text
    assert all(i["basis"] == "read" for i in c["items"] if "runs `" in i["claim"])


def test_test_inventory_classifies_by_kind(box_repo):
    c = by_name(collect.collect(box_repo))["tests"]
    assert c["data"]["kinds"] == {"plain unit": 2, "mocked": 1, "real dependency": 1,
                                  "end-to-end": 1}
    images = [img for _, img in c["data"]["images"]]
    assert "postgres:18" in images and "postgres:16" in images


def test_oracles_proof_rules_and_production(box_repo):
    c = by_name(collect.collect(box_repo))
    oracles = claims(c["oracles"])
    assert "property-based tests: tests/test_props.py:1" in oracles
    assert "file names matching golden or recorded data: tests/golden/expected.json" in oracles
    assert "file names matching reconciliation against real data: finance/reconcile_balances.py" \
        in oracles
    proof = claims(c["proof_rules"])
    assert "## Proving a change" in proof and "make check" in proof
    assert "## Layout" not in proof
    assert "docs/ui-testing.md" in proof
    assert "mentions: Proof, Not verified, Closes" in proof
    assert "docs/architecture.md" in proof
    prod = claims(c["production"])
    assert "app.py:1" in prod and "sentry" in prod
    assert "deploy or release workflows: .github/workflows/deploy.yml" in prod
    assert "vendor/" in prod and "deployed service or app" in prod
    assert "into another repo or site: scripts/vendor-into-site" in prod


def test_defects_from_git_history(box_repo):
    c = by_name(collect.collect(box_repo))["defects"]
    assert c["data"] == {"commits": 5, "fixes": 3, "fixes_with_tests": 1, "reverts": 1}
    text = claims(c)
    assert "fix: typo in readme (no test file changed)" in text
    assert "asks which change introduced" in text


def test_agents_md_without_proof_section_is_reported(repo):
    write(repo, "AGENTS.md", "# Agents\n\n## Layout\n\nsrc/\n")
    commit(repo, "agents")
    text = claims(by_name(collect.collect(repo))["proof_rules"])
    assert "no section on proof" in text


def link(target, at):
    """A link at `at` to `target`: a symlink, or on Windows without that privilege a junction."""
    try:
        os.symlink(str(target), str(at), target_is_directory=Path(target).is_dir())
    except OSError:
        if os.name != "nt" or not Path(target).is_dir():
            pytest.skip("cannot create a symlink here")
        import _winapi
        _winapi.CreateJunction(str(target), str(at))


@pytest.fixture
def outside(repo, tmp_path):
    """Owner files outside the checkout, and a repo tracking AGENTS.md and a workflow. A tracked
    path that is, or sits under, a link can point at them; their text must not reach the
    evidence the judge scores."""
    owner_files = tmp_path / "owner-files"
    write(owner_files, "AGENTS.md", "# Mine\n\n## Proof\n\nOUTSIDE_CANARY always watch CI\n")
    write(owner_files, "gh/workflows/ci.yml", "on: push\njobs:\n  t:\n    runs-on: x\n"
                                              "    steps:\n      - run: echo OUTSIDE_CANARY\n")
    write(repo, "AGENTS.md", "# Agents\n\n## Proof\n\nRun the tests.\n")
    write(repo, ".github/workflows/ci.yml", "on: push\n")
    commit(repo, "instructions and ci")
    return owner_files


def test_tracked_paths_under_a_linked_folder_are_not_read(repo, outside):
    (repo / ".github" / "workflows" / "ci.yml").unlink()
    (repo / ".github" / "workflows").rmdir()
    (repo / ".github").rmdir()
    link(outside / "gh", repo / ".github")
    assert collect.read(repo, ".github/workflows/ci.yml") is None
    ev = collect.collect(repo)
    assert "OUTSIDE_CANARY" not in json.dumps(ev) + collect.render_md(ev)
    assert ".github/workflows/ci.yml" in claims(by_name(ev)["repo"])


def test_a_tracked_agents_md_link_is_not_read(repo, outside):
    (repo / "AGENTS.md").unlink()
    link(outside / "AGENTS.md", repo / "AGENTS.md")
    ev = collect.collect(repo)
    assert "OUTSIDE_CANARY" not in json.dumps(ev) + collect.render_md(ev)
    assert "AGENTS.md is a link" in claims(by_name(ev)["proof_rules"])


# ----- collect: host evidence from fixture responses -----------------------------------------

def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_fixtures_are_synthetic():
    """This repository is public: fixtures are invented, never recorded issues, runs or names."""
    files = sorted(p for p in FIXTURES.iterdir() if p.suffix == ".json")
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    assert "invented" in readme and "captured" not in readme.lower()
    ours = {p.name for d in ("agent-ready", "box", "ci", "experiments", "tests")
            for p in (ROOT / d).rglob("*") if p.is_file() and p.suffix in (".py", ".md")}
    remote = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"],
                            capture_output=True, text=True).stdout.strip()
    names = re.split(r"[/:]", re.sub(r"\.git$", "", remote))[-2:] if remote else []
    for path in files:
        assert path.name in readme, path.name
        text = path.read_text(encoding="utf-8")
        for name in ours | set(names):
            assert name not in text, "%s names %s" % (path.name, name)
        # Commit ids are small counters, so none can be a real commit.
        for sha in re.findall(r"\b[0-9a-f]{40}\b", text):
            assert int(sha, 16) < 16 ** 12, "%s has a real-looking commit id" % path.name
        assert not re.search(r"https?://(?!example\.com)", text), path.name
        for slug in re.findall(r'"ruleset_source": "([^"]+)"', text):
            assert slug.startswith("example/"), path.name


def at(hhmm):
    """A GitHub timestamp on the day the merge-time tests merge."""
    return "2026-10-01T%s:00Z" % hhmm


def head_routes(sha, runs=(), statuses=()):
    """What GitHub serves for one commit, built from its full history: every check run with
    filter=all and only the latest run per name without it, every status newest first, and the
    combined status, which holds the latest status per context."""
    checks = "repos/owner/app/commits/%s/check-runs?per_page=100" % sha
    status = "repos/owner/app/commits/%s/status?per_page=100" % sha
    latest = {}
    for r in runs:
        if r["id"] > latest.get(r["name"], {}).get("id", -1):
            latest[r["name"]] = r
    newest_first = sorted(statuses, key=lambda s: (s["created_at"], s["id"]), reverse=True)
    per_context = {}
    for s in newest_first:
        per_context.setdefault(s["context"], s)
    states = [s["state"] for s in per_context.values()]
    combined = ("failure" if {"failure", "error"} & set(states) else
                "pending" if not states or "pending" in states else "success")
    return {checks + "&filter=all": ({"total_count": len(runs), "check_runs": list(runs)}, None),
            checks: ({"total_count": len(latest), "check_runs": list(latest.values())}, None),
            "repos/owner/app/commits/%s/statuses?per_page=100" % sha: (newest_first, None),
            status: ({"state": combined, "statuses": list(per_context.values())}, None)}


def run_of(run_id, conclusion, started, completed, name="gate"):
    return {"id": run_id, "name": name, "status": "completed" if completed else "in_progress",
            "conclusion": conclusion, "started_at": started and at(started),
            "completed_at": completed and at(completed)}


def status_of(status_id, state, created, context="external-ci"):
    return {"id": status_id, "context": context, "state": state, "created_at": at(created)}


def fixture_host(overrides=None):
    """A runner answering `gh api` paths with the fixture responses; unknown paths are a 404."""
    routes = {
        "repos/owner/app": ({"default_branch": "main"}, None),
        "repos/owner/app/rules/branches/main?per_page=100": (fixture("rules_required.json"),
                                                             None),
        "repos/owner/app/rulesets?includes_parents=true&per_page=100": (
            [{"name": "default-branch", "target": "branch", "enforcement": "active"}], None),
        "repos/owner/app/branches/main": ({"protected": False, "protection": {
            "required_status_checks": {"contexts": []}}}, None),
        "repos/owner/app/labels?per_page=100": (fixture("labels.json"), None),
        "repos/owner/app/issues?state=all&per_page=100&labels=bug": (fixture("issues_bug.json"),
                                                                     None),
        "repos/owner/app/pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100": (
            [{"number": 7, "merged_at": at("10:05"), "head": {"sha": "a" * 40},
              "labels": [{"name": "ready"}]},
             {"number": 6, "merged_at": at("09:30"), "head": {"sha": "b" * 40}, "labels": []},
             {"number": 5, "merged_at": None, "head": {"sha": "c" * 40}}], None),
    }
    routes.update(head_routes("a" * 40, runs=[run_of(1, "failure", "09:00", "09:02")]))
    # A rerun that passed before the merge replaces the earlier failure: not merged red.
    routes.update(head_routes("b" * 40, runs=[run_of(11, "failure", "08:00", "08:02"),
                                              run_of(12, "success", "08:10", "08:12")],
                              statuses=[status_of(1, "success", "08:00", context="lint")]))
    runs = fixture("runs.json")
    routes["repos/owner/app/actions/runs?per_page=100&page=1"] = (runs, None)
    routes.update(overrides or {})
    calls = []

    def runner(path):
        calls.append(path)
        return routes.get(path, (None, "HTTP 404"))
    runner.calls = calls
    return runner


HEAD_B_CHECKS = "repos/owner/app/commits/%s/check-runs?per_page=100&filter=all" % ("b" * 40)


ACTIONS = {"id": 15, "slug": "github-actions"}
HEAD_B_WORKFLOWS = "repos/owner/app/actions/runs?head_sha=%s&per_page=100" % ("b" * 40)


def workflow_runs(*pairs):
    """An actions/runs response mapping each (check suite, workflow) pair."""
    return ({"total_count": len(pairs), "workflow_runs": [
        {"id": 900 + i, "check_suite_id": suite, "workflow_id": wf}
        for i, (suite, wf) in enumerate(pairs)]}, None)


def timed(checks):
    """Check runs that all finished before PR #6 merged at 09:30, in id order."""
    return [dict(c, status="completed", started_at=at("08:%02d" % c["id"]),
                 completed_at=at("08:%02d" % c["id"])) for c in checks]


# Equal names from another app or another workflow are separate checks, not reruns of one.
SAME_NAME_CHECKS = timed([
    {"name": "test", "conclusion": "failure", "id": 10, "app": {"id": 1},
     "check_suite": {"id": 30}},
    {"name": "test", "conclusion": "success", "id": 11, "app": {"id": 2},
     "check_suite": {"id": 31}},
    {"name": "lint", "conclusion": "failure", "id": 12, "app": ACTIONS,
     "check_suite": {"id": 32}},
    {"name": "lint", "conclusion": "success", "id": 13, "app": ACTIONS,
     "check_suite": {"id": 33}},
])


def test_same_name_checks_from_other_apps_or_workflows_are_not_reruns(box_repo):
    checks = {HEAD_B_CHECKS: ({"check_runs": SAME_NAME_CHECKS}, None),
              HEAD_B_WORKFLOWS: workflow_runs((32, 501), (33, 502))}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(checks)))["merged_prs"]
    assert merged["data"]["merged_red"] == [7, 6]
    assert "PR #6 merged with non-green checks at its head %s: lint, test" % ("b" * 12) \
        in claims(merged)


# The shape of a label-gated re-judge on a real repo: each labeled or reopened event starts a
# new run of the same workflow on the same head, in a new check suite; cancel-in-progress
# leaves the run it replaced cancelled. Only the latest run of the workflow is its verdict.
REJUDGED_CHECKS = timed([
    {"name": "guard / guard", "conclusion": "success", "id": 25, "app": ACTIONS,
     "check_suite": {"id": 44}},
    {"name": "ci / test", "conclusion": "success", "id": 24, "app": ACTIONS,
     "check_suite": {"id": 43}},
    {"name": "ci / test", "conclusion": "cancelled", "id": 22, "app": ACTIONS,
     "check_suite": {"id": 41}},
    {"name": "guard / guard", "conclusion": "success", "id": 23, "app": ACTIONS,
     "check_suite": {"id": 42}},
    {"name": "guard / guard", "conclusion": "failure", "id": 21, "app": ACTIONS,
     "check_suite": {"id": 40}},
])
REJUDGED_WORKFLOWS = workflow_runs((44, 601), (43, 602), (42, 601), (41, 602), (40, 601))


def test_a_rerun_of_the_same_workflow_in_a_new_suite_is_one_check(box_repo):
    runner = fixture_host({HEAD_B_CHECKS: ({"check_runs": REJUDGED_CHECKS}, None),
                           HEAD_B_WORKFLOWS: REJUDGED_WORKFLOWS})
    merged = by_name(collect.collect(box_repo, slug="owner/app", runner=runner))["merged_prs"]
    assert merged["data"] == {"merged": 2, "merged_red": [7], "checks_unavailable": [],
                              "red_now": [7]}
    assert HEAD_B_WORKFLOWS in runner.calls
    # The latest run is the verdict: a failure after the success is red.
    later = dict(REJUDGED_CHECKS[0], conclusion="failure")
    runner = fixture_host({HEAD_B_CHECKS: ({"check_runs": [later] + REJUDGED_CHECKS[1:]}, None),
                           HEAD_B_WORKFLOWS: REJUDGED_WORKFLOWS})
    merged = by_name(collect.collect(box_repo, slug="owner/app", runner=runner))["merged_prs"]
    assert merged["data"]["merged_red"] == [7, 6]
    assert "PR #6 merged with non-green checks at its head %s: guard / guard" % ("b" * 12) \
        in claims(merged)


def test_a_check_of_another_app_is_keyed_by_name_without_a_workflow_lookup(box_repo):
    """Only GitHub Actions has workflows; another app's suites for one name are one check."""
    other = [dict(c, app={"id": 1}) for c in REJUDGED_CHECKS]
    runner = fixture_host({HEAD_B_CHECKS: ({"check_runs": other}, None)})
    merged = by_name(collect.collect(box_repo, slug="owner/app", runner=runner))["merged_prs"]
    assert merged["data"]["merged_red"] == [7]
    assert not any("head_sha" in p for p in runner.calls)


def test_unknown_workflows_count_red_only_when_every_lineage_would(box_repo):
    """Without the workflow of a suite, a check's latest run across all its workflows decides.
    A failure there is red under any lineage; anything else is unknown, not clean."""
    for workflows, reason in (((None, "HTTP 403"), "#6: actions/runs HTTP 403"),
                              (workflow_runs((44, 601), (43, 602)),
                               "#6: workflow of check suite 40, 41, 42 unknown")):
        runner = fixture_host({HEAD_B_CHECKS: ({"check_runs": REJUDGED_CHECKS}, None),
                               HEAD_B_WORKFLOWS: workflows})
        merged = by_name(collect.collect(box_repo, slug="owner/app",
                                         runner=runner))["merged_prs"]
        assert merged["data"]["merged_red"] == [7]
        assert merged["data"]["checks_unavailable"] == [6]
        assert reason in claims(merged)
    later = dict(REJUDGED_CHECKS[0], conclusion="failure")
    runner = fixture_host({HEAD_B_CHECKS: ({"check_runs": [later] + REJUDGED_CHECKS[1:]}, None),
                           HEAD_B_WORKFLOWS: (None, "HTTP 403")})
    merged = by_name(collect.collect(box_repo, slug="owner/app", runner=runner))["merged_prs"]
    assert merged["data"]["merged_red"] == [7, 6]
    assert merged["data"]["checks_unavailable"] == []


def test_host_collectors_on_fixture_responses(box_repo):
    runner = fixture_host()
    ev = collect.collect(box_repo, slug="owner/app", runner=runner)
    c = by_name(ev)
    assert ev["host_evidence"] == "available" and ev["repo"] == "app"
    prot = claims(c["protection"])
    assert "required checks on main: build, lint / lint (must be up to date with base: no)" in prot
    assert "PR required on main: 0 approvals" in prot
    assert "classic branch protection on main: not enabled" in prot
    assert all(i["basis"] == "verified" for i in c["protection"]["items"])
    runs = c["ci_runs"]
    assert runs["status"] == "ok" and runs["data"]["total"] == 40
    assert "default-branch runs (main)" in claims(runs)
    merged = c["merged_prs"]
    assert merged["data"] == {"merged": 2, "merged_red": [7], "checks_unavailable": [],
                              "red_now": [7]}
    assert "PR #7 merged with non-green checks" in claims(merged)
    defects = c["defects"]
    assert defects["data"]["defect_issues"] == 2 and defects["data"]["traced"] == 0
    # GET only: every call was a read of this repo.
    assert all(p.startswith("repos/owner/app") for p in runner.calls)


def test_no_rules_means_nothing_is_required(box_repo):
    runner = fixture_host({"repos/owner/app/rules/branches/main?per_page=100": ([], None)})
    text = claims(by_name(collect.collect(box_repo, slug="owner/app", runner=runner))
                  ["protection"])
    assert "no ruleset rules and no classic branch protection: nothing is required to merge " \
           "main" in text


def test_host_refusals_are_recorded_not_raised(box_repo):
    runner = fixture_host({
        "repos/owner/app/rules/branches/main?per_page=100": (None, "HTTP 403"),
        "repos/owner/app/branches/main": (None, "HTTP 403"),
        "repos/owner/app/actions/runs?per_page=100&page=1": (None, "HTTP 403"),
    })
    c = by_name(collect.collect(box_repo, slug="owner/app", runner=runner))
    assert c["protection"]["status"] == "unavailable"
    assert "unavailable: HTTP 403" in claims(c["protection"])
    assert c["ci_runs"]["status"] == "unavailable" and "403" in c["ci_runs"]["reason"]


def test_no_rulesets_is_not_no_protection(box_repo):
    """The rules endpoint covers rulesets only; classic protection can still require checks."""
    no_rules = {"repos/owner/app/rules/branches/main?per_page=100": ([], None)}
    classic = dict(no_rules, **{"repos/owner/app/branches/main": (
        {"protected": True, "protection": {"required_status_checks": {"contexts": ["gate"]}}},
        None)})
    text = claims(by_name(collect.collect(box_repo, slug="owner/app",
                                          runner=fixture_host(classic)))["protection"])
    assert "nothing is required" not in text
    assert "classic branch protection on main: enabled; required checks gate" in text
    refused = dict(no_rules, **{"repos/owner/app/branches/main": (None, "HTTP 403")})
    text = claims(by_name(collect.collect(box_repo, slug="owner/app",
                                          runner=fixture_host(refused)))["protection"])
    assert "nothing is required" not in text
    assert "classic branch protection on main unavailable: HTTP 403" in text
    assert "unknown" in text


def test_unreadable_head_checks_are_not_counted_clean(box_repo):
    checks = "repos/owner/app/commits/%s/check-runs?per_page=100&filter=all"
    refused = {checks % ("a" * 40): (None, "HTTP 403"), checks % ("b" * 40): (None, "HTTP 403")}
    c = by_name(collect.collect(box_repo, slug="owner/app", runner=fixture_host(refused)))
    merged = c["merged_prs"]
    assert merged["status"] == "unavailable" and "403" in merged["reason"]
    assert "0 of" not in claims(merged)
    one = {checks % ("b" * 40): (None, "HTTP 403")}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(one)))["merged_prs"]
    assert merged["status"] == "ok"
    assert merged["data"]["checks_unavailable"] == [6] and merged["data"]["merged_red"] == [7]
    text = claims(merged)
    assert "1 of 1 merged PRs whose merge verdict could be read" in text
    assert "#6: check-runs HTTP 403" in text


HEAD_B_STATUSES = "repos/owner/app/commits/%s/statuses?per_page=100" % ("b" * 40)


def test_failing_commit_status_marks_a_merged_pr_red(box_repo):
    """Status-based CI posts commit statuses, not check runs; a failing one is a red merge."""
    for state in ("failure", "error"):
        failing = {HEAD_B_STATUSES: ([status_of(2, state, "09:00"),
                                      status_of(1, "success", "08:00", context="lint")], None)}
        merged = by_name(collect.collect(box_repo, slug="owner/app",
                                         runner=fixture_host(failing)))["merged_prs"]
        assert merged["data"]["merged_red"] == [7, 6]
        text = claims(merged)
        assert "PR #6 merged with non-green checks at its head %s: external-ci" % ("b" * 12) in text
        assert "2 of 2 merged PRs" in text
    pending = {HEAD_B_STATUSES: ([status_of(1, "pending", "09:00")], None)}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(pending)))["merged_prs"]
    assert merged["data"]["merged_red"] == [7]


def test_unreadable_commit_status_is_not_counted_clean(box_repo):
    statuses = "repos/owner/app/commits/%s/statuses?per_page=100"
    one = {statuses % ("b" * 40): (None, "HTTP 403")}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(one)))["merged_prs"]
    assert merged["status"] == "ok"
    assert merged["data"]["checks_unavailable"] == [6] and merged["data"]["merged_red"] == [7]
    text = claims(merged)
    assert "1 of 1 merged PRs whose merge verdict could be read" in text
    assert "#6: statuses HTTP 403" in text
    # A failure already seen in the check runs is red whatever the statuses say.
    both = dict(one, **{statuses % ("a" * 40): (None, "HTTP 403")})
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(both)))["merged_prs"]
    assert merged["status"] == "ok" and merged["data"]["merged_red"] == [7]
    assert merged["data"]["checks_unavailable"] == [6]


def passing_checks(n):
    return [run_of(i, "success", "08:00", "08:02", name="test (%d)" % i) for i in range(n)]


def passing_statuses(n, created="08:00"):
    return [status_of(i, "success", created, context="ci/%d" % i) for i in range(n)]


def test_a_failure_on_a_later_page_marks_a_merged_pr_red(box_repo):
    """Heads with more than 100 check runs or statuses are read to the last page."""
    checks = {HEAD_B_CHECKS: ({"total_count": 101, "check_runs": passing_checks(100)}, None),
              HEAD_B_CHECKS + "&page=2": ({"total_count": 101, "check_runs": [
                  run_of(100, "failure", "08:00", "08:02", name="test (100)")]}, None)}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(checks)))["merged_prs"]
    assert merged["data"]["merged_red"] == [7, 6]
    assert "PR #6 merged with non-green checks at its head %s: test (100)" % ("b" * 12) \
        in claims(merged)
    # Newest first, so the older failure is on the second page.
    statuses = {HEAD_B_STATUSES: (passing_statuses(100), None),
                HEAD_B_STATUSES + "&page=2": ([status_of(100, "failure", "07:00")], None)}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(statuses)))["merged_prs"]
    assert merged["data"]["merged_red"] == [7, 6]
    assert "PR #6 merged with non-green checks at its head %s: external-ci" % ("b" * 12) \
        in claims(merged)


def test_a_status_red_on_a_read_page_is_red_when_later_pages_were_not_read(box_repo):
    """Statuses come newest first, so a context's latest status before the merge on a page
    that was read is its verdict: the pages not read hold only older ones."""
    statuses = {HEAD_B_STATUSES: (passing_statuses(99) + [status_of(100, "failure", "09:00")],
                                  None),
                HEAD_B_STATUSES + "&page=2": (None, "HTTP 403")}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(statuses)))["merged_prs"]
    assert merged["data"]["merged_red"] == [7, 6]
    assert merged["data"]["checks_unavailable"] == []
    assert "PR #6 merged with non-green checks at its head %s: external-ci" % ("b" * 12) \
        in claims(merged)


def test_an_unread_later_page_is_not_counted_clean(box_repo):
    checks = {HEAD_B_CHECKS: ({"total_count": 101, "check_runs": passing_checks(100)}, None),
              HEAD_B_CHECKS + "&page=2": (None, "HTTP 403")}
    statuses = {HEAD_B_STATUSES: (passing_statuses(100), None),
                HEAD_B_STATUSES + "&page=2": (None, "HTTP 403")}
    for refused, reason in ((checks, "#6: check-runs page 2 HTTP 403"),
                            (statuses, "#6: statuses page 2 HTTP 403")):
        merged = by_name(collect.collect(box_repo, slug="owner/app",
                                         runner=fixture_host(refused)))["merged_prs"]
        assert merged["data"]["merged_red"] == [7]
        assert merged["data"]["checks_unavailable"] == [6]
        text = claims(merged)
        assert "1 of 1 merged PRs whose merge verdict could be read" in text
        assert reason in text


def test_a_head_past_the_page_bound_is_not_counted_clean(box_repo, monkeypatch):
    monkeypatch.setattr(collect, "MAX_PAGES", 1)
    checks = {HEAD_B_CHECKS: ({"total_count": 101, "check_runs": passing_checks(100)}, None)}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(checks)))["merged_prs"]
    assert merged["data"]["checks_unavailable"] == [6]
    assert "#6: check-runs stopped after 1 page at 100 of 101" in claims(merged)



def ten_full_pages_then(last):
    """A runner for a list without a total: ten pages of 100, a page of `last`, then nothing,
    and the pages it was asked for."""
    calls = []

    def run(path):
        m = re.search(r"&page=(\d+)$", path)
        n = int(m.group(1)) if m else 1
        calls.append(n)
        return [{"n": n}] * (100 if n <= 10 else last if n == 11 else 0), None
    run.calls = calls
    return run


def test_exactly_ten_full_pages_without_a_total_is_a_complete_list():
    """Issue #64: 1000 entries, page 11 empty, is read whole, not cut short."""
    run = ten_full_pages_then(0)
    entries, _, error = collect.Host("owner/app", runner=run).get_all("{repo}/x?per_page=100")
    assert (len(entries), error) == (1000, None)
    assert run.calls == list(range(1, 12))


def test_more_than_ten_full_pages_without_a_total_is_incomplete():
    entries, _, error = collect.Host("owner/app", runner=ten_full_pages_then(1)).get_all(
        "{repo}/x?per_page=100")
    assert len(entries) == 1000
    assert error == "stopped after 10 pages at 1000 of None"


RULES = "repos/owner/app/rules/branches/main?per_page=100"
PULLS = "repos/owner/app/pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100"
LABELS = "repos/owner/app/labels?per_page=100"
BUG_ISSUES = "repos/owner/app/issues?state=all&per_page=100&labels=bug"
RUNS = "repos/owner/app/actions/runs?per_page=100&page=%d"


def merged_at_ten_past(repo, runs=(), statuses=()):
    """PR #6 alone, merged at 10:05 with head b, judged from that head's full history."""
    routes = head_routes("b" * 40, runs, statuses)
    routes[PULLS] = ([{"number": 6, "merged_at": at("10:05"), "head": {"sha": "b" * 40}}], None)
    return by_name(collect.collect(repo, slug="owner/app",
                                   runner=fixture_host(routes)))["merged_prs"]


def test_a_green_merge_that_fails_a_later_rerun_is_not_merged_red(box_repo):
    """Issue #38: the merge was green; a rerun after it changes the head, not the merge."""
    merged = merged_at_ten_past(box_repo, runs=[run_of(11, "success", "10:00", "10:02"),
                                                run_of(12, "failure", "11:00", "11:04")])
    assert merged["data"]["merged_red"] == [] and merged["data"]["checks_unavailable"] == []
    assert merged["data"]["red_now"] == [6]
    text = claims(merged)
    assert "0 of 1 merged PRs" in text and "merged with non-green" not in text
    assert "now" in text and "#6" in text


def test_a_red_merge_that_passes_a_later_rerun_stays_merged_red(box_repo):
    merged = merged_at_ten_past(box_repo, runs=[run_of(11, "failure", "10:00", "10:02"),
                                                run_of(12, "success", "11:00", "11:04")])
    assert merged["data"]["merged_red"] == [6] and merged["data"]["red_now"] == []
    assert "PR #6 merged with non-green checks at its head %s: gate" % ("b" * 12) \
        in claims(merged)


@pytest.mark.parametrize("older,newer,red", [("failure", "success", []),
                                             ("success", "failure", [6])])
def test_the_newest_run_started_by_the_merge_is_its_verdict_whatever_the_start_order(
        box_repo, older, newer, red):
    """PR #54 review: overlapping runs can start out of creation order. Run 12 is the newer
    run though it started first, so it is the check's verdict at the merge, as it is now."""
    runs = [dict(run_of(11, older, "10:03", "10:04"), check_suite={"id": 40}),
            dict(run_of(12, newer, "10:00", "10:02"), check_suite={"id": 41})]
    merged = merged_at_ten_past(box_repo, runs=runs)
    assert merged["data"]["merged_red"] == red and merged["data"]["red_now"] == red


def test_status_ci_is_judged_as_of_the_merge(box_repo):
    """The same two cases for status-based CI: commit statuses, not check runs."""
    merged = merged_at_ten_past(box_repo, statuses=[status_of(1, "success", "10:00"),
                                          status_of(2, "failure", "11:00")])
    assert merged["data"]["merged_red"] == [] and merged["data"]["red_now"] == [6]
    merged = merged_at_ten_past(box_repo, statuses=[status_of(1, "error", "10:00"),
                                          status_of(2, "success", "11:00")])
    assert merged["data"]["merged_red"] == [6] and merged["data"]["red_now"] == []
    assert "PR #6 merged with non-green checks at its head %s: external-ci" % ("b" * 12) \
        in claims(merged)


def test_runs_that_were_not_finished_or_not_started_at_the_merge_are_not_its_verdict(
        box_repo):
    # Still running at 10:05, failed at 10:08: pending at the merge, not red.
    merged = merged_at_ten_past(box_repo, runs=[run_of(11, "failure", "10:00", "10:08")])
    assert merged["data"]["merged_red"] == [] and merged["data"]["checks_unavailable"] == []
    # A check that first ran after the merge was not part of it.
    late = run_of(12, "failure", "10:30", "10:32", name="late")
    merged = merged_at_ten_past(box_repo, runs=[run_of(11, "success", "10:00", "10:02"), late])
    assert merged["data"]["merged_red"] == [] and merged["data"]["red_now"] == [6]


def test_a_merge_verdict_without_run_times_is_unknown(box_repo):
    """No timestamps means no history to place the merge in: unknown, not clean."""
    for runs in ([run_of(11, "success", None, None)],
                 [dict(run_of(11, "success", "10:00", "10:02"), completed_at=None)]):
        merged = merged_at_ten_past(box_repo, runs=runs)
        assert merged["status"] == "unavailable"
        assert "gate" in merged["reason"] and "time" in merged["reason"]
    status = dict(status_of(1, "success", "10:00"), created_at=None)
    merged = merged_at_ten_past(box_repo, statuses=[status])
    assert merged["status"] == "unavailable" and "external-ci" in merged["reason"]


def test_a_current_failure_is_kept_when_the_merge_verdict_is_unknown(box_repo):
    """PR #41 review: an untimed older run leaves the merge unknown, but the latest run is
    timed and failed, so the head is red now whatever happened at the merge."""
    merged = merged_at_ten_past(box_repo, runs=[run_of(1, "success", None, None),
                                                run_of(2, "failure", "11:00", "11:02")])
    assert merged["status"] == "unavailable" and "without run times: gate" in merged["reason"]
    assert merged["data"] == {"merged": 1, "merged_red": [], "checks_unavailable": [6],
                              "red_now": [6]}
    text = claims(merged)
    assert "merge verdict unknown for 1 merged PRs" in text and "0 of" not in text
    assert "snapshot, not the merge verdict: 1 merged PRs" in text and "#6 (gate)" in text


def test_an_unreadable_merge_time_still_takes_the_snapshot(box_repo):
    routes = head_routes("b" * 40, runs=[run_of(1, "failure", "11:00", "11:02")],
                         statuses=[status_of(2, "error", "11:00")])
    routes[PULLS] = ([{"number": 6, "merged_at": "yesterday", "head": {"sha": "b" * 40}}], None)
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(routes)))["merged_prs"]
    assert merged["status"] == "unavailable" and "merge time 'yesterday'" in merged["reason"]
    assert merged["data"] == {"merged": 1, "merged_red": [], "checks_unavailable": [6],
                              "red_now": [6]}
    assert "#6 (external-ci, gate)" in claims(merged)


def test_a_required_check_on_a_later_rules_page_is_read(box_repo):
    filler = [{"type": "deletion"}] * 100
    later = {RULES: (filler, None), RULES + "&page=2": ([{"type": "required_status_checks",
                                                          "parameters": {
                                                              "required_status_checks": [
                                                                  {"context": "gate"}]}}], None)}
    text = claims(by_name(collect.collect(box_repo, slug="owner/app",
                                          runner=fixture_host(later)))["protection"])
    assert "required checks on main: gate" in text
    refused = {RULES: (filler, None), RULES + "&page=2": (None, "HTTP 403")}
    text = claims(by_name(collect.collect(box_repo, slug="owner/app",
                                          runner=fixture_host(refused)))["protection"])
    assert "effective rules on main read only in part: page 2 HTTP 403" in text
    assert "nothing is required" not in text


def test_a_merged_pr_past_the_first_page_of_closed_prs_is_read(box_repo):
    unmerged = [{"number": 1000 + i, "merged_at": None, "head": {"sha": "c" * 40}}
                for i in range(100)]
    later = {PULLS: (unmerged, None), PULLS + "&page=2": ([
        {"number": 7, "merged_at": at("10:05"), "head": {"sha": "a" * 40}}], None)}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(later)))["merged_prs"]
    assert merged["data"]["merged"] == 1 and merged["data"]["merged_red"] == [7]
    refused = {PULLS: (unmerged, None), PULLS + "&page=2": (None, "HTTP 403")}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(refused)))["merged_prs"]
    assert merged["status"] == "unavailable" and "page 2 HTTP 403" in merged["reason"]
    assert "0 of 0" not in claims(merged)
    # Merged PRs read before a refused page are a smaller sample, and say so.
    some = {PULLS: (unmerged[:99] + [{"number": 7, "merged_at": at("10:05"),
                                      "head": {"sha": "a" * 40}}], None),
            PULLS + "&page=2": (None, "HTTP 403")}
    merged = by_name(collect.collect(box_repo, slug="owner/app",
                                     runner=fixture_host(some)))["merged_prs"]
    assert merged["status"] == "ok" and merged["data"]["merged_red"] == [7]
    assert "closed PRs read only in part: page 2 HTTP 403" in claims(merged)


def test_a_defect_label_on_a_later_page_is_read(box_repo):
    filler = [{"name": "area-%d" % i} for i in range(100)]
    later = {LABELS: (filler, None), LABELS + "&page=2": ([{"name": "bug"}], None)}
    defects = by_name(collect.collect(box_repo, slug="owner/app",
                                      runner=fixture_host(later)))["defects"]
    assert defects["data"]["defect_issues"] == 2
    refused = {LABELS: (filler[:99] + [{"name": "bug"}], None),
               LABELS + "&page=2": (None, "HTTP 403")}
    defects = by_name(collect.collect(box_repo, slug="owner/app",
                                      runner=fixture_host(refused)))["defects"]
    text = claims(defects)
    assert "at least 2 defect-labelled issues" in text
    assert "labels page 2 HTTP 403" in text


def test_defect_issues_past_the_first_page_are_counted(box_repo):
    first = [{"number": i, "state": "closed", "labels": [{"name": "bug"}], "body": "",
              "created_at": "2026-09-01"} for i in range(1, 101)]
    hunt = {"number": 101, "state": "open", "title": "bug hunt finding",
            "labels": [{"name": "bug"}], "body": "Introduced by #41", "created_at": "2026-10-01"}
    later = {BUG_ISSUES: (first, None), BUG_ISSUES + "&page=2": ([hunt], None)}
    defects = by_name(collect.collect(box_repo, slug="owner/app",
                                      runner=fixture_host(later)))["defects"]
    assert defects["data"]["defect_issues"] == 101 and defects["data"]["traced"] == 1
    assert defects["data"]["bug_hunt_days"] == {"2026-10-01": 1}
    refused = {BUG_ISSUES: (first, None), BUG_ISSUES + "&page=2": (None, "HTTP 403")}
    defects = by_name(collect.collect(box_repo, slug="owner/app",
                                      runner=fixture_host(refused)))["defects"]
    assert defects["data"]["issues_incomplete"] == ["bug"]
    text = claims(defects)
    assert "label 'bug': at least 100 issues (page 2 HTTP 403)" in text
    assert "at least 100 defect-labelled issues" in text


def test_label_names_are_url_encoded(box_repo):
    issue = {"number": 3, "state": "open", "labels": [{"name": "bug&regression"}], "body": ""}
    runner = fixture_host({
        LABELS: ([{"name": "bug&regression"}], None),
        "repos/owner/app/issues?state=all&per_page=100&labels=bug%26regression": ([issue], None)})
    defects = by_name(collect.collect(box_repo, slug="owner/app", runner=runner))["defects"]
    assert defects["data"]["defect_issues"] == 1
    assert not any("labels=bug&" in p for p in runner.calls)


def test_a_refused_second_runs_page_is_an_incomplete_sample(box_repo):
    runs = [{"name": "ci", "head_sha": str(i), "conclusion": "success", "head_branch": "main",
             "event": "push", "created_at": "2026-10-01"} for i in range(130)]
    refused = {RUNS % 1: ({"total_count": 130, "workflow_runs": runs[:100]}, None),
               RUNS % 2: (None, "HTTP 403")}
    out = by_name(collect.collect(box_repo, slug="owner/app", runs=200,
                                  runner=fixture_host(refused)))["ci_runs"]
    assert out["status"] == "ok" and out["data"]["incomplete"] == "page 2 HTTP 403"
    assert "read 100 of the 200 runs asked for (page 2 HTTP 403)" in claims(out)
    # A list that simply ends is complete.
    ended = {RUNS % 1: ({"total_count": 130, "workflow_runs": runs[:100]}, None),
             RUNS % 2: ({"total_count": 130, "workflow_runs": runs[100:]}, None)}
    out = by_name(collect.collect(box_repo, slug="owner/app", runs=200,
                                  runner=fixture_host(ended)))["ci_runs"]
    assert out["data"]["total"] == 130 and "incomplete" not in out["data"]
    assert "asked for" not in claims(out)


def test_the_host_default_branch_is_read_once(box_repo):
    """A refused second metadata read must not swap the host's default for a local guess."""
    runner = fixture_host()
    answers = [({"default_branch": "release"}, None), (None, "HTTP 403")]

    def sequential(path):
        if path == "repos/owner/app":
            runner.calls.append(path)
            return answers.pop(0)
        return runner(path)
    ev = collect.collect(box_repo, slug="owner/app", runner=sequential)
    assert ev["default_branch"] == "release" and ev["default_branch_source"] == "host"
    assert runner.calls.count("repos/owner/app") == 1
    # A host that does not name its default leaves only a local guess, and the evidence says so.
    ev = collect.collect(box_repo, slug="owner/app",
                         runner=fixture_host({"repos/owner/app": ({}, None)}))
    assert ev["default_branch"] == "main"
    assert "not confirmed by the host" in ev["default_branch_source"]
    assert "not confirmed by the host" in collect.render_md(ev)


def test_refused_defect_issue_lookups_are_not_a_verified_zero(box_repo):
    issues = "repos/owner/app/issues?state=all&per_page=100&labels=%s"
    labels = {"repos/owner/app/labels?per_page=100": ([{"name": "bug"}, {"name": "regression"},
                                                       {"name": "docs"}], None)}
    refused = dict(labels, **{issues % "bug": (None, "HTTP 403"),
                              issues % "regression": (None, "HTTP 403")})
    defects = by_name(collect.collect(box_repo, slug="owner/app",
                                      runner=fixture_host(refused)))["defects"]
    assert defects["status"] == "unavailable" and "403" in defects["reason"]
    text = claims(defects)
    assert "0 defect-labelled" not in text and "defect_issues" not in defects["data"]
    assert "non-merge commits" in text  # git history still reported
    one = dict(labels, **{issues % "regression": (None, "HTTP 403")})
    defects = by_name(collect.collect(box_repo, slug="owner/app",
                                      runner=fixture_host(one)))["defects"]
    assert defects["status"] == "ok"
    assert defects["data"]["defect_issues"] == 2
    assert defects["data"]["issues_unavailable"] == ["regression"]
    text = claims(defects)
    assert "under 1 of 2 defect labels" in text
    assert "'regression': HTTP 403" in text


def test_only_a_named_introducing_change_counts_as_traced(box_repo):
    issues = [{"number": n, "state": "open", "labels": [{"name": "bug"}], "body": body}
              for n, body in enumerate([
                  "## Introducing PR\n\nunknown\n",
                  "### Introducing change\n\n_No response_\n",
                  "**Introducing commit:** \n\nN/A\n",
                  "Introducing PR: TBD\n",
                  "## Introducing PR\n\n#41\n",
                  "**Introducing commit:** 3f2c9ab1d\n",
                  "Regressed in #12.\n",
              ], start=1)]
    runner = fixture_host({"repos/owner/app/issues?state=all&per_page=100&labels=bug":
                            (issues, None)})
    defects = by_name(collect.collect(box_repo, slug="owner/app", runner=runner))["defects"]
    assert defects["data"]["defect_issues"] == 7 and defects["data"]["traced"] == 3


def test_unreachable_repo_falls_back_to_local_evidence(box_repo):
    runner = fixture_host({"repos/owner/app": (None, "HTTP 404")})
    ev = collect.collect(box_repo, slug="owner/app", runner=runner)
    assert ev["host_evidence"] == "unavailable (owner/app: HTTP 404)"
    assert by_name(ev)["ci_runs"]["status"] == "unavailable"


def test_summarize_runs_flags_cancellations_reruns_and_flakes():
    runs = [
        {"name": "ci", "head_sha": "1", "conclusion": "success", "head_branch": "main",
         "event": "push", "created_at": "2026-10-03", "run_attempt": 2},
        {"name": "ci", "head_sha": "1", "conclusion": "failure", "head_branch": "main",
         "event": "push", "created_at": "2026-10-02"},
        {"name": "ci", "head_sha": "0", "conclusion": "cancelled", "head_branch": "main",
         "event": "push", "created_at": "2026-10-01"},
        {"name": "ci", "head_sha": "9", "conclusion": "cancelled", "head_branch": "topic",
         "event": "pull_request", "created_at": "2026-10-01"},
    ]
    out = collect.summarize_runs(runs, "main")
    assert out["data"]["default_branch_cancelled"] == 1
    assert out["data"]["reruns"] == 1 and out["data"]["flake_suspects"] == ["ci"]
    assert "2026-10-01 to 2026-10-03" in claims(out)


# ----- card ----------------------------------------------------------------------------------

def dimension(dim, mark, verified=True, issues=1, extra=""):
    name = card.NAMES[dim]
    if mark == "–":
        return "## %s: %s\n\n**Mark:** –\n\n**Reason:** nothing deployed.\n%s" % (dim, name,
                                                                                   extra)
    issue_text = "\n".join(ISSUE.format(title="Fix %s gap %d" % (dim, i)) for i in range(issues))
    return textwrap.dedent("""\
        ## {dim}: {name}

        **Mark:** {mark}
        {extra}
        ### Evidence

        **Verified**
        {verified}

        **Read only**
        - The workflow says so. (ci.yml:3)

        ### Gap

        - A red PR can merge.

        ### Proposed issues

        """).format(dim=dim, name=name, mark=mark, extra=extra,
                    verified="- API shows it. (api rules)" if verified else "none") + \
        (issue_text or "No issue: an external blocker.\n")


ISSUE = """#### {title}

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
It is broken.

**Want**
- It works.

**Constraints**
- Tests in tests/.

**Dependencies**
none

**Out of scope**
Other things.
"""


def make_card(marks, score=None, sections=None):
    row = " · ".join("%s %s" % (d, m) for d, m in zip(card.DIMENSIONS, marks))
    score = card.overall(marks) if score is None else score
    head = textwrap.dedent("""\
        # Box audit: app (2026-10-19)

        - Repo: app at 0123456789ab, default branch main
        - Remote: none
        - Host evidence: unavailable (no remote)
        - Judge: isolated: test
        - Score: `{row} → {score}`

        ## Summary

        It scores {score}.

        """).format(row=row, score=score)
    body = sections or [dimension(d, m) for d, m in zip(card.DIMENSIONS, marks)]
    return head + "\n".join(body)


def test_valid_card_passes(tmp_path):
    path = tmp_path / "card.md"
    path.write_text(make_card(["✓", "~", "✗", "~", "–", "~"]), encoding="utf-8")
    r = script("card.py", "check", path)
    assert r.returncode == 0 and "CARD_OK" in r.stdout, r.stdout


@pytest.mark.parametrize("mutate,problem", [
    (lambda t: t.replace("→ 8`", "→ 7`"), "does not follow the rule"),
    (lambda t: t.replace("**Mark:** ✓", "**Mark:** ~", 1), "differs from the score row"),
    (lambda t: t.replace("Labels: tier:standard, ready, P1", "Labels: tier:standard, "
                         "tier:frontier, ready", 1), "exactly one tier label"),
    (lambda t: t.replace("Open decisions: none", "Open decisions: which database?", 1),
     "ready with open decisions"),
    (lambda t: t.replace("**Want**", "**Wanted**", 1), "missing **Want**"),
    (lambda t: t.replace("Labels: tier:standard, ready, P1", "Labels: tier:standard, urgent", 1),
     "unknown labels"),
    (lambda t: t.replace("## Summary\n\nIt scores 8.", "## Summary\n"), "Summary missing"),
    (lambda t: t.replace("- Judge: isolated: test\n", ""), "`- Judge:` missing"),
    (lambda t: t.replace("## J: Outside judge", "## J: Judge"), "heading should be"),
    (lambda t: t.replace("none\n\n**Out of scope**", "#12\n\n**Out of scope**", 1),
     "Dependencies must be"),
    (lambda t: t.replace("**Reason:** nothing deployed.", ""), "n/a needs a `**Reason:**`"),
    (lambda t: t.replace("- A red PR can merge.", "", 1), "### Gap missing or empty"),
    (lambda t: t.replace("#### Fix R gap 0", "#### Fix G gap 0"),
     "R: issue title 'Fix G gap 0' is also proposed under G"),
])
def test_card_problems_are_caught(mutate, problem):
    text = make_card(["✓", "~", "✗", "~", "–", "~"])
    assert not card.check(text)
    problems = card.check(mutate(text))
    assert any(problem in p for p in problems), problems


def test_read_only_evidence_cannot_meet_the_bar():
    marks = ["✓", "~", "✗", "~", "–", "~"]
    sections = [dimension("G", "✓", verified=False)] + [
        dimension(d, m) for d, m in zip(card.DIMENSIONS[1:], marks[1:])]
    assert any("no verified evidence" in p for p in card.check(make_card(marks, sections=sections)))


def test_never_na_dimensions_and_missing_issues():
    marks = ["–", "~", "✗", "~", "–", "~"]
    assert any("G is never n/a" in p for p in card.check(make_card(marks)))
    marks = ["✓", "~", "✗", "~", "–", "~"]
    sections = [dimension(d, m, issues=0 if d == "R" else 1) for d, m in
                zip(card.DIMENSIONS, marks)]
    text = make_card(marks, sections=sections).replace("No issue: an external blocker.\n", "")
    assert any("R: below ★ needs a proposed issue" in p for p in card.check(text))


def test_nine_with_one_partial_needs_a_written_blocker():
    marks = ["✓", "~", "✓", "✓", "–", "✓"]
    plain = make_card(marks, score=9)
    assert any("does not follow the rule" in p for p in card.check(plain))
    sections = [dimension(d, m, extra="\n**Blocker:** the runner hardware is not owned yet.\n"
                          if d == "R" else "") for d, m in zip(card.DIMENSIONS, marks)]
    assert not card.check(make_card(marks, score=9, sections=sections))


def test_overall_matches_the_standards_rule_for_every_row():
    for marks in itertools.product("✗~✓★–", repeat=6):
        assert card.overall(list(marks)) == standard_overall(list(marks)), marks


def test_score_command():
    r = script("card.py", "score", "G ✓ · R ~ · J ✗ · W ✗ · P – · D ✗ → 6")
    assert r.returncode == 0 and r.stdout.strip() == "6"
    assert script("card.py", "score", "G ✓ · R ~").returncode == 2
    assert script("card.py", "check").returncode == 2


# ----- judge isolation -----------------------------------------------------------------------

FAKE_CLI = r'''
import os, sys
from pathlib import Path
prompt = sys.stdin.read()
seen = []
home = Path(os.path.expanduser("~"))
for f in [home / ".agent" / "AGENTS.md"] + [p / "AGENTS.md" for p in [Path.cwd()] +
                                             list(Path.cwd().parents)]:
    if f.is_file():
        seen.append(f.read_text())
print("PROMPT:" + prompt.splitlines()[0] if prompt else "PROMPT:none")
print("SEEN:" + " | ".join(seen))
print("ENV:" + ",".join(sorted(k for k in os.environ if k.startswith("OWNER_"))))
print("KEPT:" + os.environ.get("JUDGE_API_KEY", "missing"))
print("CWD:" + ",".join(sorted(os.listdir("."))))
'''


@pytest.fixture
def owner(tmp_path, monkeypatch):
    """A fake owner home holding a personal instruction file, set as the process's home."""
    home = tmp_path / "owner-home"
    write(home, ".agent/AGENTS.md", "OWNER_CANARY always watch CI after every push\n")
    write(home, ".agent/credentials.json", '{"token": "t1"}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("OWNER_SECRET", "s3cret")
    monkeypatch.setenv("JUDGE_API_KEY", "k")
    # Only the test's marker counts as an instruction file, so the real folders above the
    # temp dir on a developer machine do not decide the outcome.
    monkeypatch.setattr(judge, "INSTRUCTION_ENTRIES", (MARKER,))
    root = tmp_path / "work-root"
    root.mkdir()
    cli = tmp_path / "cli" / "fake_cli.py"
    write(cli.parent, cli.name, FAKE_CLI)
    bundle = tmp_path / "bundle"
    write(bundle, "prompt.md", "Score this repo.\n")
    return {"home": home, "root": root, "cli": cli, "bundle": bundle, "tmp": tmp_path}


def test_judge_runs_without_the_owners_instructions_or_environment(owner, capfd):
    code = judge.run(owner["bundle"], [sys.executable, str(owner["cli"])],
                     keep=["JUDGE_API_KEY"], work_root=str(owner["root"]))
    out = capfd.readouterr().out
    assert code == 0, out
    lines = out.splitlines()
    assert "PROMPT:Score this repo." in lines
    assert "OWNER_CANARY" not in out and "SEEN:" in lines
    assert "ENV:" in lines  # OWNER_SECRET was not passed
    assert "KEPT:k" in lines
    assert "CWD:prompt.md" in lines
    assert list(owner["root"].iterdir()) == []  # temp home and work dir removed


def test_baseline_sees_the_owners_instructions(owner):
    """Positive control: without the launcher the fake CLI does find the planted file."""
    r = run([sys.executable, str(owner["cli"])], cwd=str(owner["tmp"]), input="x\n")
    assert "OWNER_CANARY" in r.stdout and "s3cret" not in r.stdout


def test_work_root_with_instruction_files_above_it_is_refused(owner, capfd):
    write(owner["root"], MARKER, "project rules\n")
    nested = owner["root"] / "deep"
    nested.mkdir()
    code = judge.run(owner["bundle"], [sys.executable, str(owner["cli"])],
                     work_root=str(nested))
    assert code == 2 and "unsafe --work-root" in capfd.readouterr().err
    assert judge.unsafe_root(owner["home"] / ".agent") is not None  # inside the home


def test_copy_home_copies_logins_refuses_instructions_and_keeps_refreshes(owner, capfd):
    refresh = owner["tmp"] / "cli" / "refresh.py"
    write(refresh.parent, refresh.name, "import os, sys\nsys.stdin.read()\n"
          "open(os.path.join(os.environ['HOME'], '.agent', 'credentials.json'), 'w')"
          ".write('{\"token\": \"t2\"}')\nprint('refreshed')\n")
    code = judge.run(owner["bundle"], [sys.executable, str(refresh)],
                     copy=[".agent/credentials.json"], work_root=str(owner["root"]))
    assert code == 0
    assert (owner["home"] / ".agent" / "credentials.json").read_text() == '{"token": "t2"}'
    for bad in (".agent/AGENTS.md", "../x.json", ".agent/missing.json"):
        assert judge.run(owner["bundle"], [sys.executable, str(refresh)], copy=[bad],
                         work_root=str(owner["root"])) == 2
    assert "refusing --copy-home" in capfd.readouterr().err


def test_folders_left_by_a_killed_run_are_swept(owner):
    stale = owner["root"] / "box-audit-judge-killed"
    write(stale, "home/.agent/credentials.json", "{}")
    write(stale, judge.OWN_MARK, "")
    old = stale.stat().st_mtime - judge.STALE_SECONDS - 60
    os.utime(str(stale), (old, old))
    fresh = owner["root"] / "box-audit-judge-running"
    write(fresh, judge.OWN_MARK, "")
    other = owner["root"] / "unrelated"
    other.mkdir()
    unmarked = owner["root"] / "box-audit-judge-not-ours"  # same name, no mark: not ours
    unmarked.mkdir()
    for folder in (other, unmarked):
        os.utime(str(folder), (old, old))
    assert judge.run(owner["bundle"], [sys.executable, str(owner["cli"])],
                     work_root=str(owner["root"])) == 0
    assert not stale.exists() and fresh.exists() and other.exists() and unmarked.exists()


def test_refresh_is_not_written_over_a_newer_owner_login(owner):
    clash = owner["tmp"] / "cli" / "clash.py"
    real = owner["home"] / ".agent" / "credentials.json"
    write(clash.parent, clash.name, "import os, sys\nsys.stdin.read()\n"
          "open(os.path.join(os.environ['HOME'], '.agent', 'credentials.json'), 'w')"
          ".write('judge')\nopen(%r, 'w').write('owner-newer')\nprint('x')\n" % str(real))
    assert judge.run(owner["bundle"], [sys.executable, str(clash)],
                     copy=[".agent/credentials.json"], work_root=str(owner["root"])) == 0
    assert real.read_text() == "owner-newer"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_refreshed_login_keeps_the_owners_file_mode(tmp_path):
    original, copy = tmp_path / "credentials.json", tmp_path / "judge-copy.json"
    original.write_text("t1")
    os.chmod(str(original), 0o600)
    before = judge.digest(original)
    copy.write_text("t2")
    old = os.umask(0o022)
    try:
        judge.write_back(original, copy, before)
    finally:
        os.umask(old)
    assert original.read_text() == "t2"
    assert original.stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["credentials.json", "judge-copy.json"]


def test_failed_or_silent_judge_exits_1(owner):
    silent = owner["tmp"] / "cli" / "silent.py"
    write(silent.parent, silent.name, "import sys\nsys.stdin.read()\n")
    assert judge.run(owner["bundle"], [sys.executable, str(silent)],
                     work_root=str(owner["root"])) == 1
    assert judge.run(owner["bundle"], [sys.executable, "-c", "import sys; sys.exit(3)"],
                     work_root=str(owner["root"])) == 1
    assert judge.run(owner["bundle"], ["no-such-judge-cli"], work_root=str(owner["root"])) == 2


def probe_cli(owner, name, body):
    path = owner["tmp"] / "cli" / name
    write(path.parent, path.name, body)
    return [sys.executable, str(path)]


ECHO_HOME = ("import os, sys\nsys.stdin.read()\nf = os.path.join(os.path.expanduser('~'), "
             "'.agent', 'AGENTS.md')\nprint(open(f).read() if os.path.exists(f) else 'NONE')\n")


def test_probe_passes_leaks_and_is_inconclusive(owner, capsys):
    instructions = str(owner["home"] / ".agent" / "AGENTS.md")
    kw = {"work_root": str(owner["root"])}
    assert judge.probe(instructions, probe_cli(owner, "home.py", ECHO_HOME), **kw) == 0
    assert "PROBE_PASS" in capsys.readouterr().out
    leaky = "import sys\nsys.stdin.read()\nprint(open(%r).read())\n" % instructions
    assert judge.probe(instructions, probe_cli(owner, "leaky.py", leaky), **kw) == 1
    assert "PROBE_LEAK" in capsys.readouterr().out
    blind = "import sys\nsys.stdin.read()\nprint('NONE')\n"
    assert judge.probe(instructions, probe_cli(owner, "blind.py", blind), **kw) == 3
    assert "PROBE_INCONCLUSIVE" in capsys.readouterr().out


def test_prepare_inlines_everything_the_judge_needs(tmp_path):
    ev = tmp_path / "evidence.md"
    ev.write_text("# Evidence for app\n- [verified] thing\n", encoding="utf-8")
    fb = tmp_path / "fb.md"
    fb.write_text("- G: Mark missing\n", encoding="utf-8")
    prompt = judge.prepare(ev, tmp_path / "b", "2026-10-19", "isolated: probe PASS", fb)
    text = prompt.read_text(encoding="utf-8")
    for needle in ("# Box audit: scoring instructions", "# Score card format", "# Box standard",
                   "## G: Enforced gate", "# Evidence for app", "G: Mark missing",
                   "2026-10-19", "isolated: probe PASS"):
        assert needle in text, needle


# ----- audit.py end to end -------------------------------------------------------------------

def judge_script(base, cards):
    """A judge that prints the given cards on successive calls, with chatter around the card."""
    state = base / "judge-state"
    state.mkdir(parents=True)
    for i, text in enumerate(cards):
        (state / ("card%d.md" % i)).write_text(text, encoding="utf-8")
    path = base / "judge_cli.py"
    path.write_text(textwrap.dedent("""\
        import os, sys
        from pathlib import Path
        prompt = sys.stdin.read()
        state = Path(os.environ["JUDGE_STATE"])
        n = len(list(state.glob("prompt*.md")))
        (state / ("prompt%d.md" % n)).write_text(prompt, encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        print("Here is the card:\\n\\n```markdown")
        print((state / ("card%d.md" % n)).read_text(encoding="utf-8"))
        print("```")
        """), encoding="utf-8")
    return path, state


def test_audit_report_writes_only_the_card(box_repo, owner, monkeypatch, capsys):
    good = make_card(["✓", "~", "✗", "~", "–", "~"])
    cli, state = judge_script(owner["tmp"], [good])
    monkeypatch.setenv("JUDGE_STATE", str(state))
    out = owner["tmp"] / "cards"
    before = snapshot(box_repo)
    code = audit.main([str(box_repo), "--no-remote", "--out", str(out), "--date", "2026-10-19",
                       "--keep-env", "JUDGE_STATE", "--work-root", str(owner["root"]), "--",
                       sys.executable, str(cli)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert snapshot(box_repo) == before
    cards = list(out.iterdir())
    assert [c.name for c in cards] == ["box-audit-repo-2026-10-19.md"]
    assert cards[0].read_text(encoding="utf-8") == good.strip() + "\n"
    prompt = (state / "prompt0.md").read_text(encoding="utf-8")
    assert "Host evidence: unavailable (skipped with --no-remote)" in prompt
    assert "## Proving a change" in prompt  # the audited repo's proof rules reach the judge


@pytest.fixture
def old_card(box_repo, owner, monkeypatch):
    """A repo holding a committed card, and the audit arguments for a judge that would pass."""
    cli, state = judge_script(owner["tmp"], [make_card(["✓", "~", "✗", "~", "–", "~"])] * 4)
    monkeypatch.setenv("JUDGE_STATE", str(state))
    write(box_repo, "box-audit-repo-2026-10-19.md", "an old card\n")
    commit(box_repo, "old card")
    run = ["--no-remote", "--date", "2026-10-19", "--keep-env", "JUDGE_STATE",
           "--work-root", str(owner["root"]), "--", sys.executable, str(cli)]
    return run, state


def test_audit_refuses_a_card_inside_the_repo(box_repo, owner, old_card, monkeypatch, capsys):
    run, state = old_card
    before = snapshot(box_repo)
    monkeypatch.chdir(box_repo)  # the default --out is the current directory
    assert audit.main([str(box_repo)] + run) == 2
    assert audit.main([str(box_repo), "--out", str(box_repo / "cards")] + run) == 2
    via_dir = owner["tmp"] / "via-dir"
    link(box_repo, via_dir)
    assert audit.main([str(box_repo), "--out", str(via_dir / "cards")] + run) == 2
    assert "outside the audited repo" in capsys.readouterr().err
    assert snapshot(box_repo) == before
    assert not list(state.glob("prompt*.md"))  # the judge never ran


def test_audit_refuses_a_card_that_links_into_the_repo(box_repo, owner, old_card, capsys):
    run, state = old_card
    before = snapshot(box_repo)
    out = owner["tmp"] / "cards"
    out.mkdir()
    link(box_repo / "box-audit-repo-2026-10-19.md", out / "box-audit-repo-2026-10-19.md")
    assert audit.main([str(box_repo), "--out", str(out)] + run) == 2
    assert "resolves inside the audited repo" in capsys.readouterr().err
    assert snapshot(box_repo) == before
    assert not list(state.glob("prompt*.md"))


def test_audit_refuses_a_card_hard_linked_into_the_repo(box_repo, owner, old_card, capsys):
    run, state = old_card
    out = owner["tmp"] / "cards"
    hard_link(box_repo / "box-audit-repo-2026-10-19.md", out / "box-audit-repo-2026-10-19.md")
    before = snapshot(box_repo)
    assert audit.main([str(box_repo), "--out", str(out)] + run) == 2
    assert "other hard links" in capsys.readouterr().err
    assert snapshot(box_repo) == before
    assert (box_repo / "box-audit-repo-2026-10-19.md").read_text(encoding="utf-8") == \
        "an old card\n"
    assert not list(state.glob("prompt*.md"))  # the judge never ran


def test_audit_replaces_an_existing_card_instead_of_writing_through_it(box_repo, owner,
                                                                       old_card, capsys):
    run, state = old_card
    out = owner["tmp"] / "cards"
    write(out, "box-audit-repo-2026-10-19.md", "last week's card\n")
    before = os.stat(str(out / "box-audit-repo-2026-10-19.md")).st_ino
    assert audit.main([str(box_repo), "--out", str(out)] + run) == 0, capsys.readouterr()
    card_path = out / "box-audit-repo-2026-10-19.md"
    assert card_path.read_text(encoding="utf-8").startswith("# Box audit:")
    assert os.stat(str(card_path)).st_ino != before  # a new file, renamed into place
    assert [p.name for p in out.iterdir()] == ["box-audit-repo-2026-10-19.md"]


def test_audit_from_a_subdirectory_guards_the_whole_checkout(box_repo, owner, old_card,
                                                             capsys):
    run, state = old_card
    before = snapshot(box_repo)
    sub = str(box_repo / "tests")
    assert audit.main([sub, "--out", str(box_repo)] + run) == 2
    assert audit.main([sub, "--out", str(box_repo / "docs")] + run) == 2
    assert audit.main([sub, "--no-remote", "--bundle-only", str(box_repo / "b")]) == 2
    assert "outside the audited repo" in capsys.readouterr().err
    assert snapshot(box_repo) == before
    assert not list(state.glob("prompt*.md"))  # the judge never ran


def test_audit_refuses_a_temp_dir_or_work_root_inside_the_repo(box_repo, owner, old_card,
                                                               monkeypatch, capsys):
    run, state = old_card
    out = str(owner["tmp"] / "cards")
    before = snapshot(box_repo)
    i = run.index("--work-root")
    inside_root = run[:i + 1] + [str(box_repo / "docs")] + run[i + 2:]
    assert audit.main([str(box_repo), "--out", out] + inside_root) == 2
    monkeypatch.setenv("TMP", str(box_repo / "docs"))  # the judge would inherit it
    assert audit.main([str(box_repo), "--out", out] + run) == 2
    assert audit.main([str(box_repo), "--no-remote", "--bundle-only",
                       str(owner["tmp"] / "b")]) == 2
    assert "inside the audited repo" in capsys.readouterr().err
    assert snapshot(box_repo) == before
    assert not list(state.glob("prompt*.md"))


def test_audit_retries_once_with_the_problems(box_repo, owner, monkeypatch, capsys):
    good = make_card(["✓", "~", "✗", "~", "–", "~"])
    bad = good.replace("→ 8`", "→ 9`")
    cli, state = judge_script(owner["tmp"], [bad, good])
    monkeypatch.setenv("JUDGE_STATE", str(state))
    code = audit.main([str(box_repo), "--no-remote", "--out", str(owner["tmp"] / "o"),
                       "--keep-env", "JUDGE_STATE", "--work-root", str(owner["root"]), "--",
                       sys.executable, str(cli)])
    assert code == 0, capsys.readouterr().out
    second = (state / "prompt1.md").read_text(encoding="utf-8")
    assert "Problems found by card.py check" in second and "does not follow the rule" in second

    cli2, state2 = judge_script(owner["tmp"] / "again", [bad, bad])
    monkeypatch.setenv("JUDGE_STATE", str(state2))
    code = audit.main([str(box_repo), "--no-remote", "--out", str(owner["tmp"] / "o2"),
                       "--keep-env", "JUDGE_STATE", "--work-root", str(owner["root"]), "--",
                       sys.executable, str(cli2)])
    assert code == 1 and "CARD_INVALID after 2 attempts" in capsys.readouterr().out
    assert list((owner["tmp"] / "o2").iterdir())  # written anyway, for the owner to see


def test_audit_bundle_only_and_usage(box_repo, tmp_path):
    out = tmp_path / "bundle"
    r = script("audit.py", box_repo, "--no-remote", "--bundle-only", out)
    assert r.returncode == 0, r.stderr
    assert {p.name for p in out.iterdir()} == {"evidence.md", "prompt.md"}
    assert script("audit.py", box_repo, "--no-remote").returncode == 2
    assert script("audit.py", box_repo, "--no-remote", "--bundle-only",
                  box_repo / "b").returncode == 2
    assert script("audit.py", box_repo, "--date", "19 Oct", "--bundle-only", out).returncode == 2


def test_audit_bundle_refuses_files_hard_linked_into_the_repo(box_repo, tmp_path):
    out = tmp_path / "bundle"
    write(out, "evidence.md", "an old bundle\n")
    hard_link(box_repo / "app.py", out / "prompt.md")
    before = snapshot(box_repo)
    r = script("audit.py", box_repo, "--no-remote", "--bundle-only", out)
    assert r.returncode == 2 and "other hard links" in r.stderr
    assert snapshot(box_repo) == before
    assert (out / "evidence.md").read_text(encoding="utf-8") == "an old bundle\n"


# Runs audit.py as a script would, except that only the test's marker counts as an instruction
# file (as in the owner fixture): real folders above the temp dir on a developer machine would
# otherwise refuse the work root. It patches judge as it is imported, so the import is audit's own.
AUDIT_WITH_TEST_MARKER = """\
import builtins, runpy, sys
real_import = builtins.__import__
def patched(name, *args, **kw):
    module = real_import(name, *args, **kw)
    if name == "judge":
        module.INSTRUCTION_ENTRIES = (%r,)
    return module
builtins.__import__ = patched
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
""" % MARKER


def test_report_run_in_a_fresh_process_leaves_the_checkout_unchanged(repo, owner, monkeypatch):
    """Self-audit end to end: fresh interpreters run the skill from inside the audited checkout,
    given a subdirectory as REPO. The first run's card destination is hard-linked to a tracked
    file and is refused; the second writes its card. Nothing in the checkout may change between
    the snapshots: no bytecode, no card, no temp folder, no link count."""
    shutil.copytree(str(ROOT / "box"), str(repo / "box"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    write(repo, "box-audit-app-2026-10-19.md", "an old card\n")
    commit(repo, "the box and an old card")
    good = make_card(["✓", "~", "✗", "~", "–", "~"])
    cli, state = judge_script(owner["tmp"], [good])
    monkeypatch.setenv("JUDGE_STATE", str(state))
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    linked, out = owner["tmp"] / "linked", owner["tmp"] / "cards"
    hard_link(repo / "box-audit-app-2026-10-19.md", linked / "box-audit-app-2026-10-19.md")
    wrapper = owner["tmp"] / "audit_with_test_marker.py"
    wrapper.write_text(AUDIT_WITH_TEST_MARKER, encoding="utf-8")

    def report(card_dir):
        return run([sys.executable, str(wrapper),
                    str(repo / "box" / "skills" / "box-audit" / "scripts" / "audit.py"),
                    str(repo / "box"), "--no-remote", "--name", "app", "--date", "2026-10-19",
                    "--out", str(card_dir), "--keep-env", "JUDGE_STATE",
                    "--work-root", str(owner["root"]), "--", sys.executable, str(cli)],
                   cwd=str(owner["tmp"]), encoding="utf-8")

    before = snapshot(repo)
    assert not [k for k in before if "__pycache__" in k]
    r = report(linked)
    assert r.returncode == 2 and "other hard links" in r.stderr, r.stdout + r.stderr
    assert not list(state.glob("prompt*.md"))  # refused before the judge
    r = report(out)
    assert r.returncode == 0 and "CARD_OK" in r.stdout, r.stdout + r.stderr
    after = snapshot(repo)
    assert sorted(set(after) ^ set(before)) == []
    assert after == before
    assert (repo / "box-audit-app-2026-10-19.md").read_text(encoding="utf-8") == "an old card\n"
    assert (out / "box-audit-app-2026-10-19.md").read_text(encoding="utf-8") == \
        good.strip() + "\n"


# Each case below is one way the caller's machine could make report mode change the checkout.
# Every one runs audit.py (or collect.py) in a fresh interpreter, the way the owner would.

@pytest.fixture
def fresh_audit(owner):
    """Run audit.py through AUDIT_WITH_TEST_MARKER in a fresh interpreter, from outside REPO."""
    wrapper = owner["tmp"] / "audit_with_test_marker.py"
    wrapper.write_text(AUDIT_WITH_TEST_MARKER, encoding="utf-8")

    def go(*args, env=None):
        return run([sys.executable, str(wrapper), str(SCRIPTS / "audit.py")] +
                   [str(a) for a in args], cwd=str(owner["tmp"]), env=env, encoding="utf-8")
    return go


def checkout(at):
    at.mkdir(parents=True, exist_ok=True)
    git(at, "init", "-q")
    git(at, "config", "user.email", "test@example.com")
    git(at, "config", "user.name", "Test")
    git(at, "config", "commit.gpgsign", "false")
    # No background maintenance: it writes .git/objects/maintenance.lock at its own time.
    git(at, "config", "maintenance.auto", "false")
    git(at, "config", "gc.auto", "0")
    write(at, "README.md", "hello\n")
    commit(at, "init")
    return at


def test_a_test_checkout_runs_no_background_maintenance(tmp_path):
    """git commit can start auto-maintenance in the background, which writes
    .git/objects/maintenance.lock whenever it gets to it: between two snapshots, a change no
    entry point made (seen on macOS). The tests' checkouts turn it off."""
    at = checkout(tmp_path / "c")
    for key, want in (("maintenance.auto", "false"), ("gc.auto", "0")):
        got = subprocess.run(["git", "config", "--get", key], cwd=str(at), capture_output=True,
                             text=True).stdout.strip()
        assert got == want, key


def maintenance_started(trace):
    """The auto-maintenance runs a GIT_TRACE2_EVENT file records as started. Matched by argv word,
    since a temp path can hold the word too."""
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    return [e["argv"] for e in events
            if e["event"] == "child_start" and {"maintenance", "gc"} & set(e["argv"])]


def test_the_repo_fixtures_start_no_background_maintenance(request, monkeypatch, tmp_path):
    """Since git 2.55 the detached run keeps .git/objects/maintenance.lock after git commit has
    returned, so a fixture that starts one races the snapshots taken after it."""
    trace = tmp_path / "trace2.json"
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))
    at = request.getfixturevalue("box_repo")
    assert maintenance_started(trace) == []
    # The reading above does see a run when one starts.
    git(at, "-c", "maintenance.auto=true", "commit", "-q", "--allow-empty", "-m", "control")
    assert maintenance_started(trace) != []


@pytest.mark.parametrize("case", ["unmarked ancestor", "marked ancestor", "marked checkout"])
def test_sweep_never_removes_the_audited_checkout(owner, fresh_audit, monkeypatch, case):
    """The work root holds an old judge-named folder that is, or contains, the checkout. The
    sweep for folders a killed run left behind must not delete it: it only removes folders a run
    marked as its own, and never one overlapping the checkout."""
    saved = owner["root"] / "box-audit-judge-saved"
    repo = checkout(saved if case == "marked checkout" else saved / "project")
    if case != "unmarked ancestor":
        write(saved, judge.OWN_MARK, "")
    old = saved.stat().st_mtime - judge.STALE_SECONDS - 60
    os.utime(str(saved), (old, old))
    cli, state = judge_script(owner["tmp"], [make_card(["✓", "~", "✗", "~", "–", "~"])])
    monkeypatch.setenv("JUDGE_STATE", str(state))
    before = snapshot(repo)
    r = fresh_audit(repo, "--no-remote", "--date", "2026-10-19",
                    "--out", owner["tmp"] / "cards", "--keep-env", "JUDGE_STATE",
                    "--work-root", owner["root"], "--", sys.executable, cli)
    assert repo.is_dir(), "the sweep deleted the audited checkout"
    assert r.returncode == 0 and "CARD_OK" in r.stdout, r.stdout + r.stderr
    assert snapshot(repo) == before


# judge.py's own CLI in a fresh interpreter, with only the test's marker as an instruction file
# (see AUDIT_WITH_TEST_MARKER).
JUDGE_WITH_TEST_MARKER = """\
import sys
sys.path.insert(0, %r)
import judge
judge.INSTRUCTION_ENTRIES = (%r,)
sys.exit(judge.main())
""" % (str(SCRIPTS), MARKER)


@pytest.mark.parametrize("case", ["marked ancestor", "marked checkout", "work root in a checkout"])
@pytest.mark.parametrize("entry", ["judge.py run", "judge.py probe", "audit.py"])
def test_no_entry_point_sweeps_away_a_checkout(repo, owner, fresh_audit, monkeypatch, entry,
                                               case):
    """An old marked judge folder in the work root is, holds or sits inside a git checkout that
    no caller named: judge.py run and probe name none, and audit.py names only the one it audits
    (`repo` here). The sweep itself must leave it alone, whichever command starts the judge."""
    saved = owner["root"] / "box-audit-judge-saved"
    write(saved, judge.OWN_MARK, "")
    if case == "marked ancestor":
        checkout(saved / "project")
    elif case == "marked checkout":
        checkout(saved)
    else:
        write(saved, "home/.agent/credentials.json", "{}")
        checkout(owner["root"])  # the work root is a checkout, and the folder is tracked in it
    old = saved.stat().st_mtime - judge.STALE_SECONDS - 60
    os.utime(str(saved), (old, old))
    before = snapshot(saved)
    if entry == "audit.py":
        cli, state = judge_script(owner["tmp"], [make_card(["✓", "~", "✗", "~", "–", "~"])])
        monkeypatch.setenv("JUDGE_STATE", str(state))
        r = fresh_audit(repo, "--no-remote", "--date", "2026-10-19",
                        "--out", owner["tmp"] / "cards", "--keep-env", "JUDGE_STATE",
                        "--work-root", owner["root"], "--", sys.executable, cli)
        ok = "CARD_OK"
    else:
        wrapper = owner["tmp"] / "judge_with_test_marker.py"
        wrapper.write_text(JUDGE_WITH_TEST_MARKER, encoding="utf-8")
        if entry == "judge.py run":
            args, cli, ok = ["run", owner["bundle"]], [sys.executable, owner["cli"]], "PROMPT:"
        else:
            args = ["probe", "--instructions", owner["home"] / ".agent" / "AGENTS.md"]
            cli, ok = probe_cli(owner, "home.py", ECHO_HOME), "PROBE_PASS"
        r = run([sys.executable, str(wrapper)] +
                [str(a) for a in args + ["--work-root", owner["root"], "--"] + cli],
                cwd=str(owner["tmp"]), encoding="utf-8")
    assert saved.is_dir(), "the sweep deleted a checkout"
    assert snapshot(saved) == before
    assert r.returncode == 0 and ok in r.stdout, r.stdout + r.stderr


REFRESH_CLI = """\
import os, sys
sys.stdin.read()
with open(os.path.join(os.environ["HOME"], %r, "credentials.json"), "w") as f:
    f.write('{"token": "t2"}')
sys.stdout.reconfigure(encoding="utf-8")
print(open(os.environ["JUDGE_CARD"], encoding="utf-8").read())
"""


@pytest.mark.parametrize("how", ["linked folder", "hard link"])
def test_a_refreshed_login_is_never_written_back_into_the_checkout(repo, owner, fresh_audit,
                                                                   monkeypatch, how):
    """The CLI's credentials file reaches into the checkout, through a linked folder in the home
    or as a hard link. The judge refreshes its copy; the write-back would change the checkout
    (its content, or the tracked file's link count), so the copy is refused before the judge
    runs."""
    write(repo, "config/credentials.json", '{"token": "t1"}')
    commit(repo, "config")
    if how == "linked folder":
        link(repo / "config", owner["home"] / ".cli")
    else:
        hard_link(repo / "config" / "credentials.json",
                  owner["home"] / ".cli" / "credentials.json")
    cli = owner["tmp"] / "refresh_cli.py"
    cli.write_text(REFRESH_CLI % ".cli", encoding="utf-8")
    good = owner["tmp"] / "good-card.md"
    good.write_text(make_card(["✓", "~", "✗", "~", "–", "~"]), encoding="utf-8")
    monkeypatch.setenv("JUDGE_CARD", str(good))
    before = snapshot(repo)
    r = fresh_audit(repo, "--no-remote", "--date", "2026-10-19",
                    "--out", owner["tmp"] / "cards", "--keep-env", "JUDGE_CARD",
                    "--copy-home", ".cli/credentials.json", "--work-root", owner["root"], "--",
                    sys.executable, cli)
    assert snapshot(repo) == before
    assert (repo / "config" / "credentials.json").read_text() == '{"token": "t1"}'
    assert r.returncode == 2 and "refusing --copy-home" in r.stderr, r.stdout + r.stderr


@pytest.mark.parametrize("source", ["environment", "global git config"])
@pytest.mark.parametrize("entry", ["audit.py", "collect.py"])
def test_git_trace_settings_cannot_write_into_the_checkout(repo, owner, entry, source):
    """Trace files named by the caller's environment, or by trace2 targets in the global git
    config (read from the home), all inside the checkout."""
    out = owner["tmp"] / "out"
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    if source == "environment":
        env.update(GIT_TRACE=str(repo / "git-trace.log"),
                   GIT_TRACE_PERFORMANCE=str(repo / "git-perf.log"),
                   GIT_TRACE_SETUP=str(repo / "git-setup.log"),
                   GIT_TRACE2=str(repo / "trace2.log"), GIT_TRACE2_EVENT=str(repo / "trace2.json"),
                   GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="trace2.perfTarget",
                   GIT_CONFIG_VALUE_0=str(repo / "trace2-perf.log"))
    else:
        write(owner["home"], ".gitconfig", "[trace2]\n" + "".join(
            "\t%sTarget = %s\n" % (kind, (repo / ("trace2-%s.log" % kind)).as_posix())
            for kind in ("event", "normal", "perf")))
    before = snapshot(repo)
    if entry == "audit.py":
        r = script(entry, repo, "--no-remote", "--bundle-only", out, cwd=owner["tmp"], env=env)
    else:
        r = script(entry, repo, "--no-remote", "--out", out / "evidence.json", cwd=owner["tmp"],
                   env=env)
    assert sorted(set(snapshot(repo)) - set(before)) == []
    assert snapshot(repo) == before
    assert r.returncode == 0, r.stderr


def test_a_bytecode_cache_prefix_inside_the_checkout(repo, tmp_path):
    """PYTHONPYCACHEPREFIX points inside the checkout. With -B, the documented entry point,
    nothing is written. Without it, interpreter startup may already have written there before
    the script's first line runs, which no script can prevent: the audit refuses, and its own
    imports add nothing."""
    prefix = repo / "cache"
    prefix.mkdir()
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(prefix))
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    before = snapshot(repo)
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "audit.py"), str(repo),
                        "--no-remote", "--bundle-only", str(tmp_path / "b1")], cwd=str(tmp_path),
                       env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert snapshot(repo) == before
    r = script("audit.py", repo, "--no-remote", "--bundle-only", tmp_path / "b2",
               cwd=tmp_path, env=env)
    assert r.returncode == 2 and "python -B" in r.stderr, r.stdout + r.stderr
    assert not (tmp_path / "b2").exists()
    written = [f.name for f in prefix.rglob("*.pyc")]
    assert not [n for n in written if n.split(".")[0] in ("argparse", "tempfile", "shutil",
                                                          "card", "collect", "judge")], written


@pytest.mark.parametrize("inside", [("TMPDIR", "TEMP", "TMP"), ("TMP",)])
def test_a_temp_dir_inside_the_checkout_is_refused_without_probing_it(repo, tmp_path, inside):
    """The caller's temp variables point inside the checkout. Python's own temp-dir lookup
    creates and deletes a file in its pick to test it; the audit must refuse without that. A
    later variable counts too, since the judge inherits it."""
    docs = repo / "docs"
    docs.mkdir()
    outside = tmp_path / "temp"
    outside.mkdir()
    env = dict(os.environ)
    for name in ("TMPDIR", "TEMP", "TMP"):
        env[name] = str(docs if name in inside else outside)
    before = snapshot(repo)
    r = script("audit.py", repo, "--no-remote", "--bundle-only", tmp_path / "b", cwd=tmp_path,
               env=env)
    assert snapshot(repo) == before
    assert r.returncode == 2 and "inside the audited repo" in r.stderr, r.stdout + r.stderr
    assert not (tmp_path / "b").exists()


# ----- file mode -----------------------------------------------------------------------------

def test_proposed_issues_become_host_issue_bodies():
    text = make_card(["✓", "~", "✗", "~", "–", "~"])
    issues = file_issues.proposed(text)
    assert [i["title"] for i in issues] == ["Fix %s gap 0" % d for d in "GRJWD"]
    first = issues[0]
    assert first["labels"] == ["tier:standard", "ready", "P1"]
    body = first["body"]
    assert body.index("## Problem") < body.index("## Want") < body.index("## Constraints") < \
        body.index("Dependencies: none") < body.index("## Out of scope")
    assert "(dimension G)" in body


FAKE_GH = r'''
import json, os, re, sys
args = sys.argv[1:]
state = os.environ["GH_STATE"]
page = re.search(r"[?&]page=(\d+)", args[1]) if args[0] == "api" else None
# The first GH_FULL_PAGES pages of each list are full of other labels and issues.
full = page and int(page.group(1)) <= int(os.environ.get("GH_FULL_PAGES", "0"))
if args[0] == "api" and "/labels" in args[1]:
    names = ["other %s-%d" % (page.group(1), n) for n in range(100)] if full else \
        os.environ["GH_LABELS"].split(",")
    print(json.dumps([{"name": n} for n in names]))
elif args[0] == "api" and "/issues" in args[1]:
    print(json.dumps([{"title": "other %s-%d" % (page.group(1), n)} for n in range(100)] if full
                     else [{"title": "Fix G gap 0"}, {"title": "a PR", "pull_request": {}}]))
elif args[:2] == ["issue", "create"]:
    with open(state, "a") as f:
        f.write(args[args.index("--title") + 1] + "\n")
    print("https://example.com/issues/1")
else:
    sys.exit(1)
'''


def fake_gh(tmp_path, labels, full_pages=0):
    """A stand-in gh: its command, the environment it reads, and the file it logs creates to."""
    gh = tmp_path / "gh.py"
    gh.write_text(FAKE_GH, encoding="utf-8")
    created = tmp_path / "created.txt"
    env = dict(os.environ, GH_STATE=str(created), GH_LABELS=labels,
               GH_FULL_PAGES=str(full_pages))
    return '"%s" "%s"' % (Path(sys.executable).as_posix(), gh.as_posix()), env, created


def test_file_mode_dry_run_checks_labels_and_apply_creates(tmp_path):
    path = tmp_path / "card.md"
    path.write_text(make_card(["✓", "~", "✗", "~", "–", "~"]), encoding="utf-8")
    gh_cmd, env, created = fake_gh(tmp_path, "tier:standard,ready")
    r = script("file_issues.py", path, "--repo", "o/r", "--gh", gh_cmd, "--apply", env=env)
    assert r.returncode == 1 and "MISSING LABELS on o/r: P1" in r.stdout
    assert not created.exists()
    env["GH_LABELS"] = "tier:standard,ready,P1"
    r = script("file_issues.py", path, "--repo", "o/r", "--gh", gh_cmd, env=env)
    assert r.returncode == 0 and r.stdout.startswith("DRY RUN: 5 proposed issues")
    assert "SKIP: an open issue has this title" in r.stdout and not created.exists()
    r = script("file_issues.py", path, "--repo", "o/r", "--gh", gh_cmd, "--apply", env=env)
    assert r.returncode == 0, r.stdout
    assert created.read_text().splitlines() == ["Fix %s gap 0" % d for d in "RJWD"]


def test_file_mode_never_files_one_title_twice(tmp_path):
    """Two dimensions proposing one title would both pass the open-issue check in one run."""
    path = tmp_path / "card.md"
    path.write_text(make_card(["✓", "~", "✗", "~", "–", "~"]).replace(
        "#### Fix R gap 0", "#### Fix J gap 0"), encoding="utf-8")
    gh_cmd, env, created = fake_gh(tmp_path, "tier:standard,ready,P1")
    r = script("file_issues.py", path, "--repo", "o/r", "--gh", gh_cmd, "--apply", env=env)
    assert r.returncode == 1 and "CARD_INVALID" in r.stdout, r.stdout
    assert "'Fix J gap 0' is also proposed under R" in r.stdout
    assert not created.exists()


def na_card(issue):
    """The valid test card with P marked n/a and `issue` proposed under P."""
    marks = ["✓", "~", "✗", "~", "–", "~"]
    extra = "\n### Proposed issues\n\n" + issue
    return make_card(marks, sections=[dimension(d, m, extra=extra if d == "P" else "")
                                      for d, m in zip(card.DIMENSIONS, marks)])


@pytest.mark.parametrize("issue, problem", [
    (ISSUE.format(title="Fix J gap 0"), "P: issue title 'Fix J gap 0' is also proposed under J"),
    (ISSUE.format(title="Fix P gap 0").replace("Open decisions: none", "Open decisions: which?"),
     "P issue 'Fix P gap 0': labelled ready with open decisions"),
])
def test_file_mode_checks_proposals_under_an_na_dimension(tmp_path, issue, problem):
    """Filing reads proposals under every mark, so the check must too."""
    path = tmp_path / "card.md"
    path.write_text(na_card(issue), encoding="utf-8")
    assert any(problem in p for p in card.check(na_card(issue)))
    gh_cmd, env, created = fake_gh(tmp_path, "tier:standard,ready,needs-refinement,P1")
    r = script("file_issues.py", path, "--repo", "o/r", "--gh", gh_cmd, "--apply", env=env)
    assert r.returncode == 1 and "CARD_INVALID" in r.stdout and problem in r.stdout, r.stdout
    assert not created.exists()


def test_file_mode_reads_labels_and_open_issues_past_ten_pages(tmp_path):
    path = tmp_path / "card.md"
    path.write_text(make_card(["✓", "~", "✗", "~", "–", "~"]), encoding="utf-8")
    gh_cmd, env, created = fake_gh(tmp_path, "tier:standard,ready,P1", full_pages=10)
    r = script("file_issues.py", path, "--repo", "o/r", "--gh", gh_cmd, "--apply", env=env)
    assert r.returncode == 0, r.stdout
    assert "SKIP: an open issue has this title" in r.stdout
    assert created.read_text().splitlines() == ["Fix %s gap 0" % d for d in "RJWD"]


def test_file_mode_usage(tmp_path):
    path = tmp_path / "card.md"
    path.write_text(make_card(["✓", "~", "✗", "~", "–", "~"]), encoding="utf-8")
    r = script("file_issues.py", path, "--repo", "o/r", "--offline")
    assert r.returncode == 0 and "offline: labels and duplicates not checked" in r.stdout
    assert script("file_issues.py", path, "--repo", "o/r", "--offline",
                  "--apply").returncode == 2
    assert script("file_issues.py", path, "--repo", "bad").returncode == 2
    assert script("file_issues.py", path, "--repo", "o/r", "--offline", "--only",
                  "nope").returncode == 2
    path.write_text("# not a card\n", encoding="utf-8")
    assert script("file_issues.py", path, "--repo", "o/r", "--offline").returncode == 1


@pytest.mark.parametrize("gh", ["gh '", str(Path("no-such-dir") / "gh")])
def test_file_mode_bad_gh_command_exits_2(tmp_path, gh):
    """Exit 1 means the card or a label failed; a --gh that cannot run is a usage error."""
    path = tmp_path / "card.md"
    path.write_text(make_card(["✓", "~", "✗", "~", "–", "~"]), encoding="utf-8")
    r = script("file_issues.py", path, "--repo", "o/r", "--gh", gh)
    assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr


def test_collect_bad_gh_command_exits_2(box_repo):
    r = script("collect.py", box_repo, "--gh", "gh '")
    assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr


@pytest.mark.parametrize("text", ["[]", '{"scripts": null}', '{"scripts": ["check"]}'])
def test_collect_skips_a_package_json_that_is_not_an_object(box_repo, text):
    write(box_repo, "package.json", text)
    commit(box_repo, "odd package.json")
    r = script("collect.py", box_repo, "--no-remote")
    assert r.returncode == 0, r.stderr


# ----- docs ------------------------------------------------------------------------------------

def test_skill_front_matter_and_links():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: box-audit\ndescription: ")
    assert "](../../STANDARD.md)" in text and (SKILL / "../../STANDARD.md").resolve().is_file()
    for name in ("audit.py", "collect.py", "judge.py", "card.py", "file_issues.py"):
        assert name in text, name
        header = (SCRIPTS / name).read_text(encoding="utf-8").split('"""')[1]
        assert "Exit codes:" in header and "Stdlib only" in header, name


def test_skill_is_vendor_neutral():
    names = ["Claude", "Codex", "Cursor", "OpenAI", "Anthropic", "GPT", "Copilot", "Gemini"]
    for path in SKILL.rglob("*"):
        if path.is_file() and path.suffix in (".md", ".py"):
            text = path.read_text(encoding="utf-8")
            for name in names:
                assert name not in text, "%s names %s" % (path.name, name)
