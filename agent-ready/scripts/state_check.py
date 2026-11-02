#!/usr/bin/env python3
"""Validate and maintain a per-work-item state file. Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux); other versions and distributions are not verified.

Usage:
  state_check.py validate FILE
  state_check.py dead-ends FILE
  state_check.py refresh-files FILE --base REF [--dir REPO]

  validate       Check the shape. Prints STATE_OK or STATE_INVALID with reasons.
                 Exit 0 valid, 1 invalid.
  dead-ends      Print the do-not-retry list (errors with "dead_end": true).
  refresh-files  Rewrite files_modified from `git diff --name-status REF...HEAD` so the list
                 comes from git, not from the agent's memory. REF must not start with "-";
                 such a value is rejected before the state file is touched. If git cannot
                 answer, the list is emptied (never left stale) and the exit code is 2.

Exit codes: 0 ok, 1 state file missing, unreadable or invalid (any command), 2 git could
not answer, or --base was rejected (refresh-files).

Shape (see templates/STATE.json):
  {"goal": str, "facts": [str], "files_modified": [{"path": str, "change": str}],
   "errors": [{"what": str, "cause": str, "dead_end": bool}], "next_step": str}
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

WARN_BYTES = 20000


def problems(data):
    out = []
    if not isinstance(data, dict):
        return ["top level must be a JSON object"]
    if not isinstance(data.get("goal"), str) or not data["goal"].strip():
        out.append("goal must be a non-empty string")
    if not isinstance(data.get("next_step"), str) or not data["next_step"].strip():
        out.append("next_step must be a non-empty string")
    facts = data.get("facts")
    if not isinstance(facts, list) or not all(isinstance(f, str) for f in facts):
        out.append("facts must be a list of strings")
    files = data.get("files_modified")
    if not isinstance(files, list) or not all(
            isinstance(f, dict) and isinstance(f.get("path"), str)
            and isinstance(f.get("change"), str) for f in files):
        out.append("files_modified must be a list of {path: str, change: str}")
    errors = data.get("errors")
    if not isinstance(errors, list) or not all(
            isinstance(e, dict) and isinstance(e.get("what"), str)
            and isinstance(e.get("cause"), str) and isinstance(e.get("dead_end"), bool)
            for e in errors):
        out.append("errors must be a list of {what: str, cause: str, dead_end: bool}")
    return out


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except OSError as exc:
        return None, "cannot read file: %s" % exc
    except ValueError as exc:
        return None, "not valid JSON: %s" % exc


def cmd_validate(args):
    data, err = load(args.file)
    found = [err] if err else problems(data)
    if found:
        print("STATE_INVALID")
        for p in found:
            print("  - " + p)
        return 1
    print("STATE_OK")
    if Path(args.file).stat().st_size > WARN_BYTES:
        print("  note: file is over %d bytes; trim old facts and resolved errors" % WARN_BYTES)
    return 0


def cmd_dead_ends(args):
    data, err = load(args.file)
    if err or problems(data):
        print("STATE_INVALID; run 'validate' first", file=sys.stderr)
        return 1
    for e in data["errors"]:
        if e["dead_end"]:
            print("- %s (%s)" % (e["what"], e["cause"]))
    return 0


def cmd_refresh(args):
    data, err = load(args.file)
    if err or problems(data):
        print("STATE_INVALID; run 'validate' first", file=sys.stderr)
        return 1
    proc = subprocess.run(["git", "-C", args.dir, "diff", "--name-status", "-z",
                           "--end-of-options", "%s...HEAD" % args.base], capture_output=True)
    if proc.returncode != 0:
        data["files_modified"] = []
        Path(args.file).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print("git could not answer (%s); files_modified emptied"
              % proc.stderr.decode("utf-8", "replace").strip(), file=sys.stderr)
        return 2
    parts = [p for p in proc.stdout.decode("utf-8", "replace").split("\0")]
    files, i = [], 0
    while i < len(parts) and parts[i]:
        status = parts[i]
        if status[0] in "RC":  # rename or copy: status, old path, new path
            files.append({"path": parts[i + 2], "change": status[0]})
            i += 3
        else:
            files.append({"path": parts[i + 1], "change": status[0]})
            i += 2
    data["files_modified"] = files
    Path(args.file).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("files_modified: %d file(s) from git" % len(files))
    return 0


def git_ref(value):
    # git reads a leading "-" as an option (e.g. --output=FILE writes a file), not as a ref.
    if value.startswith("-"):
        raise argparse.ArgumentTypeError("must be a git ref, not an option: %r" % value)
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "dead-ends", "refresh-files"):
        p = sub.add_parser(name)
        p.add_argument("file")
        if name == "refresh-files":
            p.add_argument("--base", required=True, type=git_ref,
                           help="base ref, e.g. origin/main")
            p.add_argument("--dir", default=".")
    args = ap.parse_args(argv)
    return {"validate": cmd_validate, "dead-ends": cmd_dead_ends,
            "refresh-files": cmd_refresh}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
