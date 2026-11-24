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

From Python, import `profiles` from box/lib (this file's name is the stdlib's `profile` module's
too): `load(repo)` returns the profile as a dict, or None when unset, and raises ProfileError for
anything invalid. `load_profile(name)` reads one profile by name.
"""
import sys
# Before any other import: no module may write bytecode, which an inherited PYTHONPYCACHEPREFIX
# would put inside the repo being read. Startup, before this line, is startup_bytecode()'s job.
sys.dont_write_bytecode = True

from pathlib import Path  # noqa: E402

# box/lib, in the checkout this file sits in, holds the helpers box scripts share (issue #36).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import argparse  # noqa: E402
import json  # noqa: E402

import paths  # noqa: E402
from profiles import CHOICE, ProfileError, load  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Print a repo's box profile as JSON.")
    ap.add_argument("repo", nargs="?", default=".", help="repo root (default: current directory)")
    args = ap.parse_args(argv)
    if not Path(args.repo).is_dir():
        print("profile.py: %s is not a directory" % args.repo, file=sys.stderr)
        return 2
    problem = paths.startup_bytecode(args.repo, args.repo)
    if problem:
        print("profile.py: %s" % problem, file=sys.stderr)
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
