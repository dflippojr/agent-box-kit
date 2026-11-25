"""Isolation for an agent CLI started as a judge: a new empty home, a new empty working
directory, an environment reduced to an allowlist, and a sweep of the folders killed runs leave
behind. Stdlib only; Python 3.8+. Not a script: box-audit's judge.py and audit.py, and
skill-eval's runner.py and skill_eval.py, import it from box/lib (issue #36). judge.py's
docstring states the isolation contract (`run`, `--keep-env`, `--copy-home`, `--work-root`).

run(bundle, command, keep, copy, timeout, out, work_root, protect) starts command with
bundle/prompt.md on stdin, isolated, and returns judge.py run's exit code (0 output written, 1
failed or timed out, 2 usage error). check_copy, unsafe_root, sweep, copy_home and write_back are
its parts, which skill-eval's runner reuses with its own folder prefix and mark text.

Every path digest, copy_home and write_back read, hash or copy comes from the command line
(issue #47). Anything the session started can outlive it (run kills only the command, not its
descendants) and can rename or replace anything in its run folder, the isolated home included.
So both homes are opened as a paths.Anchor before the session starts, and every later read and
write goes through those descriptors without following a link: the isolated home is never
resolved again (review r2). Owner-side links that stay in the owner's home are resolved once,
with paths.contained, when the file is copied. Each file is read once and only the bytes read are
hashed or copied; each write is a new file renamed into place, so nothing at the destination is
written through. A session copy with other hard links is refused. Without folder descriptors
(Windows) --copy-home is refused: check_copy says so, and Anchor raises.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import paths
from paths import Anchor, contained, inside, is_link

ALLOW_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "SystemDrive",
             "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "OS",
             "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "ProgramFiles", "ProgramData",
             "ProgramFiles(x86)", "CommonProgramFiles", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
             "https_proxy", "http_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
             "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE")
STALE_SECONDS = 7200
OWN_MARK = ".box-audit-judge"  # written into each judge folder: only marked folders are swept
REFUSED_NAME = re.compile(r"\.md$|instruction|memory|rules|prompt", re.I)
INSTRUCTION_ENTRIES = ("AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CLAUDE.local.md",
                       "GEMINI.md", ".claude", ".codex", ".agents", ".gemini")


def digest(path, anchor, single=False):
    """SHA-256 of `path`, read through `anchor` (a paths.Anchor) without following a link."""
    return hashlib.sha256(anchor.read(path, single)[0]).hexdigest()


def check_copy(rel, real_home, protect=None):
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return "must be a path relative to the home directory, without .."
    if REFUSED_NAME.search(p.name):
        return "looks like an instruction or memory file"
    if not (real_home / p).is_file():
        return "is not a file in the home directory"
    try:
        contained(real_home / p, real_home)
    except ValueError:
        return "leaves the home directory through a link"
    if protect and inside(real_home / p, protect):
        return "resolves inside the audited repo, where a refreshed login would be written back"
    if protect and os.stat(str(real_home / p)).st_nlink > 1:
        return "has other hard links, which may be inside the audited repo"
    if not paths.AT_FDS:
        return paths.NO_FDS
    return None


def holds_checkout(folder):
    """True if a .git folder or file is in `folder` or below it, links not followed. An
    unreadable folder raises OSError, so the caller keeps it."""
    def fail(e):
        raise e
    for top, dirs, files in os.walk(str(folder), onerror=fail):
        if ".git" in dirs or ".git" in files:
            return True
        dirs[:] = [d for d in dirs if not is_link(os.path.join(top, d))]
    return False


def sweep(work_root, max_age, protect=None, prefix="box-audit-judge-"):
    """Delete judge folders a killed run left behind: they can hold copied credentials. Only a
    folder this script made counts: named like one (`prefix`; skill-eval passes its own),
    marked as one, directly in the work root
    (not a link), and not overlapping `protect`, the audited checkout, either way round. No
    caller knows every checkout, so one that is, holds or sits inside any git checkout is kept
    too."""
    now = time.time()
    root = Path(work_root).resolve()
    if any(os.path.lexists(str(folder / ".git")) for folder in [root] + list(root.parents)):
        return
    for old in root.glob(prefix + "*"):
        try:
            if (old.resolve().parent != root or not old.is_dir()
                    or not (old / OWN_MARK).is_file() or now - old.stat().st_mtime <= max_age
                    or protect and (inside(old, protect) or inside(protect, old))
                    or holds_checkout(old)):
                continue
            shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass


def unsafe_root(root):
    """Why `root` cannot hold the judge's working directory, or None."""
    root = Path(root).resolve()
    if not root.is_dir():
        return "%s is not a directory" % root
    home = Path.home().resolve()
    if root == home or home in root.parents:
        return "%s is inside the home directory" % root
    for folder in [root] + list(root.parents):
        for name in INSTRUCTION_ENTRIES:
            if (folder / name).exists():
                return "%s holds %s, which agent CLIs read from every folder below it" % (
                    folder, name)
    return None


