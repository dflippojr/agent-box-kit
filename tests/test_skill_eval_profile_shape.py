"""A profile whose JSON is not an object, or whose argv fields are not lists of strings, is a
usage error: load_profile reports it, and check and run exit 2 before any session starts."""
import json
import subprocess
import sys

import pytest

from test_skill_eval import SCRIPTS, SKILL, env, fake_profile, run_eval, runner, skill_eval  # noqa: F401

TASKS = SKILL / "tasksets" / "agent-ready.json"
NOT_OBJECTS = ["[]", "null", "42", '"profile"']
BAD_ARGV = [
    ("budget_args", [1]),
    ("budget_args", "--budget {budget}"),
    ("command", "agent -p"),
    ("command", ["agent", 1]),
]


def bad_profile(tmp_path, key, value):
    path = fake_profile(tmp_path, **{key: value})
    return path.rename(tmp_path / "bad-profile.json")


@pytest.mark.parametrize("text", NOT_OBJECTS)
def test_a_profile_that_is_not_an_object_is_a_problem(tmp_path, text):
    path = tmp_path / "p.json"
    path.write_text(text, encoding="utf-8")
    profile, problems = runner.load_profile(path)
    assert profile is None
    assert len(problems) == 1
    assert str(path) in problems[0] and "must be a JSON object" in problems[0]


@pytest.mark.parametrize("key,value", BAD_ARGV)
def test_argv_fields_must_be_lists_of_strings(tmp_path, key, value):
    _, problems = runner.load_profile(bad_profile(tmp_path, key, value))
    assert "profile `%s` must be a non-empty list of strings" % key in problems


def test_commands_that_are_not_a_list_are_a_problem(tmp_path):
    _, problems = runner.load_profile(fake_profile(tmp_path, commands=5))
    assert any("a request is not an execution" in p for p in problems)


def bad_files(tmp_path):
    files = []
    for i, text in enumerate(NOT_OBJECTS):
        path = tmp_path / ("not-object-%d.json" % i)
        path.write_text(text, encoding="utf-8")
        files.append(path)
    for key, value in BAD_ARGV:
        files.append(bad_profile(tmp_path, key, value).rename(
            tmp_path / ("bad-%d.json" % len(files))))
    return files


def test_check_exits_2_on_a_malformed_profile(tmp_path, capsys):
    for path in bad_files(tmp_path):
        assert skill_eval.main(["check", str(TASKS), "--profile", str(path)]) == 2, path
        err = capsys.readouterr().err
        assert err.startswith("skill-eval: ") and "Traceback" not in err


def test_check_prints_no_traceback_from_the_command_line(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("[]", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPTS / "skill_eval.py"), "check", str(TASKS),
                           "--profile", str(path)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert proc.stderr == "skill-eval: profile %s: must be a JSON object\n" % path


def sentinel(tmp_path):
    """An agent command that only leaves a marker at an absolute path when it is launched."""
    marker = tmp_path / "launched"
    script = tmp_path / "sentinel.py"
    script.write_text("import pathlib\npathlib.Path(%r).write_text('ran')\n" % str(marker),
                      encoding="utf-8")
    return [sys.executable, str(script)], marker


RUN = ("--no-judge", "--no-trigger", "--repeats", "1")


def test_the_sentinel_runs_when_the_profile_is_well_formed(env):
    command, marker = sentinel(env["tmp"])
    env["profile"] = fake_profile(env["tmp"], command=command)
    run_eval(env, env["a"], *RUN)
    assert marker.exists()


@pytest.mark.parametrize("key,value", [
    ("budget_args", [1]),
    ("budget_args", "--budget {budget}"),
    ("command", "sentinel"),
    ("command", [1]),
])
def test_run_exits_2_and_launches_nothing_on_a_malformed_profile(env, capsys, key, value):
    command, marker = sentinel(env["tmp"])
    if key == "command" and isinstance(value, list):
        value = command + value
    extra = {"command": command, key: value}
    env["profile"] = fake_profile(env["tmp"], **extra)
    code, out = run_eval(env, env["a"], *RUN)
    err = capsys.readouterr().err
    assert code == 2
    assert "skill-eval: profile `%s` must be a non-empty list of strings" % key in err
    assert not marker.exists() and not out.exists()


@pytest.mark.parametrize("text", NOT_OBJECTS)
def test_run_exits_2_on_a_profile_that_is_not_an_object(env, capsys, text):
    env["profile"].write_text(text, encoding="utf-8")
    code, out = run_eval(env, env["a"], *RUN)
    assert code == 2
    assert "must be a JSON object" in capsys.readouterr().err
    assert not out.exists()
