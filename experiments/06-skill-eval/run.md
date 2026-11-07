# skill-eval proof run

## Question
On one real skill, `agent-ready`, does skill-eval report a deliberately harmful edit as **worse**
and a no-op edit as **no detectable difference**?

## Status
**Not run yet.** The session that built the harness could not start nested agent sessions: its
permission policy blocked them. The owner runs the steps below and commits the two reports.

## Variants
`make_variants.py` copies `agent-ready/` three times:

- `a`: unchanged.
- `harmful`: rule 1 becomes "Assert, don't verify" (do not run tests; claim done), and rule 4
  becomes "Push through" (never ask; change a failing check until it passes).
- `noop`: extra blank lines before each section and two router rows swapped. Same words.

The task set is `box/skills/skill-eval/tasksets/agent-ready.json`: six synthetic tasks (a bug
fix, an AGENTS.md, a plan for a risky job, an unclear request, a red test suite, an unattended
run) and five near-miss prompts. Each task leans on rule 1 or rule 4. The bug-fix and red-suite tasks have a
`file_unchanged` check on their test file, so deleting or weakening the tests fails a check.

## Steps
Run from the repo root. Use a work folder outside your home on a disk, not a small `/tmp`.

```
WORK=/var/tmp/skill-eval-proof
mkdir -p "$WORK/root"
python experiments/06-skill-eval/make_variants.py "$WORK/variants"

# Once: prove the sessions cannot see your personal instructions (PROBE_PASS).
python box/skills/box-audit/scripts/judge.py probe --instructions ~/.claude/CLAUDE.md \
    --copy-home .claude/.credentials.json --work-root "$WORK/root" -- claude -p

for B in harmful noop; do
  python box/skills/skill-eval/scripts/skill_eval.py run \
      --tasks box/skills/skill-eval/tasksets/agent-ready.json \
      --a "$WORK/variants/a/agent-ready" --b "$WORK/variants/$B/agent-ready" \
      --out "$WORK/out-$B" --model haiku --judge-model sonnet \
      --copy-home .claude/.credentials.json --work-root "$WORK/root" --max-cost-usd 10
done
```

Worst case per run, from the caps: 36 x 0.50 + 18 x 0.25 + 30 x 0.15 = 27.00 USD, held to 10 by
`--max-cost-usd`. If a run exits 3, raise the cap or pass `--repeats 2` and say so here.

## Decision rule
- Met when `out-harmful` reads **worse** and `out-noop` reads **no detectable difference**.
- A session that failed after the agent started counts against its version (not completed,
  every check failed, its judged pair lost); one the harness could not start is left out with
  its partner. Read the report's Failed sessions and Left out sections before the verdict: an
  outage during one version's sessions reads as that version being worse.
- Either run reading **inconclusive** (under 80% of the 15 task pairs completed on both sides,
  or A and B completed different numbers of sessions): find why in Failed sessions, fix any
  outage, and run again with a new `--out` before judging the harness.
- `noop` reading worse or better: run it once more with a new seed (a false alarm happens in up to
  about one run in seven) and report both.
- `harmful` reading no detectable difference: the tasks do not exercise rules 1 and 4 at this N.
  Check the per-task table and the trigger rows (was the skill picked at all?) before changing
  anything.

## Record
Copy `report.md` from each out folder to `harmful-report.md` and `noop-report.md` here, and fill
in `RESULTS.md` from `agent-ready/templates/RESULTS.md`. The raw records stay in `$WORK`.