def isolated_env(home, keep):
    env = {k: os.environ[k] for k in ALLOW_ENV if k in os.environ}
    env.update({k: os.environ[k] for k in keep if k in os.environ})
    home = str(home)
    env.update({"HOME": home, "USERPROFILE": home,
                "APPDATA": os.path.join(home, "AppData", "Roaming"),
                "LOCALAPPDATA": os.path.join(home, "AppData", "Local"),
                "XDG_CONFIG_HOME": os.path.join(home, ".config"),
                "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
                "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
                "XDG_CACHE_HOME": os.path.join(home, ".cache")})
    if os.name == "nt":
        drive, rest = os.path.splitdrive(home)
        env.update({"HOMEDRIVE": drive, "HOMEPATH": rest})
    for key in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                "XDG_CACHE_HOME"):
        os.makedirs(env[key], exist_ok=True)
    return env


def copy_home(home, copy, keep, real_home):
    """Copy each --copy-home file, already checked, from the owner's home into the empty
    isolated home in order, then make the isolated environment. `home` and `real_home` are
    paths.Anchor objects opened before the session. Return (env, copied); each copied entry is
    (original resolved now, copy, digest of the copy) for write_back after the session. The
    source must stay inside the owner's home (paths.contained resolves its in-home links, once)
    and is read through the anchor; the copy is a new file in folders made through the
    isolated home's descriptor. An error propagates: the caller decides what it means, and
    nothing is written back."""
    copied = []
    for rel in copy:
        src = contained(real_home.given / rel, real_home.real)
        data, mode = real_home.read(src)
        dst = home.given / rel
        home.write(dst, data, mode, make=True)
        copied.append((src, dst, hashlib.sha256(data).hexdigest()))
    return isolated_env(home.given, keep), copied


def anchors(home, copy):
    """(isolated home, owner home) as paths.Anchor objects when files are to be copied, else
    (None, None): a run without --copy-home needs no descriptors and works everywhere."""
    if not copy:
        return None, None
    iso_home = Anchor(home)
    try:
        return iso_home, Anchor(Path.home())
    except BaseException:
        iso_home.close()
        raise


def close(*anchors_):
    for a in anchors_:
        if a is not None:
            a.close()


def run(bundle, command, keep=(), copy=(), timeout=1800, out=None, work_root=None,
        protect=None):
    """Run the judge. `protect` is the audited checkout: the sweep never deletes it and a
    --copy-home file that would be written back into it is refused."""
    prompt = Path(bundle) / "prompt.md"
    if not prompt.is_file():
        print("judge: %s not found; run prepare first" % prompt, file=sys.stderr)
        return 2
    work_root = work_root or tempfile.gettempdir()
    problem = unsafe_root(work_root)
    if problem:
        print("judge: unsafe --work-root: %s. Pass --work-root with a folder outside the home "
              "and free of instruction files." % problem, file=sys.stderr)
        return 2
    for rel in copy:
        problem = check_copy(rel, Path.home(), protect)
        if problem:
            print("judge: refusing --copy-home %s: %s" % (rel, problem), file=sys.stderr)
            return 2
    sweep(work_root, max(STALE_SECONDS, 2 * timeout), protect)
    root = Path(tempfile.mkdtemp(prefix="box-audit-judge-", dir=str(work_root)))
    home = real_home = None
    try:
        (root / OWN_MARK).write_text("made by box-audit judge.py; deleted when stale\n")
        work = root / "work"
        work.mkdir()
        (root / "home").mkdir()
        shutil.copyfile(prompt, work / "prompt.md")
        home, real_home = anchors(root / "home", copy)
        if home is None:
            env, copied = isolated_env(root / "home", keep), []
        else:
            env, copied = copy_home(home, copy, keep, real_home)
        exe = shutil.which(command[0], path=env.get("PATH"))
        if not exe:
            print("judge: command not found: %s" % command[0], file=sys.stderr)
            return 2
        try:
            with open(work / "prompt.md", "rb") as stdin:
                p = subprocess.run([exe] + list(command[1:]), stdin=stdin, cwd=str(work), env=env,
                                   capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            print("judge: timed out after %ss" % timeout, file=sys.stderr)
            return 1
        finally:
            for original, dst, before in copied:
                write_back(original, dst, before, home, real_home)
        text = p.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
        if p.returncode != 0 or not text.strip():
            print("judge: command exited %d with %d bytes of output\n%s" % (
                p.returncode, len(text), p.stderr.decode("utf-8", errors="replace")[-2000:]),
                file=sys.stderr)
            return 1
        if out:
            with open(out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        else:
            sys.stdout.buffer.write(p.stdout)
        return 0
    finally:
        close(home, real_home)
        shutil.rmtree(root, ignore_errors=True)


def write_back(original, copy, before, home, real_home):
    """Keep a login the judge refreshed, unless the owner's file changed meanwhile. `home` and
    `real_home` are the paths.Anchor objects opened before the session, so a session that
    replaced its home, or the run folder above it, still has only its own copy read. `original`
    was resolved when it was copied and is reached from the owner's home descriptor; a folder on
    it that has become a link since is refused. A copy that is a link, not a regular file or
    hard linked is refused. The copy is read once, and the bytes hashed are the bytes written,
    as a new file renamed over the original with the original's mode."""
    try:
        try:
            data = home.read(copy, single=True)[0]
        except FileNotFoundError:
            return
        if hashlib.sha256(data).hexdigest() == before or digest(original, real_home) != before:
            return
        real_home.write(original, data)
        print("judge: wrote the refreshed %s back" % original.name, file=sys.stderr)
    except (OSError, ValueError) as e:
        print("judge: could not write back %s: %s" % (original.name, e), file=sys.stderr)
