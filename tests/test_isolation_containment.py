"""Issue #47: box/lib/isolation.py's digest(), copy_home() and write_back() keep each path inside
the root it must stay under. A path that escapes (`..` segments, an absolute path elsewhere, a
link that leaves the root at the top or at a nested level) is refused before any file outside
the root is opened, so nothing there is read, hashed or copied. Paths inside the root work as
before.

Review r1 on PR #48 added three cases: a link chain whose middle hop leaves the root and comes
back; a swap of the file or a folder above it between the check and the open (anything the
session started can outlive it and still write its home); and a session copy replaced by a hard
link to an outside file."""
import builtins
import hashlib
import io
import os
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from conftest import write

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "box" / "lib"))

import isolation  # noqa: E402
import paths  # noqa: E402

needs_links = pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")


@pytest.fixture
def tree(tmp_path):
    """An owner home and an isolated home side by side, and a secret outside both."""
    real_home, home, outside = tmp_path / "owner-home", tmp_path / "iso-home", tmp_path / "out"
    write(real_home, ".agent/login.json", "owner-login")
    write(outside, "secret.json", "outside-secret")
    write(outside, "dir/login.json", "outside-login")
    home.mkdir()
    return {"tmp": tmp_path, "real_home": real_home, "home": home, "outside": outside}


@pytest.fixture
def opened(monkeypatch):
    """Every path opened through open() or io.open() while the test runs: shutil.copyfile and
    Path.read_bytes both go through them."""
    seen = []
    real = builtins.open

    def spy(file, *a, **kw):
        if isinstance(file, (str, bytes, os.PathLike)):
            seen.append(Path(os.fsdecode(file)))
        return real(file, *a, **kw)

    real_os_open = os.open

    def os_spy(file, *a, **kw):
        fd = real_os_open(file, *a, **kw)
        where = fd_path(fd)
        if where is not None:
            seen.append(where)
        elif "dir_fd" not in kw:
            seen.append(Path(os.fsdecode(file)))
        return fd

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    monkeypatch.setattr(os, "open", os_spy)
    return seen


