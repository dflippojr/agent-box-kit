"""The `outside_checkout` marker: a test that needs pytest's temp dir outside any git checkout
fails at setup, with the cause and the fix, when the base temp dir sits inside one. It fails
rather than skips, because a skip reads as green."""
import re
from pathlib import Path

from conftest import git

CONFTEST = Path(__file__).resolve().parent / "conftest.py"

MESSAGE = "needs a temp dir outside any git checkout: pass --basetemp=<dir outside one>"


def test_marked_test_fails_at_setup_inside_a_checkout(pytester):
    pytester.makeconftest(CONFTEST.read_text(encoding="utf-8"))
    pytester.makepyfile(test_layout='''
        import pytest

        @pytest.mark.outside_checkout
        def test_marked(tmp_path):
            pass

        def test_unmarked(tmp_path):
            pass
    ''')
    checkout = pytester.path / "checkout"
    checkout.mkdir()
    git(checkout, "init", "-q")
    (checkout / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    (checkout / "scratch").mkdir()  # pytest makes the base temp dir, not its parents
    result = pytester.runpytest("-p", "no:cacheprovider", "--strict-markers",
                                "--basetemp=%s" % (checkout / "scratch" / "pytest"))
    result.assert_outcomes(passed=1, errors=1)
    # The setup error's own text is the message; the short summary may repeat it, depending on
    # the terminal width, so match it under the header rather than counting it.
    result.stdout.re_match_lines([r".*ERROR at setup of test_marked.*", "^" + re.escape(MESSAGE)],
                                 consecutive=True)
