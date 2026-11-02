import os
import sys

import pytest

from conftest import git, py, run, write

BUGGY = "def avg(total, n):\n    return total // n\n"
FIXED = "def avg(total, n):\n    if n == 0:\n        return 0\n    return total // n\n"
REPRO_TEST = "import calc\nassert calc.avg(10, 0) == 0\n"          # red on buggy, green after fix
FALSE_TEST = "import calc\nassert calc.avg(10, 2) == 5\n"          # green both before and after
WRONG_TEST = "import calc\nassert calc.avg(10, 0) == 99\n"         # red both before and after
SYNTAX_ERR = "import calc\nassert calc.avg(10, 0) ==\n"            # red for the wrong reason


@pytest.fixture
def bug(repo):
    """A repo with a buggy calc.py committed and fix.patch (outside the repo) that repairs it."""
    write(repo, "calc.py", BUGGY)
    git(repo, "add", "calc.py")
    git(repo, "commit", "-q", "-m", "buggy calc")
    write(repo, "calc.py", FIXED)
    patch = repo.parent / "fix.patch"
    patch.write_bytes(git(repo, "diff").encode("utf-8"))
    git(repo, "checkout", "-q", "calc.py")
    return repo, patch


def gate(repo, patch, test_name, *extra, cmd=None):
    cmd = cmd or [sys.executable, test_name]
    return py("red_green_gate.py", "--fix", str(patch), "--dir", str(repo), *extra, "--", *cmd)


def tree_is_clean(repo):
    return git(repo, "status", "--porcelain", "--untracked-files=no").strip() == ""


def test_red_for_the_wrong_reason_is_caught_by_the_green_step(bug):
    repo, patch = bug
    write(repo, "check.py", SYNTAX_ERR)
    r = gate(repo, patch, "check.py")
    assert r.returncode == 1
    assert "still FAILS after the fix" in r.stdout


def test_red_pattern_must_match_the_failure(bug):
    repo, patch = bug
    write(repo, "check.py", REPRO_TEST)
    assert gate(repo, patch, "check.py", "--red-pattern", "ZeroDivisionError").returncode == 0
    r = gate(repo, patch, "check.py", "--red-pattern", "KeyError")
    assert r.returncode == 1
    assert "wrong reason" in r.stdout
    assert tree_is_clean(repo)


def test_dirty_tracked_tree_is_refused_and_left_untouched(bug):
    repo, patch = bug
    write(repo, "check.py", REPRO_TEST)
    write(repo, "calc.py", BUGGY + "# local edit\n")
    r = gate(repo, patch, "check.py")
    assert r.returncode == 2
    assert "uncommitted changes" in r.stderr
    assert (repo / "calc.py").read_text() == BUGGY + "# local edit\n"


def test_staged_change_counts_as_dirty(bug):
    repo, patch = bug
    write(repo, "check.py", REPRO_TEST)
    write(repo, "extra.txt", "x\n")
    git(repo, "add", "extra.txt")
    assert gate(repo, patch, "check.py").returncode == 2


def test_patch_that_does_not_apply_is_a_harness_error(bug):
    repo, patch = bug
    write(repo, "check.py", REPRO_TEST)
    write(repo, "calc.py", "def avg(total, n):\n    return 0\n")
    git(repo, "commit", "-q", "-am", "diverge")
    r = gate(repo, patch, "check.py")
    assert r.returncode == 2
    assert "does not apply" in r.stderr


def test_missing_command_is_a_harness_error_never_red(bug):
    repo, patch = bug
    r = gate(repo, patch, "x", cmd=["definitely-not-a-real-command-xyz"])
    assert r.returncode == 2
    assert "command not found" in r.stderr
    assert tree_is_clean(repo)


def test_timeout_during_the_green_run_restores_the_tree(bug):
    repo, patch = bug
    # Fails fast on the buggy tree; hangs once the fix is applied.
    write(repo, "check.py",
          "import time, calc\n"
          "if calc.avg.__code__.co_argcount and 'n == 0' in open('calc.py').read():\n"
          "    time.sleep(30)\n"
          "assert calc.avg(10, 0) == 0\n")
    r = gate(repo, patch, "check.py", "--timeout", "3")
    assert r.returncode == 2
    assert "timed out" in r.stderr
    assert (repo / "calc.py").read_text() == BUGGY
    assert tree_is_clean(repo)