def fd_path(fd):
    """Where an open descriptor really is, where the platform can say."""
    try:
        if sys.platform.startswith("linux"):
            return Path(os.readlink("/proc/self/fd/%d" % fd))
        if sys.platform == "darwin":
            import fcntl
            return Path(os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0")))
    except OSError:
        return None
    return None


def read_outside(seen, outside):
    """The opened paths that are, after links, in `outside`."""
    return [p for p in seen if paths.inside(p, outside)]


# The escapes each function is fed: (rel under the root, setup that makes it escape).
def dotdot(t, root):
    return "../out/secret.json"


def absolute(t, root):
    return str(t["outside"] / "secret.json")


def top_link(t, root):
    os.symlink(str(t["outside"] / "secret.json"), str(root / "linked.json"))
    return "linked.json"


def nested_link(t, root):
    os.symlink(str(t["outside"] / "dir"), str(root / "nested"))
    return "nested/login.json"


def out_and_back(t, root):
    """A nested link that leaves the root and a second link that comes back: the final path is
    inside the root, but the walk to it is not."""
    write(root, "real.json", "inside")
    os.symlink(str(root / "real.json"), str(t["outside"] / "back.json"))
    os.symlink(str(t["outside"]), str(root / "via"))
    return "via/back.json"


def chained(t, root):
    """An in-root link whose target is an outside link back into the root: the supplied path
    and the final file are both inside, but the middle hop is not (review r1, finding 2)."""
    write(root, "real.json", "inside")
    os.symlink(str(root / "real.json"), str(t["outside"] / "hop.json"))
    os.symlink(str(t["outside"] / "hop.json"), str(root / "alias.json"))
    return "alias.json"


def chained_folder(t, root):
    write(root, "sub/real.json", "inside")
    os.symlink(str(root / "sub"), str(t["outside"] / "hop"))
    os.symlink(str(t["outside"] / "hop"), str(root / "via"))
    return "via/real.json"


ESCAPES = [pytest.param(dotdot, id="dotdot"), pytest.param(absolute, id="absolute"),
           pytest.param(top_link, id="top-link", marks=needs_links),
           pytest.param(nested_link, id="nested-link", marks=needs_links),
           pytest.param(out_and_back, id="out-and-back", marks=needs_links),
           pytest.param(chained, id="chained", marks=needs_links),
           pytest.param(chained_folder, id="chained-folder", marks=needs_links)]


@pytest.mark.parametrize("escape", ESCAPES)
def test_digest_refuses_a_path_that_escapes_its_root(tree, opened, escape):
    root = tree["home"]
    rel = escape(tree, root)
    with pytest.raises(ValueError):
        isolation.digest(root / rel, root)
    assert read_outside(opened, tree["outside"]) == []


@pytest.mark.parametrize("escape", ESCAPES)
def test_copy_home_refuses_a_source_that_escapes_the_owner_home(tree, opened, escape):
    rel = escape(tree, tree["real_home"])
    before = sorted(str(p) for p in tree["tmp"].rglob("*"))
    with pytest.raises(ValueError):
        isolation.copy_home(tree["home"], [rel], (), tree["real_home"])
    assert read_outside(opened, tree["outside"]) == []
    assert sorted(str(p) for p in tree["tmp"].rglob("*")) == before  # nothing was copied
    assert (tree["outside"] / "secret.json").read_text() == "outside-secret"


@needs_links
@pytest.mark.parametrize("where", ["top", "nested"])
def test_copy_home_refuses_a_destination_link_that_leaves_the_isolated_home(tree, opened, where):
    """A link already in the isolated home (a copied skill folder, say) must not carry the copy
    out of it: copyfile follows a link at the destination."""
    home = tree["home"]
    if where == "top":
        (home / ".agent").mkdir()
        os.symlink(str(tree["outside"] / "secret.json"), str(home / ".agent" / "login.json"))
    else:
        os.symlink(str(tree["outside"] / "dir"), str(home / ".agent"))
    with pytest.raises(ValueError):
        isolation.copy_home(home, [".agent/login.json"], (), tree["real_home"])
    assert read_outside(opened, tree["outside"]) == []
    assert (tree["outside"] / "secret.json").read_text() == "outside-secret"
    assert (tree["outside"] / "dir" / "login.json").read_text() == "outside-login"


@needs_links
def test_write_back_refuses_a_copy_the_session_turned_into_a_link_out(tree, opened):
    """The judged session swaps its copied login for a link to a file outside its home. The
    owner's login must stay as it was, and the outside file must not be read."""
    env, copied = isolation.copy_home(tree["home"], [".agent/login.json"], (), tree["real_home"])
    (original, dst, before), = copied
    del opened[:]
    os.remove(str(dst))
    os.symlink(str(tree["outside"] / "secret.json"), str(dst))
    isolation.write_back(original, dst, before, tree["home"], tree["real_home"])
    assert read_outside(opened, tree["outside"]) == []
    assert (tree["real_home"] / ".agent" / "login.json").read_text() == "owner-login"


@needs_links
def test_a_judged_session_cannot_write_an_outside_file_into_the_owners_login(tree, monkeypatch):
    """End to end through judge.py's run: the session replaces its copied login with a link to
    a file outside its home. On write-back, that file's bytes must not reach the owner's login."""
    real_home = tree["real_home"]
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("USERPROFILE", str(real_home))
    monkeypatch.setattr(isolation, "INSTRUCTION_ENTRIES", ("CONTAINMENT_TEST_MARKER.md",))
    agent = write(tree["tmp"] / "cli", "agent.py",
                  "import os, sys\nsys.stdin.read()\n"
                  "p = os.path.join(os.environ['HOME'], '.agent', 'login.json')\n"
                  "os.remove(p)\nos.symlink(%r, p)\nprint('done')\n"
                  % str(tree["outside"] / "secret.json"))
    bundle = write(tree["tmp"] / "bundle", "prompt.md", "Score.\n").parent
    work_root = tree["tmp"] / "work-root"
    work_root.mkdir()
    assert isolation.run(bundle, [sys.executable, str(agent)], copy=[".agent/login.json"],
                         work_root=str(work_root)) == 0
    assert (real_home / ".agent" / "login.json").read_text() == "owner-login"


@needs_links
def test_write_back_refuses_an_original_that_now_leaves_the_owner_home(tree, opened):
    env, copied = isolation.copy_home(tree["home"], [".agent/login.json"], (), tree["real_home"])
    (original, dst, before), = copied
    dst.write_text("refreshed")
    agent = tree["real_home"] / ".agent"
    os.rename(str(agent), str(tree["tmp"] / "moved"))
    os.symlink(str(tree["outside"] / "dir"), str(agent))
    (tree["outside"] / "dir" / "login.json").write_text("owner-login")  # same bytes as before
    del opened[:]
    isolation.write_back(original, dst, before, tree["home"], tree["real_home"])
    assert read_outside(opened, tree["outside"]) == []
    assert (tree["outside"] / "dir" / "login.json").read_text() == "owner-login"


@needs_links
def test_check_copy_refuses_a_link_out_so_run_exits_2(tree, monkeypatch, capsys):
    """judge.py run refuses up front (exit 2) instead of failing inside copy_home."""
    real_home = tree["real_home"]
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("USERPROFILE", str(real_home))
    monkeypatch.setattr(isolation, "INSTRUCTION_ENTRIES", ("CONTAINMENT_TEST_MARKER.md",))
    os.symlink(str(tree["outside"] / "dir"), str(real_home / "nested"))
    assert isolation.check_copy("nested/login.json", real_home) == (
        "leaves the home directory through a link")
    bundle = write(tree["tmp"] / "bundle", "prompt.md", "Score.\n").parent
    work_root = tree["tmp"] / "work-root"
    work_root.mkdir()
    assert isolation.run(bundle, [sys.executable, "-c", "print('x')"],
                         copy=["nested/login.json"], work_root=str(work_root)) == 2
    assert "refusing --copy-home nested/login.json: leaves the home directory through a link" in (
        capsys.readouterr().err)


@needs_links
def test_a_link_that_stays_inside_the_home_still_works(tree):
    """Behaviour inside the root is unchanged: a dotfile linked to another place in the same
    home is copied, recorded resolved, and hashed."""
    real_home = tree["real_home"]
    write(real_home, "dotfiles/tool.json", "linked-login")
    (real_home / ".config").mkdir()
    os.symlink(str(real_home / "dotfiles"), str(real_home / ".config" / "tool"))
    assert isolation.check_copy(".config/tool/tool.json", real_home) is None
    env, copied = isolation.copy_home(tree["home"], [".config/tool/tool.json"], (), real_home)
    (original, dst, before), = copied
    assert original == (real_home / "dotfiles" / "tool.json").resolve()
    assert dst.read_text() == "linked-login"
    assert before == isolation.digest(dst, tree["home"])
    dst.write_text("refreshed")
    isolation.write_back(original, dst, before, tree["home"], real_home)
    assert (real_home / "dotfiles" / "tool.json").read_text() == "refreshed"


def test_contained_returns_the_resolved_path_inside_the_root(tmp_path):
    write(tmp_path, "a/b.txt", "x")
    assert paths.contained(tmp_path / "a" / "b.txt", tmp_path) == (tmp_path / "a" / "b.txt").resolve()
    assert paths.contained(tmp_path, tmp_path) == tmp_path.resolve()
    with pytest.raises(FileNotFoundError):
        paths.contained(tmp_path / "a" / "missing.txt", tmp_path)  # strict by default
    assert paths.contained(tmp_path / "a" / "new" / "c.txt", tmp_path, strict=False) == (
        tmp_path.resolve() / "a" / "new" / "c.txt")


@needs_links
@pytest.mark.parametrize("escape", [chained, chained_folder])
def test_contained_refuses_a_chain_whose_middle_hop_leaves_the_root(tree, escape):
    root = tree["home"]
    rel = escape(tree, root)
    with pytest.raises(ValueError):
        paths.contained(root / rel, root)


def swap(level, folder, name, outside):
    """Replace folder/name (leaf) or folder (parent) with a link to `outside`."""
    if level == "leaf":
        os.remove(str(folder / name))
        os.symlink(str(outside / "secret.json"), str(folder / name))
    else:
        os.rename(str(folder), str(folder.parent / (folder.name + "-old")))
        os.symlink(str(outside / "dir"), str(folder))


def swap_after_check(monkeypatch, level, folder, name, outside):
    """Let the containment check pass, then swap, once: the window between check and open."""
    real = paths.contained
    done = []

    def hook(path, root, *a, **kw):
        out = real(path, root, *a, **kw)
        if not done and Path(path).name == name:
            done.append(1)
            swap(level, folder, name, outside)
        return out

    monkeypatch.setattr(paths, "contained", hook)
    monkeypatch.setattr(isolation, "contained", hook, raising=False)
    return done


@needs_links
@pytest.mark.parametrize("level", ["leaf", "parent"])
def test_digest_refuses_a_swap_between_check_and_open(tree, opened, monkeypatch, level):
    home = tree["home"]
    write(home, ".agent/login.json", "copy")
    del opened[:]  # the setup write above
    done = swap_after_check(monkeypatch, level, home / ".agent", "login.json", tree["outside"])
    with pytest.raises((OSError, ValueError)):
        isolation.digest(home / ".agent" / "login.json", home)
    assert done and read_outside(opened, tree["outside"]) == []


@needs_links
@pytest.mark.parametrize("level", ["leaf", "parent"])
def test_copy_home_refuses_a_source_swapped_between_check_and_open(tree, opened, monkeypatch,
                                                                 level):
    real_home, home = tree["real_home"], tree["home"]
    done = swap_after_check(monkeypatch, level, real_home / ".agent", "login.json",
                            tree["outside"])
    with pytest.raises((OSError, ValueError)):
        isolation.copy_home(home, [".agent/login.json"], (), real_home)
    assert done and read_outside(opened, tree["outside"]) == []
    assert not any(b"outside" in p.read_bytes() for p in home.rglob("*") if p.is_file())


@needs_links
def test_write_back_writes_the_bytes_it_hashed_not_a_later_swap(tree, monkeypatch):
    """Something the session started swaps its copy for a link out right after write_back hashed
    it. The owner's login gets the hashed bytes or nothing, never the outside file."""
    home, real_home = tree["home"], tree["real_home"]
    env, copied = isolation.copy_home(home, [".agent/login.json"], (), real_home)
    (original, dst, before), = copied
    dst.write_text("refreshed")
    real_sha = hashlib.sha256
    done = []

    def sha(data=b""):
        out = real_sha(data)
        if not done and data == b"refreshed":
            done.append(1)
            swap("leaf", dst.parent, dst.name, tree["outside"])
        return out

    monkeypatch.setattr(isolation, "hashlib", SimpleNamespace(sha256=sha))
    isolation.write_back(original, dst, before, home, real_home)
    assert done
    assert (real_home / ".agent" / "login.json").read_text() in ("refreshed", "owner-login")


@pytest.mark.skipif(not hasattr(os, "link"), reason="no hard links")
def test_write_back_refuses_a_copy_hard_linked_to_an_outside_file(tree):
    """Review r1, advisory 3: a hard link has an in-root name, so only the descriptor's link
    count shows it. A session copy with other links is refused."""
    home, real_home = tree["home"], tree["real_home"]
    env, copied = isolation.copy_home(home, [".agent/login.json"], (), real_home)
    (original, dst, before), = copied
    os.remove(str(dst))
    os.link(str(tree["outside"] / "secret.json"), str(dst))
    isolation.write_back(original, dst, before, home, real_home)
    assert (real_home / ".agent" / "login.json").read_text() == "owner-login"


def test_write_inside_checks_the_leaf_it_opens(tmp_path):
    """Sonar S8707 on r1: write_inside opened the supplied leaf name, not the checked one."""
    (tmp_path / "a").mkdir()
    with pytest.raises(ValueError):
        paths.write_inside(tmp_path / "a" / "..", tmp_path / "a", b"x")
    paths.write_inside(tmp_path / "a" / "new.txt", tmp_path, b"x")
    assert (tmp_path / "a" / "new.txt").read_bytes() == b"x"
