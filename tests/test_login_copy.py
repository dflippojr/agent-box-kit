"""Characterization tests for the home-file (login) copy that box-audit's judge (judge.run) and
skill-eval's runner (runner.session) share: what is copied, in what order, what is recorded for
write-back, when the isolated environment is made, and when a refreshed login is written back.
Both callers run here end to end with a small Python program standing in for an agent CLI; the
spies only record calls and pass them through to the real functions."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from conftest import write

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "box" / "skills" / "box-audit" / "scripts"))
sys.path.insert(0, str(ROOT / "box" / "skills" / "skill-eval" / "scripts"))

import judge  # noqa: E402
import runner  # noqa: E402

MARKER = "LOGIN_COPY_TEST_INSTRUCTIONS.md"
# Nested at different depths; bytes a text-mode copy or a re-encoding would change.
LOGINS = {
    ".agent/login.json": b'{"session": "one"}\r\n',
    ".config/tool/nested/token.bin": b"\x00\xffbinary\r\nlogin\n",
    "top-level.dat": "café\n".encode("utf-8"),
}
CALLERS = ("judge", "runner")


@pytest.fixture
def owner(tmp_path, monkeypatch):
    home = tmp_path / "owner-home"
    for rel, data in LOGINS.items():
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("OWNER_SECRET", "canary-value")
    monkeypatch.setenv("LOGIN_KEEP", "kept-value")
    # Only the test's marker counts as an instruction file, so the folders above the temp dir
    # do not decide the outcome. The other box tests do the same.
    monkeypatch.setattr(judge, "INSTRUCTION_ENTRIES", (MARKER,))
    root = tmp_path / "work-root"
    root.mkdir()
    bundle = tmp_path / "bundle"
    write(bundle, "prompt.md", "Score this repo.\n")
    calls = {"env": [], "write_back": []}
    real_env, real_write_back = judge.isolated_env, judge.write_back

    def env_spy(home_arg, keep):
        calls["env"].append({"home": Path(home_arg), "keep": list(keep), "files": {
            rel: (Path(home_arg) / rel).read_bytes() if (Path(home_arg) / rel).is_file() else None
            for rel in LOGINS}})
        return real_env(home_arg, keep)

    def write_back_spy(original, copy, before):
        calls["write_back"].append((original, copy, before, copy.read_bytes()))
        return real_write_back(original, copy, before)

    monkeypatch.setattr(judge, "isolated_env", env_spy)
    monkeypatch.setattr(judge, "write_back", write_back_spy)
    return {"tmp": tmp_path, "home": home, "root": root, "bundle": bundle, "calls": calls}


def cli(owner, body):
    """A fake agent CLI: reads the prompt, records what it saw, then runs `body`."""
    path = write(owner["tmp"] / "cli", "agent.py",
                 "import json, os, sys, time\nsys.stdin.read()\n"
                 "seen = {k: os.environ.get(k) for k in ('HOME', 'LOGIN_KEEP', 'OWNER_SECRET')}\n"
                 "open(%r, 'w').write(json.dumps(seen))\n" % str(owner["tmp"] / "seen.json")
                 + body + "print('done')\n")
    return [sys.executable, str(path)]


def refresh(rels, data):
    """CLI body: rewrite each copied login in the isolated home."""
    return "".join("open(os.path.join(os.environ['HOME'], %r), 'wb').write(%r)\n" % (rel, data)
                   for rel in rels)


def launch(caller, owner, command, copy=tuple(LOGINS), timeout=60):
    """Run one session through `caller`; return judge.run's exit code or runner's record."""
    if caller == "judge":
        return judge.run(owner["bundle"], command, keep=["LOGIN_KEEP"], copy=list(copy),
                         timeout=timeout, work_root=str(owner["root"]))
    profile = {"command": command, "budget_args": [], "skills_dir": ".fake/skills",
               "result": "stdout", "cost": {"match": {"type": "result"}, "field": "cost"}}
    return runner.session(profile, "Make a widget.\n", owner["root"], keep=["LOGIN_KEEP"],
                          copy=list(copy), timeout=timeout)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def test_runner_reuses_the_judges_isolation_module():
    assert runner.iso is judge


@pytest.mark.parametrize("caller", CALLERS)
def test_copies_keep_order_bytes_resolved_originals_and_hashes_and_env_comes_after(caller, owner):
    out = launch(caller, owner, cli(owner, ""))
    assert out == 0 if caller == "judge" else out["exit"] == 0 and out["error"] is None
    calls = owner["calls"]
    assert len(calls["env"]) == 1
    made = calls["env"][0]
    assert made["keep"] == ["LOGIN_KEEP"]
    assert made["files"] == LOGINS  # every copy is in place, byte for byte, before the env
    assert [c[0] for c in calls["write_back"]] == [(owner["home"] / rel).resolve()
                                                   for rel in LOGINS]
    assert [c[1] for c in calls["write_back"]] == [made["home"] / rel for rel in LOGINS]
    assert [c[2] for c in calls["write_back"]] == [sha(d) for d in LOGINS.values()]
    assert [c[3] for c in calls["write_back"]] == list(LOGINS.values())
    seen = json.loads((owner["tmp"] / "seen.json").read_text())
    assert seen == {"HOME": str(made["home"]), "LOGIN_KEEP": "kept-value", "OWNER_SECRET": None}
    for rel, data in LOGINS.items():
        assert (owner["home"] / rel).read_bytes() == data
    assert list(owner["root"].iterdir()) == []


@pytest.mark.parametrize("caller", CALLERS)
def test_a_later_copy_that_fails_stops_before_the_env_and_writes_nothing_back(
        caller, owner, monkeypatch):
    rels = list(LOGINS)
    real_copyfile = shutil.copyfile

    def copyfile(src, dst, *a, **kw):
        if Path(src) == owner["home"] / rels[1]:
            raise PermissionError("synthetic copy failure")
        return real_copyfile(src, dst, *a, **kw)

    monkeypatch.setattr(shutil, "copyfile", copyfile)
    command = cli(owner, refresh(rels, b"changed"))
    if caller == "judge":
        with pytest.raises(PermissionError, match="synthetic copy failure"):
            launch(caller, owner, command)
    else:
        record = launch(caller, owner, command)
        assert record["infra"] is True and record["exit"] is None
        assert record["error"] == "could not start: PermissionError: synthetic copy failure"
    assert owner["calls"] == {"env": [], "write_back": []}
    assert not (owner["tmp"] / "seen.json").exists()  # the CLI never started
    for rel, data in LOGINS.items():
        assert (owner["home"] / rel).read_bytes() == data
    assert list(owner["root"].iterdir()) == []


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("ending", ("succeeds", "fails", "times out"))
def test_a_refreshed_login_is_written_back_however_the_session_ends(caller, ending, owner):
    tail = {"succeeds": "", "fails": "sys.exit(3)\n",
            "times out": "sys.stdout.flush()\ntime.sleep(60)\n"}[ending]
    out = launch(caller, owner, cli(owner, refresh(LOGINS, b"refreshed") + tail),
                 timeout=3 if ending == "times out" else 60)
    if caller == "judge":
        assert out == (0 if ending == "succeeds" else 1)
    else:
        assert out["infra"] is False
        assert out["timed_out"] is (ending == "times out")
        assert out["exit"] == {"succeeds": 0, "fails": 3, "times out": None}[ending]
    assert len(owner["calls"]["write_back"]) == len(LOGINS)
    for rel in LOGINS:
        assert (owner["home"] / rel).read_bytes() == b"refreshed"
    assert list(owner["root"].iterdir()) == []


@pytest.mark.parametrize("caller", CALLERS)
def test_a_command_that_is_not_found_writes_nothing_back(caller, owner):
    out = launch(caller, owner, ["no-such-login-copy-cli"])
    if caller == "judge":
        assert out == 2
    else:
        assert out["infra"] is True
        assert out["error"] == "command not found: no-such-login-copy-cli"
    assert len(owner["calls"]["env"]) == 1  # the copies and env were made before the lookup
    assert owner["calls"]["write_back"] == []
    for rel, data in LOGINS.items():
        assert (owner["home"] / rel).read_bytes() == data
    assert list(owner["root"].iterdir()) == []


@pytest.mark.parametrize("caller", CALLERS)
def test_an_unchanged_copy_leaves_the_original_untouched(caller, owner, capfd):
    old = 1000000000
    for rel in LOGINS:
        os.utime(str(owner["home"] / rel), (old, old))
    launch(caller, owner, cli(owner, ""))
    for rel, data in LOGINS.items():
        assert (owner["home"] / rel).read_bytes() == data
        assert int((owner["home"] / rel).stat().st_mtime) == old
    assert "wrote the refreshed" not in capfd.readouterr().err


@pytest.mark.parametrize("caller", CALLERS)
def test_an_original_the_owner_changed_meanwhile_is_kept(caller, owner):
    real = owner["home"] / ".agent" / "login.json"
    launch(caller, owner, cli(owner, refresh([".agent/login.json"], b"refreshed")
                              + "open(%r, 'wb').write(b'owner-newer')\n" % str(real)))
    assert real.read_bytes() == b"owner-newer"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
@pytest.mark.parametrize("caller", CALLERS)
def test_the_original_is_resolved_when_copied_not_when_written_back(caller, owner):
    first, second = owner["tmp"] / "store-a", owner["tmp"] / "store-b"
    write(first, "login.json", "one")
    write(second, "login.json", "other")
    link = owner["home"] / "linked"
    os.symlink(str(first), str(link))
    retarget = "os.remove(%r)\nos.symlink(%r, %r)\n" % (str(link), str(second), str(link))
    launch(caller, owner, cli(owner, refresh(["linked/login.json"], b"refreshed") + retarget),
           copy=["linked/login.json"])
    assert owner["calls"]["write_back"][0][0] == (first / "login.json").resolve()
    assert (first / "login.json").read_bytes() == b"refreshed"
    assert (second / "login.json").read_bytes() == b"other"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
@pytest.mark.parametrize("caller", CALLERS)
def test_a_folder_that_became_a_link_is_not_written_back(caller, owner, capfd):
    folder = owner["home"] / ".agent"
    moved = owner["home"] / ".agent-moved"
    swap = "os.rename(%r, %r)\nos.symlink(%r, %r)\n" % (str(folder), str(moved), str(moved),
                                                         str(folder))
    launch(caller, owner, cli(owner, refresh([".agent/login.json"], b"refreshed") + swap),
           copy=[".agent/login.json"])
    assert (moved / "login.json").read_bytes() == LOGINS[".agent/login.json"]
    assert "could not write back login.json: a folder on its path is now a link" in (
        capfd.readouterr().err)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
@pytest.mark.parametrize("caller", CALLERS)
def test_a_written_back_login_keeps_the_owners_file_mode(caller, owner):
    for rel in LOGINS:
        os.chmod(str(owner["home"] / rel), 0o600)
    old = os.umask(0o022)
    try:
        launch(caller, owner, cli(owner, refresh(LOGINS, b"refreshed")))
    finally:
        os.umask(old)
    for rel in LOGINS:
        assert (owner["home"] / rel).read_bytes() == b"refreshed"
        assert (owner["home"] / rel).stat().st_mode & 0o777 == 0o600
