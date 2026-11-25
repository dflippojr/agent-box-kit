"""Issue #47, review r2 on PR #48, and the owner's decision in #47 (Linux and macOS now, Windows
tracked separately). The isolated home is opened once, before the session starts, and every later
read and write goes through that descriptor, so a session cannot redefine the home by replacing
it or its parent. A copy is written as a new file created exclusively and then renamed into
place, so an entry already at the destination (a hard link to an outside file, a FIFO) is never
written through, and a folder swapped in during the copy cannot carry folders outside the home.
Where descriptors relative to a folder are missing (Windows), --copy-home is refused with a
stated error.

These tests go through judge.run and skill-eval's runner.session, or through seams both the r1
and r2 code have, so they fail on r1 for behavioural reasons, not on changed signatures."""
import os
import shutil
import sys
import threading
from pathlib import Path

import pytest

from conftest import write

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "box" / "lib"))
sys.path.insert(0, str(ROOT / "box" / "skills" / "skill-eval" / "scripts"))

import isolation  # noqa: E402
import paths  # noqa: E402
import runner  # noqa: E402

needs_links = pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
LOGIN = ".agent/login.json"
REFUSAL = "needs folder descriptors (openat), which this platform lacks"


@pytest.fixture
def owner(tmp_path, monkeypatch):
    real_home = tmp_path / "owner-home"
    write(real_home, LOGIN, "owner-login")
    write(real_home, ".tool/nested/token.bin", "owner-token")
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("USERPROFILE", str(real_home))
    monkeypatch.setattr(isolation, "INSTRUCTION_ENTRIES", ("ANCHOR_TEST_MARKER.md",))
    outside = tmp_path / "out"
    write(outside, "secret.json", "outside-secret")
    write(outside, "home/" + LOGIN, "outside-secret")  # a stand-in home
    write(outside, "run/home/" + LOGIN, "outside-secret")  # a stand-in run folder
    (outside / "dir").mkdir()
    bundle = write(tmp_path / "bundle", "prompt.md", "Score.\n").parent
    work_root = tmp_path / "work-root"
    work_root.mkdir()
    return {"tmp": tmp_path, "real_home": real_home, "outside": outside, "bundle": bundle,
            "work_root": work_root}


def agent(o, body):
    path = write(o["tmp"] / "cli", "agent.py",
                 "import os, sys\nsys.stdin.read()\nh = os.environ['HOME']\n" + body
                 + "print('done')\n")
    return [sys.executable, str(path)]


def launch(caller, o, command, copy=(LOGIN,)):
    if caller == "judge":
        return isolation.run(o["bundle"], command, copy=list(copy), work_root=str(o["work_root"]))
    profile = {"command": command, "budget_args": [], "skills_dir": ".fake/skills",
               "result": "stdout", "cost": {"match": {"type": "result"}, "field": "cost"}}
    return runner.session(profile, "Make a widget.\n", o["work_root"], copy=list(copy),
                          timeout=60)


def outside_unchanged(o):
    assert (o["outside"] / "secret.json").read_text() == "outside-secret"
    assert list((o["outside"] / "dir").iterdir()) == []


@needs_links
@pytest.mark.parametrize("caller", ["judge", "runner"])
@pytest.mark.parametrize("level", ["home", "run folder"])
def test_a_session_that_replaces_its_home_cannot_redefine_the_root(owner, caller, level):
    """Review r2, finding 1: the session renames its home (or the run folder above it) and puts
    a link to an outside tree in its place. Write-back must still read the session's own copy
    through the descriptor opened before the session, not the outside tree."""
    if level == "home":
        body = "os.rename(h, h + '-old')\nos.symlink(%r, h)\n" % str(owner["outside"] / "home")
    else:
        body = ("p = os.path.dirname(h)\nos.rename(p, p + '-old')\nos.symlink(%r, p)\n"
                % str(owner["outside"] / "run"))
    launch(caller, owner, agent(owner, body))
    assert (owner["real_home"] / LOGIN).read_text() == "owner-login"


def plant_before_copy(monkeypatch, plant):
    """Run `plant(home)` right before copy_home writes, through a seam r1 and r2 both have:
    judge.run copies prompt.md into the work folder just before copy_home."""
    real = shutil.copyfile

    def copyfile(src, dst, *a, **kw):
        out = real(src, dst, *a, **kw)
        if Path(dst).name == "prompt.md" and Path(dst).parent.name == "work":
            plant(Path(dst).parent.parent / "home")
        return out

    monkeypatch.setattr(shutil, "copyfile", copyfile)


