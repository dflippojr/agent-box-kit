"""Tests for the box-bootstrap skill (box/skills/box-bootstrap). Sample Python repos are built in
temp folders with real git, bootstrap runs as a subprocess the way SKILL.md documents it, and the
result is judged with box-audit's collectors (collect.py), not with bootstrap's own report and not
with box-audit's judge. The scripts bootstrap writes into the sample (gate, tamper guard, PR-body
lint, ready) are run there too."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import git, write

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "box" / "skills" / "box-bootstrap"
BOOTSTRAP = SKILL / "scripts" / "bootstrap.py"
TEMPLATES = SKILL / "templates"
AGENT_READY = ROOT / "agent-ready" / "templates"
sys.path.insert(0, str(ROOT / "box" / "skills" / "box-audit" / "scripts"))

import collect  # noqa: E402

PROFILES = ["home", "corporate"]
DOCS = ["docs/README.md", "docs/architecture.md", "docs/data-model.md", "docs/runtime.md",
        "docs/testing.md"]
GOOD_BODY = """\
## What and why

Adds a thing.

## Proof

| Acceptance criterion | How verified | Evidence |
|---|---|---|
| the thing works | `python scripts/check.py` | GATE_PASS, 1 passed |

### Not verified

Nothing on Windows.

### Gate changes

none

