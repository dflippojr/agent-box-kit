#!/usr/bin/env python3
"""Compare merged-work correctness before and after each rubric or lesson change, from an outcome
ledger in the format box/ratchet/README.md defines. Stdlib only. CI runs it on Python 3.10
(Linux, macOS, Windows) and 3.8 (Linux).

Usage:
  ratchet.py LEDGER CHANGES [--window N] [--as-of YYYY-MM-DD]

  LEDGER      One row per merged PR: a .csv file with a header row, or a .jsonl file with one
              JSON object per line. The columns or keys are LEDGER_FIELDS, all present.
  CHANGES     The rubric or lesson changes: .csv or .jsonl, columns or keys `date` and `change`.
  --window N  PRs per window (default 20): the last N settled PRs merged before the change and
              the first N merged after it. Below N on either side the change gets "too few PRs
              to say" instead of a verdict.
  --as-of D   The report date (default today). A PR merged less than 30 days before it is
              pending: in no window and no rate, only counted.

A PR is incorrect when, within 30 days of its merge, an escaped defect traces to it (an issue
with the `escaped-defect` label, or a bug-hunt finding naming it as the introducing change) or it
is reverted. A PR merged on a change's own date is in neither of that change's windows: the
ledger has no times, so it cannot tell which version was in force.

Exit codes: 0 report printed, including "too few PRs to say"; 2 usage error, or a ledger or
change list that is unreadable or has a malformed row (a missing or unknown field, a bad date or
number, a duplicate PR). The error names the file and the row. Exit 1 is not used.
"""
import argparse
import csv
import datetime
import json
import re
import sys
from pathlib import Path

LEDGER_FIELDS = ["repo", "pr", "merged", "tier", "kit_commit", "defect_date", "defect_source",
                 "revert_date", "review_findings"]
OPTIONAL = {"defect_date", "defect_source", "revert_date"}
CHANGE_FIELDS = ["date", "change"]
TIERS = {"mechanical", "standard", "frontier", "none"}
DEFECT_SOURCES = {"escaped-defect", "bug-hunt"}
DAYS = 30
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
INT_RE = re.compile(r"^\d+$")


class Malformed(Exception):
    """A row or file the report cannot use; the message names the file and row."""


def parse_date(text):
    if not isinstance(text, str) or not DATE_RE.match(text):
        raise ValueError("bad date %r (want YYYY-MM-DD)" % (text,))
    try:
        return datetime.date(int(text[:4]), int(text[5:7]), int(text[8:]))
    except ValueError:
        raise ValueError("bad date %r (no such day)" % (text,))


def parse_int(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("bad number %r" % (value,))
    if isinstance(value, str):
        if not INT_RE.match(value):
            raise ValueError("bad number %r" % (value,))
        value = int(value)
    if value < (1 if positive else 0):
        raise ValueError("bad number %r" % (value,))
    return value


def records(path, fields):
    """Yield (row label, dict) from a .csv or .jsonl file, with exactly `fields` as keys."""
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".jsonl"):
        raise Malformed("%s: unknown extension %r (want .csv or .jsonl)" % (path, path.suffix))
    try:
        handle = open(str(path), encoding="utf-8-sig", newline="")
    except OSError as err:
        raise Malformed("%s: cannot read: %s" % (path, err.strerror or err))
    with handle:
        try:
            if suffix == ".csv":
                yield from csv_records(path, handle, fields)
            else:
                yield from jsonl_records(path, handle, fields)
        except UnicodeDecodeError:
            raise Malformed("%s: not UTF-8" % path)


def check_keys(where, keys, fields):
    missing = [f for f in fields if f not in keys]
    unknown = sorted(k for k in keys if k not in fields)
    if missing:
        raise Malformed("%s: missing field %s" % (where, ", ".join(missing)))
    if unknown:
        raise Malformed("%s: unknown field %s" % (where, ", ".join(unknown)))


def csv_records(path, handle, fields):
    reader = csv.reader(handle, strict=True)
    try:
        header = next(reader, None)
        if header is None:
            raise Malformed("%s: empty file (want a header row)" % path)
        header = [h.strip() for h in header]
        check_keys("%s row 1 (header)" % path, header, fields)
        if len(set(header)) != len(header):
            raise Malformed("%s row 1 (header): a column appears twice" % path)
        for cells in reader:
            where = "%s row %d" % (path, reader.line_num)
            if not cells:
                continue
            if len(cells) != len(header):
                raise Malformed("%s: %d cells, header has %d" % (where, len(cells), len(header)))
            yield where, {h: c.strip() for h, c in zip(header, cells)}
    except csv.Error as err:
        raise Malformed("%s row %d: %s" % (path, reader.line_num, err))


def jsonl_records(path, handle, fields):
    for number, line in enumerate(handle, 1):
        where = "%s row %d" % (path, number)
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as err:
            raise Malformed("%s: not JSON: %s" % (where, err))
        if not isinstance(row, dict):
            raise Malformed("%s: not a JSON object" % where)
        check_keys(where, row.keys(), fields)
        yield where, {k: ("" if v is None else v) for k, v in row.items()}


def text_field(row, name):
    value = row[name]
    if not isinstance(value, str):
        raise ValueError("%s: want text, got %r" % (name, value))
    return value.strip()


