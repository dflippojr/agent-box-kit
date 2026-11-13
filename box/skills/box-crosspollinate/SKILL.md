---
name: box-crosspollinate
description: Compare box-audit score cards from two or more repos and propose porting each dimension's strongest practice (G R J W P D) to the repos that score lower. Use when asked to compare boxes across repos, find which repo does a dimension best, or spread a practice that already works in one repo to the others. Reads finished cards only; to score a repo, use box-audit.
---

# box-crosspollinate

Each repo's box grows on its own, so one repo has a strong practice the others lack. box-audit
scores one repo at a time and proposes issues from that repo's evidence alone. This skill reads
several finished cards side by side and, for each dimension, proposes porting the strongest
repo's practice to the weaker ones.

It reads cards only. It does not re-score them or read the repos: the card's marks and evidence
are the input, checked by box-audit's own `card.py`. Install it by symlinking this folder, not by
copying it, as box-audit's skill says: `scripts/compare.py` loads box-audit's `card.py` from the
checkout it sits in, and the `../box-audit/` paths below resolve through the link on POSIX.

## Inputs

- **Cards**: two or more box-audit cards, one per repo, each passing
  `python -B ../box-audit/scripts/card.py check <card>`. Use each repo's newest card.

## Compare

1. Run:

   ```
   python -B scripts/compare.py <card> <card> [<card>...] [--max-age DAYS] --out <folder>
   ```

   It prints a matrix of repo against the G R J W P D marks with each card's date, score and
   Proven value, then, for each dimension, the strongest repo or repos (highest mark, ties all
   listed) with the evidence items behind that mark and their sources. n/a is never strongest.

   For each repo below the strongest on some dimension, it writes
   `crosspollinate-<repo>-<date>.md` in the folder: one proposal per such dimension, titled
   "Port the <dimension> from <repo>", in [card-format.md](../box-audit/card-format.md)'s shape
   and labels, naming the source paths the strong card cites. A repo marked n/a on a dimension
   gets no proposal for it. An existing file is never overwritten. Without `--out`, the proposals
   are printed instead. The script's header lists its exit codes.

2. **Mind the warning.** Cards more than `--max-age` days apart (default 30) print a `WARNING:`
   line. A stale card may score a box that has changed since: re-audit that repo before filing.

3. **Read the proposals before anyone acts on them.** A higher mark is the judge's reading of
   that repo's evidence, not proof the practice fits the weaker repo. Check the quoted evidence
   and source paths in the strong repo, and edit or drop a proposal that does not fit. Keep the
   file's shape: `file_issues.py` checks it again.

## File

File a proposal file with box-audit's `file_issues.py`, exactly as a card's proposals are filed
(see box-audit's [File](../box-audit/SKILL.md#file) steps):

```
python -B ../box-audit/scripts/file_issues.py crosspollinate-<repo>-<date>.md --repo OWNER/NAME
```

The dry run prints every issue with its labels and checks labels and duplicate titles. Show it
to the owner: filing needs the owner's go-ahead. Then rerun with `--apply`. `--folder`,
`--offline` and `--only` work as they do for a card. File each weaker repo's file into that repo.

## Limits

- The comparison is only as good as the cards. Marks from different judge runs can differ by one
  where the standard leaves room, so a one-mark lead is a lead, not a verdict.
- Source paths are what the strong card cites, in its trailing `(source)` and in code spans that
  name a folder. Host sources (`api ...`, `CI run ...`, `git log`) are quoted, not listed as
  paths.
- It proposes; it never ports code.
