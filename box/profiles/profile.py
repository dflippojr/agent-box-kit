#!/usr/bin/env python3
"""Resolve the box profile a repo has chosen. Stdlib only. CI runs it on Python 3.10 (Linux,
macOS, Windows) and 3.8 (Linux).

Usage:
  python -B profile.py [REPO]   Print REPO's profile as JSON. REPO defaults to the current
                                directory.

A repo chooses a profile with a `.box-profile` file at its root holding exactly one profile name
(`home` or `corporate`, the JSON files next to this script) and an optional trailing newline
(`\\n` or `\\r\\n`). Anything else, a symlink included, is an error, never a fallback. Without
the file the profile is unset: the loader never picks one, and each component says what it does
then. The profile file itself is checked too: exactly the documented fields and values, and
`name` matching its file name.

Exit codes: 0 profile resolved and printed; 3 no `.box-profile` (unset); 2 usage error, an
invalid `.box-profile` or profile file, or a PYTHONPYCACHEPREFIX inside REPO without -B. Exit 1
is not used.

Writes nothing. Run it as `python -B`: interpreter startup, before the first line, can write
bytecode under a PYTHONPYCACHEPREFIX, so without -B a prefix inside REPO is refused (exit 2).

From Python, load this file by path (the stdlib has its own `profile` module, so a plain
`import profile` can find that one): `load(repo)` returns the profile as a dict, or None when unset, and raises
ProfileError for anything invalid. `load_profile(name)` reads one profile by name.
"""
import sys
# Before any other import: no module may write bytecode, which an inherited PYTHONPYCACHEPREFIX
# would put inside the repo being read. Startup, before this line, is startup_bytecode()'s job.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PROFILES = Path(__file__).resolve().parent
CHOICE = ".box-profile"
# One key per row of box/STANDARD.md's "Host-agnostic mechanisms" table, in table order.
MECHANISMS = ["required_checks", "judge_protection", "worker_identity", "owner_labels",
              "tamper_guard_lint", "scheduled_judges"]
COLUMNS = ["github", "elsewhere", "none"]  # On GitHub, Elsewhere, No hosted VCS
FIELDS = {
    "name": None,  # must equal the file name
    "model_access": {"provider": ["any", "subscription", "api", "bedrock", "other"],
                     "second_family": ["yes", "no", "unknown"]},
    "source_control": ["github", "other", "none", "unknown"],
    "ci_host": ["github", "other", "none", "unknown"],
    "ide": ["any", "none", "other"],
    "mechanisms": dict((key, COLUMNS) for key in MECHANISMS),
}


class ProfileError(Exception):
    """An invalid `.box-profile` or profile file."""


def names():
    """Profile names available, from the JSON files next to this script."""
    return sorted(p.stem for p in PROFILES.glob("*.json"))


def problems(data, name):
    """What is wrong with a parsed profile file called `name`.json, as a list of strings."""
    if not isinstance(data, dict):
        return ["%s.json: not a JSON object" % name]
    out = []

    def walk(value, spec, where):
        if spec is None:
            if value != name:
                out.append("%s: %r does not match the file name %r" % (where, value, name))
        elif isinstance(spec, dict):
            if not isinstance(value, dict):
                out.append("%s: not an object" % where)
                return
            for key in sorted(set(spec) - set(value)):
                out.append("%s.%s: missing" % (where, key))
            for key in sorted(set(value) - set(spec)):
                out.append("%s.%s: not a profile field" % (where, key))
            for key in spec:
                if key in value:
                    walk(value[key], spec[key], "%s.%s" % (where, key))
        elif value not in spec:
            out.append("%s: %r is not one of %s" % (where, value, ", ".join(spec)))

    for key in sorted(set(FIELDS) - set(data)):
        out.append("%s: missing" % key)
    for key in sorted(set(data) - set(FIELDS)):
        out.append("%s: not a profile field" % key)
    for key in FIELDS:
        if key in data:
            walk(data[key], FIELDS[key], key)
    return out


def load_profile(name):
    """The profile called `name`, checked. Raises ProfileError."""
    if name not in names():
        raise ProfileError("unknown profile %r; known: %s" % (name, ", ".join(names())))
    path = PROFILES / (name + ".json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ProfileError("%s: unreadable: %s" % (path.name, exc))
    found = problems(data, name)
    if found:
        raise ProfileError("%s is invalid:\n  %s" % (path.name, "\n  ".join(found)))
    return data


def chosen(repo):
    """The name in REPO/.box-profile, or None if there is no such file. Raises ProfileError."""
    path = Path(repo) / CHOICE
    if path.is_symlink():
        raise ProfileError("%s is a symlink; write the profile name into the file itself" % path)
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProfileError("%s: unreadable: %s" % (path, exc))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ProfileError("%s is not UTF-8 text" % path)
    for ending in ("\r\n", "\n"):
        if text.endswith(ending):
            text = text[:-len(ending)]
            break
    if not text:
        raise ProfileError("%s is empty; write one of: %s" % (path, ", ".join(names())))
    if text != text.strip() or len(text.split()) != 1:
        raise ProfileError("%s must hold exactly one profile name and an optional trailing "
                           "newline; write one of: %s" % (path, ", ".join(names())))
    if text not in names():
        raise ProfileError("%s names unknown profile %r; known: %s"
                           % (path, text[:40], ", ".join(names())))
    return text


def load(repo):
    """REPO's profile as a dict, or None when unset. Raises ProfileError."""
    name = chosen(repo)
    return None if name is None else load_profile(name)


def startup_bytecode(repo):
    """Why interpreter startup may have written bytecode inside repo, or None. Startup runs
    before a script's first line, so only `python -B` (or PYTHONDONTWRITEBYTECODE) stops it."""
    prefix = getattr(sys, "pycache_prefix", None)
    if sys.flags.dont_write_bytecode or not prefix:
        return None
    try:
        Path(prefix).resolve().relative_to(Path(repo).resolve())
    except ValueError:
        return None
    return ("PYTHONPYCACHEPREFIX (%s) is inside %s, so interpreter startup may already have "
            "written bytecode there. Run with `python -B`, or unset it" % (prefix, repo))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Print a repo's box profile as JSON.")
    ap.add_argument("repo", nargs="?", default=".", help="repo root (default: current directory)")
    args = ap.parse_args(argv)
    if not Path(args.repo).is_dir():
        print("profile.py: %s is not a directory" % args.repo, file=sys.stderr)
        return 2
    if startup_bytecode(args.repo):
        print("profile.py: %s" % startup_bytecode(args.repo), file=sys.stderr)
        return 2
    try:
        profile = load(args.repo)
    except ProfileError as exc:
        print("profile.py: %s" % exc, file=sys.stderr)
        return 2
    if profile is None:
        print("profile.py: no %s in %s: profile unset" % (CHOICE, args.repo), file=sys.stderr)
        return 3
    print(json.dumps(profile, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
