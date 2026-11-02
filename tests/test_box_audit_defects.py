"""Characterization of the box audit's defects collector (collect.defects): the whole result,
pinned exactly, for local git history and bug forms read alone and alongside a host that answers
in full, in part or not at all. Real git in temporary repositories; the host is a runner of
invented responses. The local evidence must read the same whatever the host does."""
import os
import sys
from pathlib import Path

import pytest

from conftest import git, run, write

SCRIPTS = Path(__file__).resolve().parent.parent / "box" / "skills" / "box-audit" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import collect  # noqa: E402

LABELS = "repos/owner/app/labels?per_page=100"
ISSUES = "repos/owner/app/issues?state=all&per_page=100&labels=%s"

# Oldest first: (subject, files, day). Each commit gets its own day so log order is fixed.
HISTORY = [
    ("Add the app", ["src/app.py", "src/util.py", "README.md"], 1),
    ("fix: parser crash (#3)", ["src/app.py", "tests/test_app.py"], 2),
    ("Fix the loader", ["src/app.py"], 3),
    ("hotfix: config default", ["config.ini"], 4),
    ("Update docs; fixes #4", ["docs/a.md", "docs/b.md"], 5),
    ('Revert "fix: parser crash (#3)"', ["src/app.py", "tests/test_app.py"], 6),
    ("revert: drop the cache", ["src/cache.py"], 7),
    ("Revert the logo", ["web/logo.svg"], 8),
    ("fix: " + "a very long subject " * 8, ["src/long.py"], 9),
    ("bugfix: off by one", ["src/app.py"], 10),
    ("fix: retry once", ["src/net.py", "src/net_test.py"], 11),
    ("fix: timezone", ["src/time.py"], 12),
    ("fix: unicode names", ["src/names.py"], 13),
    ("Refactor names", ["src/names.py", "src/util.py"], 14),
]


def commit_on(repo, subject, files, day=None):
    """Commit `files` with `subject`, dated 2026-10-`day` (today when no day is given)."""
    for f in files:
        write(repo, f, "%s %s\n" % (f, day))
    git(repo, "add", "-A")
    env = dict(os.environ)
    if day:
        stamp = "2026-10-%02dT12:00:00+00:00" % day
        env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    proc = run(["git", "-C", str(repo), "commit", "-q", "-m", subject], env=env)
    assert proc.returncode == 0, proc.stderr
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def history(repo):
    """The HISTORY commits on main, a side branch merged with a fix-looking merge subject, and
    three issue forms: two bug forms, one asking for the introducing change, and a feature form.
    Returns the repo and each subject's commit id."""
    git(repo, "branch", "-M", "main")
    write(repo, ".github/ISSUE_TEMPLATE/bug_report.yml", "label: Which commit introduced it?\n")
    write(repo, ".github/ISSUE_TEMPLATE/Bug-UI.md", "Steps to reproduce\n")
    write(repo, ".github/ISSUE_TEMPLATE/feature.md", "Which change introduced the need?\n")
    sha = {"forms": commit_on(repo, "Add issue forms", [])}
    for subject, files, day in HISTORY:
        sha[subject] = commit_on(repo, subject, files, day)
    git(repo, "checkout", "-q", "-b", "side")
    sha["fix: side branch"] = commit_on(repo, "fix: side branch", ["src/side.py"], 15)
    git(repo, "checkout", "-q", "main")
    stamp = "2026-10-16T12:00:00+00:00"
    proc = run(["git", "-C", str(repo), "merge", "-q", "--no-ff", "-m", "fix: merge side", "side"],
               env=dict(os.environ, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp))
    assert proc.returncode == 0, proc.stderr
    return repo, sha


def context(repo, branch="main", host=None, reason="skipped with --no-remote"):
    # Listed with the tests' git, so the collector's own git calls are the only ones recorded.
    files = sorted(git(repo, "ls-files").splitlines())
    return {"repo": repo, "files": files, "default_branch": branch,
            "host": host, "host_reason": reason}