def ledger_row(where, row):
    """Check one ledger row; return a dict with dates and numbers parsed."""
    try:
        out = {}
        for name in ("repo", "tier", "kit_commit", "defect_source"):
            out[name] = text_field(row, name)
        for name in LEDGER_FIELDS:
            if name not in OPTIONAL and row[name] in ("", None):
                raise ValueError("%s is empty" % name)
        out["pr"] = parse_int(row["pr"], positive=True)
        out["review_findings"] = parse_int(row["review_findings"])
        out["merged"] = parse_date(row["merged"])
        if out["tier"] not in TIERS:
            raise ValueError("tier: %r is not one of %s" % (out["tier"], ", ".join(sorted(TIERS))))
        if not COMMIT_RE.match(out["kit_commit"]):
            raise ValueError("kit_commit: %r is not a commit id (7-40 lowercase hex)"
                             % out["kit_commit"])
        for name in ("defect_date", "revert_date"):
            text = text_field(row, name)
            out[name] = parse_date(text) if text else None
            if out[name] and out[name] < out["merged"]:
                raise ValueError("%s %s is before the merge" % (name, text))
        if bool(out["defect_date"]) != bool(out["defect_source"]):
            raise ValueError("defect_date and defect_source go together")
        if out["defect_source"] and out["defect_source"] not in DEFECT_SOURCES:
            raise ValueError("defect_source: %r is not one of %s"
                             % (out["defect_source"], ", ".join(sorted(DEFECT_SOURCES))))
    except ValueError as err:
        raise Malformed("%s: %s" % (where, err))
    return out


def load_ledger(path):
    rows, seen = [], {}
    for where, row in records(path, LEDGER_FIELDS):
        pr = ledger_row(where, row)
        key = (pr["repo"], pr["pr"])
        if key in seen:
            raise Malformed("%s: %s#%d already at %s" % (where, key[0], key[1], seen[key]))
        seen[key] = where
        rows.append(pr)
    rows.sort(key=lambda r: (r["merged"], r["repo"], r["pr"]))
    return rows


def load_changes(path):
    changes = []
    for where, row in records(path, CHANGE_FIELDS):
        try:
            name = text_field(row, "change")
            if not name:
                raise ValueError("change is empty")
            changes.append((parse_date(text_field(row, "date")), name))
        except ValueError as err:
            raise Malformed("%s: %s" % (where, err))
    return changes


def incorrect(pr):
    limit = pr["merged"] + datetime.timedelta(days=DAYS)
    return any(d is not None and d <= limit for d in (pr["defect_date"], pr["revert_date"]))


def pending(pr, as_of):
    return (as_of - pr["merged"]).days < DAYS


def compare(rows, change_date, window, as_of):
    """Before and after windows for one change: dicts of incorrect, merged, pending, full."""
    before = [r for r in rows if r["merged"] < change_date]
    after = [r for r in rows if r["merged"] > change_date]
    sides = []
    for side, take in ((before, lambda s: s[-window:]), (after, lambda s: s[:window])):
        settled = [r for r in side if not pending(r, as_of)]
        chosen = take(settled)
        sides.append({"incorrect": sum(incorrect(r) for r in chosen), "merged": len(chosen),
                      "pending": len(side) - len(settled), "full": len(chosen) == window})
    return sides


def rate(side):
    return side["incorrect"] / side["merged"] if side["merged"] else 0.0


def describe(label, side):
    shown = "%.1f%%" % (100 * rate(side)) if side["merged"] else "n/a"
    return "  %-7s %d/%d incorrect (%s), %d pending" % (label + ":", side["incorrect"],
                                                       side["merged"], shown, side["pending"])


def report(rows, changes, window, as_of, ledger_name):
    lines = ["Ratchet report as of %s: windows of %d PRs; incorrect = escaped defect or revert "
             "within %d days of the merge" % (as_of, window, DAYS),
             "ledger: %s, %d PRs, %d pending" % (ledger_name, len(rows),
                                                 sum(pending(r, as_of) for r in rows))]
    if not changes:
        lines.append("")
        lines.append("no changes listed")
    for change_date, name in changes:
        before, after = compare(rows, change_date, window, as_of)
        lines += ["", "change: %s (%s)" % (name, change_date), describe("before", before),
                  describe("after", after)]
        if not (before["full"] and after["full"]):
            lines.append("  verdict: too few PRs to say (before %d of %d, after %d of %d)"
                         % (before["merged"], window, after["merged"], window))
        elif before["incorrect"] > after["incorrect"]:
            lines.append("  verdict: lower incorrect rate after")
        elif before["incorrect"] < after["incorrect"]:
            lines.append("  verdict: higher incorrect rate after")
        else:
            lines.append("  verdict: same incorrect rate")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ratchet.py", description="Incorrect rate of merged PRs before and after each "
        "rubric or lesson change. Exit 0 report printed; 2 usage error or bad input.")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("changes", type=Path)
    parser.add_argument("--window", type=int, default=20, help="PRs per window (default 20)")
    parser.add_argument("--as-of", dest="as_of", help="report date, YYYY-MM-DD (default today)")
    args = parser.parse_args(argv)
    if args.window < 1:
        parser.error("--window must be at least 1")
    try:
        as_of = parse_date(args.as_of) if args.as_of else datetime.date.today()
    except ValueError as err:
        parser.error("--as-of: %s" % err)
    try:
        rows = load_ledger(args.ledger)
        changes = load_changes(args.changes)
    except Malformed as err:
        print("ratchet.py: %s" % err, file=sys.stderr)
        return 2
    sys.stdout.write(report(rows, changes, args.window, as_of, args.ledger.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
