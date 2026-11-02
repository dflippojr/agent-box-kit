"""Checks the Sanitized rule (AGENTS.md): the docs carry no personal paths, private hostnames or
private addresses. Pure stdlib.

The docs are every tracked text file under agent-ready/ and box/ (all extensions, scripts
included), plus README.md and AGENTS.md. "Infrastructure detail" means exactly the five patterns
in PATTERNS. A file with a NUL byte and no UTF-16 BOM is binary and skipped. Any other file that
is not UTF-8 fails, because it cannot be scanned. In a .py file, attribute access in code such
as `args.local` is not a .local hostname; its strings and comments are still scanned, and a .py
file that does not parse gets no exemption.

ALLOWLIST maps an exact (relative path, matched text) pair to a one-line reason. Allowing a
generic example in one file does not hide a different match, or the same text in another file.
An entry that no longer matches anything fails the test, so remove it when its text goes.
"""
import ast
import re
import subprocess
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC_PATHS = ["agent-ready", "box", "README.md", "AGENTS.md"]

OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
# A hostname ends where no further label follows; a trailing full stop is punctuation.
HOST_END = r"(?!\.?[\w-])"

# A user name is at least one character and not a placeholder such as <you>, %USERNAME% or $USER.
NOT_PLACEHOLDER = r"(?![%$<{])"

PATTERNS = [
    # One or more separators, so escaped forms in code and JSON ("C:\\Users") match too. The
    # second form is the WSL (/mnt/c/Users) or Git Bash (/c/Users) spelling of the same path.
    ("Windows user path", re.compile(
        r"(?<![A-Za-z])[A-Za-z]:[\\/]+Users[\\/]+%s[^\\/\s\"'`<>]+"
        r"|(?<![\w.-])(?:/mnt)?/[A-Za-z]/Users/%s[^/\s\"'`<>)\]]+"
        % (NOT_PLACEHOLDER, NOT_PLACEHOLDER), re.I)),
    ("macOS user path", re.compile(r"(?<![\w:.])/(?:Users)/%s[^/\s\"'`<>)\]]+"
                                   % NOT_PLACEHOLDER)),
    (".ts.net hostname", re.compile(r"(?<![\w.-])%s(?:\.%s)*\.ts\.net%s" % (LABEL, LABEL, HOST_END),
                                    re.I)),
    ("RFC 1918 address", re.compile(
        r"(?<![\w.])(?:10(?:\.%s){3}|172\.(?:1[6-9]|2\d|3[01])(?:\.%s){2}|192\.168(?:\.%s){2})"
        r"(?!\.?\d|\w)" % (OCTET, OCTET, OCTET))),
    # The label must sit directly before .local, so path parts like ~/.local/share do not match.
    (".local hostname", re.compile(r"(?<![\w.-])%s(?:\.%s)*\.local%s" % (LABEL, LABEL, HOST_END),
                                   re.I)),
]

# (relative path, matched text) -> reason. Keep this small.
ALLOWLIST = {}


def doc_files():
    proc = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--"] + DOC_PATHS,
                          capture_output=True)
    assert proc.returncode == 0, "git ls-files failed: %s" % proc.stderr.decode("utf-8", "replace")
    names = [n for n in proc.stdout.decode("utf-8").split("\0") if n]
    assert "README.md" in names and "AGENTS.md" in names, "git ls-files missed the root docs"
    return sorted(names)


UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def read_text(path):
    """Return the file's text, or None for a binary file (a NUL byte and no UTF-16 BOM).

    Any other file that is not UTF-8 raises UnicodeDecodeError, so it is never skipped unscanned.
    """
    data = path.read_bytes()
    if b"\0" in data and not data.startswith(UTF16_BOMS):
        return None
    return data.decode("utf-8")


# Python's tokenizer ends a line only at \r\n, \r or \n. str.splitlines() also splits at form
# feed, vertical tab, \x1c-\x1e, U+0085, U+2028 and U+2029, which would let a comment's tail pass
# as a line of code. All of those are \s for PATTERNS, so a match never spans one either way.
PHYSICAL_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")


def physical_lines(text):
    """Return the text's lines as the tokenizer sees them, line ends kept."""
    return PHYSICAL_LINE.findall(text)


def attribute_ends(text):
    """Return the (line, column) ends of `.local` attribute names in Python code.

    `args.local` in code is attribute access, not a hostname. Strings and comments are not NAME
    tokens, so a hostname in them is still scanned. Fail closed: text that does not parse, or
    tokenizes with an ERRORTOKEN (an unterminated string on Python 3.8 and 3.10), gets none.
    """
    ends, prev = set(), None
    try:
        ast.parse(text)
        for tok in tokenize.generate_tokens(iter(physical_lines(text)).__next__):
            if tok.type == tokenize.ERRORTOKEN:
                return set()
            if tok.type == tokenize.NAME and tok.string.lower() == "local" and prev == ".":
                ends.add(tok.end)
            prev = tok.string if tok.type == tokenize.OP else None
    except (tokenize.TokenError, SyntaxError, ValueError):
        return set()
    return ends


