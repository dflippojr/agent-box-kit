"""Shared helpers. Tests use real git in temporary repositories; nothing is mocked."""
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

SCRIPTS = Path(__file__).resolve().parent.parent / "agent-ready" / "scripts"

OUTSIDE_CHECKOUT = "needs a temp dir outside any git checkout: pass --basetemp=<dir outside one>"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "outside_checkout: " + OUTSIDE_CHECKOUT + ". Keep the list short and give "
        "each marked test its reason.")


def enclosing_checkout(path):
    """The first folder at or above `path` that holds `.git`, or None."""
    path = Path(path).resolve()
    for folder in [path] + list(path.parents):
        if (folder / ".git").exists() or (folder / ".git").is_symlink():
            return folder
    return None


@pytest.fixture(autouse=True)
def _outside_checkout(request, tmp_path_factory):
    """Fail, not skip, a marked test whose temp dir sits inside a git checkout: a skip reads
    as green, and the test's subject cannot be exercised there."""
    if request.node.get_closest_marker("outside_checkout") is None:
        return
    base = tmp_path_factory.getbasetemp()
    checkout = enclosing_checkout(base)
    if checkout is not None:
        pytest.fail("%s (%s is inside the checkout at %s)" % (OUTSIDE_CHECKOUT, base, checkout),
                    pytrace=False)


def script(name):
    return str(SCRIPTS / name)


def run(args, cwd=None, **kw):
    """Run a command, capturing text output. Never raises on non-zero."""
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, **kw)


def py(script_name, *args, cwd=None, **kw):
    return run([sys.executable, script(script_name)] + list(args), cwd=cwd, **kw)


def git(repo, *args):
    proc = run(["git", "-C", str(repo)] + list(args))
    assert proc.returncode == 0, "git %s failed: %s" % (" ".join(args), proc.stderr)
    return proc.stdout


def write(repo, name, text):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # LF endings on every platform
    return path


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "gpg.format", "openpgp")  # a global gpg.format=ssh would change how tests sign
    git(root, "config", "core.autocrlf", "false")
    # No background maintenance: it writes .git/objects/maintenance.lock at its own time.
    git(root, "config", "maintenance.auto", "false")
    git(root, "config", "gc.auto", "0")
    write(root, "README.md", "hello\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root