@pytest.mark.skipif(not hasattr(os, "link"), reason="no hard links")
def test_a_destination_hard_linked_outside_is_not_written_through(owner, monkeypatch):
    """Review r2, finding 2: copying into an existing destination entry that is a hard link to
    an outside file must not truncate or write that file."""
    def plant(home):
        (home / ".agent").mkdir(parents=True)
        os.link(str(owner["outside"] / "secret.json"), str(home / LOGIN))

    plant_before_copy(monkeypatch, plant)
    try:
        code = launch("judge", owner, agent(owner, ""))
    except (OSError, ValueError) as e:  # r1 refuses only after it wrote through the link
        code = e
    outside_unchanged(owner)
    assert code == 0
    assert (owner["real_home"] / LOGIN).read_text() == "owner-login"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs")
def test_a_fifo_at_the_destination_does_not_block_the_copy(owner, monkeypatch):
    """Review r2, finding 2: a FIFO at the destination must not block a write-only open."""
    fifo = []

    def plant(home):
        (home / ".agent").mkdir(parents=True)
        os.mkfifo(str(home / LOGIN))
        fifo.append(home / LOGIN)

    plant_before_copy(monkeypatch, plant)
    result = []
    t = threading.Thread(target=lambda: result.append(launch("judge", owner, agent(owner, ""))),
                         daemon=True)
    t.start()
    t.join(20)
    blocked = t.is_alive()
    if blocked:  # release the writer so the thread ends
        fd = os.open(str(fifo[0]), os.O_RDONLY | os.O_NONBLOCK)
        t.join(20)
        os.close(fd)
    assert not blocked, "the copy blocked on a FIFO at its destination"
    assert result == [0]
    assert (owner["real_home"] / LOGIN).read_text() == "owner-login"


@needs_links
def test_a_folder_swapped_during_the_copy_creates_nothing_outside(owner, monkeypatch):
    """Review r2, finding 2: a folder made for the copy and then swapped for a link out must not
    let the next folder be made outside the home."""
    real = os.mkdir
    done = []

    def mkdir(path, *a, **kw):
        real(path, *a, **kw)
        p = Path(os.fsdecode(path))
        if not done and p.name == ".tool" and (kw.get("dir_fd") is not None
                                                or p.parent.name == "home"):
            done.append(1)
            folder = p if kw.get("dir_fd") is None else fd_dir(kw["dir_fd"]) / p
            os.rename(str(folder), str(folder) + "-old")
            os.symlink(str(owner["outside"] / "dir"), str(folder))

    monkeypatch.setattr(os, "mkdir", mkdir)
    with pytest.raises((OSError, ValueError)):
        launch("judge", owner, agent(owner, ""), copy=[".tool/nested/token.bin"])
    assert done
    outside_unchanged(owner)


def fd_dir(fd):
    """Where folder descriptor fd is (Linux /proc, macOS F_GETPATH)."""
    if sys.platform.startswith("linux"):
        return Path(os.readlink("/proc/self/fd/%d" % fd))
    import fcntl
    return Path(os.fsdecode(fcntl.fcntl(fd, getattr(fcntl, "F_GETPATH"), bytes(1024))
                            .rstrip(b"\0")))


@pytest.mark.parametrize("caller", ["judge", "runner"])
def test_without_folder_descriptors_copy_home_is_refused(owner, monkeypatch, capsys, caller):
    """The owner's decision in #47: with no descriptors relative to a folder (Windows),
    --copy-home is refused with a stated error and nothing is copied. judge.run (and so
    skill-eval's own up-front check) refuses through check_copy; runner.session, which trusts
    its caller's check, fails closed when it opens the anchor. On the Windows CI job this runs
    on the real platform; elsewhere AT_FDS is switched off."""
    monkeypatch.setattr(paths, "AT_FDS", False)
    assert (isolation.check_copy(LOGIN, owner["real_home"]) or "").startswith(REFUSAL)
    out = launch(caller, owner, agent(owner, "open(os.path.join(h, 'ran'), 'w').close()\n"))
    if caller == "judge":
        assert out == 2
        assert ("refusing --copy-home %s: %s" % (LOGIN, REFUSAL)) in capsys.readouterr().err
        assert not any(owner["work_root"].iterdir())  # no run folder, so nothing was copied
    else:
        assert out["infra"] is True and REFUSAL in (out["error"] or "")
        assert out["exit"] is None  # the session never started


@pytest.mark.skipif(paths.AT_FDS, reason="only where the platform has no folder descriptors")
def test_this_platform_refuses_copy_home_without_patching(owner):
    """Runs on the Windows CI job unpatched: the refusal the README documents."""
    assert (isolation.check_copy(LOGIN, owner["real_home"]) or "").startswith(REFUSAL)
    with pytest.raises(OSError, match="folder descriptors"):
        paths.Anchor(owner["real_home"])
