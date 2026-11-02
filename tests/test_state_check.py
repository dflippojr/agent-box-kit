import json
from pathlib import Path

import pytest

from conftest import git, py, write

TEMPLATE = Path(__file__).resolve().parent.parent / "agent-ready" / "templates" / "STATE.json"


def state(**over):
    base = {
        "goal": "Fix the thing",
        "facts": ["a fact"],
        "files_modified": [],
        "errors": [{"what": "tried X", "cause": "X is unsupported", "dead_end": True},
                   {"what": "flaky test", "cause": "timing", "dead_end": False}],
        "next_step": "Do Y",
    }
    base.update(over)
    return base


def write_state(tmp_path, data, name="state.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_shipped_template_is_valid():
    r = py("state_check.py", "validate", str(TEMPLATE))
    assert r.returncode == 0, r.stdout
    assert "STATE_OK" in r.stdout


def test_valid_state_passes_and_extra_keys_are_allowed(tmp_path):
    f = write_state(tmp_path, state(extra_note="ok"))
    assert py("state_check.py", "validate", str(f)).returncode == 0


@pytest.mark.parametrize("over,needle", [
    ({"goal": ""}, "goal"),
    ({"next_step": 3}, "next_step"),
    ({"facts": "not a list"}, "facts"),
    ({"facts": [1, 2]}, "facts"),
    ({"files_modified": [{"path": "a"}]}, "files_modified"),
    ({"errors": [{"what": "x", "cause": "y", "dead_end": "yes"}]}, "errors"),
])
def test_invalid_shapes_are_reported(tmp_path, over, needle):
    f = write_state(tmp_path, state(**over))
    r = py("state_check.py", "validate", str(f))
    assert r.returncode == 1
    assert "STATE_INVALID" in r.stdout and needle in r.stdout


def test_missing_key_is_invalid(tmp_path):
    data = state()
    del data["errors"]
    r = py("state_check.py", "validate", str(write_state(tmp_path, data)))
    assert r.returncode == 1


def test_not_json_and_missing_file_are_invalid(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    assert py("state_check.py", "validate", str(bad)).returncode == 1
    assert py("state_check.py", "validate", str(tmp_path / "missing.json")).returncode == 1


def test_top_level_must_be_an_object(tmp_path):
    f = tmp_path / "list.json"
    f.write_text("[]")
    assert py("state_check.py", "validate", str(f)).returncode == 1


def test_dead_ends_lists_only_dead_ends(tmp_path):
    r = py("state_check.py", "dead-ends", str(write_state(tmp_path, state())))
    assert r.returncode == 0
    assert "tried X" in r.stdout and "X is unsupported" in r.stdout
    assert "flaky test" not in r.stdout


def test_refresh_files_comes_from_git_including_rename_and_delete(repo, tmp_path):
    write(repo, "keep.txt", "keep\n")
    write(repo, "gone.txt", "gone\n")
    write(repo, "old_name.txt", "content that is long enough to be detected as a rename\n" * 5)
    write(repo, "edit.txt", "v1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "branch", "base")
    git(repo, "checkout", "-q", "-b", "work")
    write(repo, "edit.txt", "v2\n")
    write(repo, "added.txt", "new\n")
    git(repo, "rm", "-q", "gone.txt")
    git(repo, "mv", "old_name.txt", "new_name.txt")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "work")

    f = write_state(tmp_path, state(files_modified=[{"path": "invented.py", "change": "M"}]))
    r = py("state_check.py", "refresh-files", str(f), "--base", "base", "--dir", str(repo))
    assert r.returncode == 0, r.stderr
    got = {e["path"]: e["change"] for e in json.loads(f.read_text())["files_modified"]}
    assert got == {"edit.txt": "M", "added.txt": "A", "gone.txt": "D", "new_name.txt": "R"}
    assert py("state_check.py", "validate", str(f)).returncode == 0


def test_refresh_files_when_git_cannot_answer_empties_the_list(tmp_path):
    f = write_state(tmp_path, state(files_modified=[{"path": "invented.py", "change": "M"}]))
    r = py("state_check.py", "refresh-files", str(f), "--base", "nope", "--dir", str(tmp_path))
    assert r.returncode == 2
    assert json.loads(f.read_text())["files_modified"] == []


@pytest.mark.parametrize("base_args", [["--base=--output=x"], ["--base", "--output=x"]])
def test_option_like_base_is_rejected_and_writes_nothing(repo, tmp_path, base_args):
    before = [{"path": "invented.py", "change": "M"}]
    f = write_state(tmp_path, state(files_modified=before))
    r = py("state_check.py", "refresh-files", str(f), *base_args, "--dir", str(repo))
    assert r.returncode == 2
    assert "--base" in r.stderr
    assert not (repo / "x...HEAD").exists()  # git must never see --output=x as an option
    assert json.loads(f.read_text())["files_modified"] == before
