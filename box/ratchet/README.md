# Ratchet

The standard, the box-audit rubric and the lessons change by judgment. The ratchet checks whether
a change made merged work more correct, so the kit does not gather rules that cost worker time and
catch nothing. It is [STANDARD.md](../STANDARD.md#d-defect-ratchet)'s D dimension applied to the
kit itself.

It needs an **outcome ledger**, one row per merged PR, and a list of the rubric and lesson changes
with their dates. `scripts/ratchet.py` compares the PRs merged before each change with those merged
after it.

## The ledger format

This is the kit's own format. A private ledger maps to it, not the other way round: export or
convert your ledger into these columns before running the script. No real ledger rows belong in
this repo; they carry repo names and PR detail.

| Column / key | Value | Empty allowed |
|---|---|---|
| `repo` | A generic repo id, such as `example/app` | no |
| `pr` | The PR number, a positive integer | no |
| `merged` | Merge date, `YYYY-MM-DD` | no |
| `tier` | The issue's tier: `mechanical`, `standard`, `frontier`, or `none` | no |
| `kit_commit` | The commit of this repo in force at the merge: the version of the standard and lessons the work was held to (7 to 40 lowercase hex characters) | no |
| `defect_date` | Date an escaped defect was traced to this PR | yes: none traced |
| `defect_source` | How it was traced: `escaped-defect` (an issue with that label) or `bug-hunt` (a bug-hunt finding naming this PR as the introducing change) | only with an empty `defect_date` |
| `revert_date` | Date the PR was reverted | yes: not reverted |
| `review_findings` | The number of review findings on the PR, an integer from 0 | no |

**CSV** (`.csv`): a header row with exactly these nine column names, in any order, then one row
per PR; an empty cell means "none". UTF-8, with or without a byte order mark.

```
repo,pr,merged,tier,kit_commit,defect_date,defect_source,revert_date,review_findings
example/app,101,2026-03-05,standard,abc1230,2026-03-17,escaped-defect,,3
example/lib,102,2026-03-08,mechanical,abc1230,,,2026-03-10,0
```

**JSON Lines** (`.jsonl`): one JSON object per line with exactly these nine keys; `null` or `""`
means "none".

```
{"repo": "example/app", "pr": 101, "merged": "2026-03-05", "tier": "standard", "kit_commit": "abc1230", "defect_date": "2026-03-17", "defect_source": "escaped-defect", "revert_date": null, "review_findings": 3}
```

A missing or unknown column, an empty required value, a bad date or number, an outcome dated
before the merge, or the same `repo` and `pr` twice is an error naming the file and row. The script
never skips a row it cannot read.

## Incorrect and pending

A merged PR is **incorrect** when, within 30 days of its merge, an `escaped-defect` issue traces to
it, a bug-hunt finding names it as the introducing change, or it is reverted. A defect or revert
after day 30 does not count.

A PR merged less than 30 days before the report date (`--as-of`, default today) is **pending**: its
30 days are not up, so it counts in neither the incorrect count nor a window. The report shows how
many PRs on each side of a change are pending.

## Running it

The change list is a `.csv` or `.jsonl` file with `date` (`YYYY-MM-DD`) and `change` (a short name,
such as the lesson file or the STANDARD.md heading):

```
date,change
2026-05-15,lesson: exit-1-is-a-verdict
2026-08-20,STANDARD.md D: trace each defect
```

```
python scripts/ratchet.py LEDGER CHANGES [--window N] [--as-of YYYY-MM-DD]
```

For each change it takes the last N settled PRs merged before the change date and the first N
merged after it (N is `--window`, default 20), and prints each window's incorrect count, size,
rate and pending count. A PR merged on the change date is in neither window, because a ledger has
dates, not times. With fewer than N settled PRs on either side it prints **too few PRs to say**
instead of a verdict. Exit 0 means the report printed, including "too few PRs to say"; exit 2 is a
usage error or an unreadable or malformed ledger or change list. Exit 1 is not used.

On a synthetic ledger of 70 PRs, three days apart:

```
Ratchet report as of 2026-10-10: windows of 20 PRs; incorrect = escaped defect or revert within 30 days of the merge
ledger: ledger.csv, 70 PRs, 5 pending

change: lesson: exit-1-is-a-verdict (2026-05-15)
  before: 6/20 incorrect (30.0%), 0 pending
  after:  0/20 incorrect (0.0%), 5 pending
  verdict: lower incorrect rate after

change: STANDARD.md D: trace each defect (2026-08-20)
  before: 1/20 incorrect (5.0%), 0 pending
  after:  2/7 incorrect (28.6%), 5 pending
  verdict: too few PRs to say (before 20 of 20, after 7 of 20)
```

## Acting on a result

The comparison is two fixed windows with no significance test, so read it as a prompt to look,
not a proof.

- **Lower after: keep** the rule. Note the report in the change's `EVIDENCE.md` row; it moves the
  rule toward `observed`.
- **Same: revise or drop.** A rule that costs worker time and moves nothing is a candidate to cut
  (AGENTS.md: prefer cutting to adding). Before dropping it, read the incorrect PRs after the
  change: if the rule should have caught one and did not, sharpen it or turn it into a check.
- **Higher after: revise.** Read the incorrect PRs after the change and look for the rule's part
  in them, such as work it pushed aside or a check it weakened. Drop it if you find none and the
  next report agrees.
- **Too few PRs to say: wait.** Keep collecting and run it again later. Do not shrink `--window`
  to force a verdict.

Two changes less than N PRs apart share PRs between their windows, and a difference of one or two
PRs in 20 is within noise. In either case, wait for the next report before acting.