def find_problems(rel_path, text, allowlist=ALLOWLIST, used=None):
    """Return one `path:line` message per match not allow-listed for this exact path."""
    problems = []
    code_attrs = attribute_ends(text) if rel_path.endswith(".py") else set()
    for n, line in enumerate(physical_lines(text), 1):
        for label, pattern in PATTERNS:
            for m in pattern.finditer(line):
                if label == ".local hostname" and (n, m.end()) in code_attrs:
                    continue
                key = (rel_path, m.group(0))
                if key in allowlist:
                    if used is not None:
                        used.add(key)
                    continue
                problems.append("%s:%d: %s %r (AGENTS.md: sanitized)" % (rel_path, n, label,
                                                                          m.group(0)))
    return problems


def test_docs_are_sanitized():
    problems, used = [], set()
    for name in doc_files():
        try:
            text = read_text(ROOT / name)
        except UnicodeDecodeError as e:
            problems.append("%s: not UTF-8 (byte %d), so it cannot be scanned; save it as UTF-8 "
                            "(AGENTS.md: sanitized)" % (name, e.start))
            continue
        if text is not None:
            problems += find_problems(name, text, used=used)
    for key in sorted(set(ALLOWLIST) - used):
        problems.append("%s: stale allow-list entry %r matches nothing; remove it" % key)
    assert not problems, "\n".join(problems)


# Samples are assembled at runtime so this file never contains one itself.
SAMPLES = [
    ("Windows user path", "see " + "C:" + "\\" + "Users" + "\\" + "alice" + "\\notes"),
    ("Windows user path", "see " + "d:" + "/" + "users" + "/" + "alice" + "/notes"),
    ("Windows user path", "see /mnt/" + "c" + "/" + "Users" + "/alice/notes"),
    ("Windows user path", "see /" + "e" + "/" + "users" + "/alice/notes"),
    ("macOS user path", "see /" + "Users" + "/alice/projects"),
    (".ts.net hostname", "ssh build-box." + "tail1234" + ".ts" + ".net now"),
    ("RFC 1918 address", "at " + ".".join(["10", "1", "2", "3"])),
    ("RFC 1918 address", "at " + ".".join(["172", "20", "0", "9"]) + "."),
    ("RFC 1918 address", "at " + ".".join(["192", "168", "1", "50"]) + ":8080"),
    (".local hostname", "open http://printer" + ".local" + "/status"),
]


def test_each_pattern_flags_a_sample():
    for label, line in SAMPLES:
        problems = find_problems("x.md", line, allowlist={})
        assert len(problems) == 1, (label, line, problems)
        assert problems[0].startswith("x.md:1: %s " % label), problems


def test_near_misses_are_not_flagged():
    for line in [
        'os.path.join(home, ".local", "share")',
        "data lives in ~/" + ".local" + "/share",
        "CLAUDE" + ".local" + ".md",
        "## " + "Users",
        ".".join(["172", "15", "0", "1"]),       # just below 172.16/12
        ".".join(["192", "169", "1", "1"]),
        ".".join(["10", "1", "2", "300"]),       # not an address
        "version 1." + ".".join(["10", "0", "0", "1"]),
        "https://example.com/" + "Users" + "/guide",
        "https://example.com/c/" + "Users" + "/guide",
        "see src/c/" + "Users" + "/model.py and docs/a/" + "Users" + "/guide.md",
        "run ./c/" + "Users" + "/setup.sh",
        "Plan C/" + "Users" + " first, then plan D: " + "Users" + " later",
        # Placeholders name nobody.
        "C:" + "\\" + "Users" + "\\" + "<you>\\.claude",
        "C:" + "\\" + "Users" + "\\" + "%USERNAME%\\.claude",
        "/mnt/c/" + "Users" + "/$USER/notes and /c/" + "Users" + "/${USER}/notes",
        "/" + "Users" + "/<you>/projects",
        "C:" + "\\" + "Users" + "\\",
    ]:
        assert find_problems("x.md", line, allowlist={}) == [], line


