"""Tests for the box-crosspollinate skill (box/skills/box-crosspollinate). Its input is three
synthetic score cards for invented repos (tests/fixtures/box_crosspollinate): a tie on G, P n/a on
two cards, and one card 46 days older than the newest. Filing runs box-audit's file_issues.py
against an issue folder and a stand-in gh, as box-audit's own tests do."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_box_audit import fake_gh

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "box" / "skills" / "box-crosspollinate"
COMPARE = SKILL / "scripts" / "compare.py"
AUDIT_SCRIPTS = ROOT / "box" / "skills" / "box-audit" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "box_crosspollinate"
ALPHA = FIXTURES / "box-audit-repo-alpha-2026-11-01.md"
BETA = FIXTURES / "box-audit-repo-beta-2026-11-05.md"
GAMMA = FIXTURES / "box-audit-repo-gamma-2026-09-20.md"
CARDS = [ALPHA, BETA, GAMMA]
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(AUDIT_SCRIPTS))
sys.path.insert(0, str(ROOT / "box" / "skills" / "queue-fill" / "scripts"))

import card  # noqa: E402
import compare  # noqa: E402
import issue_lint  # noqa: E402


def run(path, *args, cwd=None, env=None):
    return subprocess.run([sys.executable, "-B", str(path)] + [str(a) for a in args],
                          cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def compare_run(*args):
    return run(COMPARE, *args)


def titles(text):
    return re.findall(r"^#### (.+)$", text, re.M)


def with_mark(text, dim, mark):
    """The card `text` with `dim` re-marked n/a (`–`), its score row and Proven recomputed."""
    assert mark == "–"
    row = card.ROW.search(text)
    marks = card.parse_row(row.group(1))
    marks[card.DIMENSIONS.index(dim)] = mark
    new_row = " · ".join("%s %s" % (d, m) for d, m in zip(card.DIMENSIONS, marks))
    text = text.replace(row.group(0), "`%s → %d`" % (new_row, card.overall(marks)))
    text = re.sub(r"^- Proven: .*$", "- Proven: %s" % card.proven(marks), text, flags=re.M)
    section = ("## %s: %s\n\n**Mark:** –\n\n**Reason:** invented for the test.\n\n"
               "### Evidence\n\nnone\n\n### Gap\n\nnone\n\n### Proposed issues\n\nnone\n\n"
               % (dim, card.NAMES[dim]))
    return re.sub(r"^## %s: .*?(?=^## )" % dim, lambda m: section, text, flags=re.M | re.S)


def test_fixture_cards_pass_the_card_check_and_use_generic_names():
    for path in CARDS:
        text = path.read_text(encoding="utf-8")
        assert card.check(text) == [], path.name
        assert run(AUDIT_SCRIPTS / "card.py", "check", path).stdout.strip() == "CARD_OK"
        assert re.match(r"^# Box audit: repo-(alpha|beta|gamma) \(", text)
        assert "example/repo-" in text


def test_matrix_lists_each_cards_marks_date_score_and_proven():
    r = compare_run(*CARDS)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    start = lines.index("Repo        Date        G  R  J  W  P  D  Score  Proven")
    assert lines[start + 1:start + 4] == [
        "repo-alpha  2026-11-01  ✓  ✓  ~  ~  –  ~  → 8    7.0",
        "repo-beta   2026-11-05  ✓  ~  ✓  ★  ~  ✗  → 8    6.7",
        "repo-gamma  2026-09-20  ~  ✗  ~  ✓  –  ✓  → 8    6.0"]


def strongest_lines(stdout):
    return [l for l in stdout.splitlines() if re.match(r"^[GRJWPD] [A-Z]", l)]


def test_strongest_per_dimension_lists_ties_and_never_picks_na():
    r = compare_run(*CARDS)
    assert strongest_lines(r.stdout) == [
        "G Enforced gate: ✓ repo-alpha, repo-beta",
        "R Real-thing tests: ✓ repo-alpha",
        "J Outside judge: ✓ repo-beta",
        "W Worker-runnable proof: ★ repo-beta",
        "P Real-use feedback: ~ repo-beta",
        "D Defect ratchet: ✓ repo-gamma"]


def test_strongest_quotes_the_evidence_behind_the_mark_with_sources():
    out = compare_run(*CARDS).stdout
    g = out[out.index("G Enforced gate:"):out.index("R Real-thing tests:")]
    assert "  repo-alpha (2026-11-01):\n    Verified:\n    - Required check `gate` on main " \
           "blocks merging (api repos/example/repo-alpha/rules/branches/main)\n" in g
    assert "    Read only:\n    - The gate workflow runs the full suite " \
           "(.github/workflows/gate.yml:9)" in g
    p = out[out.index("P Real-use feedback:"):out.index("D Defect ratchet:")]
    assert "    Verified: none\n    Read only:\n    - A health endpoint is defined " \
           "(src/app/health.py:8)" in p


def test_a_dimension_na_on_every_card_has_no_strongest_and_no_proposal(tmp_path):
    paths = []
    for path in CARDS:
        text = with_mark(path.read_text(encoding="utf-8"), "R", "–")
        assert card.check(text) == [], path.name
        paths.append(tmp_path / path.name)
        paths[-1].write_text(text, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    r = compare_run(*paths, "--out", out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "R Real-thing tests: none (n/a on every card)" in r.stdout
    written = "".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    assert "## R:" not in written and "real-thing tests" not in written


def test_cards_more_than_max_age_apart_warn_and_still_compare():
    r = compare_run(*CARDS)
    assert r.returncode == 0
    assert "WARNING: the cards are 46 days apart (repo-gamma 2026-09-20, repo-beta 2026-11-05), " \
           "more than 30" in r.stdout
    assert "WARNING" not in compare_run(*CARDS, "--max-age", "46").stdout
    assert "more than 45" in compare_run(*CARDS, "--max-age", "45").stdout
    assert "WARNING" not in compare_run(ALPHA, BETA).stdout


def write_proposals(tmp_path, *cards):
    out = tmp_path / "out"
    out.mkdir()
    r = compare_run(*(cards or CARDS), "--out", out)
    assert r.returncode == 0, r.stdout + r.stderr
    return out, r


def test_each_weaker_repo_gets_one_port_proposal_per_weaker_dimension(tmp_path):
    out, r = write_proposals(tmp_path)
    files = sorted(p.name for p in out.iterdir())
    assert files == ["crosspollinate-repo-%s-2026-11-05.md" % n for n in ("alpha", "beta",
                                                                           "gamma")]
    text = {n: (out / ("crosspollinate-repo-%s-2026-11-05.md" % n)).read_text(encoding="utf-8")
            for n in ("alpha", "beta", "gamma")}
    assert titles(text["alpha"]) == ["Port the outside judge from repo-beta",
                                     "Port the worker-runnable proof from repo-beta",
                                     "Port the defect ratchet from repo-gamma"]
    assert titles(text["beta"]) == ["Port the real-thing tests from repo-alpha",
                                    "Port the defect ratchet from repo-gamma"]
    assert titles(text["gamma"]) == ["Port the enforced gate from repo-alpha and repo-beta",
                                     "Port the real-thing tests from repo-alpha",
                                     "Port the outside judge from repo-beta",
                                     "Port the worker-runnable proof from repo-beta"]
    # P: beta is strongest, and alpha and gamma are n/a there, so nobody gets a P proposal.
    assert not any("## P:" in t for t in text.values())
    for n in ("alpha", "beta", "gamma"):
        assert "- repo-%s: %s" % (n, out / ("crosspollinate-repo-%s-2026-11-05.md" % n)) \
            in r.stdout


def test_proposals_have_the_card_shape_and_name_the_strong_repos_source_paths(tmp_path):
    out, _ = write_proposals(tmp_path)
    for path in out.iterdir():
        text = path.read_text(encoding="utf-8")
        assert card.check_proposal_file(text) == [], path.name
    gamma = (out / "crosspollinate-repo-gamma-2026-11-05.md").read_text(encoding="utf-8")
    assert gamma.startswith("# Box crosspollinate: repo-gamma (2026-11-05)\n")
    proposals = {t: b for _, t, b in card.proposals(gamma)}
    g = proposals["Port the enforced gate from repo-alpha and repo-beta"]
    assert "Labels: tier:standard, ready\nOpen decisions: none\n" in g
    assert "repo-gamma marks G (Enforced gate) ~ in its box audit of 2026-09-20; repo-alpha " \
           "and repo-beta mark it ✓." in g
    assert "- A red PR merges because no check is required." in g
    assert "Evidence behind repo-alpha's ✓ on G (card of 2026-11-01):" in g
    assert "Evidence behind repo-beta's ✓ on G (card of 2026-11-05):" in g
    assert "`.github/workflows/gate.yml` (repo-alpha), `.github/workflows/gate.yml` " \
           "(repo-beta)" in g
    w = proposals["Port the worker-runnable proof from repo-beta"]
    assert "Source paths its card cites: `scripts/verify.py` (repo-beta), " \
           "`docs/testing.md` (repo-beta)." in w
    assert "marks W at ★, with verified evidence" in w


def test_every_proposal_passes_issue_lint_as_file_issues_would_file_it(tmp_path):
    out, _ = write_proposals(tmp_path)
    sys.path.insert(0, str(AUDIT_SCRIPTS))
    import file_issues
    for path in out.iterdir():
        for issue in file_issues.proposed(path.read_text(encoding="utf-8"), "box-crosspollinate"):
            assert issue_lint.lint(issue["body"], issue["labels"]) == [], issue["title"]
            assert issue["body"].rstrip().endswith(
                "_Proposed by box-crosspollinate (dimension %s)._" % issue["dimension"])


def test_file_issues_dry_runs_then_files_a_proposal_file_into_a_folder(tmp_path):
    out, _ = write_proposals(tmp_path)
    proposal = out / "crosspollinate-repo-gamma-2026-11-05.md"
    folder = tmp_path / "issues"
    folder.mkdir()
    fi = AUDIT_SCRIPTS / "file_issues.py"
    r = run(fi, proposal, "--folder", folder)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("DRY RUN: 4 proposed issues for %s" % folder)
    assert list(folder.iterdir()) == []
    r = run(fi, proposal, "--folder", folder, "--apply", "--only",
            "Port the real-thing tests from repo-alpha")
    assert r.returncode == 0, r.stdout + r.stderr
    filed = (folder / "1.md").read_text(encoding="utf-8")
    assert "title: Port the real-thing tests from repo-alpha\n" in filed
    assert "labels: tier:standard, ready\n" in filed
    assert sorted(p.name for p in folder.iterdir()) == ["1.md"]


def test_file_issues_checks_labels_on_the_host_before_filing_a_proposal_file(tmp_path):
    out, _ = write_proposals(tmp_path)
    proposal = out / "crosspollinate-repo-beta-2026-11-05.md"
    gh_cmd, env, created = fake_gh(tmp_path, "tier:standard")
    fi = AUDIT_SCRIPTS / "file_issues.py"
    r = run(fi, proposal, "--repo", "o/r", "--gh", gh_cmd, "--apply", env=env)
    assert r.returncode == 1 and "MISSING LABELS on o/r: ready" in r.stdout, r.stdout
    assert not created.exists()
    env["GH_LABELS"] = "tier:standard,ready"
    r = run(fi, proposal, "--repo", "o/r", "--gh", gh_cmd, env=env)
    assert r.returncode == 0 and r.stdout.startswith("DRY RUN: 2 proposed issues for o/r")
    assert not created.exists()
    r = run(fi, proposal, "--repo", "o/r", "--gh", gh_cmd, "--apply", env=env)
    assert r.returncode == 0, r.stdout
    assert created.read_text().splitlines() == ["Port the real-thing tests from repo-alpha",
                                                "Port the defect ratchet from repo-gamma"]


@pytest.mark.parametrize("edit, problem", [
    (lambda t: t.replace("(2026-11-05)", "2026-11-05", 1),
     "first line must be `# Box crosspollinate: <repo> (<YYYY-MM-DD>)`"),
    (lambda t: t.replace("## R: Real-thing tests", "## R: Real tests"),
     "section `## R: Real tests` is not a dimension heading"),
    (lambda t: t.replace("Port the defect ratchet from repo-gamma",
                         "Port the real-thing tests from repo-alpha"),
     "issue title 'Port the real-thing tests from repo-alpha' is also proposed under R"),
    (lambda t: t.replace("Labels: tier:standard, ready", "Labels: ready"),
     "needs exactly one tier label"),
    (lambda t: t.split("\n## ")[0], "no proposed issues"),
])
def test_file_issues_refuses_a_broken_proposal_file(tmp_path, edit, problem):
    out, _ = write_proposals(tmp_path)
    proposal = out / "crosspollinate-repo-beta-2026-11-05.md"
    text = edit(proposal.read_text(encoding="utf-8"))
    assert any(problem in p for p in card.check_proposal_file(text))
    proposal.write_text(text, encoding="utf-8")
    folder = tmp_path / "issues"
    folder.mkdir()
    r = run(AUDIT_SCRIPTS / "file_issues.py", proposal, "--folder", folder, "--apply")
    assert r.returncode == 1, r.stdout + r.stderr
    assert problem in r.stdout
    assert list(folder.iterdir()) == []


def test_without_out_the_proposals_are_printed():
    r = compare_run(ALPHA, BETA)
    assert r.returncode == 0, r.stderr
    assert "# Box crosspollinate: repo-alpha (2026-11-05)" in r.stdout
    assert "#### Port the outside judge from repo-beta" in r.stdout
    assert "#### Port the real-thing tests from repo-alpha" in r.stdout


def test_equal_cards_propose_nothing(tmp_path):
    other = tmp_path / "other.md"
    other.write_text(ALPHA.read_text(encoding="utf-8").replace("repo-alpha", "repo-delta"),
                     encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    r = compare_run(ALPHA, other, "--out", out)
    assert r.returncode == 0, r.stderr
    assert "- repo-alpha: none (no dimension below the strongest)" in r.stdout
    assert "- repo-delta: none (no dimension below the strongest)" in r.stdout
    assert list(out.iterdir()) == []


def test_an_invalid_card_stops_before_anything_is_written(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text(BETA.read_text(encoding="utf-8").replace("**Mark:** ★", "**Mark:** ✓"),
                   encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    r = compare_run(ALPHA, bad, GAMMA, "--out", out)
    assert r.returncode == 1
    assert "bad.md: CARD_INVALID" in r.stdout and "W: Mark ✓ differs" in r.stdout
    assert "Repo " not in r.stdout and list(out.iterdir()) == []


def test_a_card_date_that_is_not_a_calendar_date_is_invalid(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text(BETA.read_text(encoding="utf-8").replace("(2026-11-05)", "(2026-13-45)", 1),
                   encoding="utf-8")
    r = compare_run(ALPHA, bad)
    assert r.returncode == 1 and "is not a calendar date" in r.stdout


def test_usage_errors_exit_2_and_write_nothing(tmp_path):
    assert compare_run(ALPHA).returncode == 2
    assert compare_run(ALPHA, tmp_path / "missing.md").returncode == 2
    r = compare_run(ALPHA, ALPHA)
    assert r.returncode == 2 and "two cards for repo-alpha" in r.stderr
    assert compare_run(ALPHA, BETA, "--max-age", "-1").returncode == 2
    assert compare_run(ALPHA, BETA, "--out", tmp_path / "nowhere").returncode == 2
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "crosspollinate-repo-beta-2026-11-05.md"
    existing.write_text("keep me\n", encoding="utf-8")
    r = compare_run(*CARDS, "--out", out)
    assert r.returncode == 2 and "already exists" in r.stderr
    assert existing.read_text(encoding="utf-8") == "keep me\n"
    assert sorted(p.name for p in out.iterdir()) == [existing.name]


@pytest.mark.parametrize("item, paths", [
    ("Gate runs (.github/workflows/gate.yml:14)", [".github/workflows/gate.yml"]),
    ("Golden files (tests/golden/report.txt; tests/test_golden.py:12-20)",
     ["tests/golden/report.txt", "tests/test_golden.py"]),
    ("A worker ran `scripts/verify.py` (CI run 460)", ["scripts/verify.py"]),
    ("Rules (api repos/example/repo/rules)", []),
    ("Fixes touch tests (git log)", []),
    ("Version pinned (3.10)", []),
    ("Ran `make check` and `gate` (README.md:4)", ["README.md"]),
])
def test_source_paths_come_from_the_trailing_source_and_folder_code_spans(item, paths):
    assert compare.source_paths(item) == paths


def test_skill_names_its_script_and_header_states_options_and_exit_codes():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: box-crosspollinate\ndescription: ")
    assert "compare.py" in text and "file_issues.py" in text
    for target in re.findall(r"\]\(([^)#\s]+)", text):
        assert (SKILL / target).resolve().exists(), target
    header = COMPARE.read_text(encoding="utf-8").split('"""')[1]
    for needle in ("Stdlib only", "Exit codes:", "--max-age", "--out"):
        assert needle in header, needle
    assert "skills/box-crosspollinate/" in (ROOT / "box" / "README.md").read_text(encoding="utf-8")
    assert "skills/box-crosspollinate/" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_skill_is_vendor_neutral_and_stdlib_only():
    from test_scripts_stdlib import non_stdlib_imports
    names = ["Claude", "Codex", "Cursor", "OpenAI", "Anthropic", "GPT", "Copilot", "Gemini"]
    for path in sorted(SKILL.rglob("*")):
        if path.suffix in (".md", ".py"):
            text = path.read_text(encoding="utf-8")
            for name in names:
                assert not re.search(r"\b%s\b" % name, text), (path, name)
    if sys.version_info >= (3, 10):  # card is box-audit's card.py, loaded from the checkout
        assert [p for p in non_stdlib_imports(COMPARE) if "'card'" not in p] == []
