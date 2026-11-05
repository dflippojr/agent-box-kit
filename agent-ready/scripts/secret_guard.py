#!/usr/bin/env python3
"""Secret and sensitive-data guard for git repositories. Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux); other versions and distributions are not verified.

Modes
  --staged        Scan the added lines of the staged diff (default). Exit 1 on findings.
                  This is what the pre-commit hook runs.
  --tree          Scan every git-tracked text file in the working tree. Exit 1 on findings.
  --install-hook  Install a git pre-commit hook that runs --staged. Refuses to overwrite a
                  hook this script did not write unless --force is given.

Exit codes: 0 clean, 1 findings, 2 usage or environment error.

Design notes
  * Findings never print the full secret: only the file, line, label and the first four
    characters. The tool must not leak into the transcript it is protecting.
  * The placeholder allowlist is applied to the MATCHED VALUE, never the whole line, so a real
    secret on a line that also says "example" is still caught.
  * Suppress a single line with the marker  secret-guard: allow  (add a reason next to it).
  * Optional repo config `.secret-guard.json`:
      {"extra_patterns": [{"label": "SSN-shaped", "regex": "\\b\\d{3}-\\d{2}-\\d{4}\\b"}],
       "allow_substrings": ["000-00-0000"],
       "ignore_paths": ["tests/fixtures/*"]}
  * A pre-commit hook is a safety net, not enforcement: `git commit --no-verify` skips it.
    Back it with a CI check (run `--tree`) if the repo matters.
  * The repository is untrusted input. --tree skips a tracked file that is a link, or sits in a
    folder that is one, and a config that is a link is an error (exit 2): a link can point at a
    file outside the repo, and a one-character extra pattern would print it in full. Files are
    opened folder by folder with links refused (POSIX), or opened and then checked for where
    the handle really is (Windows). A platform with neither is refused (exit 2), since a link
    swapped in after a check would otherwise be followed.
"""
import argparse
import fnmatch
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

HOOK_MARKER = "installed by secret_guard.py"
ALLOW_MARKER = "secret-guard: allow"
CONFIG_NAME = ".secret-guard.json"
MAX_FILE_BYTES = 1_000_000

# (label, regex). Group 1, if present, is the value to inspect; otherwise the whole match.
PATTERNS = [
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("AWS secret access key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?(\S{20,})")),
    ("Private key block",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{40,})")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("API key (sk-/pa- prefix)", re.compile(r"\b(?:sk|pa)-[A-Za-z0-9_-]{32,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    ("Hugging Face token", re.compile(r"\bhf_[0-9A-Za-z]{34}\b")),
    ("npm token", re.compile(r"\bnpm_[0-9A-Za-z]{36}\b")),
    ("Live payment key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{24,}\b")),
    ("Assigned secret",
     re.compile(r"(?i)(?:api[_-]?key|secret|password|passwd|token|access[_-]?key)\w*[\"']?"
                r"\s*[=:]\s*[\"']?([A-Za-z0-9/+_.\-]{12,})")),
]

# A matched value containing any of these is treated as a placeholder.
PLACEHOLDER_HINTS = [
    "example", "placeholder", "your", "changeme", "change-me", "redacted", "xxxx", "dummy",
    "fake", "notreal", "environ", "getenv", "process.env", "secret_here", "<", "${", "{{",
]


class Finding:
    def __init__(self, path, line, label, value):
        self.path = path
        self.line = line
        self.label = label
        self.value = value

    def render(self):
        return "%s:%s: %s: %s... (%d chars)" % (
            self.path, self.line, self.label, self.value[:4], len(self.value))


def die(message):
    """Environment or usage error: exit 2, never 1 (1 means 'findings')."""
    print(message, file=sys.stderr)
    sys.exit(2)


class Refused(Exception):
    """A path in the repo that is not read: a link, under a link, not a plain file, too large."""


def is_link(st):
    """A symlink, or on Windows any reparse point (a junction too)."""
    attrs = getattr(st, "st_file_attributes", 0)
    return stat.S_ISLNK(st.st_mode) or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
WALK_FDS = bool(NOFOLLOW) and hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd


def handle_path(fd):
    """Where open file fd really is, after every link, or None where the platform cannot say.
    Only Windows is asked (GetFinalPathNameByHandleW); elsewhere the descriptor walk is used."""
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