def fake_host(routes):
    """A host answering from `routes` (path: (body, error)); unknown paths are a 404. Its
    `calls` list records every path asked for, in order."""
    calls = []

    def runner(path):
        calls.append(path)
        return routes.get(path, (None, "HTTP 404"))
    host = collect.Host("owner/app", runner=runner)
    host.calls = calls
    return host


@pytest.fixture
def git_calls(monkeypatch):
    """Every git argument list the collector runs, in order."""
    calls, real = [], collect.git

    def recording(repo, *args):
        calls.append(list(args))
        return real(repo, *args)
    monkeypatch.setattr(collect, "git", recording)
    return calls


def verified(claim):
    return {"claim": claim, "source": "git log", "basis": "verified"}


# Both bug forms in path order (upper case first); the feature form is not one.
FORMS = [{"claim": "bug form .github/ISSUE_TEMPLATE/Bug-UI.md does not ask which change "
                   "introduced the defect", "source": ".github/ISSUE_TEMPLATE/Bug-UI.md",
          "basis": "read"},
         {"claim": "bug form .github/ISSUE_TEMPLATE/bug_report.yml asks which change introduced "
                   "the defect", "source": ".github/ISSUE_TEMPLATE/bug_report.yml",
          "basis": "read"}]


def local_items(sha, ref="main"):
    def example(subject, day, suffix=" (no test file changed)"):
        return verified("%s 2026-10-%02d %s%s" % (sha[subject][:10], day, subject[:100], suffix))
    return [
        verified("last 17 non-merge commits on %s: 13 look like fixes, 3 of those touched a "
                 "test file, 3 reverts" % ref),
        # Reverts first, newest first, whether or not they also look like fixes or touch tests.
        example("Revert the logo", 8, ""),
        example("revert: drop the cache", 7, ""),
        example('Revert "fix: parser crash (#3)"', 6, ""),
        # Then fixes with no test file, newest first, until eight examples in all.
        example("fix: side branch", 15),
        example("fix: unicode names", 13),
        example("fix: timezone", 12),
        example("bugfix: off by one", 10),
        example("fix: " + "a very long subject " * 8, 9),
    ] + FORMS


LOCAL_DATA = {"commits": 17, "fixes": 13, "fixes_with_tests": 3, "reverts": 3}
LOCAL_GIT = [["rev-parse", "--verify", "-q", "origin/main"],
             ["rev-parse", "--verify", "-q", "main"],
             ["log", "main", "-n", "300", "--no-merges", "--format=%H%x09%cs%x09%s",
              "--name-only"]]


def test_local_history_and_forms_without_a_host(history, git_calls):
    repo, sha = history
    out = collect.defects(context(repo))
    assert out == {"name": "defects", "status": "unavailable", "reason": "skipped with --no-remote",
                   "items": local_items(sha), "data": LOCAL_DATA}
    assert git_calls == LOCAL_GIT


