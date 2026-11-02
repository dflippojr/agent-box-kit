"""Tests for the evaluator-experiment baseline (experiments/05-evaluator/heuristic.py)."""
import subprocess
import sys
from pathlib import Path

import pytest

EXPERIMENT = Path(__file__).resolve().parent.parent / "experiments" / "05-evaluator"
sys.path.insert(0, str(EXPERIMENT))

import heuristic  # noqa: E402

SOURCE = "retry attempt=5 base=3.0 max_delay=45 and a size of 2,500,000,000 bytes for `2.5GB`"


def test_literals_skip_trivial_values_and_docstrings():
    code = 'def test_x():\n    """doc 99"""\n    assert f(0, 1, True, None, "", -1) == 7\n'
    assert heuristic.literals(code) == [7]


def test_numbers_match_numerically_and_ignore_thousands_separators():
    found, total = heuristic.grounded_fraction("assert f(5, 3.0, 45) == 2500000000\n", SOURCE)
    assert (found, total) == (4, 4)


def test_strings_match_as_substrings():
    assert heuristic.grounded_fraction("assert f('2.5GB')\n", SOURCE) == (1, 1)
    assert heuristic.grounded_fraction("assert f('9TB')\n", SOURCE) == (0, 1)


def test_pick_returns_the_single_fully_grounded_candidate():
    cands = {"a": "assert f(10, 1.0, 30) == 30\n", "b": "assert f(5, 3.0, 45) == 45\n"}
    assert heuristic.pick(SOURCE, cands) == "b"


@pytest.mark.parametrize("cands", [
    {"a": "assert f(10) == 30\n", "b": "assert f(99) == 31\n"},          # none grounded
    {"a": "assert f(5) == 45\n", "b": "assert f(3.0) == 45\n"},          # two grounded: ambiguous
    {"a": "assert f(0, 1)\n"},                                           # no usable literals
])
def test_pick_makes_no_pick_when_none_or_several_qualify(cands):
    assert heuristic.pick(SOURCE, cands) is None


def test_cli_runs_over_the_committed_cases(tmp_path):
    csv = tmp_path / "h.csv"
    proc = subprocess.run([sys.executable, str(EXPERIMENT / "heuristic.py"), "--csv", str(csv)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    lines = csv.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "case,heuristic_pick,grounded_literals"
    assert len(lines) == 11
