"""Path checks box scripts share: link detection, containment, safe output. Stdlib only; Python
3.8+. Not a script: box scripts import it from box/lib (issue #36), so each check has one
implementation.

is_link_stat(st): a stat result is a symlink or, on Windows, any reparse point (a junction, or
one os.readlink cannot read): the more conservative refusal.
is_link(path): is_link_stat of os.lstat(path); False when path does not exist. Any other OSError
propagates, so a caller that must refuse on doubt (linked) or keep on doubt decides.
linked(root, rel): rel, or a folder on the way to it from root, is a link; a component that
cannot be checked counts as a link.
inside(path, root): path, after links are resolved, is root or below it.
contained(path, root, strict=True): path, resolved once, after checking that it stays inside root
at every level: no `..`, not elsewhere, and no link on the way from root to it that leaves root.
Each link is expanded one hop at a time and every hop is checked, so a chain that leaves root and
comes back is refused too; more than MAX_LINKS hops (a loop) is refused. Raises ValueError
otherwise, and FileNotFoundError when `strict` (the default) and path does not exist. The one
containment check for paths an agent can supply (issue #47). Path.is_relative_to is 3.9+, so the
check compares parts.
Anchor(root): root opened once, before anything untrusted can change it; every later path
under it is reached from that descriptor, one folder at a time without following a link, and root
is never resolved again (issue #47, review r2). open/read give a regular file (with `single`, one
with no other hard links); write puts data at a path as a new file created exclusively in the
verified folder, checked, then renamed over the entry, so an existing file is never written
through. Where descriptors relative to a folder are missing (AT_FDS false: Windows), Anchor raises
NoFolderDescriptors with NO_FDS: the owner's decision in #47 is to refuse there, not fall back.
startup_bytecode(root, where): why interpreter startup may have written bytecode inside root, or
None. Startup runs before a script's first line, so only `python -B` (or PYTHONDONTWRITEBYTECODE)
stops it. `where` names root in the message (default: the audited repo).
unsafe_output(path, root): why writing path could change something inside root, or None. A file
with other hard links is refused: the other link may be inside root, and replacing this one would
still change that file's link count.
write_outside(path, text, root): write text to path, which unsafe_output must pass. The text goes
to a new file created beside path, which then replaces path's directory entry: an existing file
is never written through or truncated. Raises ValueError when unsafe_output refuses.
handle_path(fd): where open file fd really is, after every link, or None where the platform cannot
say. Only Windows is asked (GetFinalPathNameByHandleW). agent-ready's secret_guard.py keeps its
own copy, since agent-ready/ is copied alone.
"""
import os
import stat
import sys
import tempfile
from pathlib import Path

REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


def is_link_stat(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & REPARSE_POINT)


def is_link(path):
    try:
        st = os.lstat(str(path))
    except (FileNotFoundError, NotADirectoryError):
        return False
    return is_link_stat(st)


def linked(root, rel):
    p = Path(root)
    for part in Path(rel).parts:
        p = p / part
        try:
            if is_link(p):
                return True
        except OSError:
            return True
    return False


def inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    return path == root or root in path.parents


MAX_LINKS = 40  # hops through links before a path counts as a loop (Linux's own limit)
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY = getattr(os, "O_DIRECTORY", 0)
BINARY = getattr(os, "O_BINARY", 0)
NONBLOCK = getattr(os, "O_NONBLOCK", 0)  # a FIFO swapped in must not block the open
AT_FDS = bool(NOFOLLOW and DIRECTORY) and hasattr(os, "fchmod") and all(
    f in os.supports_dir_fd for f in (os.open, os.stat, os.unlink, os.rename, os.mkdir))


def _under(path, tops):
    """path relative to the first of `tops` it is lexically below (or equal to), else None."""
    for top in tops:
        try:
            return path.relative_to(top)
        except ValueError:
            continue
    return None