def test_python_attribute_access_is_not_a_local_hostname():
    loc = ".local"
    for line in ["run(args" + loc + ", args.branch)",
                 "if not (args" + loc + " and args.branch):\n    pass",
                 "x = self.opts" + loc]:
        assert find_problems("x.py", line, allowlist={}) == [], line
    # Strings and comments in code are still scanned, and so is the same text in prose.
    for path, line, text in [
            ("x.py", 'HOST = "printer' + loc + '"', "printer" + loc),
            ("x.py", "# ssh build" + loc + " first", "build" + loc),
            ("x.py", 'connect(args' + loc + ', "printer' + loc + '")', "printer" + loc),
            ("x.md", "pass args" + loc + " through", "args" + loc)]:
        problems = find_problems(path, line, allowlist={})
        assert [p.split(" hostname ")[1] for p in problems] == [
            "%r (AGENTS.md: sanitized)" % text], (path, line, problems)
    # A .py file that does not parse, or tokenizes only with an error token, is scanned as plain
    # text: an unterminated string (an ERRORTOKEN on Python 3.8 and 3.10) and prose that
    # tokenizes but is not Python.
    for line, text in [('f(args' + loc + ', "', "args" + loc),
                       ("HOST = 'printer" + loc, "printer" + loc),
                       ("ssh printer" + loc + " first", "printer" + loc)]:
        problems = find_problems("x.py", line, allowlist={})
        assert [p.split(" hostname ")[1] for p in problems] == [
            "%r (AGENTS.md: sanitized)" % text], (line, problems)


def test_line_separators_inside_a_line_do_not_hide_a_local_hostname():
    # str.splitlines() also splits at these, but Python's tokenizer does not: a comment holding
    # one is still a single comment line, so a .local name after it is not attribute access.
    loc = ".local"
    for sep in ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]:
        for path, text in [("x.py", "# instructions" + sep + "ssh printer" + loc + " first\n"),
                           ("x.py", "# see" + sep + "run(args" + loc + ")\n"),
                           ("x.md", "notes" + sep + "ssh printer" + loc + " first\n")]:
            problems = find_problems(path, text, allowlist={})
            assert len(problems) == 1 and problems[0].startswith(path + ":1: .local hostname"), (
                repr(sep), path, problems)
    # Lines are numbered as the tokenizer counts them, so a form feed (legal at the start of a
    # Python line) neither shifts the exemption nor the line number of a later match.
    text = "x = 1\n\x0crun(args" + loc + ")\n# ssh printer" + loc + "\n"
    assert find_problems("x.py", text, allowlist={}) == [
        "x.py:3: .local hostname 'printer%s' (AGENTS.md: sanitized)" % loc]
    host = "x.py:3: .local hostname 'printer%s' (AGENTS.md: sanitized)" % loc
    attr = "x.py:2: .local hostname 'args%s' (AGENTS.md: sanitized)" % loc
    for sep in ["\r\n", "\r"]:
        text = "x = 1" + sep + "run(args" + loc + ")" + sep + "# ssh printer" + loc + sep
        problems = find_problems("x.py", text, allowlist={})
        # Python 3.8 and 3.10 tokenize a bare \r as an ERRORTOKEN, so the file gets no exemption.
        assert problems == [host] or (sep == "\r" and problems == [attr, host]), (
            repr(sep), problems)


def test_allowlist_is_exact_per_path():
    text = ".".join(["192", "168", "0", "1"])
    allow = {("a.md", text): "generic example"}
    used = set()
    assert find_problems("a.md", "router at " + text, allowlist=allow, used=used) == []
    assert used == {("a.md", text)}
    assert len(find_problems("b.md", "router at " + text, allowlist=allow)) == 1
    other = ".".join(["192", "168", "0", "2"])
    assert len(find_problems("a.md", "router at " + other, allowlist=allow)) == 1


def test_windows_path_forms_in_code_and_data_files(tmp_path):
    bs = "\\"
    forms = {
        "escaped": "C:" + bs * 2 + "Users" + bs * 2 + "alice",
        "forward-slash": "C:" + "/" + "Users" + "/" + "alice",
        "mixed": "C:" + bs * 2 + "Users" + "/" + "alice",
        "wsl": "/mnt/" + "d" + "/" + "Users" + "/" + "alice",
        "git-bash": "/" + "c" + "/" + "Users" + "/" + "alice",
    }
    wrappers = {".py": 'HOME = "%s"\n', ".json": '{"home": "%s"}\n',
                ".md": "Notes live in `%s`.\n"}
    for form, path_text in forms.items():
        for ext, wrapper in wrappers.items():
            path = tmp_path / ("sample" + ext)
            path.write_bytes((wrapper % path_text).encode("utf-8"))
            problems = find_problems(path.name, read_text(path), allowlist={})
            assert problems == ["%s:1: Windows user path %r (AGENTS.md: sanitized)"
                                % (path.name, path_text)], (form, ext, problems)


def test_non_utf8_text_is_not_skipped(tmp_path):
    leak = "see " + "C:" + "\\" + "Users" + "\\" + "alice"
    for name, data in [("cp1252.md", (leak + " caf\xe9\n").encode("cp1252")),
                       ("utf16.md", (leak + "\n").encode("utf-16"))]:
        path = tmp_path / name
        path.write_bytes(data)
        with pytest.raises(UnicodeDecodeError):
            read_text(path)
    binary = tmp_path / "image.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR")
    assert read_text(binary) is None
