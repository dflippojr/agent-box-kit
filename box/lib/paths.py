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