def _readlink(path):
    target = os.readlink(str(path))
    if target.startswith("\\\\?\\UNC\\"):  # Windows: \\?\UNC\server\share
        return "\\" + target[7:]
    if target.startswith("\\\\?\\"):  # Windows: \\?\C:\...
        return target[4:]
    return target


def contained(path, root, strict=True):
    base = Path(root)
    real_root = base.resolve(strict=True)
    tops = (base, base.absolute(), real_root)  # root as given, or resolved
    path = Path(path)
    rel = _under(path, tops)
    if rel is None:
        raise ValueError("%s is not under %s" % (path, real_root))
    if ".." in rel.parts:
        raise ValueError("%s leaves %s through .." % (path, real_root))
    out = ValueError("%s leaves %s through a link" % (path, real_root))
    cur, todo, hops = real_root, list(rel.parts), 0  # cur: resolved, link free, inside root
    while todo:
        part = todo.pop(0)  # Path parts are never "" or "."
        if part == "..":  # only from a link's target
            if cur == real_root:
                raise out
            cur = cur.parent
            continue
        step = cur / part
        try:
            st = os.lstat(str(step))
        except (FileNotFoundError, NotADirectoryError):
            if strict:
                raise FileNotFoundError("%s does not exist" % path)
            if ".." in todo:
                raise out
            return step.joinpath(*todo)
        except OSError:
            raise out  # cannot be checked: counts as leaving
        if not is_link_stat(st):
            cur = step
            continue
        hops += 1
        if hops > MAX_LINKS:
            raise ValueError("%s has more than %d links on its way (a loop?)" % (path, MAX_LINKS))
        try:
            target = Path(_readlink(step))
        except OSError:
            raise out
        if target.is_absolute():
            rel = _under(target, tops)
            if rel is None:
                raise out
            cur, todo = real_root, list(rel.parts) + todo
        else:
            todo = list(target.parts) + todo
    return cur