Closes #7
"""


def run(args, cwd=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def bootstrap(repo, *args):
    return run([sys.executable, "-B", BOOTSTRAP, repo] + list(args))


def in_repo(repo, script, *args):
    """Run a script bootstrap wrote, from the sample repo, with this interpreter (it has pytest)."""
    return run([sys.executable, "scripts/%s" % script] + list(args), cwd=repo)


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def new_repo(root, files):
    root.mkdir()
    git(root, "init", "-q")
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test"),
                       ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                       ("core.autocrlf", "false")):
        git(root, "config", key, value)
    for name, text in files.items():
        write(root, name, text)
    commit(root, "init")
    git(root, "branch", "-M", "main")
    return root


def empty_project(root):
    """A Python project with no tests and no CI."""
    return new_repo(root, {"pyproject.toml": '[project]\nname = "demo"\nversion = "0.1.0"\n',
                           "src/demo/__init__.py": "def add(a, b):\n    return a + b\n",
                           "README.md": "# demo\n"})


def project_with_tests(root):
    """A Python project with tests but no CI, and an AGENTS.md without a proof section."""
    return new_repo(root, {"pyproject.toml": '[project]\nname = "calc"\nversion = "0.1.0"\n',
                           "calc.py": "def add(a, b):\n    return a + b\n",
                           "tests/test_calc.py": "from calc import add\n\n\n"
                                                 "def test_add():\n    assert add(2, 2) == 4\n",
                           "AGENTS.md": "# AGENTS.md\n\n## Layout\n\ncalc.py holds it all.\n"})


SAMPLES = {"empty": empty_project, "tested": project_with_tests}


def head(repo, ref="HEAD"):
    return git(repo, "rev-parse", ref).strip()


def evidence(repo):
    found = collect.collect(repo, no_remote=True)
    return dict((c["name"], c["data"]) for c in found["collectors"])


@pytest.fixture(params=[(s, p) for s in SAMPLES for p in PROFILES],
                ids=lambda sp: "%s-%s" % sp)
def built(request, tmp_path):
    """A sample repo after one bootstrap run: (repo, profile, main before, result)."""
    sample, profile = request.param
    repo = SAMPLES[sample](tmp_path / sample)
    main_before = head(repo, "main")
    result = bootstrap(repo, "--profile", profile)
    return repo, profile, main_before, result


# ----- the acceptance criteria --------------------------------------------------------------

def test_every_g_and_w_item_is_present_by_the_collectors(built):
    repo, profile, _, result = built
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BOOTSTRAP_DONE" in result.stdout
    ev = evidence(repo)
    ci, proof, prot = ev["ci_config"], ev["proof_rules"], ev["protection"]
    # W: one command, AGENTS.md proof naming it, docs layer, verify skill, instance contract,
    # PR template.
    assert ("scripts/check.py", "scripts/check.py") in ci["local_gate"]
    assert proof["proof_excerpt"] and "python scripts/check.py" in proof["proof_excerpt"]
    assert set(DOCS) <= set(proof["docs"])
    assert proof["verify"] == [".agents/skills/verify/SKILL.md"]
    assert proof["instance_contract"] == ["docs/disposable-instance.md"]
    assert list(proof["pr_templates"].values()) == [["Proof", "Not verified", "Gate changes",
                                                    "Closes"]]
    if profile == "home":
        # G: the gate workflow runs on PRs and on pushes, without cancelling default-branch
        # runs; the tamper guard and the PR-body lint run in a workflow.
        gate = ci["workflows"][".github/workflows/gate.yml"]
        assert {"pull_request", "push"} <= set(gate["triggers"])
        assert any("scripts/check.py" in cmd for _, _, cmd in gate["runs"])
        assert [v for _, v in gate["cancel_in_progress"]] == [
            "${{ github.event_name == 'pull_request' }}"]
        checks = ci["workflows"][".github/workflows/pr-checks.yml"]
        for script in ("scripts/tamper_guard.py", "scripts/pr_body_lint.py"):
            assert any(script in cmd for _, _, cmd in checks["runs"]), script
        assert proof["pr_body_lint"] == [".github/workflows/pr-checks.yml"]
        assert prot["ready_scripts"] == []
    else:
        assert prot["ready_scripts"] == ["scripts/ready.py"]
        assert ci["workflows"] == {}


@pytest.mark.parametrize("sample", sorted(SAMPLES))
def test_corporate_writes_nothing_github_only(tmp_path, sample):
    repo = SAMPLES[sample](tmp_path / sample)
    result = bootstrap(repo, "--profile", "corporate")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (repo / ".github").exists()
    assert not [f for f in collect.tracked_files(repo) if f.startswith(".github/")]
    assert "github" not in result.stdout.lower()
    for name in ["AGENTS.md", ".agents/skills/verify/SKILL.md", "docs/pull_request_template.md"]:
        assert "github" not in (repo / name).read_text(encoding="utf-8").lower(), name


def test_the_work_is_on_a_new_branch_and_main_is_unchanged(built):
    repo, profile, main_before, result = built
    assert result.returncode == 0, result.stdout + result.stderr
    assert head(repo, "main") == main_before
    assert git(repo, "symbolic-ref", "--short", "HEAD").strip() == "box-bootstrap"
    assert git(repo, "rev-list", "--count", "main..box-bootstrap").strip() != "0"
    assert git(repo, "status", "--porcelain").strip() == ""
    assert (repo / ".box-profile").read_text(encoding="utf-8") == profile + "\n"
    assert ".box-profile" not in git(repo, "ls-tree", "--name-only", "main")


def test_a_second_run_changes_nothing(built):
    repo, profile, main_before, result = built
    assert result.returncode == 0, result.stdout + result.stderr
    before = head(repo)
    again = bootstrap(repo, "--profile", profile)
    assert again.returncode == 0, again.stdout + again.stderr
    assert head(repo) == before
    assert head(repo, "main") == main_before
    assert git(repo, "status", "--porcelain").strip() == ""
    # The profile is on the branch now, so it no longer needs the option.
    assert bootstrap(repo).returncode == 0
    assert head(repo) == before


def test_owner_steps_are_printed_never_done(built):
    repo, profile, _, result = built
    assert result.returncode == 0
    steps = result.stdout.split("Owner steps", 1)[1]
    if profile == "home":
        assert "Require the checks `gate`, `tamper-guard` and `pr-body` on main" in steps
    else:
        assert "merge into main only on `python scripts/ready.py --body FILE` exit 0" in steps
    assert "D: bug-hunt history" in result.stdout and "P: deploy signals" in result.stdout
    assert git(repo, "tag").strip() == ""
    assert git(repo, "remote").strip() == ""


def test_no_profile_is_a_usage_error(tmp_path):
    repo = project_with_tests(tmp_path / "r")
    result = bootstrap(repo)
    assert result.returncode == 2
    assert "no profile" in result.stderr
    assert git(repo, "branch", "--list").strip() == "* main"


@pytest.mark.parametrize("files, args", [
    ({"package.json": "{}\n", "index.js": "\n"}, ["--profile", "home"]),
    ({"pyproject.toml": "[project]\n"}, ["--profile", "home", "--stack", "javascript"]),
    ({"pyproject.toml": "[project]\n", "go.mod": "module x\n"}, ["--profile", "home"]),
    ({"README.md": "words\n"}, ["--profile", "home"]),
], ids=["javascript", "explicit-other", "mixed", "unknown"])
def test_a_non_python_stack_is_a_usage_error(tmp_path, files, args):
    repo = new_repo(tmp_path / "r", files)
    result = bootstrap(repo, *args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "supported stacks: python" in result.stderr
    assert git(repo, "branch", "--list").strip() == "* main"


def test_a_mixed_repo_can_name_python(tmp_path):
    repo = new_repo(tmp_path / "r", {"pyproject.toml": "[project]\n", "package.json": "{}\n"})
    result = bootstrap(repo, "--profile", "corporate", "--stack", "python")
    assert result.returncode == 0, result.stdout + result.stderr


# ----- the gate and the scripts it wrote ----------------------------------------------------

def test_the_gate_passes_with_tests_and_fails_without(tmp_path):
    tested = project_with_tests(tmp_path / "tested")
    empty = empty_project(tmp_path / "empty")
    for repo in (tested, empty):
        assert bootstrap(repo, "--profile", "home").returncode == 0
    ok = in_repo(tested, "check.py")
    assert ok.returncode == 0 and "GATE_PASS" in ok.stdout, ok.stdout + ok.stderr
    # A gate that runs nothing must not report green.
    none = in_repo(empty, "check.py")
    assert none.returncode == 1 and "GATE_FAIL: tests" in none.stdout, none.stdout


@pytest.fixture
def corporate(tmp_path):
    """The tested sample bootstrapped with the corporate profile, a body file outside it, and
    the bootstrap branch as the base for later changes."""
    repo = project_with_tests(tmp_path / "repo")
    assert bootstrap(repo, "--profile", "corporate").returncode == 0
    body = write(tmp_path, "body.md", GOOD_BODY)
    git(repo, "checkout", "-q", "-b", "change")
    return repo, body


def ready(repo, body):
    return in_repo(repo, "ready.py", "--body", body, "--base", "box-bootstrap")


def test_ready_runs_the_gate_the_tamper_guard_and_the_lint(corporate):
    repo, body = corporate
    write(repo, "calc.py", "def add(a, b):\n    return b + a\n")
    commit(repo, "harmless")
    result = ready(repo, body)
    assert result.returncode == 0, result.stdout + result.stderr
    for line in ("== gate", "GATE_PASS", "== tamper guard", "TAMPER_GUARD_PASS",
                 "== PR-body lint", "PR_BODY_PASS", "READY: merge %s" % head(repo)):
        assert line in result.stdout, line


def test_ready_fails_a_red_gate(corporate):
    repo, body = corporate
    write(repo, "calc.py", "def add(a, b):\n    return a - b\n")
    commit(repo, "break it")
    result = ready(repo, body)
    assert result.returncode == 1
    assert "NOT_READY at %s: gate" % head(repo) in result.stdout


def test_ready_fails_a_bad_description(corporate, tmp_path):
    repo, _ = corporate
    template = (repo / "docs" / "pull_request_template.md").read_text(encoding="utf-8")
    result = ready(repo, write(tmp_path, "unfilled.md", template))
    assert result.returncode == 1
    assert "PR-body lint" in result.stdout.splitlines()[-1]


def test_ready_needs_the_owners_tag_for_a_gate_change(corporate):
    repo, body = corporate
    write(repo, "tests/test_calc.py", "import pytest\nfrom calc import add\n\n\n"
                                      "@pytest.mark.skip\ndef test_add():\n"
                                      "    assert add(2, 2) == 4\n")
    write(repo, "tests/test_more.py", "def test_more():\n    assert True\n")
    commit(repo, "skip a test")
    result = ready(repo, body)
    assert result.returncode == 1
    assert "adds a skip, xfail or retry at tests/test_calc.py:5" in result.stdout
    assert result.stdout.splitlines()[-1].endswith(": tamper guard")
    git(repo, "tag", "gate-change-approved/%s" % head(repo))
    approved = ready(repo, body)
    assert approved.returncode == 0, approved.stdout
    assert "approved by the owner" in approved.stdout
    # A tag naming an older commit does not approve the new head.
    write(repo, "tests/test_more.py", "def test_more():\n    assert 1\n")
    commit(repo, "more")
    assert ready(repo, body).returncode == 1


def test_ready_refuses_changes_outside_the_head_commit(corporate):
    repo, body = corporate
    write(repo, "calc.py", "def add(a, b):\n    return 0\n")
    result = ready(repo, body)
    assert result.returncode == 1
    assert "not in the head commit" in result.stdout


@pytest.mark.parametrize("change, flagged", [
    (lambda r: git(r, "rm", "-q", "tests/test_calc.py"), "deletes test file tests/test_calc.py"),
    (lambda r: git(r, "mv", "tests/test_calc.py", "calc_check.py"),
     "deletes test file tests/test_calc.py"),
    (lambda r: write(r, "tests/test_calc.py", "from calc import add\n"),
     "removes test test_add from tests/test_calc.py"),
    (lambda r: write(r, "tests/conftest.py", "def pytest_collection_modifyitems(items):\n"
                                             "    import pytest\n"
                                             "    items[:] = [pytest.mark.xfail(i) for i in "
                                             "items]\n"),
     "adds a skip, xfail or retry at tests/conftest.py:3"),
    (lambda r: write(r, "pyproject.toml", '[project]\nname = "calc"\nversion = "0.1.0"\n\n'
                                          '[tool.coverage.report]\nfail_under = 10\n'),
     "edits gate config pyproject.toml"),
    (lambda r: write(r, "scripts/check.py", "print('GATE_PASS')\n"),
     "edits gate config scripts/check.py"),
    (lambda r: write(r, ".github/workflows/x.yml", "on: push\n"),
     "edits gate config .github/workflows/x.yml"),
], ids=["delete", "move-out", "remove-test", "xfail", "coverage", "gate-script", "workflow"])
def test_tamper_guard_flags_gate_weakening(corporate, change, flagged):
    repo, _ = corporate
    change(repo)
    commit(repo, "weaken")
    result = in_repo(repo, "tamper_guard.py", "--base", "box-bootstrap")
    assert result.returncode == 1, result.stdout + result.stderr
    assert flagged in result.stdout
    approved = in_repo(repo, "tamper_guard.py", "--base", "box-bootstrap", "--approved")
    assert approved.returncode == 0


@pytest.mark.parametrize("change", [
    lambda r: write(r, "calc.py", "def add(a, b):\n    return a + b  # same\n"),
    lambda r: write(r, "tests/test_extra.py", "def test_extra():\n    assert True\n"),
    lambda r: git(r, "mv", "tests/test_calc.py", "tests/test_adding.py"),
    lambda r: write(r, "pyproject.toml", '[project]\nname = "calc"\nversion = "0.2.0"\n'),
], ids=["product", "new-test", "rename-in-tests", "pyproject-version"])
def test_tamper_guard_passes_ordinary_changes(corporate, change):
    repo, _ = corporate
    change(repo)
    commit(repo, "ordinary")
    result = in_repo(repo, "tamper_guard.py", "--base", "box-bootstrap")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TAMPER_GUARD_PASS: no gate change" in result.stdout


def test_tamper_guard_reports_a_bad_ref(corporate):
    repo, _ = corporate
    assert in_repo(repo, "tamper_guard.py", "--base", "no-such-branch").returncode == 3


@pytest.mark.parametrize("edit, problem", [
    (lambda b: b, None),
    (lambda b: b.replace("## Proof", "## Evidence"), "no `## Proof` section"),
    (lambda b: b.replace("| the thing works | `python scripts/check.py` | GATE_PASS, 1 passed |\n",
                         ""), "has no table"),
    (lambda b: b.replace("GATE_PASS, 1 passed", ""), "proof row has an empty cell"),
    (lambda b: b.replace("Nothing on Windows.", ""), "`### Not verified` is empty"),
    (lambda b: b.replace("### Gate changes\n\nnone\n", ""), "no `### Gate changes` section"),
    (lambda b: b.replace("Closes #7", "Closes the loop"), "no closing reference"),
    (lambda b: b.replace("the thing works", "<criterion>"), "placeholder left in: <criterion>"),
    (lambda b: b.replace("Closes #7", "Fixes PROJ-12"), None),
    (lambda b: b.replace("Nothing on Windows.", "<!-- say what -->"), "is empty"),
    # The closing line right after it is not part of the section's content.
    (lambda b: b.replace("### Gate changes\n\nnone\n", "### Gate changes\n\n"),
     "`### Gate changes` is empty"),
    (lambda b: b.replace("Nothing on Windows.", "Fixes #7"), "`### Not verified` is empty"),
], ids=["good", "no-proof", "no-rows", "empty-cell", "empty-not-verified", "no-gate-changes",
        "no-closing", "placeholder", "issue-key", "comment-only", "empty-gate-changes",
        "closing-only-not-verified"])
def test_pr_body_lint(tmp_path, edit, problem):
    lint = TEMPLATES / "scripts" / "pr_body_lint.py"
    body = write(tmp_path, "body.md", edit(GOOD_BODY))
    result = run([sys.executable, lint, body])
    if problem is None:
        assert result.returncode == 0, result.stdout
    else:
        assert result.returncode == 1 and problem in result.stdout, result.stdout
    piped = subprocess.run([sys.executable, str(lint), "-"], input=edit(GOOD_BODY),
                           capture_output=True, text=True)
    assert piped.returncode == result.returncode
    assert run([sys.executable, lint, tmp_path / "missing.md"]).returncode == 2


@pytest.mark.parametrize("gate_changes, passes", [("", False), ("none", True)],
                         ids=["empty-gate-changes", "none"])
def test_pr_body_lint_on_the_filled_in_template(tmp_path, gate_changes, passes):
    """The real template, filled in except (or including) `### Gate changes`."""
    lint = TEMPLATES / "scripts" / "pr_body_lint.py"
    body = (TEMPLATES / "pull_request_template.md").read_text(encoding="utf-8")
    body = body.replace("Closes #<issue>", "Closes #7").replace(
        "| <criterion> | <command you ran, or what you observed> | <output, link or file> |",
        "| it works | `python scripts/check.py` | GATE_PASS |")
    body = re.sub(r"(### Not verified\n\n<!--.*?-->\n)", r"\1\nNothing on Windows.\n", body,
                  flags=re.S)
    body = re.sub(r"(### Gate changes\n\n<!--.*?-->\n)", r"\1\n%s\n" % gate_changes, body,
                  flags=re.S)
    result = run([sys.executable, lint, write(tmp_path, "body.md", body)])
    if passes:
        assert result.returncode == 0, result.stdout
    else:
        assert result.returncode == 1, result.stdout
        assert "`### Gate changes` is empty" in result.stdout


# ----- existing repos, the loop's verdict, and errors ---------------------------------------

def test_existing_files_are_kept_and_agents_md_gains_a_proof_section(tmp_path):
    repo = project_with_tests(tmp_path / "r")
    write(repo, "docs/architecture.md", "# Our architecture\n")
    commit(repo, "docs")
    assert bootstrap(repo, "--profile", "home").returncode == 0
    assert (repo / "docs/architecture.md").read_text(encoding="utf-8") == "# Our architecture\n"
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# AGENTS.md\n\n## Layout\n\ncalc.py holds it all.\n\n")
    assert "## Proving a change" in agents and "python scripts/check.py" in agents


def test_an_ignored_target_leaves_the_item_missing(tmp_path):
    repo = project_with_tests(tmp_path / "r")
    write(repo, ".gitignore", "docs/\n")
    commit(repo, "ignore docs")
    main_before = head(repo, "main")
    result = bootstrap(repo, "--profile", "corporate")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BOOTSTRAP_INCOMPLETE: docs, instance, pr_template" in result.stdout
    assert "is ignored by git" in result.stdout
    assert head(repo, "main") == main_before
    assert len(re.findall(r"^Round \d", result.stdout, re.M)) <= 3


def test_an_existing_file_the_collectors_do_not_accept_is_reported(tmp_path):
    repo = project_with_tests(tmp_path / "r")
    write(repo, ".github/pull_request_template.md", "## Summary\n")
    commit(repo, "own template")
    result = bootstrap(repo, "--profile", "home")
    assert result.returncode == 1
    assert "MISSING: its files exist (.github/pull_request_template.md)" in result.stdout
    assert "BOOTSTRAP_INCOMPLETE: pr_template" in result.stdout


def symlink(target, at):
    try:
        os.symlink(str(target), str(at), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create a symlink here")


def worktree_state(repo):
    """Everything git sees in the checkout: the branch, its commit, and every change, untracked
    and ignored files included."""
    return (git(repo, "symbolic-ref", "--short", "HEAD"), head(repo),
            git(repo, "status", "--porcelain", "--untracked-files=all", "--ignored"))


@pytest.mark.parametrize("folder, profile, tracked, target", [
    ("docs", "corporate", True, "outside"),
    ("scripts", "home", False, "outside"),
    ("docs", "home", True, "inside"),
], ids=["tracked-docs-out", "untracked-scripts-out", "tracked-docs-in-repo"])
def test_a_linked_folder_is_refused_before_anything_is_written(tmp_path, folder, profile,
                                                                tracked, target):
    repo = project_with_tests(tmp_path / "r")
    there = tmp_path / "outside" if target == "outside" else repo / "real"
    there.mkdir()
    write(there, "keep.txt", "x\n")
    symlink(there, repo / folder)
    if tracked:
        commit(repo, "link %s" % folder)
    git(repo, "checkout", "-q", "-b", "box-bootstrap")
    before = worktree_state(repo)
    # Creating and then deleting a file there would still change the folder's mtime.
    there_mtime = there.stat().st_mtime_ns
    result = bootstrap(repo, "--profile", profile)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "refusing to write" in result.stderr and "Nothing was written" in result.stderr
    assert "%s/" % folder in result.stderr and "is a link" in result.stderr, result.stderr
    assert sorted(p.name for p in there.iterdir()) == ["keep.txt"]
    assert there.stat().st_mtime_ns == there_mtime
    assert worktree_state(repo) == before
    # Once the link is gone, a run builds everything.
    (repo / folder).unlink() if not tracked else git(repo, "rm", "-q", folder)
    if tracked:
        git(repo, "commit", "-q", "-m", "unlink")
    assert bootstrap(repo, "--profile", profile).returncode == 0


def test_a_failed_commit_leaves_nothing_behind(tmp_path):
    repo = project_with_tests(tmp_path / "r")
    hook = write(repo, ".git/hooks/pre-commit", "#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    git(repo, "checkout", "-q", "-b", "box-bootstrap")
    before = worktree_state(repo)
    result = bootstrap(repo, "--profile", "home")
    assert result.returncode == 3, result.stdout + result.stderr
    assert worktree_state(repo) == before
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == \
        "# AGENTS.md\n\n## Layout\n\ncalc.py holds it all.\n"


@pytest.mark.parametrize("ignored", [True, False], ids=["ignored", "untracked"])
def test_an_agents_md_git_does_not_track_is_left_alone(tmp_path, ignored):
    repo = empty_project(tmp_path / "r")
    if ignored:
        write(repo, ".gitignore", "AGENTS.md\n")
        commit(repo, "ignore AGENTS.md")
    private = "# My notes\n\nPRIVATE_CANARY\n"
    write(repo, "AGENTS.md", private)
    result = bootstrap(repo, "--profile", "home")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "AGENTS.md is untracked or ignored; bootstrap does not commit it" in result.stdout
    assert "BOOTSTRAP_INCOMPLETE: agents_proof" in result.stdout
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == private
    assert "AGENTS.md" not in collect.tracked_files(repo)
    assert "PRIVATE_CANARY" not in git(repo, "log", "-p", "box-bootstrap")
    assert git(repo, "status", "--porcelain", "--untracked-files=no").strip() == ""
    # The other items were built and committed.
    assert (repo / "scripts" / "check.py").is_file()
    assert "scripts/check.py" in collect.tracked_files(repo)


def test_the_gate_workflow_gives_each_default_branch_push_its_own_group(tmp_path):
    """GitHub cancels a pending run when a newer one joins its concurrency group, whatever
    cancel-in-progress says, so pushes to the default branch must not share a group."""
    repo = empty_project(tmp_path / "r")
    assert bootstrap(repo, "--profile", "home").returncode == 0
    text = (repo / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
    group = re.search(r"^  group: (.+)$", text, re.M).group(1)
    assert "github.sha" in group and "github.event.pull_request.number" in group, group
    assert re.search(r"github\.event_name == 'pull_request' &&\s*"
                     r"[^|]*github\.event\.pull_request\.number[^|]*\|\|\s*github\.sha", group)
    assert re.search(r"^  cancel-in-progress: \$\{\{ github\.event_name == 'pull_request' \}\}$",
                     text, re.M)


@pytest.mark.parametrize("setup, args, code", [
    (lambda r: write(r, "calc.py", "changed\n"), ["--profile", "home"], 3),
    (lambda r: None, ["--profile", "home", "--rounds", "4"], 2),
    (lambda r: None, ["--profile", "home", "--rounds", "0"], 2),
    (lambda r: None, ["--profile", "home", "--branch", "main"], 2),
    (lambda r: None, ["--profile", "home", "--base", "nope"], 2),
    (lambda r: None, ["--profile", "elsewhere-profile"], 2),
    (lambda r: write(r, ".box-profile", "home\n"), ["--profile", "corporate"], 2),
    (lambda r: write(r, ".box-profile", "laptop\n"), [], 2),
], ids=["dirty", "rounds-high", "rounds-low", "branch-is-base", "no-base", "unknown-profile",
        "profile-conflict", "invalid-box-profile"])
def test_usage_and_git_errors(tmp_path, setup, args, code):
    repo = project_with_tests(tmp_path / "r")
    setup(repo)
    if (repo / ".box-profile").exists():
        commit(repo, "profile")
    result = bootstrap(repo, *args)
    assert result.returncode == code, result.stdout + result.stderr


def test_a_repo_without_commits_is_a_git_error(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo, "app.py", "x = 1\n")
    assert bootstrap(repo, "--profile", "home", "--stack", "python").returncode == 3


def test_not_a_checkout_top_is_a_usage_error(tmp_path):
    repo = project_with_tests(tmp_path / "r")
    assert bootstrap(repo / "tests", "--profile", "home").returncode == 2
    assert bootstrap(tmp_path / "missing", "--profile", "home").returncode == 2


def test_elsewhere_prints_the_host_side_setting():
    """A mechanism set to `elsewhere` gets the host-neutral variant plus an owner step."""
    sys.path.insert(0, str(BOOTSTRAP.parent))
    import bootstrap as bs
    profile = bs.profiles.load_profile("corporate")
    profile["mechanisms"]["required_checks"] = "elsewhere"
    profile["mechanisms"]["tamper_guard_lint"] = "elsewhere"
    items, pr_template = bs.plan(profile)
    assert pr_template == "docs/pull_request_template.md"
    assert "scripts/ready.py" in dict((i[0], i[3]) for i in items)["gate"]
    steps = "\n".join(bs.owner_steps(profile, "main"))
    assert "In the host, run `python scripts/check.py` in a pipeline" in steps
    assert "In the host, add required pipeline jobs" in steps


# ----- templates and docs -------------------------------------------------------------------

def test_docs_templates_are_agent_readys():
    for name in ("README", "architecture", "data-model", "runtime", "testing"):
        ours = (TEMPLATES / "docs" / (name + ".md")).read_text(encoding="utf-8")
        theirs = (AGENT_READY / "docs" / (name + ".md")).read_text(encoding="utf-8")
        assert ours.replace("\r\n", "\n") == theirs.replace("\r\n", "\n"), name


def test_agents_template_keeps_agent_readys_sections():
    ours = re.findall(r"^## .+$", (TEMPLATES / "AGENTS.md").read_text(encoding="utf-8"), re.M)
    theirs = re.findall(r"^## .+$", (AGENT_READY / "AGENTS.md").read_text(encoding="utf-8"),
                        re.M)
    assert [h for h in theirs if h not in ours] == []


def test_every_template_is_used_and_every_script_states_its_exit_codes():
    import ast
    text = BOOTSTRAP.read_text(encoding="utf-8")
    for path in sorted(TEMPLATES.rglob("*")):
        if path.is_file():
            rel = path.relative_to(TEMPLATES).as_posix()
            assert '"%s"' % rel in text or rel.endswith("merge-gate.md") or \
                rel.endswith("pr-checks.md") or rel == "proving.md", "unused template " + rel
    for path in [BOOTSTRAP] + sorted(TEMPLATES.rglob("*.py")):
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
        assert doc and re.search(r"exit codes", doc, re.I), path


def test_readme_and_skill_point_at_box_bootstrap():
    readme = (ROOT / "box" / "README.md").read_text(encoding="utf-8")
    assert "](skills/box-bootstrap/SKILL.md)" in readme
    layout = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "skills/box-bootstrap/" in layout
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert re.match(r"---\nname: box-bootstrap\ndescription: \S", skill)
    for needed in ("bug-hunt", "deploy signals", "at most 3 rounds",
                   "python -B scripts/bootstrap.py"):
        assert needed in skill, needed
