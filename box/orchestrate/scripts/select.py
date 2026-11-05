#!/usr/bin/env python3
"""List the ready issues that can be dispatched now, in priority order. Stdlib only. CI runs it on
Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux). The rules are in ../README.md (Selection).

Usage:
  select.py (--json FILE | --folder DIR | --repo OWNER/NAME) [--capacity N] [--owner-present]
            [--gh CMD] [--format text|json]

  --json FILE      Issues in the shape of `gh issue list --state all --json
                   number,title,state,labels,body,createdAt`; `-` reads stdin. A dependency
                   missing from the list counts as open, so pass closed issues too.
  --folder DIR     A folder of issue files, for a project with no hosted VCS (format in the README).
  --repo O/N       Read open issues from GitHub with `gh api` (GET only), and look up each
                   dependency that is not among them.
  --capacity N     Worker slots free now (default 1, the solo case). The first N dispatchable
                   issues are listed to dispatch; the rest wait for capacity.
  --owner-present  The owner is at hand, so `user-present` issues may be dispatched too.
  --gh CMD         The command that runs gh, split like a shell would (default: `gh` on PATH).
  --format         text (default) or json.

Exit codes: 0 listed, even when nothing is dispatchable; 2 usage or input error (bad option,
unreadable or malformed issue data); 3 host error (gh missing, a refused or incomplete issue list).
Only `ready`, open issues are considered. Each one that cannot be dispatched is listed with every
reason, so a refiner can fix it. A dependency whose state cannot be read counts as open, and a
`Dependencies` line that cannot be read holds the issue, and so does a key with no reference or
`none` under it, or with both. References may follow the key on its line, sit on the lines below
it, or both.
"""
import os
import sys

# This file shares its name with the standard library's select module, which subprocess imports
# on POSIX. Drop this folder from the import path before anything imports subprocess (gh_read
# below does), or it finds us.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != HERE]

import argparse  # noqa: E402
import errno  # noqa: E402
import fnmatch  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
from pathlib import Path  # noqa: E402

# gh's response handling, one implementation for box-audit and orchestrate, loaded by path from
# box/lib in the checkout this file sits in, now that this folder is off the import path.
GH_READ = Path(__file__).resolve().parents[2] / "lib" / "gh_read.py"
_spec = importlib.util.spec_from_file_location("box_gh_read", str(GH_READ))
gh_read = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gh_read)

PRIORITIES = ["P0", "P1", "P2"]
HELD = {  # lifecycle labels that keep a ready issue from dispatch, and why
    "needs-refinement": "has an open question (needs-refinement)",
    "blocked": "is blocked",
    "user-action": "waits on the owner (user-action)",
    "parked": "is parked",
    "reserved": "is reserved (a session holds it)",
}
PRESENT = "user-present"
# The key: `Dependencies: <refs>` (also bold, or a list item of any kind `LIST_ITEM` reads), or
# the key alone on its line as a heading or bold label, with the references on the lines below it.
# Any space or a byte-order mark may come before it. `key_start` reads what comes before the
# word in parts, each matched once and never shortened: no later part can start with a character
# the part before it takes, so a shorter match never helps, and a long line costs one pass. As
# one regex, the parts that share spaces, `*` and `_` were retried against each other (over 5 s
# on a 64 KB line).
KEY_LEAD = re.compile(r"[\s\ufeff>*_-]*")
KEY_MARKER = re.compile(r"(?:[+\u2022\u2013\u2014]|\d{1,9}[.)])[ \t]+")
KEY_BOX = re.compile(r"\[[ xX]\][ \t]+")
KEY_HASHES = re.compile(r"(#*)\s*[*_]*")
# After the word: an optional colon and the value, which `dependencies_key` trims.
KEY_WORD = re.compile(r"Dependencies[*_]*(?::(.*)|[ \t]*)$", re.I)
# A line that starts like the key but is not one, such as `Dependencies (blocking): #1`,
# `Dependencies - #1` or `Dependency: #1`. Prose such as `Dependencies are pinned` is not matched.
OTHER_WORD = re.compile(r"Dependenc(?:y|ies)[*_]*\s*(?:[^\w\s]|$)", re.I)
# The key in a table row, HTML or code (`| Dependencies | #1 |`, `<b>Dependencies:</b> #1`). It is
# not read, and holds the issue when its line has a digit; a mention such as `Dependencies: #N` in
# backticks does not.
MARKUP_KEY = re.compile(r"^(?:[\W_]|\d{1,9}[.)]|<[a-z][^>\n]*>)*Dependenc(?:y|ies)[*_]*\s*"
                        r"(?:[^\w\s]|$)", re.I)
HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]|$)")
# A heading, or a bold label such as the box-audit card's `**Out of scope**` (no reference in it).
SECTION_END = re.compile(HEADING.pattern + r"|^[ \t]*(\*\*|__)[^\W\d_][^#/*_]*\2:?[ \t]*$")
LIST_ITEM = re.compile(r"^[ \t>]*(?:[-*+\u2022\u2013\u2014]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?")
# A list item that starts another key, such as `- Tier: standard` (not a link's `https:`)
# A trailing `*` run may follow the label's words; a `_` there is already one of them.
LABEL = re.compile(r"[*_]*[^\W\d_][\w \t()/-]*(?:\*[*_]*)?:(?!//)")
NONE = re.compile(r"[\W_]*none\b", re.I)
# `#12`, `owner/name#12`, or an issue link as the host pastes it (https://host/owner/name/issues/12)
# `owner/name` starts only where a word starts, so a long word is read once, not from each letter.
REF = re.compile(r"(?:(?<![\w.-])([\w.-]+/[\w.-]+))?#(\d+)\b"
                 r"|https?://[^\s/]+/([\w.-]+/[\w.-]+)/issues/(\d+)\b")


def key_start(line):
    """(hashes, start): a heading key's `#` run ("" if none) and where the key's word may start."""
    start = KEY_LEAD.match(line).end()
    for part in (KEY_MARKER, KEY_BOX):
        m = part.match(line, start)
        start = m.end() if m else start
    m = KEY_HASHES.match(line, start)
    return m.group(1), m.end()


def dependencies_key(line):
    """(hashes, value) for a `Dependencies` key line, else None. The value is the text after the
    colon without its leading `*`/`_` run and outer spaces and tabs ("" if there is none)."""
    hashes, start = key_start(line)
    m = KEY_WORD.match(line, start)
    return (hashes, (m.group(1) or "").lstrip("*_").strip(" \t")) if m else None


def other_key(line):
    """A line that starts like the key but is not one (`OTHER_WORD`)."""
    return bool(OTHER_WORD.match(line, key_start(line)[1]))


def only_references(text):
    """A line that holds references and nothing else, such as `#1, #2` or `- **#1**`."""
    return bool(REF.search(text)) and not re.sub(r"[\W_]", "", REF.sub("", LIST_ITEM.sub("", text)))


class InputError(Exception):
    """Malformed issue data: exit 2."""


class HostError(Exception):
    """The host refused or cut short a read: exit 3."""


# ----- reading issues ------------------------------------------------------------------------

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


def read_json(path):
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError) as e:
        raise InputError("%s: %s" % (path, e))
    if not isinstance(data, list):
        raise InputError("%s: expected a list of issues" % path)
    return [normalize(d, "%s[%d]" % (path, i)) for i, d in enumerate(data)]


def linked(st):
    """A symlink or, on Windows, another reparse point (0x400), such as a junction."""
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


DIR_FDS = (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
           and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
           and os.listdir in os.supports_fd)


def handle_path(fd):
    """Where open file fd really is, after every link, or None where the platform cannot say.
    Only Windows is asked (GetFinalPathNameByHandleW); elsewhere IssueDir walks by descriptor."""
    if os.name != "nt":
        return None
    import ctypes
    import msvcrt
    from ctypes import wintypes
    get = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    get.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get.restype = wintypes.DWORD
    size = 32768
    buf = ctypes.create_unicode_buffer(size)
    n = get(msvcrt.get_osfhandle(fd), buf, size, 0)
    if not n or n >= size:
        raise ctypes.WinError(ctypes.get_last_error())
    path = buf.value
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    return path[4:] if path.startswith("\\\\?\\") else path


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
        absolute = Path(self.path).is_absolute()
        fd = os.open(parts[0] if absolute else os.curdir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parts[1:] if absolute else parts:
                try:
                    inner = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=fd)
                except OSError:
                    try:
                        is_link = linked(os.stat(part, dir_fd=fd, follow_symlinks=False))
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
        with os.fdopen(fd, "rb") as f:
            if self.fd is None:
                final = handle_path(fd)
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
            try:
                text = f.read().decode("utf-8")
            except (OSError, UnicodeDecodeError) as e:
                raise InputError("%s: %s" % (name, e))
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


