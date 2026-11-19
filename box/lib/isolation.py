"""Isolation for an agent CLI started as a judge: a new empty home, a new empty working
directory, an environment reduced to an allowlist, and a sweep of the folders killed runs leave
behind. Stdlib only; Python 3.8+. Not a script: box-audit's judge.py and audit.py, and
skill-eval's runner.py and skill_eval.py, import it from box/lib (issue #36). judge.py's
docstring states the isolation contract (`run`, `--keep-env`, `--copy-home`, `--work-root`).

run(bundle, command, keep, copy, timeout, out, work_root, protect) starts command with
bundle/prompt.md on stdin, isolated, and returns judge.py run's exit code (0 output written, 1
failed or timed out, 2 usage error). check_copy, unsafe_root, sweep, copy_home and write_back are
its parts, which skill-eval's runner reuses with its own folder prefix and mark text.
"""
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from paths import inside, is_link

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


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_copy(rel, real_home, protect=None):
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return "must be a path relative to the home directory, without .."
    if REFUSED_NAME.search(p.name):
        return "looks like an instruction or memory file"
    if not (real_home / p).is_file():
        return "is not a file in the home directory"
    if protect and inside(real_home / p, protect):
        return "resolves inside the audited repo, where a refreshed login would be written back"
    if protect and os.stat(str(real_home / p)).st_nlink > 1:
        return "has other hard links, which may be inside the audited repo"
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
    """Copy each --copy-home file, already checked, from `real_home` into the empty `home` in
    order, then make the isolated environment. Return (env, copied); each copied entry is
    (original resolved now, copy, digest of the copy) for write_back after the session. An
    error propagates: the caller decides what it means, and nothing is written back."""
    copied = []
    for rel in copy:
        dst = home / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(real_home / rel), str(dst))
        copied.append(((real_home / rel).resolve(), dst, digest(dst)))
    return isolated_env(home, keep), copied


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
    real_home = Path.home()
    for rel in copy:
        problem = check_copy(rel, real_home, protect)
        if problem:
            print("judge: refusing --copy-home %s: %s" % (rel, problem), file=sys.stderr)
            return 2
    sweep(work_root, max(STALE_SECONDS, 2 * timeout), protect)
    root = Path(tempfile.mkdtemp(prefix="box-audit-judge-", dir=str(work_root)))
    try:
        (root / OWN_MARK).write_text("made by box-audit judge.py; deleted when stale\n")
        home, work = root / "home", root / "work"
        work.mkdir()
        home.mkdir()
        shutil.copyfile(prompt, work / "prompt.md")
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
                write_back(original, dst, before)
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
        shutil.rmtree(root, ignore_errors=True)


def write_back(original, copy, before):
    """Keep a login the judge refreshed, unless the owner's file changed meanwhile. `original`
    was resolved when it was copied; a folder on it that has become a link since is refused."""
    try:
        if not copy.is_file() or digest(copy) == before or digest(original) != before:
            return
        if original.parent.resolve() != original.parent:
            raise OSError("a folder on its path is now a link")
        # mkstemp creates the file exclusively and owner-only; it then takes the original's mode,
        # so a private login never becomes readable by others on the way.
        fd, tmp = tempfile.mkstemp(prefix=original.name + ".", suffix=".box-audit-tmp",
                                   dir=str(original.parent))
        try:
            with os.fdopen(fd, "wb") as f, open(copy, "rb") as src:
                shutil.copyfileobj(src, f)
            os.chmod(tmp, stat.S_IMODE(original.stat().st_mode))
            os.replace(tmp, str(original))
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        print("judge: wrote the refreshed %s back" % original.name, file=sys.stderr)
    except OSError as e:
        print("judge: could not write back %s: %s" % (original.name, e), file=sys.stderr)