def _open_dir(real):
    """A descriptor for folder `real` (resolved, so link free), opened from its anchor one folder
    at a time without following a link."""
    fd = os.open(real.anchor, os.O_RDONLY | DIRECTORY)
    try:
        for name in real.parts[1:]:
            nxt = os.open(name, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
    except BaseException:
        os.close(fd)
        raise
    return fd


class NoFolderDescriptors(OSError):
    """This platform cannot open a file relative to a folder descriptor (Windows)."""


NO_FDS = ("needs folder descriptors (openat), which this platform lacks: --copy-home works on "
          "Linux and macOS, not Windows")
FOLDER_LINK = "a folder on its path is now a link"


class Anchor:
    """A root folder opened once, so every later path under it is reached from that descriptor
    and the root is never resolved again (issue #47, review r2)."""

    def __init__(self, root):
        if not AT_FDS:
            raise NoFolderDescriptors(NO_FDS)
        self.given = Path(root)
        self.real = self.given.resolve(strict=True)
        self.fd = _open_dir(self.real)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def rel(self, path):
        """The parts of `path` below this root, compared by spelling only, never resolved."""
        path = Path(path)
        rel = _under(path, (self.given, self.given.absolute(), self.real))
        if rel is None or not rel.parts or ".." in rel.parts:
            raise ValueError("%s is not under %s" % (path, self.real))
        return rel.parts

    def _folder(self, parts, make=False):
        """A descriptor for folder `parts` below the root, no part of it followed as a link.
        With `make`, missing folders are created through the parent's descriptor."""
        fd = os.dup(self.fd)
        try:
            for name in parts:
                if make:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if is_link_stat(st):
                    raise ValueError(FOLDER_LINK)
                try:
                    nxt = os.open(name, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=fd)
                except OSError:  # swapped since the stat: ELOOP or ENOTDIR, by platform
                    raise ValueError(FOLDER_LINK)
                os.close(fd)
                fd = nxt
        except BaseException:
            os.close(fd)
            raise
        return fd

    def open(self, path, single=False):
        """A read descriptor for regular file `path`, opened without following a link; with
        `single`, it must have no other hard links."""
        parts = self.rel(path)
        folder = self._folder(parts[:-1])
        try:
            fd = os.open(parts[-1], os.O_RDONLY | NOFOLLOW | NONBLOCK, dir_fd=folder)
        finally:
            os.close(folder)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise ValueError("%s is not a regular file" % path)
            if single and st.st_nlink > 1:
                raise ValueError("%s has other hard links, which may be outside %s"
                                 % (path, self.real))
        except BaseException:
            os.close(fd)
            raise
        return fd

    def read(self, path, single=False):
        """(bytes, mode) of regular file `path`, read once through open()."""
        fd = self.open(path, single)
        with os.fdopen(fd, "rb") as f:
            return f.read(), stat.S_IMODE(os.fstat(f.fileno()).st_mode)

    def write(self, path, data, mode=None, make=False):
        """Put `data` at `path` as a new file: created exclusively in its verified folder,
        checked (regular, one link), given `mode`, then renamed over the entry. An existing
        file is never opened or truncated, so a hard link or FIFO there is only unlinked. With
        mode None, the existing entry must be a regular file and its mode is kept."""
        parts = self.rel(path)
        folder = self._folder(parts[:-1], make)
        try:
            name = parts[-1]
            if mode is None:
                st = os.stat(name, dir_fd=folder, follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode):
                    raise OSError("%s is no longer a regular file" % path)
                mode = stat.S_IMODE(st.st_mode)
            tmp = ".%s.%s.box-tmp" % (name, os.urandom(6).hex())
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW | BINARY, 0o600,
                         dir_fd=folder)
            try:
                with os.fdopen(fd, "wb") as f:
                    st = os.fstat(f.fileno())
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                        raise OSError("%s: the new file is not a single regular file" % path)
                    f.write(data)
                    os.fchmod(f.fileno(), mode)
                os.rename(tmp, name, src_dir_fd=folder, dst_dir_fd=folder)
            except BaseException:
                try:
                    os.unlink(tmp, dir_fd=folder)
                except OSError:
                    pass
                raise
        finally:
            os.close(folder)


def startup_bytecode(root, where="the audited repo"):
    prefix = getattr(sys, "pycache_prefix", None)
    if sys.flags.dont_write_bytecode or not prefix or not inside(prefix, root):
        return None
    return ("PYTHONPYCACHEPREFIX (%s) is inside %s, so interpreter startup may already have "
            "written bytecode there. Run with `python -B`, or unset it" % (prefix, where))


def unsafe_output(path, root):
    path = Path(path)
    if inside(path, root) or inside(path.parent, root):
        return "%s resolves inside the audited repo" % path
    try:
        if os.lstat(str(path)).st_nlink > 1:
            return "%s has other hard links, which may be inside the audited repo" % path
    except OSError:
        pass
    return None


def write_outside(path, text, root):
    path = Path(path)
    problem = unsafe_output(path, root)
    if problem:
        raise ValueError(problem)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        mask = os.umask(0o077)  # probe with a restrictive mask: never open, even briefly
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)  # mkstemp makes it owner-only; give it a new file's mode
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def handle_path(fd):
    if os.name != "nt":
        return None
    import ctypes
    import msvcrt
    buf = ctypes.create_unicode_buffer(32768)  # the longest path Windows has
    n = ctypes.WinDLL("kernel32").GetFinalPathNameByHandleW(
        ctypes.c_void_p(msvcrt.get_osfhandle(fd)), buf, len(buf), 0)
    if not 0 < n < len(buf):
        raise OSError("cannot tell where an open file is")
    unc = buf.value.startswith("\\\\?\\UNC\\")  # \\?\UNC\server\share\...
    return "\\" + buf.value[7:] if unc else buf.value[4:]
