"""Tests for box/ratchet/scripts/ratchet.py. Every ledger is synthetic, built at runtime in
tmp_path with generic repo ids; no real ledger rows are committed (the issue's constraint). The
script runs as a subprocess, the way an owner runs it, so exit codes and stderr are tested as
they are."""
import csv
import datetime
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "box" / "ratchet" / "scripts" / "ratchet.py"
sys.path.insert(0, str(SCRIPT.parent))

import ratchet  # noqa: E402

AS_OF = datetime.date(2026, 6, 1)
CHANGE = datetime.date(2026, 2, 1)


def day(offset, base=CHANGE):
    return base + datetime.timedelta(days=offset)


def pr(number, merged, defect=None, revert=None, source="escaped-defect", repo="example/app"):
    """One ledger row as the README defines it. `defect`/`revert` are days after the merge."""
    return {"repo": repo, "pr": number, "merged": merged.isoformat(), "tier": "standard",
            "kit_commit": "0123abc", "review_findings": 0,
            "defect_date": day(defect, merged).isoformat() if defect is not None else None,
            "defect_source": source if defect is not None else None,
            "revert_date": day(revert, merged).isoformat() if revert is not None else None}


def series(start_number, first_day, count, bad=(), step=1):
    """`count` PRs merged `step` days apart from `first_day` (an offset from CHANGE); the ones
    whose index is in `bad` get an escaped defect 10 days after their merge."""
    return [pr(start_number + i, day(first_day + i * step), defect=10 if i in bad else None)
            for i in range(count)]