def open_inside(root, parts):
    """Open root/parts... for reading, never through a link, even one swapped in after the
    checks. Where the platform allows, walk the folders by descriptor and refuse links at open.
    Otherwise open the path, then ask where the handle really is and refuse it unless that is
    root/parts. Where neither works, refuse to scan at all (exit 2)."""
    flags = os.O_RDONLY | NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    if not WALK_FDS:
        path = os.path.join(str(root), *parts)
        fd = os.open(path, flags)
        try:
            final = handle_path(fd)
            if final is None:
                die("secret_guard: this platform cannot open a file without following links, "
                    "so the repository cannot be read safely; refusing to scan")
            if os.path.normcase(final) != os.path.normcase(path):
                raise Refused("%s is reached through a link" % "/".join(parts))
        except BaseException:
            os.close(fd)
            raise
        return fd
    folder = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            inner = os.open(part, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = inner
        return os.open(parts[-1], flags, dir_fd=folder)
    finally:
        os.close(folder)


def read_inside(root, rel, limit):
    """The bytes of rel, a `/`-separated path under root. Raises Refused if rel or a folder on
    the way to it is a link, or rel is not a plain file of at most limit bytes; OSError if it is
    missing or unreadable."""
    parts = rel.split("/")
    path = str(root)
    for i, part in enumerate(parts):
        path = os.path.join(path, part)
        st = os.lstat(path)
        if is_link(st):
            raise Refused("%s is a link" % "/".join(parts[:i + 1]))
    if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
        raise Refused("%s is not a plain file of at most %d bytes" % (rel, limit))
    fd = open_inside(root, parts)
    with os.fdopen(fd, "rb") as f:
        if not os.path.samestat(st, os.fstat(fd)):
            raise Refused("%s changed while it was read" % rel)
        return f.read(limit)


def load_config(root):
    cfg = {"extra_patterns": [], "allow_substrings": [], "ignore_paths": []}
    try:
        raw = json.loads(read_inside(root, CONFIG_NAME, MAX_FILE_BYTES).decode("utf-8"))
    except FileNotFoundError:
        return cfg
    except Refused as exc:
        die("secret_guard: refusing to read %s: %s" % (CONFIG_NAME, exc))
    except (OSError, ValueError) as exc:
        die("secret_guard: cannot read %s: %s" % (CONFIG_NAME, exc))
    if not isinstance(raw, dict):
        die("secret_guard: %s must be a JSON object" % CONFIG_NAME)
    for key in cfg:
        cfg[key] = raw.get(key, [])
    try:
        cfg["extra_patterns"] = [(p["label"], re.compile(p["regex"]))
                                 for p in cfg["extra_patterns"]]
    except Exception as exc:  # re.compile also raises OverflowError, RecursionError, ...
        die("secret_guard: bad extra_patterns in %s: %s" % (CONFIG_NAME, exc))
    return cfg


def looks_like_placeholder(value, cfg):
    low = value.lower()
    if any(h in low for h in PLACEHOLDER_HINTS):
        return True
    return any(s.lower() in low for s in cfg["allow_substrings"])


def is_plausible_assigned_secret(value):
    """Reduce noise: an identifier like `token = some_function_name` has no digit."""
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value)


def scan_line(text, cfg):
    """Yield (label, value) for each finding on one line."""
    if ALLOW_MARKER in text:
        return
    for label, rx in PATTERNS + cfg["extra_patterns"]:
        for m in rx.finditer(text):
            value = m.group(1) if m.groups() else m.group(0)
            if label == "Assigned secret" and not is_plausible_assigned_secret(value):
                continue
            if looks_like_placeholder(value, cfg):
                continue
            yield label, value


def path_ignored(path, cfg):
    return any(fnmatch.fnmatch(path, pat) for pat in cfg["ignore_paths"])


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=off"] + list(args),
                          capture_output=True)