class Host:
    """`gh api` GETs against one repository. Errors are returned, never raised."""

    def __init__(self, slug, gh=None, runner=None):
        self.slug = slug
        self.gh = gh or ([shutil.which("gh")] if shutil.which("gh") else None)
        self.runner = runner or self._gh

    def _gh(self, path):
        if not self.gh:
            return None, "gh CLI not found"
        return gh_read.read(self.gh + ["api", "-X", "GET", "-H",
                                       "Accept: application/vnd.github+json", path])

    def get(self, path):
        return self.runner(path.replace("{repo}", "repos/" + self.slug))


def from_rest(raw):
    return normalize(dict(raw, createdAt=raw.get("created_at")), "#%s" % raw.get("number"))


def read_host(host):
    """Open issues (pull requests left out), read to the last page with gh_read.paged. Each page
    is checked before the next is asked for; a page past the bound only shows the list is
    incomplete."""
    issues = []

    def fetch(page):
        body, error = host.get("{repo}/issues?state=open&per_page=100&page=%d" % page)
        if error:
            raise HostError("issues page %d: %s" % (page, error))
        if not isinstance(body, list):
            raise HostError("issues page %d: not a list" % page)
        if page <= gh_read.MAX_PAGES:
            try:
                issues.extend(from_rest(i) for i in body if "pull_request" not in i)
            except InputError as e:
                raise HostError("issues page %d: %s" % (page, e))
        return body, None
    _, error = gh_read.paged(fetch)
    if error:
        raise HostError("more than %d pages of open issues; list incomplete" % gh_read.MAX_PAGES)
    return issues


# ----- selection -----------------------------------------------------------------------------

def lines_below(lines, level):
    """The lines under a key alone on its line, with any list marker removed, or None when another
    key comes first. Under a heading of `level` (1 to 6), up to the next heading of that level or
    higher, past blank lines, sub-headings and bold labels. Otherwise (`level` 0), up to the next
    heading, bold label, or blank line with no list item after it."""
    out = []
    for j, text in enumerate(lines):
        if dependencies_key(text) or other_key(text):
            return out or None
        heading = HEADING.match(text)
        if level:
            if heading and len(heading.group(1)) <= level:
                break
            if heading or SECTION_END.match(text) or not text.strip():
                continue
        elif SECTION_END.match(text):
            break
        elif not text.strip():
            after = next((t for t in lines[j:] if t.strip()), "")
            if not out or LIST_ITEM.match(after) or only_references(after):
                continue
            break
        if LIST_ITEM.sub("", text).strip():
            out.append(LIST_ITEM.sub("", text))
    return out


def nested_under(text, lines):
    """The lines that follow `text` indented deeper than it (a tab counts to the next multiple of
    four), up to the last one that is not blank."""
    def indent(t):
        return len(re.match(r"[\s>]*", t.expandtabs(4)).group())
    out = []
    for t in lines:
        if t.strip() and indent(t) <= indent(text):
            break
        out.append(t)
    while out and not out[-1].strip():
        out.pop()
    return out


def empty_label(text):
    """A sub-label with nothing after its colon and no reference, such as `- Hard:`."""
    item = LIST_ITEM.sub("", text)
    label = LABEL.match(item)
    return bool(label) and not REF.search(item) and not re.sub(r"[\s*_]", "", item[label.end():])


