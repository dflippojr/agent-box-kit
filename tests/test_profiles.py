"""Checks box/profiles: each profile has exactly the fields and values issue #43 fixes, the
corporate profile assumes no GitHub and no editor, the mechanism keys follow the rows of
box/STANDARD.md's "Host-agnostic mechanisms" table, and profile.py resolves `.box-profile` with
the documented exit codes. The allowed values are restated here, not imported, so loosening
profile.py does not loosen the test. Pure stdlib."""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import git, write

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "box" / "profiles"
SCRIPT = PROFILES / "profile.py"
STANDARD = ROOT / "box" / "STANDARD.md"
SKILL = ROOT / "box" / "skills" / "box-audit"

# Loaded by path: the stdlib has its own `profile` module, which `import profile` could find first.
_spec = importlib.util.spec_from_file_location("box_profile", str(SCRIPT))
box_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(box_profile)

# The table's "Need" column, row by row, and the profile key each row maps to.
NEEDS = {
    "Required checks on the head commit": "required_checks",
    "A PR cannot rewrite its own judge": "judge_protection",
    "Worker identity separate from the owner": "worker_identity",
    "Owner-only labels": "owner_labels",
    "Tamper guard and PR-body lint": "tamper_guard_lint",
    "Scheduled judges and drift checks": "scheduled_judges",
}
COLUMNS = {"On GitHub": "github", "Elsewhere": "elsewhere", "No hosted VCS": "none"}
ALLOWED = {
    "model_access.provider": {"any", "subscription", "api", "bedrock", "other"},
    "model_access.second_family": {"yes", "no", "unknown"},
    "source_control": {"github", "other", "none", "unknown"},
    "ci_host": {"github", "other", "none", "unknown"},
    "ide": {"any", "none", "other"},
}
TOP = {"name", "model_access", "source_control", "ci_host", "ide", "mechanisms"}


