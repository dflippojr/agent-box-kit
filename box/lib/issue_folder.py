"""Issue folders: the issue files box/orchestrate's format defines (README, Selection), read
safely. Stdlib only; Python 3.8+. Not a script: select.py, box-audit's collect.py and
file_issues.py, and queue-fill's issue_lint.py and refine.py import it from box/lib (issue #36).

The folder and its files are untrusted. IssueDir opens the folder once; a folder on the way to it
that is a link is refused, and so is an issue file that is a link or has other hard links, even
one swapped in after a check. On POSIX every open is relative to the folder's descriptor with links
refused (DIR_FDS). On Windows a file is opened by path and refused unless its handle is where the
path says (paths.handle_path). A platform with neither is refused.

normalize(raw, where) checks one issue in the `gh issue list --json` shape. parse_issue_text,
parse_issue_file and read_folder read issue files into that shape. Malformed data raises
InputError. HELD and PRESENT are the lifecycle labels that hold a ready issue from dispatch.
"""
import errno
import fnmatch
import os
import re
import stat
from pathlib import Path

import paths

HELD = {  # lifecycle labels that keep a ready issue from dispatch, and why
    "needs-refinement": "has an open question (needs-refinement)",
    "blocked": "is blocked",
    "user-action": "waits on the owner (user-action)",
    "parked": "is parked",
    "reserved": "is reserved (a session holds it)",
}
PRESENT = "user-present"


class InputError(Exception):
    """Malformed issue data: exit 2."""


def normalize(raw, where):
    """One issue in the `gh issue list --json` shape, checked: number, title, state (OPEN or
    CLOSED), labels (names), body, createdAt."""
    if not isinstance(raw, dict):
        raise InputError("%s: not an object" % where)
    try:
        number = int(raw["number"])
        labels = [l["name"] if isinstance(l, dict) else str(l) for l in raw.get("labels") or []]
        return {"number": number, "title": str(raw.get("title") or ""),
                "state": str(raw["state"]).upper(), "labels": labels,
                "body": str(raw.get("body") or ""),
                "createdAt": str(raw.get("createdAt") or raw.get("created_at") or "")}
    except (KeyError, TypeError, ValueError) as e:
        raise InputError("%s: missing or bad field %s" % (where, e))


DIR_FDS = (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
           and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
           and os.listdir in os.supports_fd)


LINKED_FILE = "%s: is a link or has other hard links; an issue file must be a plain file"


class IssueDir:
    """An issue folder, opened once; its entries are untrusted. A folder on the way to it that is
    a link is refused, and so is an issue file that is a link or has other hard links, even one
    swapped in after a check. On POSIX every open is relative to the folder's descriptor with
    links refused. On Windows a file is opened by path and refused unless its handle is where the
    path says. A platform with neither is refused."""

    def __init__(self, path):
        self.path, self.fd = str(path), None
        if DIR_FDS:
            self.fd = self._walk()
            return
        self.real = os.path.realpath(self.path)
        if os.path.normcase(self.real) != os.path.normcase(os.path.abspath(self.path)):
            raise InputError("%s: passes through a link; give the folder's real path" % path)
        if not os.path.isdir(self.real):
            raise InputError("%s: not a folder" % path)

    def _walk(self):
        parts = Path(self.path).parts
        absolute = Path(self.path).is_absolute()  # POSIX only here, so the anchor is "/"
        fd = os.open("/" if absolute else os.curdir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parts[1:] if absolute else parts:
                part = os.path.basename(part)  # one component, never a path
                try:
                    inner = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=fd)
                except OSError:
                    try:
                        is_link = paths.is_link_stat(os.stat(part, dir_fd=fd, follow_symlinks=False))
                    except OSError:
                        is_link = False
                    if is_link:
                        raise InputError("%s: %s is a link; give the folder's real path"
                                         % (self.path, part))
                    raise InputError("%s: not a folder" % self.path)
                os.close(fd)
                fd = inner
        except BaseException:
            os.close(fd)
            raise
        return fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def names(self):
        """The issue files' names, sorted."""
        try:
            names = os.listdir(self.fd if self.fd is not None else self.real)
        except OSError as e:
            raise InputError("%s: %s" % (self.path, e.strerror))
        return sorted(n for n in names if fnmatch.fnmatch(n, "*.md"))

    def read(self, name):
        """(issue, stat) for issue file name, parsed from the bytes of the file checked."""
        flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                 | getattr(os, "O_BINARY", 0))
        path = name if self.fd is not None else os.path.join(self.real, name)
        try:
            fd = os.open(path, flags, dir_fd=self.fd)
        except OSError as e:
            if e.errno in (errno.ELOOP, errno.EMLINK):
                raise InputError(LINKED_FILE % name)
            raise InputError("%s: %s" % (name, e.strerror))
        try:
            if self.fd is None:
                final = paths.handle_path(fd)
                if final is None:
                    raise InputError("%s: this platform cannot open a file without following "
                                     "links; refusing to read the folder" % name)
                if os.path.normcase(final) != os.path.normcase(path):
                    raise InputError(LINKED_FILE % name)
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise InputError("%s: not a plain file" % name)
            if st.st_nlink > 1:
                raise InputError(LINKED_FILE % name)
            with os.fdopen(fd, "rb") as f:
                fd = None  # f closes it
                text = f.read().decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise InputError("%s: %s" % (name, e))
        finally:
            if fd is not None:
                os.close(fd)
        return parse_issue_text(name, text), st


def parse_issue_text(name, text):
    """An issue file: a header of `key: value` lines between `---` lines, then the body."""
    text = text.replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---\n?(.*)\Z", text, re.S)
    if not m:
        raise InputError("%s: no header between --- lines" % name)
    fields = {}
    for line in m.group(1).splitlines():
        if line.strip():
            key, sep, value = line.partition(":")
            if not sep:
                raise InputError("%s: header line without a colon: %s" % (name, line))
            fields[key.strip()] = value.strip()
    fields["labels"] = [l.strip() for l in fields.get("labels", "").split(",") if l.strip()]
    fields["body"] = m.group(2)
    issue = normalize(fields, name)
    if Path(name).stem != str(issue["number"]):
        raise InputError("%s: number %d does not match the file name" % (name, issue["number"]))
    if issue["state"] not in ("OPEN", "CLOSED"):
        raise InputError("%s: state must be open or closed" % name)
    return issue


def parse_issue_file(path):
    """One issue file, read as IssueDir reads it."""
    path = Path(path)
    with IssueDir(path.parent) as folder:
        return folder.read(path.name)[0]


def read_folder(folder):
    with IssueDir(folder) as d:
        return [d.read(name)[0] for name in d.names()]