def items_below(lines):
    """The lines under a `Dependencies: <value>` line that add to it, with any list marker removed:
    list items, lines of only references, and lines of the key's paragraph (no blank line before
    them) that name an issue or have a digit. Up to another key, a heading or bold label, an item or
    line that starts another key and names no issue, or, past a blank line, anything but a list
    item or line of references that names an issue, or a sub-label item with nothing after its
    colon. Such a sub-label (`- Hard:`, or `Hard:` in the paragraph) does not end the key: it is
    read past with the lines nested under it, and the lines from it on are kept once one of them
    names an issue. A sub-label reading `none` over a nested reference is read, so it holds the
    issue."""
    out = []
    in_paragraph = True  # no blank line since the key or the last line read
    tentative = None  # where an empty sub-label's lines start in `out`, until one names an issue
    j = 0
    while j < len(lines):
        text = lines[j]
        j += 1
        if not text.strip():
            after = next((t for t in lines[j:] if t.strip()), "")
            if not REF.search(after) and not (LIST_ITEM.match(after) and empty_label(after)):
                break
            in_paragraph = False
            continue
        item = LIST_ITEM.sub("", text)
        if dependencies_key(text) or other_key(text) or SECTION_END.match(text):
            break
        label = LABEL.match(item)
        if label and not LIST_ITEM.match(text) and REF.search(item):
            break
        if label and not REF.search(item):
            nested = nested_under(text, lines[j:])
            named = any(REF.search(t) for t in nested)
            value = re.sub(r"[\s*_]", "", item[label.end():])
            if value and not (named and NONE.match(value)):
                break
            if value:
                out.append(item)
            elif tentative is None:
                tentative = len(out)
            out += [LIST_ITEM.sub("", t) for t in nested if LIST_ITEM.sub("", t).strip()]
            if named:
                tentative = None
            j += len(nested)
            in_paragraph = True
            continue
        paragraph = in_paragraph and not LIST_ITEM.match(text) and re.search(r"\d", text)
        if LIST_ITEM.match(text) or only_references(text) or paragraph:
            if item.strip():
                out.append(item)
                if REF.search(item) or paragraph:
                    tentative = None
            in_paragraph = True
        elif not in_paragraph:
            break
    return out if tentative is None else out[:tentative]


def read_dependencies(body):
    """(lines, keys): the text of each line that lists dependencies, and each key line that holds
    the issue on its own. A line is the rest of a `Dependencies:` line and the items below it
    (`items_below`) or, when that is empty or the key is a heading or bold label alone on its line,
    each line below it (`lines_below`). A key with nothing under it, a key with `none` and a
    reference under it, or a line that starts like the key but is not one, goes to keys."""
    lines = (body or "").replace("\r\n", "\n").split("\n")
    out, keys = [], []
    for i, line in enumerate(lines):
        key = dependencies_key(line)
        if not key:
            if other_key(line) or MARKUP_KEY.match(line) and re.search(r"\d", line):
                keys.append(line.strip())
            continue
        hashes, value = key
        if value.strip():
            below = [value] + items_below(lines[i + 1:])
        else:
            below = lines_below(lines[i + 1:], len(hashes))
            if below == []:
                keys.append(line.strip())
        below = below or []
        if any(REF.search(t) for t in below) and any(
                NONE.match(t) and not REF.search(t) for t in below):
            keys.append(line.strip())
        out += below
    return out, keys


def dependencies(body):
    """(repo or None, number) for each reference on the issue's dependency lines."""
    return [(m.group(1) or m.group(3), int(m.group(2) or m.group(4)))
            for line in read_dependencies(body)[0] for m in REF.finditer(line)]


def unread_dependencies(body):
    """The dependency lines this script cannot read in full: a key it cannot read
    (`read_dependencies`), a line with no reference and not `none`, or a bare number beside the
    references. Each one holds the issue, since a dependency it names would otherwise be
    missed."""
    lines, out = read_dependencies(body)
    for line in lines:
        rest = REF.sub("", line)
        unread = not REF.search(line) and not NONE.match(rest)
        if unread or re.search(r"\d", rest):
            out.append(line.strip())
    return out


def dependency_states(issues, slug=None, host=None):
    """Map issue number to its state, with each missing dependency looked up on the host."""
    states = {i["number"]: i["state"] for i in issues}
    if host is None:
        return states
    for issue in issues:
        for repo, number in dependencies(issue["body"]):
            if (repo is None or repo.lower() == slug.lower()) and number not in states:
                body, error = host.get("{repo}/issues/%d" % number)
                ok = isinstance(body, dict) and body.get("state")
                states[number] = str(body["state"]).upper() if ok else \
                    "unreadable (%s)" % (error or "no state")
    return states