def scan_staged(root, cfg):
    proc = git(root, "diff", "--cached", "--unified=0", "--no-color", "--no-ext-diff")
    if proc.returncode != 0:
        die("secret_guard: git diff failed: %s"
            % proc.stderr.decode("utf-8", "replace").strip())
    # File headers run from "diff --git" to the first "@@". Only read "+++ " there: an added
    # line whose text starts with "++ " is content, not a header. Split on LF only, as git does:
    # splitlines() also breaks on CR and U+2028 inside added text, which could forge a header.
    findings, path, lineno, in_header = [], None, 0, False
    for raw in proc.stdout.decode("utf-8", "replace").split("\n"):
        if raw.startswith("diff --git "):
            path, in_header = None, True
        elif in_header and raw.startswith("+++ "):
            target = raw[4:].strip().strip('"')
            path = None if target == "/dev/null" else (
                target[2:] if target.startswith("b/") else target)
        elif raw.startswith("@@"):
            in_header = False
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not in_header and path:
            if not path_ignored(path, cfg):
                # Match the record's text as --tree does: split on CR, U+2028 and the rest.
                # The fragments never reach header parsing, and lineno counts LF records.
                for text in raw[1:].splitlines():
                    for label, value in scan_line(text, cfg):
                        findings.append(Finding(path, lineno, label, value))
            lineno += 1
    return findings


def scan_tree(root, cfg):
    proc = git(root, "ls-files", "-z")
    if proc.returncode != 0:
        die("secret_guard: git ls-files failed: %s"
            % proc.stderr.decode("utf-8", "replace").strip())
    findings = []
    for name in proc.stdout.decode("utf-8", "replace").split("\0"):
        if not name or path_ignored(name, cfg):
            continue
        try:
            data = read_inside(root, name, MAX_FILE_BYTES)
        except (OSError, Refused):
            continue
        if b"\0" in data[:8000]:
            continue
        for i, text in enumerate(data.decode("utf-8", "replace").splitlines(), start=1):
            for label, value in scan_line(text, cfg):
                findings.append(Finding(name, i, label, value))
    return findings


def install_hook(root, force):
    proc = git(root, "rev-parse", "--git-path", "hooks")
    if proc.returncode != 0:
        print("secret_guard: %s is not a git repository" % root, file=sys.stderr)
        return 2
    hooks = Path(proc.stdout.decode().strip())
    if not hooks.is_absolute():
        hooks = Path(root) / hooks
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    if hook.exists() and HOOK_MARKER not in hook.read_text(encoding="utf-8", errors="replace") \
            and not force:
        print("secret_guard: %s already exists and was not written by this script; "
              "use --force to replace it" % hook, file=sys.stderr)
        return 2
    script = Path(__file__).resolve().as_posix()
    if "'" in script:
        print("secret_guard: script path contains a single quote; move it", file=sys.stderr)
        return 2
    body = (
        "#!/bin/sh\n"
        "# %s. Blocks commits that add secret-shaped content.\n"
        "PY=\n"
        "for c in python3 python py; do\n"
        "  if \"$c\" -c 'import sys' >/dev/null 2>&1; then PY=$c; break; fi\n"
        "done\n"
        "if [ -z \"$PY\" ]; then\n"
        "  echo 'secret_guard: no working python found; commit blocked' >&2\n"
        "  exit 1\n"
        "fi\n"
        "exec \"$PY\" '%s' --staged\n" % (HOOK_MARKER, script)
    )
    hook.write_bytes(body.encode("utf-8"))
    try:
        hook.chmod(0o755)
    except OSError:
        pass
    print("secret_guard: installed %s" % hook)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="scan the staged diff (default)")
    mode.add_argument("--tree", action="store_true", help="scan all tracked files")
    mode.add_argument("--install-hook", action="store_true", help="install the pre-commit hook")
    ap.add_argument("--dir", default=".", help="repository root (default: current directory)")
    ap.add_argument("--force", action="store_true", help="with --install-hook: replace a foreign hook")
    args = ap.parse_args(argv)
    root = Path(args.dir).resolve()

    if args.install_hook:
        return install_hook(root, args.force)

    cfg = load_config(root)
    findings = scan_tree(root, cfg) if args.tree else scan_staged(root, cfg)
    if not findings:
        print("secret_guard: clean")
        return 0
    for f in findings:
        print(f.render())
    print("secret_guard: %d potential secret(s) found. Remove them, use an environment "
          "variable or placeholder, or mark a false positive with '%s <reason>'. "
          "Do not bypass with --no-verify." % (len(findings), ALLOW_MARKER), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