def mechanism_table():
    """(header cells, Need cells) of STANDARD.md's "Host-agnostic mechanisms" table."""
    text = STANDARD.read_text(encoding="utf-8")
    section = re.search(r"^## Host-agnostic mechanisms$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert section, "STANDARD.md has no '## Host-agnostic mechanisms' section"
    rows = [line for line in section.group(1).splitlines() if line.startswith("|")]
    cells = [[c.strip() for c in row.strip("|").split("|")] for row in rows]
    return cells[0], [row[0] for row in cells[2:]]


def profile_problems(data, name):
    """Everything wrong with a profile against the issue's field list, as strings."""
    out = []
    if set(data) != TOP:
        out.append("top-level fields %s, want %s" % (sorted(data), sorted(TOP)))
    if data.get("name") != name:
        out.append("name %r does not match the file name %r" % (data.get("name"), name))
    access = data.get("model_access")
    if not isinstance(access, dict) or set(access) != {"provider", "second_family"}:
        out.append("model_access fields %r, want provider and second_family" % (access,))
    for path, allowed in ALLOWED.items():
        value = data
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value not in allowed:
            out.append("%s: %r not in %s" % (path, value, sorted(allowed)))
    mech = data.get("mechanisms")
    if not isinstance(mech, dict) or set(mech) != set(NEEDS.values()):
        out.append("mechanisms keys %r, want %s" % (
            sorted(mech) if isinstance(mech, dict) else mech, sorted(NEEDS.values())))
    elif any(v not in COLUMNS.values() for v in mech.values()):
        out.append("mechanisms values %r, each must be one of %s" % (mech, sorted(COLUMNS.values())))
    return out


def corporate_problems(data):
    """What makes a profile unfit to be `corporate`: GitHub assumed, or an editor named."""
    out = []
    for key in ("source_control", "ci_host"):
        if data.get(key) == "github":
            out.append("%s is github" % key)
    if data.get("ide") != "any":
        out.append("ide is %r, want any" % data.get("ide"))
    for key, value in (data.get("mechanisms") or {}).items():
        if value == "github":
            out.append("mechanism %s is github" % key)
    return out


def read_profile(name):
    return json.loads((PROFILES / (name + ".json")).read_text(encoding="utf-8"))


def cli(repo):
    return subprocess.run([sys.executable, str(SCRIPT), str(repo)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def test_profile_files_are_home_and_corporate():
    assert sorted(p.stem for p in PROFILES.glob("*.json")) == ["corporate", "home"]


@pytest.mark.parametrize("name", ["home", "corporate"])
def test_profile_has_exactly_the_fields_and_values(name):
    data = read_profile(name)
    assert profile_problems(data, name) == []
    assert box_profile.problems(data, name) == []


def test_corporate_is_the_spec_and_assumes_no_github_or_editor():
    data = read_profile("corporate")
    assert corporate_problems(data) == []
    assert data["model_access"] == {"provider": "bedrock", "second_family": "unknown"}
    assert (data["source_control"], data["ci_host"], data["ide"]) == ("unknown", "unknown", "any")
    assert set(data["mechanisms"].values()) == {"none"}


def test_mechanism_keys_follow_the_standards_table():
    header, needs = mechanism_table()
    assert header == ["Need"] + list(COLUMNS), header
    assert needs == list(NEEDS), "table rows changed; update NEEDS and both profiles: %s" % needs
    assert box_profile.MECHANISMS == [NEEDS[n] for n in needs]
    for name in ("home", "corporate"):
        assert list(read_profile(name)["mechanisms"]) == box_profile.MECHANISMS, name


def mutations():
    """(label, mutate) pairs; each turns a valid profile invalid."""
    def drop(path):
        def f(d):
            *parents, last = path.split(".")
            for p in parents:
                d = d[p]
            del d[last]
        return f

    def put(path, value):
        def f(d):
            *parents, last = path.split(".")
            for p in parents:
                d = d[p]
            d[last] = value
        return f

    yield "missing ide", drop("ide")
    yield "missing second_family", drop("model_access.second_family")
    yield "missing mechanism", drop("mechanisms.owner_labels")
    yield "extra field", put("editor", "any")
    yield "extra model_access field", put("model_access.region", "any")
    yield "extra mechanism", put("mechanisms.new_row", "none")
    yield "bad provider", put("model_access.provider", "openai")
    yield "bad second_family", put("model_access.second_family", "maybe")
    yield "bad source_control", put("source_control", "gitlab")
    yield "bad ci_host", put("ci_host", "jenkins")
    yield "editor named", put("ide", "vscode")
    yield "bad mechanism column", put("mechanisms.required_checks", "gitlab")
    yield "wrong name", put("name", "work")


@pytest.mark.parametrize("label,mutate", list(mutations()), ids=[m[0] for m in mutations()])
@pytest.mark.parametrize("name", ["home", "corporate"])
def test_invalid_profiles_are_caught(name, label, mutate):
    data = read_profile(name)
    mutate(data)
    assert profile_problems(data, name), label
    assert box_profile.problems(data, name), label


@pytest.mark.parametrize("change", [
    {"source_control": "github"}, {"ci_host": "github"}, {"ide": "none"}, {"ide": "other"},
    {"mechanisms": dict(read_profile("corporate")["mechanisms"], scheduled_judges="github")},
])
def test_corporate_github_or_editor_is_caught(change):
    data = dict(read_profile("corporate"), **change)
    assert corporate_problems(data), change


@pytest.mark.parametrize("text,name", [
    ("home", "home"), ("home\n", "home"), ("corporate\r\n", "corporate")])
def test_valid_choice_exits_0_and_prints_the_profile(tmp_path, text, name):
    write(tmp_path, ".box-profile", text)
    proc = cli(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == read_profile(name)
    assert box_profile.load(tmp_path) == read_profile(name)


def test_missing_choice_exits_3_and_loads_as_unset(tmp_path):
    proc = cli(tmp_path)
    assert proc.returncode == 3, proc.stderr
    assert proc.stdout == "" and "unset" in proc.stderr
    assert box_profile.load(tmp_path) is None


@pytest.mark.parametrize("text", [
    "", "\n", "home corporate\n", "home\ncorporate\n", "home\n\n", " home\n", "work\n",
    "Home\n", "home.json\n", "../home\n"])
def test_invalid_choice_exits_2(tmp_path, text):
    write(tmp_path, ".box-profile", text)
    proc = cli(tmp_path)
    assert proc.returncode == 2, (text, proc.stdout, proc.stderr)
    assert proc.stdout == ""
    with pytest.raises(box_profile.ProfileError):
        box_profile.load(tmp_path)


def test_symlinked_choice_exits_2(tmp_path):
    write(tmp_path, "elsewhere", "home\n")
    try:
        (tmp_path / ".box-profile").symlink_to(tmp_path / "elsewhere")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    assert cli(tmp_path).returncode == 2


def test_usage_errors_exit_2(tmp_path):
    assert cli(tmp_path / "missing").returncode == 2
    proc = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), "extra"],
                          capture_output=True, text=True)
    assert proc.returncode == 2


def test_invalid_profile_file_exits_2(tmp_path, monkeypatch):
    bad = tmp_path / "profiles"
    bad.mkdir()
    data = read_profile("home")
    data["ide"] = "vscode"
    write(bad, "home.json", json.dumps(data))
    monkeypatch.setattr(box_profile, "PROFILES", bad)
    write(tmp_path, ".box-profile", "home\n")
    with pytest.raises(box_profile.ProfileError, match="ide"):
        box_profile.load(tmp_path)
    assert box_profile.main([str(tmp_path)]) == 2


def snapshot(root):
    """Every path under root, .git included, with each file's bytes."""
    return dict((p.relative_to(root).as_posix(), None if p.is_dir() else p.read_bytes())
                for p in sorted(Path(root).rglob("*")))


def step_one():
    """The box-audit skill's step-1 command, as SKILL.md documents it."""
    text = SKILL.joinpath("SKILL.md").read_text(encoding="utf-8")
    found = re.findall(r"^\s*(python\b.*profile\.py <REPO>)\s*$", text, re.M)
    assert len(found) == 1, found
    return found[0].split()


@pytest.fixture
def audited(repo):
    """A committed repo choosing `corporate`, with an inherited bytecode prefix inside it."""
    write(repo, ".box-profile", "corporate\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(repo / ".cache"))
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    return repo, env


def test_box_audit_step_one_leaves_the_audited_repo_untouched(audited):
    repo, env = audited
    argv = step_one()
    assert argv[:2] == ["python", "-B"], argv
    before = snapshot(repo)
    proc = subprocess.run([sys.executable] + [str(repo) if a == "<REPO>" else a
                                              for a in argv[1:]],
                          cwd=str(SKILL), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == read_profile("corporate")
    assert snapshot(repo) == before
    assert git(repo, "status", "--porcelain", "--ignored") == ""


def test_without_dash_b_a_bytecode_prefix_inside_the_repo_is_refused(audited):
    """Startup may already have written there, which no script can undo; the script refuses,
    and its own imports add nothing."""
    repo, env = audited
    proc = subprocess.run([sys.executable, str(SCRIPT), str(repo)], env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 2 and "python -B" in proc.stderr, proc.stdout + proc.stderr
    assert proc.stdout == ""
    written = [p.name.split(".")[0] for p in (repo / ".cache").rglob("*.pyc")]
    assert not set(written) & {"argparse", "json", "pathlib", "profile"}, written


def test_readme_and_skill_point_at_the_profile():
    readme = (ROOT / "box" / "README.md").read_text(encoding="utf-8")
    skill = (ROOT / "box" / "skills" / "box-audit" / "SKILL.md").read_text(encoding="utf-8")
    for text in (readme, skill):
        assert ".box-profile" in text and "profile.py" in text
    assert "corporate" in readme and "home" in readme
    assert "--no-remote" in skill and "--offline" in skill