def priority(issue):
    found = [PRIORITIES.index(l) for l in issue["labels"] if l in PRIORITIES]
    return min(found) if found else len(PRIORITIES)


def reasons(issue, states, slug=None, owner_present=False):
    """Why a ready issue cannot be dispatched; empty when it can."""
    out = []
    tiers = sorted(l for l in issue["labels"] if l.startswith("tier:"))
    if not tiers:
        out.append("no tier label")
    elif len(tiers) > 1:
        out.append("%d tier labels (%s); needs exactly one" % (len(tiers), ", ".join(tiers)))
    out += ["labelled %s: %s" % (l, why) for l, why in HELD.items() if l in issue["labels"]]
    if PRESENT in issue["labels"] and not owner_present:
        out.append("labelled %s: needs the owner at hand (--owner-present)" % PRESENT)
    out += ["dependency line not understood: %s (write #n references, or none)" % line
            for line in unread_dependencies(issue["body"])]
    for repo, number in dependencies(issue["body"]):
        if repo is not None and (slug is None or repo.lower() != slug.lower()):
            out.append("dependency %s#%d is in another repo; check it and drop the line"
                       % (repo, number))
            continue
        state = states.get(number)
        if state is None:
            out.append("dependency #%d not in the input; its state is unknown" % number)
        elif state != "CLOSED":
            out.append("dependency #%d is %s" % (number, state.lower()))
    return out


def select(issues, capacity, states=None, slug=None, owner_present=False):
    """The plan: issues to dispatch now, dispatchable ones waiting for capacity, and the ready
    issues that cannot be dispatched with their reasons."""
    states = states if states is not None else dependency_states(issues)
    ready = [i for i in issues if i["state"] == "OPEN" and "ready" in i["labels"]]
    ready.sort(key=lambda i: (priority(i), i["createdAt"], i["number"]))
    go, held = [], []
    for issue in ready:
        why = reasons(issue, states, slug, owner_present)
        entry = {"number": issue["number"], "title": issue["title"],
                 "priority": (PRIORITIES + [None])[priority(issue)],
                 "tier": next((l for l in issue["labels"] if l.startswith("tier:")), None)}
        if why:
            held.append(dict(entry, reasons=why))
        else:
            go.append(entry)
    return {"capacity": capacity, "dispatch": go[:capacity], "waiting": go[capacity:],
            "not_dispatchable": held}


def render(plan):
    def line(e):
        return "  #%-5d %-3s %-17s %s" % (e["number"], e["priority"] or "-", e["tier"] or "-",
                                         e["title"])
    out = ["Dispatch now (capacity %d):" % plan["capacity"]]
    out += [line(e) for e in plan["dispatch"]] or ["  none"]
    if plan["waiting"]:
        out.append("Waiting for capacity:")
        out += [line(e) for e in plan["waiting"]]
    if plan["not_dispatchable"]:
        out.append("Ready but not dispatchable:")
        for e in plan["not_dispatchable"]:
            out.append(line(e))
            out += ["         - %s" % r for r in e["reasons"]]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--json")
    source.add_argument("--folder")
    source.add_argument("--repo")
    ap.add_argument("--capacity", type=int, default=1)
    ap.add_argument("--owner-present", action="store_true")
    ap.add_argument("--gh")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args(argv)
    if args.capacity < 0:
        print("select: --capacity must be 0 or more", file=sys.stderr)
        return 2
    if args.repo and not re.match(r"^[\w.-]+/[\w.-]+$", args.repo):
        print("select: --repo must be OWNER/NAME", file=sys.stderr)
        return 2
    try:
        gh = shlex.split(args.gh) if args.gh else None
    except ValueError as e:
        print("select: --gh: %s" % e, file=sys.stderr)
        return 2
    try:
        if args.repo:
            host = Host(args.repo, gh=gh)
            issues = read_host(host)
            states = dependency_states(issues, args.repo, host)
        else:
            issues = read_json(args.json) if args.json else read_folder(args.folder)
            states = dependency_states(issues)
    except InputError as e:
        print("select: %s" % e, file=sys.stderr)
        return 2
    except HostError as e:
        print("select: host error: %s" % e, file=sys.stderr)
        return 3
    plan = select(issues, args.capacity, states, args.repo, args.owner_present)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(plan, indent=1) if args.format == "json" else render(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