def test_the_remote_tracking_default_is_preferred_then_local_then_head(history, git_calls):
    repo, sha = history
    git(repo, "update-ref", "refs/remotes/origin/main", sha["hotfix: config default"])
    out = collect.defects(context(repo))
    # origin/main stops at the hotfix: init, forms and four HISTORY commits.
    assert out == {"name": "defects", "status": "unavailable", "reason": "skipped with --no-remote",
                   "items": [
                       verified("last 6 non-merge commits on origin/main: 3 look like fixes, 1 "
                                "of those touched a test file, 0 reverts"),
                       verified("%s 2026-10-04 hotfix: config default (no test file changed)"
                                % sha["hotfix: config default"][:10]),
                       verified("%s 2026-10-03 Fix the loader (no test file changed)"
                                % sha["Fix the loader"][:10])] + FORMS,
                   "data": {"commits": 6, "fixes": 3, "fixes_with_tests": 1, "reverts": 0}}
    assert git_calls == [["rev-parse", "--verify", "-q", "origin/main"],
                         ["log", "origin/main", "-n", "300", "--no-merges",
                          "--format=%H%x09%cs%x09%s", "--name-only"]]
    # No branch by the default's name: HEAD, whatever is checked out.
    del git_calls[:]
    git(repo, "checkout", "-q", sha["Fix the loader"])
    out = collect.defects(context(repo, branch="trunk"))
    assert out == {"name": "defects", "status": "unavailable", "reason": "skipped with --no-remote",
                   "items": [
                       verified("last 5 non-merge commits on HEAD: 2 look like fixes, 1 of those "
                                "touched a test file, 0 reverts"),
                       verified("%s 2026-10-03 Fix the loader (no test file changed)"
                                % sha["Fix the loader"][:10])] + FORMS,
                   "data": {"commits": 5, "fixes": 2, "fixes_with_tests": 1, "reverts": 0}}
    assert git_calls == [["rev-parse", "--verify", "-q", "origin/trunk"],
                         ["rev-parse", "--verify", "-q", "trunk"],
                         ["log", "HEAD", "-n", "300", "--no-merges",
                          "--format=%H%x09%cs%x09%s", "--name-only"]]
    assert not any(c[0] in ("fetch", "pull", "remote") for c in git_calls)


def test_a_history_git_cannot_read_counts_zero(tmp_path, git_calls):
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    out = collect.defects(context(empty))
    assert out == {"name": "defects", "status": "unavailable", "reason": "skipped with --no-remote",
                   "items": [verified("last 0 non-merge commits on HEAD: 0 look like fixes, 0 of "
                                      "those touched a test file, 0 reverts")],
                   "data": {"commits": 0, "fixes": 0, "fixes_with_tests": 0, "reverts": 0}}
    assert git_calls == [["rev-parse", "--verify", "-q", "origin/main"],
                         ["rev-parse", "--verify", "-q", "main"],
                         ["log", "HEAD", "-n", "300", "--no-merges",
                          "--format=%H%x09%cs%x09%s", "--name-only"]]


def test_refused_labels_keep_the_local_evidence(history, git_calls):
    repo, sha = history
    host = fake_host({LABELS: (None, "HTTP 403")})
    out = collect.defects(context(repo, host=host, reason=None))
    assert out == {"name": "defects", "status": "ok",
                   "items": local_items(sha) + [{"claim": "labels unavailable: HTTP 403",
                                                 "source": "api labels", "basis": "verified"}],
                   "data": LOCAL_DATA}
    assert host.calls == [LABELS]
    assert git_calls == LOCAL_GIT


def test_defect_labels_all_refused_keep_the_local_evidence(history):
    repo, sha = history
    host = fake_host({LABELS: ([{"name": "bug"}, {"name": "docs"}, {"name": "Regression"}], None),
                      ISSUES % "bug": (None, "HTTP 403")})
    out = collect.defects(context(repo, host=host, reason=None))
    assert out == {"name": "defects", "status": "unavailable",
                   "reason": "issues: refused for all 2 defect labels ('bug': HTTP 403, "
                             "'Regression': HTTP 404)",
                   "items": local_items(sha),
                   "data": dict(LOCAL_DATA, issues_unavailable=["bug", "Regression"])}
    assert host.calls == [LABELS, ISSUES % "bug", ISSUES % "Regression"]


def issue(number, created, state="closed", title="", body="", labels=("bug",), pr=False):
    out = {"number": number, "state": state, "title": title, "body": body,
           "created_at": created, "labels": [{"name": n} for n in labels]}
    if pr:
        out["pull_request"] = {}
    return out


def api(claim, source="api issues"):
    return {"claim": claim, "source": source, "basis": "verified"}


