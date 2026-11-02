"""Characterization of the read-only gh adapters: collect.Host (box-audit), select.Host and
handoff_check.Host (orchestrate), and file_issues.gh_json (box-audit's file mode). A stand-in gh,
driven by a sidecar file rather than the environment it is asked to report, writes the exact bytes
and exit code of each case and logs its argv and environment. No host is contacted."""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "box" / "skills" / "box-audit" / "scripts"
ORCHESTRATE = ROOT / "box" / "orchestrate" / "scripts"
ACCEPT = "Accept: application/vnd.github+json"
KINDS = ["collect", "select", "handoff"]


def load(path, alias):
    spec = importlib.util.spec_from_file_location(alias, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collect = load(AUDIT / "collect.py", "host_read_collect")
selector = load(ORCHESTRATE / "select.py", "host_read_select")
handoff = load(ORCHESTRATE / "handoff_check.py", "host_read_handoff")
file_issues = load(AUDIT / "file_issues.py", "host_read_file_issues")

FAKE_GH = r'''
import json, os, sys
with open(sys.argv[0] + ".case", encoding="utf-8") as f:
    case = json.load(f)
with open(sys.argv[0] + ".log", "w", encoding="utf-8") as f:
    json.dump({"args": sys.argv[1:], "env": dict(os.environ)}, f)
sys.stdout.buffer.write(case["out"].encode("latin-1"))
sys.stderr.buffer.write(case["err"].encode("latin-1"))
sys.stdout.flush()
sys.exit(case["code"])
'''


@pytest.fixture
def fake(tmp_path):
    """gh as an argv list, a function setting the next case, and one reading the call log."""
    script = tmp_path / "gh.py"
    script.write_text(FAKE_GH, encoding="utf-8")

    def case(out="", err="", code=0):
        Path(str(script) + ".case").write_text(json.dumps({"out": out, "err": err, "code": code}),
                                               encoding="utf-8")

    def log():
        return json.loads(Path(str(script) + ".log").read_text(encoding="utf-8"))
    case()
    return [sys.executable, str(script)], case, log


def host(kind, gh):
    if kind == "collect":
        return collect.Host("owner/app", gh=gh)
    if kind == "select":
        return selector.Host("owner/app", gh=gh)
    return handoff.Host(gh=gh)


def get(kind, h):
    return h.get("repos/owner/app/x" if kind == "handoff" else "{repo}/x")


CASES = [  # stdout and stderr as latin-1 text standing for raw bytes, exit code, result
    ('{"a": 1}', "", 0, ({"a": 1}, None)),
    ("[1, 2]", "a warning\n", 0, ([1, 2], None)),
    ("", "", 0, (None, None)),
    ("\n", "", 0, (None, "gh returned non-JSON output")),
    ("{", "", 0, (None, "gh returned non-JSON output")),
    ('"\xff"', "", 0, ("�", None)),
    ('{"a": 1}', "gh: Not Found (HTTP 404)\n", 1, (None, "HTTP 404")),
    ("", "boom\nupstream said HTTP 502\n", 1, (None, "HTTP 502")),
    ("", "", 1, (None, "gh failed")),
    ("", "  \n \n", 1, (None, "gh failed")),
    ("", "\n  first line\nsecond\n", 2, (None, "first line")),
    ("", "x" * 160 + "\nmore", 1, (None, "x" * 160)),
    ("", "y" * 161, 1, (None, "y" * 160)),
    ("", "bad \xff byte", 1, (None, "bad � byte")),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("out, err, code, expected", CASES)
def test_responses(kind, out, err, code, expected, fake):
    gh, case, log = fake
    case(out, err, code)
    assert get(kind, host(kind, gh)) == expected
    assert log()["args"] == ["api", "-X", "GET", "-H", ACCEPT, "repos/owner/app/x"]


def test_handoff_runs_the_argv_it_is_given(fake):
    gh, case, log = fake
    case('{"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": [], '
         '"pageInfo": {"hasNextPage": false, "endCursor": null}}}}}}')
    assert handoff.Host(gh=gh).threads("owner/app", 7) == []
    assert log()["args"] == ["api", "graphql", "-f", "query=" + handoff.THREADS,
                             "-f", "owner=owner", "-f", "name=app", "-F", "number=7"]


@pytest.mark.parametrize("kind", KINDS)
def test_environment_per_caller(kind, fake, monkeypatch):
    """Built at call time: the variables are set after the host is made."""
    gh, case, log = fake
    h = host(kind, gh)
    value = "probe-" + "".join(reversed("value"))
    monkeypatch.setenv("GIT_" + "BOX_PROBE", value)
    monkeypatch.setenv("GIT_TRACE2", "1")
    monkeypatch.setenv("BOX_HOST_PROBE", value)
    if os.name != "nt":
        monkeypatch.setenv("git_" + "box_probe", value)
    case("[]")
    assert get(kind, h) == ([], None)
    env = log()["env"]
    gits = {k: v for k, v in env.items() if k.upper().startswith("GIT_")}
    assert env["BOX_HOST_PROBE"] == value
    if kind in ("collect", "handoff"):
        assert gits == {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_TRACE2": "0",
                        "GIT_TRACE2_EVENT": "0", "GIT_TRACE2_PERF": "0"}
    else:
        assert gits == {k: v for k, v in os.environ.items() if k.upper().startswith("GIT_")}
        assert gits["GIT_BOX_PROBE"] == value and gits["GIT_TRACE2"] == "1"


@pytest.mark.parametrize("kind", KINDS)
def test_no_gh(kind, fake):
    h = host(kind, fake[0])
    h.gh = None
    assert get(kind, h) == (None, "gh CLI not found")


def test_no_gh_fails_handoff_threads(fake):
    h = handoff.Host(gh=fake[0])
    h.gh = None
    with pytest.raises(handoff.HostError, match="^review threads: gh CLI not found$"):
        h.threads("owner/app", 7)


def test_a_missing_executable_fails_alike(tmp_path):
    results = {kind: get(kind, host(kind, [str(tmp_path / "no-such-gh")])) for kind in KINDS}
    assert len(set(results.values())) == 1, results
    body, error = results["collect"]
    assert body is None and error.startswith("gh failed: ")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("raised", ["timeout", "launch"])
def test_timeout_and_launch_failure(kind, raised, monkeypatch):
    seen = []

    def run(argv, **kw):
        seen.append((argv, kw))
        if raised == "timeout":
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        raise OSError("synthetic launch failure")
    monkeypatch.setattr(subprocess, "run", run)
    argv = ["gh-stand-in", "api", "-X", "GET", "-H", ACCEPT, "repos/owner/app/x"]
    error = {"timeout": "gh failed: %s" % subprocess.TimeoutExpired(argv, 60),
             "launch": "gh failed: synthetic launch failure"}[raised]
    assert get(kind, host(kind, ["gh-stand-in"])) == (None, error)
    [(called, kw)] = seen
    assert called == argv
    assert (kw["timeout"], kw["capture_output"], kw["text"], kw["encoding"], kw["errors"]) == (
        60, True, True, "utf-8", "replace")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("result", [({"a": 1}, None), (None, "HTTP 500")])
def test_injected_runner_shape(kind, result):
    calls = []

    def runner(arg):
        calls.append(arg)
        return result
    h = {"collect": lambda: collect.Host("owner/app", runner=runner),
         "select": lambda: selector.Host("owner/app", runner=runner),
         "handoff": lambda: handoff.Host(runner=runner)}[kind]()
    assert get(kind, h) is result
    assert calls == [["api", "-X", "GET", "-H", ACCEPT, "repos/owner/app/x"]
                     if kind == "handoff" else "repos/owner/app/x"]


@pytest.mark.parametrize("name, args", [
    ("select.py", ["--repo", "owner/app"]),
    ("handoff_check.py", ["--repo", "owner/app", "--pr", "12"]),
])
def test_a_host_error_exits_3(name, args, fake):
    gh, case, _ = fake
    case("", "gh: Server Error (HTTP 500)\n", 1)
    command = " ".join('"%s"' % Path(p).as_posix() for p in gh)
    r = subprocess.run([sys.executable, str(ORCHESTRATE / name)] + args + ["--gh", command],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 3, r.stdout + r.stderr
    assert r.stderr.startswith(name[:-3] + ": host error: ") and "HTTP 500" in r.stderr, r.stderr


@pytest.mark.parametrize("module", [collect, selector, handoff], ids=KINDS)
def test_one_implementation_loaded_from_this_checkout(module):
    assert Path(module.gh_read.__file__) == ROOT / "box" / "lib" / "gh_read.py"


@pytest.mark.parametrize("module", [collect, handoff], ids=["collect", "handoff"])
def test_one_git_environment_loaded_from_this_checkout(module):
    assert module.git_env.__code__.co_filename == str(ROOT / "box" / "lib" / "git_env.py")


@pytest.mark.parametrize("folder,name", [(AUDIT, "collect"), (ORCHESTRATE, "handoff_check")],
                         ids=["collect", "handoff"])
def test_loads_them_without_writing_bytecode(tmp_path, folder, name):
    """Each script turns bytecode off before loading the helpers, so an inherited
    PYTHONPYCACHEPREFIX, which may point inside an audited checkout, gets nothing from it. A fresh
    interpreter per script: this module's own imports already turned bytecode off here."""
    prefix = tmp_path / "cache"
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(prefix))
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, sys.argv[1]); import " + name, str(folder)],
                       cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert not list(prefix.rglob("gh_read*.pyc")) and not list(prefix.rglob("git_env*.pyc"))


def test_file_issues_loads_the_one_implementation():
    assert Path(file_issues.gh_read.__file__) == ROOT / "box" / "lib" / "gh_read.py"


@pytest.mark.parametrize("out, err, code, expected", [
    ("[]", "", 0, ([], None)),
    ("{", "", 0, (None, "gh returned non-JSON output")),
    ("", "boom\nsecond line\n", 1, (None, "boom")),
])
def test_file_issues_read_responses_unchanged(out, err, code, expected, fake):
    gh, case, log = fake
    case(out, err, code)
    assert file_issues.gh_json(gh, ["api", "repos/owner/app/x"]) == expected
    assert log()["args"] == ["api", "repos/owner/app/x"]


@pytest.mark.parametrize("out, err, code, expected", CASES)
def test_file_issues_read_errors_match_gh_read(out, err, code, expected, fake):
    gh, case, _ = fake
    case(out, err, code)
    assert file_issues.gh_json(gh, ["api", "repos/owner/app/x"]) == expected


def test_file_issues_read_stops_at_the_shared_timeout(tmp_path, monkeypatch):
    slow = tmp_path / "slow_gh.py"
    slow.write_text("import time\ntime.sleep(20)\n", encoding="utf-8")
    monkeypatch.setattr(file_issues.gh_read, "TIMEOUT", 1)
    started = time.monotonic()
    body, error = file_issues.gh_json([sys.executable, str(slow)], ["api", "repos/owner/app/x"])
    assert body is None and error.startswith("gh failed: ") and "timed out" in error, error
    assert time.monotonic() - started < 10


def pager(sizes, errors=None):
    """fetch(page) for gh_read.paged: page n has sizes[n - 1] entries (0 past the end), or the
    error errors[n]. The pages asked for are logged."""
    calls = []

    def fetch(page):
        calls.append(page)
        if page in (errors or {}):
            return None, errors[page]
        size = sizes[page - 1] if page <= len(sizes) else 0
        return list(range(page * 1000, page * 1000 + size)), None
    fetch.calls = calls
    return fetch


@pytest.mark.parametrize("sizes, read, pages", [
    ([7], 7, [1]),
    ([], 0, [1]),
    ([100, 100, 3], 203, [1, 2, 3]),
    ([100] * 10, 1000, list(range(1, 12))),
])
def test_paged_reads_to_the_last_page(sizes, read, pages):
    fetch = pager(sizes)
    entries, error = selector.gh_read.paged(fetch)
    assert error is None and len(entries) == read and fetch.calls == pages


def test_paged_more_than_max_pages_full_pages_is_an_error():
    fetch = pager([100] * 10 + [1])
    assert selector.gh_read.paged(fetch) == (None, "more than 10 pages")
    assert fetch.calls == list(range(1, 12))


def test_paged_returns_the_first_error():
    fetch = pager([100, 100, 100], {2: "HTTP 502"})
    assert selector.gh_read.paged(fetch) == (None, "HTTP 502")
    assert fetch.calls == [1, 2]


def test_paged_honours_its_bounds():
    fetch = pager([5, 5, 5, 1])
    assert selector.gh_read.paged(fetch, per_page=5, max_pages=2) == (None, "more than 2 pages")
    assert selector.gh_read.paged(pager([5, 5, 0]), per_page=5, max_pages=2)[0] == list(
        range(1000, 1005)) + list(range(2000, 2005))


def test_one_page_bound_for_both_orchestrate_scripts():
    assert "MAX_PAGES" not in vars(selector) and "MAX_PAGES" not in vars(handoff)
    assert selector.gh_read.MAX_PAGES == handoff.gh_read.MAX_PAGES == 10