def write_ledger(path, rows):
    path = Path(path)
    if path.suffix == ".csv":
        with open(str(path), "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=ratchet.LEDGER_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: "" if v is None else v for k, v in row.items()})
    else:
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def write_changes(path, changes):
    path = Path(path)
    if path.suffix == ".csv":
        lines = ["date,change"] + ["%s,%s" % (d.isoformat(), name) for d, name in changes]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        path.write_text("".join(json.dumps({"date": d.isoformat(), "change": name}) + "\n"
                                for d, name in changes), encoding="utf-8")
    return path


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT)] + [str(a) for a in args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def ratchet_report(tmp_path, rows, changes=None, ext=".csv", window=None, as_of=AS_OF):
    ledger = write_ledger(tmp_path / ("ledger" + ext), rows)
    changes = write_changes(tmp_path / ("changes" + ext),
                            changes if changes is not None else [(CHANGE, "lesson-x")])
    args = [ledger, changes, "--as-of", as_of.isoformat()]
    if window is not None:
        args += ["--window", window]
    proc = run(*args)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    return proc.stdout


def block(text, name):
    """The report lines for one change."""
    lines = text.rstrip("\n").split("\n\n")
    found = [b for b in lines if b.startswith("change: %s " % name)]
    assert len(found) == 1, text
    return found[0]


# ----- verdicts ------------------------------------------------------------------------------

def test_a_change_that_helps_shows_a_lower_rate_after(tmp_path):
    rows = series(1, -40, 20, bad={2, 5, 9, 14}) + series(101, 1, 20, bad={7})
    out = block(ratchet_report(tmp_path, rows), "lesson-x")
    assert "before: 4/20 incorrect (20.0%), 0 pending" in out
    assert "after:  1/20 incorrect (5.0%), 0 pending" in out
    assert out.endswith("verdict: lower incorrect rate after")


def test_a_change_that_does_nothing_shows_the_same_rate(tmp_path):
    rows = series(1, -40, 20, bad={1, 11}) + series(101, 1, 20, bad={3, 18})
    out = block(ratchet_report(tmp_path, rows), "lesson-x")
    assert "before: 2/20 incorrect (10.0%)" in out
    assert "after:  2/20 incorrect (10.0%)" in out
    assert out.endswith("verdict: same incorrect rate")


def test_a_change_that_hurts_shows_a_higher_rate_after(tmp_path):
    rows = series(1, -40, 20) + series(101, 1, 20, bad={0, 1, 2})
    out = block(ratchet_report(tmp_path, rows), "lesson-x")
    assert out.endswith("verdict: higher incorrect rate after")


def test_too_few_prs_after_gives_no_verdict(tmp_path):
    rows = series(1, -40, 20, bad={0}) + series(101, 1, 7)
    out = block(ratchet_report(tmp_path, rows), "lesson-x")
    assert "after:  0/7 incorrect (0.0%)" in out
    assert out.endswith("verdict: too few PRs to say (before 20 of 20, after 7 of 20)")
    assert "lower" not in out and "same" not in out


def test_too_few_prs_before_gives_no_verdict(tmp_path):
    rows = series(1, -5, 3) + series(101, 1, 20)
    out = block(ratchet_report(tmp_path, rows), "lesson-x")
    assert out.endswith("verdict: too few PRs to say (before 3 of 20, after 20 of 20)")


def test_an_empty_ledger_is_too_few_not_an_error(tmp_path):
    out = block(ratchet_report(tmp_path, []), "lesson-x")
    assert "before: 0/0 incorrect (n/a), 0 pending" in out
    assert "verdict: too few PRs to say (before 0 of 20, after 0 of 20)" in out


def test_window_option_sets_n(tmp_path):
    rows = series(1, -40, 20) + series(101, 1, 7, bad={6})
    out = block(ratchet_report(tmp_path, rows, window=5), "lesson-x")
    assert "before: 0/5 incorrect" in out
    assert "after:  0/5 incorrect" in out  # the first five after; the bad one is sixth or later
    assert out.endswith("verdict: same incorrect rate")


def test_windows_take_the_last_n_before_and_the_first_n_after(tmp_path):
    # Old defects beyond the before window and late defects beyond the after window are ignored.
    rows = (series(1, -90, 10, bad=set(range(10))) + series(11, -40, 5)
            + series(101, 1, 5) + series(201, 20, 10, bad=set(range(10))))
    out = block(ratchet_report(tmp_path, rows, window=5), "lesson-x")
    assert "before: 0/5 incorrect" in out
    assert "after:  0/5 incorrect" in out


def test_a_pr_merged_on_the_change_date_is_in_neither_window(tmp_path):
    rows = series(1, -10, 3) + [pr(50, CHANGE, revert=1)] + series(101, 1, 3)
    out = block(ratchet_report(tmp_path, rows, window=3), "lesson-x")
    assert "before: 0/3 incorrect" in out and "after:  0/3 incorrect" in out


def test_each_change_gets_its_own_windows(tmp_path):
    rows = series(1, -40, 20, bad={0, 1}) + series(101, 1, 20) + series(201, 30, 20, step=1)
    changes = [(CHANGE, "lesson-x"), (day(25), "rubric-y")]
    text = ratchet_report(tmp_path, rows, changes=changes)
    assert block(text, "lesson-x").endswith("verdict: lower incorrect rate after")
    assert block(text, "rubric-y").endswith("verdict: same incorrect rate")


def test_no_changes_listed_is_still_a_report(tmp_path):
    text = ratchet_report(tmp_path, series(1, -5, 3), changes=[])
    assert text.rstrip().endswith("no changes listed")


# ----- what counts as incorrect --------------------------------------------------------------

@pytest.mark.parametrize("outcome, counted", [
    ({"defect": 30}, True),
    ({"defect": 31}, False),
    ({"defect": 0, "source": "bug-hunt"}, True),
    ({"revert": 3}, True),
    ({"revert": 45}, False),
    ({}, False),
])
def test_incorrect_means_a_defect_or_revert_within_30_days(outcome, counted):
    row = ratchet.ledger_row("x row 2", {k: "" if v is None else str(v) for k, v in
                                         pr(1, day(0), **outcome).items()})
    assert ratchet.incorrect(row) is counted


# ----- pending -------------------------------------------------------------------------------

def test_prs_within_30_days_of_the_report_date_are_pending(tmp_path):
    as_of = day(60)
    # 20 settled PRs after the change, then 5 merged within 30 days of the report date. Two of
    # the recent ones are already reverted; pending, they count in neither rate nor window.
    recent = [pr(301 + i, day(35 + i), revert=1 if i < 2 else None) for i in range(5)]
    rows = series(1, -40, 20, bad={0}) + series(101, 1, 20, step=1) + recent
    text = ratchet_report(tmp_path, rows, as_of=as_of)
    assert "ledger: ledger.csv, 45 PRs, 5 pending" in text
    out = block(text, "lesson-x")
    assert "after:  0/20 incorrect (0.0%), 5 pending" in out
    assert out.endswith("verdict: lower incorrect rate after")


def test_pending_prs_do_not_fill_a_short_window(tmp_path):
    as_of = day(50)
    # 15 settled after the change (days 1-15), 10 pending (days 21-39): 25 merged after it, but
    # only 15 can be judged.
    rows = series(1, -40, 20) + series(101, 1, 15) + series(201, 21, 10, step=2)
    out = block(ratchet_report(tmp_path, rows, as_of=as_of), "lesson-x")
    assert "after:  0/15 incorrect (0.0%), 10 pending" in out
    assert out.endswith("verdict: too few PRs to say (before 20 of 20, after 15 of 20)")


def test_the_pending_cutoff_is_30_days(tmp_path):
    rows = [pr(1, day(-31, AS_OF)), pr(2, day(-30, AS_OF)), pr(3, day(-29, AS_OF))]
    parsed = [ratchet.ledger_row("x", {k: "" if v is None else str(v) for k, v in r.items()})
              for r in rows]
    assert [ratchet.pending(r, AS_OF) for r in parsed] == [False, False, True]


def test_as_of_defaults_to_today(tmp_path):
    today = datetime.date.today()
    ledger = write_ledger(tmp_path / "ledger.csv", [pr(1, day(-3, today))])
    changes = write_changes(tmp_path / "changes.csv", [])
    proc = run(ledger, changes)
    assert proc.returncode == 0, proc.stderr
    assert "as of %s" % today.isoformat() in proc.stdout
    assert "1 PRs, 1 pending" in proc.stdout


# ----- CSV and JSON Lines --------------------------------------------------------------------

def test_csv_and_jsonl_give_the_same_report(tmp_path):
    rows = series(1, -40, 20, bad={4, 8}) + series(101, 1, 20, bad={2})
    rows[3]["revert_date"] = day(5, day(-37)).isoformat()
    rows += [pr(7, day(-2), repo="example/lib", defect=1, source="bug-hunt")]
    csv_dir, jsonl_dir = tmp_path / "c", tmp_path / "j"
    csv_dir.mkdir()
    jsonl_dir.mkdir()
    from_csv = ratchet_report(csv_dir, rows, ext=".csv")
    from_jsonl = ratchet_report(jsonl_dir, rows, ext=".jsonl")
    assert from_csv.replace("ledger.csv", "ledger.jsonl") == from_jsonl
    assert "before: 4/20 incorrect (20.0%)" in from_jsonl


def test_jsonl_accepts_empty_strings_for_no_outcome(tmp_path):
    row = pr(1, day(-3))
    row.update(defect_date="", defect_source="", revert_date="")
    text = ratchet_report(tmp_path, [row], ext=".jsonl")
    assert "1 PRs" in text


def test_csv_with_a_byte_order_mark_is_read(tmp_path):
    ledger = write_ledger(tmp_path / "ledger.csv", [pr(1, day(-3))])
    ledger.write_bytes(b"\xef\xbb\xbf" + ledger.read_bytes())
    changes = write_changes(tmp_path / "changes.csv", [(CHANGE, "x")])
    proc = run(ledger, changes, "--as-of", AS_OF.isoformat())
    assert proc.returncode == 0, proc.stderr


# ----- malformed input exits 2, naming the file and row --------------------------------------

def malformed(tmp_path, ext, mutate):
    rows = [pr(1, day(-3)), pr(2, day(-2)), pr(3, day(-1))]
    rows = mutate(rows) or rows
    ledger = write_ledger(tmp_path / ("ledger" + ext), rows)
    changes = write_changes(tmp_path / "changes.csv", [(CHANGE, "x")])
    proc = run(ledger, changes, "--as-of", AS_OF.isoformat())
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout == ""
    return proc.stderr


def drop(key):
    def mutate(rows):
        del rows[1][key]
    return mutate


def set_field(key, value):
    def mutate(rows):
        rows[1][key] = value
    return mutate


@pytest.mark.parametrize("mutate, message", [
    (set_field("merged", "2026-13-01"), "bad date '2026-13-01'"),
    (set_field("merged", "2026-02-30"), "no such day"),
    (set_field("merged", "1/2/2026"), "bad date '1/2/2026'"),
    (set_field("merged", ""), "merged is empty"),
    (set_field("repo", ""), "repo is empty"),
    (set_field("pr", "x7"), "bad number 'x7'"),
    (set_field("pr", 0), "bad number"),
    (set_field("review_findings", -1), "bad number"),
    (set_field("tier", "gold"), "tier: 'gold'"),
    (set_field("kit_commit", "main"), "kit_commit: 'main'"),
    (set_field("revert_date", "2025-01-01"), "before the merge"),
    (set_field("defect_date", "2026-01-31"), "defect_date and defect_source go together"),
    (set_field("defect_source", "rumour"), "defect_date and defect_source go together"),
    (set_field("pr", 1), "example/app#1 already at"),
])
@pytest.mark.parametrize("ext", [".csv", ".jsonl"])
def test_a_malformed_row_exits_2_naming_file_and_row(tmp_path, ext, mutate, message):
    err = malformed(tmp_path, ext, mutate)
    row = 3 if ext == ".csv" else 2  # CSV counts the header as row 1
    assert "ledger%s row %d:" % (ext, row) in err
    assert message in err


@pytest.mark.parametrize("ext", [".csv", ".jsonl"])
def test_a_bad_defect_source_with_a_date_is_named(tmp_path, ext):
    def mutate(rows):
        rows[1].update(defect_date=day(1, day(-2)).isoformat(), defect_source="rumour")
    assert "defect_source: 'rumour'" in malformed(tmp_path, ext, mutate)


def test_a_missing_jsonl_key_is_an_error(tmp_path):
    err = malformed(tmp_path, ".jsonl", drop("revert_date"))
    assert "ledger.jsonl row 2: missing field revert_date" in err


def test_an_unknown_jsonl_key_is_an_error(tmp_path):
    err = malformed(tmp_path, ".jsonl", set_field("revert", "2026-02-01"))
    assert "ledger.jsonl row 2: unknown field revert" in err


def test_a_jsonl_number_given_as_true_is_an_error(tmp_path):
    assert "bad number True" in malformed(tmp_path, ".jsonl", set_field("review_findings", True))


def test_a_missing_csv_column_is_an_error(tmp_path):
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("repo,pr,merged\nexample/app,1,2026-01-01\n", encoding="utf-8")
    proc = run(ledger, write_changes(tmp_path / "changes.csv", []))
    assert proc.returncode == 2
    assert "ledger.csv row 1 (header): missing field tier" in proc.stderr


def test_a_short_csv_row_is_an_error(tmp_path):
    ledger = write_ledger(tmp_path / "ledger.csv", [pr(1, day(-3))])
    with open(str(ledger), "a", encoding="utf-8", newline="") as handle:
        handle.write("example/app,2,2026-01-01\n")
    proc = run(ledger, write_changes(tmp_path / "changes.csv", []))
    assert proc.returncode == 2
    assert "ledger.csv row 3: 3 cells, header has 9" in proc.stderr


def test_a_line_that_is_not_json_is_an_error(tmp_path):
    ledger = write_ledger(tmp_path / "ledger.jsonl", [pr(1, day(-3))])
    with open(str(ledger), "a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    proc = run(ledger, write_changes(tmp_path / "changes.csv", []))
    assert proc.returncode == 2
    assert "ledger.jsonl row 2: not JSON" in proc.stderr


@pytest.mark.parametrize("text, message", [
    ("date,change\n2026-02-31,x\n", "changes.csv row 2: bad date '2026-02-31' (no such day)"),
    ("date,change\n2026-02-01,\n", "changes.csv row 2: change is empty"),
    ("when,change\n2026-02-01,x\n", "changes.csv row 1 (header): missing field date"),
    ("", "changes.csv: empty file"),
])
def test_a_malformed_change_list_exits_2(tmp_path, text, message):
    ledger = write_ledger(tmp_path / "ledger.csv", [pr(1, day(-3))])
    changes = tmp_path / "changes.csv"
    changes.write_text(text, encoding="utf-8")
    proc = run(ledger, changes)
    assert proc.returncode == 2
    assert message in proc.stderr


def test_unreadable_unknown_or_non_utf8_files_exit_2(tmp_path):
    changes = write_changes(tmp_path / "changes.csv", [])
    missing = run(tmp_path / "nope.csv", changes)
    assert missing.returncode == 2 and "nope.csv: cannot read" in missing.stderr
    other = tmp_path / "ledger.xlsx"
    other.write_bytes(b"PK")
    unknown = run(other, changes)
    assert unknown.returncode == 2 and "unknown extension '.xlsx'" in unknown.stderr
    latin = tmp_path / "ledger.csv"
    latin.write_bytes(",".join(ratchet.LEDGER_FIELDS).encode() + b"\ncaf\xe9,1\n")
    bad = run(latin, changes)
    assert bad.returncode == 2 and "ledger.csv: not UTF-8" in bad.stderr


@pytest.mark.parametrize("args", [[], ["--window", "0"], ["--window", "x"],
                                  ["--as-of", "2026-6-1"], ["--bogus"]])
def test_usage_errors_exit_2(tmp_path, args):
    ledger = write_ledger(tmp_path / "ledger.csv", [])
    changes = write_changes(tmp_path / "changes.csv", [])
    proc = run(*([ledger, changes] + args if args else []))
    assert proc.returncode == 2, proc.stdout