def test_a_complete_host_read_follows_the_local_evidence(history):
    repo, sha = history
    host = fake_host({
        LABELS: ([{"name": "bug"}, {"name": "enhancement"}, {"name": "escaped-defect"}], None),
        ISSUES % "bug": ([issue(1, "2026-09-01T00:00:00Z", body="Introduced by #41"),
                          issue(2, "2026-09-03T00:00:00Z", "open", "Bug hunt: crash"),
                          issue(3, "2026-09-02T00:00:00Z", pr=True)], None),
        ISSUES % "escaped-defect": ([issue(2, "2026-09-03T00:00:00Z", "open", "Bug hunt: crash",
                                           labels=("bug", "escaped-defect"))], None)})
    out = collect.defects(context(repo, host=host, reason=None))
    assert out == {"name": "defects", "status": "ok", "items": local_items(sha) + [
        api("label 'bug': 2 issues"),
        api("label 'escaped-defect': 1 issues"),
        api("2 defect-labelled issues; 1 name the change that introduced them; open 1"),
        api("bug-hunt issues by day: 2026-09-03 1"),
        api("#2 2026-09-03 open: Bug hunt: crash"),
        api("#1 2026-09-01 closed: "),
    ], "data": dict(LOCAL_DATA, defect_issues=2, traced=1, bug_hunt_days={"2026-09-03": 1},
                    issues_unavailable=[], issues_incomplete=[], labels_incomplete=None)}
    assert host.calls == [LABELS, ISSUES % "bug", ISSUES % "escaped-defect"]


def test_a_partial_host_read_keeps_the_local_evidence(history, git_calls):
    repo, sha = history
    labels = [{"name": "area-%02d" % i} for i in range(97)] + [
        {"name": "bug"}, {"name": "regression"}, {"name": "hunt"}]
    full = [issue(n, "2026-08-%02dT00:00:00Z" % (n % 28 + 1)) for n in range(100, 200)]
    host = fake_host({
        LABELS: (labels, None),
        LABELS + "&page=2": (None, "HTTP 502"),
        ISSUES % "bug": ([issue(1, "2026-09-01T00:00:00Z", body="Regressed in #12."),
                          issue(2, "2026-09-05T00:00:00Z", "open", "Crash on save"),
                          issue(9, "2026-09-09T00:00:00Z", pr=True)], None),
        ISSUES % "regression": (full, None),
        ISSUES % "regression" + "&page=2": (None, "HTTP 403"),
        ISSUES % "hunt": (None, "HTTP 403")})
    out = collect.defects(context(repo, host=host, reason=None))
    lower = ("; lower bounds, read in part: labels page 2 HTTP 502; 'regression' issues page 2 "
             "HTTP 403")
    assert out == {"name": "defects", "status": "ok", "items": local_items(sha) + [
        api("label 'bug': 2 issues"),
        api("label 'regression': at least 100 issues (page 2 HTTP 403)"),
        api("issues unavailable for 1 defect labels, not counted: 'hunt': HTTP 403"),
        api("at least 102 defect-labelled issues under 2 of 3 defect labels; 1 name the change "
            "that introduced them; open 1" + lower),
        api("#2 2026-09-05 open: Crash on save"),
        api("#1 2026-09-01 closed: "),
        # Newest first; equal days keep the order the issues were read in.
        api("#111 2026-08-28 closed: "), api("#139 2026-08-28 closed: "),
        api("#167 2026-08-28 closed: "), api("#195 2026-08-28 closed: "),
        api("#110 2026-08-27 closed: "), api("#138 2026-08-27 closed: "),
    ],
        "data": dict(LOCAL_DATA, defect_issues=102, traced=1, bug_hunt_days={},
                     issues_unavailable=["hunt"], issues_incomplete=["regression"],
                     labels_incomplete="page 2 HTTP 502")}
    assert host.calls == [LABELS, LABELS + "&page=2", ISSUES % "bug", ISSUES % "regression",
                          ISSUES % "regression" + "&page=2", ISSUES % "hunt"]
    assert git_calls == LOCAL_GIT
