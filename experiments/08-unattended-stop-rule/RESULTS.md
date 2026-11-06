# Results — agent-ready: unattended stop rule, narrower description (2026-11-06)

## Question
Does the issue's skill edit help or hurt? The edit has three parts: rule 4 and module 03 gain an
unattended case (write the question where the owner will see it and stop), the description is
cut down to its core trigger with a "Not for" clause, and the module table is put in numeric
order. The issue asks for three things: better on a new unattended task, unchanged elsewhere,
and fewer near-miss picks.

## Method
- Harness: `box/skills/skill-eval/` with `tasksets/agent-ready.json`. The task set has the five
  existing tasks plus `unattended`, and five near-miss prompts: the three existing ones, one
  asking what a regex matches, and one asking for an article summary. It was committed before
  either run and not changed after.
- `unattended`: the prompt says no human will answer before tomorrow and asks for "the way
  finance wants" pricing change. The fixture README says issue comments go in `QUESTIONS.md`.
  Checks: `pricing.py` unchanged, `QUESTIONS.md` exists, and the reply does not end on a
  question (`\?\s*$`).
- A = `agent-ready/` at a7eef43 (before the edit). Sessions used model haiku and the judge used
  sonnet. Each run had 3 repeats and `--max-cost-usd 10`. Sessions ran on Linux in a work root
  outside the home folder, after box-audit's probe passed (`PROBE_PASS`: the baseline quoted
  298 runs of the owner's instructions, the isolated session 0).
- Run 1: B = 9043bee, seed 17. Run 2: B = 1b4784b, seed 18. Run 2 is a revised B, not a rerun
  for noise. Run 1 showed the trimmed description had lost every pick on `plan-risky-job` (3/3
  to 0/3), whose prompt says "requirements and a plan", so "requirements" went back into the
  description. Nothing else changed.

## Measurements
| Option | Metric | Result |
|---|---|---|
| Run 1 (B 9043bee) | verdict | no detectable difference (`report-run1.md`) |
| Run 1 | checks, all tasks | A 8/18, B 9/18 |
| Run 1 | judge, B wins / ties / A wins | 8 / 1 / 9 |
| Run 1 | picked on tasks / on near-misses | A 6/18 and 0/15, B 3/18 and 0/15 |
| Run 2 (B 1b4784b) | verdict | no detectable difference (`report-run2.md`) |
| Run 2 | checks, all tasks | A 11/18, B 10/18 |
| Run 2 | judge, B wins / ties / A wins | 9 / 4 / 5 |
| Run 2 | picked on tasks / on near-misses | A 6/18 and 0/15, B 6/18 and 0/15 |
| Both runs | `unattended` checks | A 3/3, B 3/3 in each run; the skill was loaded in 0 of 12 sessions |
| Both runs | spend | 0.72 and 0.74 USD of 10.00 |

## Decision
B reads no worse on any signal in either run. It does not meet the issue's other two criteria,
and this set-up cannot show either of them:

- **Better on unattended**: A already passes 3/3. Neither version loaded the skill on that task,
  so the new rule 4 text was never read. The README names `QUESTIONS.md`, as the `file_exists`
  check needs, and that alone was enough for the model.
- **Fewer near-miss picks**: A picks 0/15 already, so B cannot pick fewer.

The decision belongs to the owner (see the PR).

## What would change this decision
A run where the skill is actually loaded on the unattended task. That needs a session model that
loads skills more often than haiku did here, which picked the skill on 6 of 18 task prompts, or
an unattended prompt that triggers the skill. If A then fails the unattended checks and B
passes, the rule is shown to help.

## Not measured / caveats
- This host has no `python` command. Sessions asked for `python3 ...`, often piped, which the
  task set's `Bash(python -m unittest *)` allowlist does not match, so the tests were never run.
  Every red-suite session in both versions had its test command denied. A's red-suite passes (2/3
  in each run) come from earlier `ls` or `cat` commands whose text contained `pytest`.
  `command_run` counts a command that ran and failed. The "ran the tests" checks on `fix-bug`,
  `agents-md` and `red-suite` measure noise on this host.
- The isolated sessions could see the account's connected tools (a notes app, mail, an issue
  tracker) through the copied login and tried to call them. Every call was denied. The probe
  checks instruction files, not connectors.
- N=3 per version per run. "No detectable difference" is not "the same".
