#!/usr/bin/env python3
"""Assemble the evaluator input for one case. Stdlib only.

Usage:
  build_input.py CASE_DIR

Prints evaluator-prompt.md followed by the case's source, buggy code, fix patch and candidate
tests. It never prints meta.json, so the evaluator cannot see which candidate is grounded.
Exit codes: 0 printed; 2 a required file is missing.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def block(title, path):
    return "## %s\n\n````\n%s\n````\n" % (title,Path(path).read_text(encoding="utf-8").rstrip("\n"))


def main(argv):
    if len(argv) != 2:
        print("usage: build_input.py CASE_DIR", file=sys.stderr)
        return 2
    case = Path(argv[1])
    try:
        parts = [(HERE / "evaluator-prompt.md").read_text(encoding="utf-8"),
                 block("SOURCE", case / "source.md"),
                 block("CODE", case / "target.py"),
                 block("FIX", case / "fix.patch")]
        for cand in sorted((case / "candidates").glob("test_*.py")):
            parts.append(block("CANDIDATE %s" % cand.stem[5:], cand))
    except OSError as exc:
        print("build_input: %s" % exc, file=sys.stderr)
        return 2
    sys.stdout.buffer.write("\n".join(parts).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
