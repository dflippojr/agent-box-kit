#!/usr/bin/env python3
"""Baseline for the evaluator experiment: pick the candidate whose literals all appear in the source. Stdlib only.

Usage:
  heuristic.py [--cases DIR] [--csv FILE]

For each cases/NN-slug/ it reads source.md and candidates/test_*.py, collects the literal values of
each candidate (numbers and strings, skipping docstrings, the trivial values 0, 1, -1, booleans,
None and the empty string), and checks each against the source. Numbers are compared as numbers
after removing thousands separators; strings are compared as substrings.

A candidate is grounded when every literal is found. The pick is the single grounded candidate. If
none or more than one qualifies, the answer is "none" (it makes no pick).

Output: one "case pick" line per case; with --csv, also writes case,heuristic_pick,grounded_literals.
Exit codes:
  0  ran
  2  a case directory was unreadable or a candidate did not parse
"""
import argparse
import ast
import re
import sys
from pathlib import Path

TRIVIAL = (0, 1, -1)


def source_numbers(text):
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    return {float(m) for m in re.findall(r"\d+(?:\.\d+)?", text)}


def literals(code):
    """Numbers and strings used in code, excluding docstrings and trivial values."""
    tree = ast.parse(code)
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                doc_ids.add(id(body[0].value))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or id(node) in doc_ids:
            continue
        value = node.value
        if isinstance(value, bool) or value is None or value == "" or value in TRIVIAL:
            continue
        if isinstance(value, (int, float, str)):
            found.append(value)
    return found


def is_grounded(value, source, numbers):
    if isinstance(value, str):
        return value in source
    return float(value) in numbers


def grounded_fraction(code, source):
    """(found, total) literals of a candidate that appear in the source."""
    numbers = source_numbers(source)
    values = literals(code)
    return sum(is_grounded(v, source, numbers) for v in values), len(values)


def pick(source, candidates):
    """candidates: {id: code}. Return the single fully grounded id, or None."""
    full = []
    for cid, code in sorted(candidates.items()):
        found, total = grounded_fraction(code, source)
        if total and found == total:
            full.append(cid)
    return full[0] if len(full) == 1 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default=str(Path(__file__).resolve().parent / "cases"))
    ap.add_argument("--csv")
    args = ap.parse_args(argv)
    rows = ["case,heuristic_pick,grounded_literals"]
    try:
        for case_dir in sorted(p for p in Path(args.cases).iterdir() if p.is_dir()):
            source = (case_dir / "source.md").read_text(encoding="utf-8")
            cands = {c.stem[5:]: c.read_text(encoding="utf-8")
                     for c in sorted((case_dir / "candidates").glob("test_*.py"))}
            chosen = pick(source, cands)
            frac = " ".join("%s=%d/%d" % ((cid,) + grounded_fraction(code, source))
                            for cid, code in sorted(cands.items()))
            print("%s %s" % (case_dir.name, chosen or "none"))
            rows.append("%s,%s,%s" % (case_dir.name, chosen or "none", frac))
    except (OSError, SyntaxError) as exc:
        print("heuristic: %s" % exc, file=sys.stderr)
        return 2
    if args.csv:
        Path(args.csv).write_bytes(("\n".join(rows) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