def test_missing_command_separator_and_patch_are_usage_errors(bug):
    repo, patch = bug
    assert py("red_green_gate.py", "--fix", str(patch)).returncode == 2
    r = py("red_green_gate.py", "--fix", str(repo / "nope.patch"), "--dir", str(repo),
           "--", sys.executable, "-c", "pass")
    assert r.returncode == 2


# --- verdict matrix: every runner x scenario; the gate only consumes the command's exit code ---

# (case id, n, expected avg(10, n), gate exit, output fragment)
SCENARIOS = [
    ("pass", 0, 0, 0, "RED->GREEN: PASS"),
    ("false", 2, 5, 1, "false reproduction"),
    ("still_red", 0, 99, 1, "still FAILS after the fix"),
]
UNITTEST_TMPL = (
    "import unittest\nimport calc\n\n\n"
    "class T(unittest.TestCase):\n"
    "    def test_it(self):\n"
    "        self.assertEqual(calc.avg(10, {n}), {want})\n"
)
SH_TMPL = 'cd "$(dirname "$0")" && python_out=$("{py}" -c "import calc; raise SystemExit(calc.avg(10, {n}) != {want})")\n'
RUNNERS = [
    "python",
    "unittest",
    pytest.param("sh", marks=pytest.mark.skipif(sys.platform == "win32", reason="POSIX sh test command")),
]


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("name,n,want,code,fragment", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_verdict_matrix(bug, runner, name, n, want, code, fragment):
    repo, patch = bug
    if runner == "python":
        write(repo, "check.py", "import calc\nassert calc.avg(10, %d) == %d\n" % (n, want))  # untracked, like a generated test
        cmd = [sys.executable, "check.py"]
    elif runner == "unittest":
        write(repo, "check_ut.py", UNITTEST_TMPL.format(n=n, want=want))
        cmd = [sys.executable, "-m", "unittest", "check_ut"]
    else:
        write(repo, "check.sh", SH_TMPL.format(py=sys.executable, n=n, want=want))
        cmd = ["sh", str(repo / "check.sh")]
    r = gate(repo, patch, None, cmd=cmd)
    assert r.returncode == code, r.stdout + r.stderr
    assert fragment in r.stdout
    assert tree_is_clean(repo)
    if runner == "python" and name == "pass":
        assert (repo / "calc.py").read_text() == BUGGY
        assert (repo / "check.py").exists()  # the test under evaluation is left alone


@pytest.mark.parametrize("warm_cache", [False, True], ids=["cold", "cached"])
@pytest.mark.parametrize("runner", RUNNERS)
def test_same_size_fix_in_same_timestamp_second(repo, runner, warm_cache, monkeypatch):
    buggy = "value = 0\n"
    fixed = "value = 1\n"
    assert len(buggy) == len(fixed)
    source = write(repo, "calc.py", buggy)
    git(repo, "add", "calc.py")
    git(repo, "commit", "-q", "-m", "buggy value")
    write(repo, "calc.py", fixed)
    patch = repo.parent / "fix.patch"
    patch.write_bytes(git(repo, "diff").encode("utf-8"))
    git(repo, "checkout", "-q", "calc.py")
    # Pin both runs to the same timestamp second without racing the wall clock.
    timestamp = 1700000000
    os.utime(str(source), (timestamp, timestamp))
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    if warm_cache:
        result = run([sys.executable, "-c", "import calc"], cwd=str(repo))
        assert result.returncode == 0, result.stderr
    cached = {path: path.read_bytes() for path in repo.rglob("*.pyc")}
    assert bool(cached) == warm_cache
    body = "import os\nos.utime('calc.py', ({0}, {0}))\nimport calc\n".format(timestamp)
    if runner == "unittest":
        # unittest exits 5 (NO TESTS RAN) on 3.12+ when the module it imports has no TestCase.
        body += ("import unittest\n\n\n"
                 "class T(unittest.TestCase):\n"
                 "    def test_value(self):\n"
                 "        self.assertEqual(calc.value, 1)\n")
    else:
        body += "assert calc.value == 1\n"
    write(repo, "check.py", body)
    if runner == "python":
        cmd = [sys.executable, "check.py"]
    elif runner == "unittest":
        cmd = [sys.executable, "-m", "unittest", "check"]
    else:
        write(repo, "check.sh", '"{0}" check.py\n'.format(sys.executable))
        cmd = ["sh", str(repo / "check.sh")]
    result = gate(repo, patch, None, cmd=cmd)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RED->GREEN: PASS" in result.stdout
    assert source.read_text() == buggy
    assert tree_is_clean(repo)
    assert {path: path.read_bytes() for path in repo.rglob("*.pyc")} == cached
