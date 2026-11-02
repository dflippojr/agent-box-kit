# Results — module 05 evaluator value (2026-10-08)

## Question
When several candidate tests all turn red-to-green under `red_green_gate.py`, does an advisory
model evaluator pick the one grounded in the source, which the gate cannot do?

## Method
- 10 synthetic cases in `cases/`: 8 with three candidates of which exactly one uses only values that
  appear in the source, and 2 negative controls where no candidate is grounded. Each case has a
  short source, a tiny buggy function and a fix patch.
- Gate: `run_gates.py` ran `red_green_gate.py` on all 30 candidates (`--red-pattern AssertionError`,
  pytest). Result in `gate-log.txt`: **30/30 RED->GREEN: PASS**. The gate alone cannot separate them.
- Evaluator: `evaluator-prompt.md` (grounding only, do not re-judge the gate, JSON only, `none`
  allowed). **10 runs, one fresh no-tool session per case, one run per case**, no shared context. Model:
  requested as the `sonnet` alias; the parent session was `claude-sonnet-5-5`. The subagent was not
  asked to self-report its ID, so treat the exact model ID as inferred. Subscription session, no API spend.
- Baseline: `heuristic.py` picks the single candidate whose numeric and string literals all appear in
  the source, otherwise `none`. Chance is 1/3 for the 8 grounded cases.
- Not run: any self-check baseline (per the issue).

## Measurements
| Option | Metric | Result |
|---|---|---|
| Gate alone | candidates separated | 0 of 30 (all pass) |
| Evaluator | grounded picks, cases 01-08 | **8/8** (chance 1/3 per case) |
| Evaluator | false endorsements, controls 09-10 | **0/2** (both answered `none`) |
| Literal-value heuristic | grounded picks, cases 01-08 | **6/8** (no pick on 05 and 08) |
| Literal-value heuristic | false endorsements, controls | 0/2 |

Per-case rows are in `results.csv`. The heuristic missed 05 and 08 because the grounded candidate's
expected value (6.3%, 9.09) is derived by the rule, not written in the source. The evaluator
noticed this in both cases, and still chose the candidate whose inputs came from the source.

## Decision
Decision rule from the issue: at least 7/8 grounded picks, no control endorsements, and better than
the heuristic. **Met: 8/8, 0 endorsements, and 8 > 6.** The evidence row moves to `observed (synthetic)`.
Module 05's wording is not contradicted, so it is unchanged. The evaluator earns its place over the
heuristic here only by the two cases with derived expected values.

## Rejected
Replacing the evaluator with the heuristic: it was 2 cases worse. It stays a cheap first filter.

## What would change this decision
- A harder set where wrong candidates share some source values with the grounded one.
- Repeat runs, other models, or a different author of the cases, if they drop below 7/8.
- Real tasks, where sources are long and messy.

## Not measured / caveats
- Small and synthetic: 8 + 2 cases, one run each, so one error would flip the 7/8 threshold and
  there is no run-to-run variance estimate.
- The ungrounded candidates use wholly unrelated values, which is the easy case. No decoy mixes
  source and invented values.
- The same model family wrote the cases and judged them, which may share blind spots.
- The grounded candidate was `b` in 4 of 8 cases, `a` in 2, `c` in 2. The picks were not all `b`.
- The evaluator sees the fix patch, which sometimes reveals the expected value.
- The gate runner needed `python -B`: a fix that changes a file without changing its size, applied
  within the same second, left a stale `.pyc` and a false "still red". Observed here with `1024` to
  `1000` and `0.05` to `0.08`; `red_green_gate.py` was not changed (out of scope).
