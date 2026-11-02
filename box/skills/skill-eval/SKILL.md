---
name: skill-eval
description: Test whether a small edit to a skill (a reworded rule, a tighter description, a removed paragraph) makes agents do better, worse or the same, by running version A and version B on a task set in isolated agent sessions with a blind judge, repeats, a cost cap and a trigger check. Use when asked to evaluate, A/B test or prove a skill change, to back a skill-change PR with evidence, or to check that a skill's description still triggers.
---

# skill-eval

Compare two versions of one skill: **A**, the current one, and **B**, the change. The output is
a report whose verdict line says **worse**, **better**, **no detectable difference at this N** or
**inconclusive**, with the numbers behind it. That report is the evidence a skill-change PR
cites. The harness only reports; a person or a PR decides.

The design follows box-audit's rule: do not ask the model to judge itself. Scripts run the
sessions and grade every check a script can grade. A judge sees only what both sessions produced,
shown as X and Y in random order, and is never told that versions exist. Scripts, not the judge,
compute the verdict.

## What one run does

1. For each task and each repeat (default 3), one session with A installed and one with B, in
   alternating order. Each session is fresh and non-interactive, in a scratch workspace holding
   only the task's fixture files, with an empty home holding only the skill, and under its own
   cost cap. Isolation reuses box-audit's `judge.py`.
2. Deterministic checks on each session: files, the final reply, the commands it ran (joined
   to their results, so a refused command does not count), and commands run in the workspace
   afterwards.
3. One blind judge call per task and repeat where both sessions completed: the A and B sessions
   as Output X and Output Y in a seeded random order. The judge sees each reply, each shell
   command with its outcome (ran, ran and failed, refused) and output, the files deleted, and the
   files created or changed, a supplied file as a diff. It picks a winner (or a tie) against
   the task's rubric and scores the dimensions, by default `execution` and `intent`, the two
   audit dimensions that apply to an output.
4. The trigger check: was the skill picked in each task session, and not picked in sessions on
   3-5 near-miss prompts, run N times per version.
5. `report.md` and `results.json`: per task and overall, completion and check pass rates A vs
   B, the judge's win rate for B with a 95% interval, trigger rates, cost and time, and the
   verdict.

## 1. Write a task set

A JSON file of 5-10 realistic tasks and 3-5 near-miss prompts. Synthetic fixtures only: never the
owner's live data or a real repo. `tasksets/agent-ready.json` is a worked example.

```json
{
  "skill": "my-skill",
  "dimensions": {"execution": "...", "intent": "..."},
  "tasks": [
    {
      "id": "fix-bug",
      "prompt": "The add function in calc.py gives wrong answers. Fix it.",
      "files": {"calc.py": "def add(a, b):\n    return a - b\n", "test_calc.py": "..."},
      "allow": ["Read", "Edit", "Write", "Skill", "Bash(python -m unittest *)"],
      "checks": [
        {"type": "file_contains", "path": "calc.py", "pattern": "return a \\+ b"},
        {"type": "exit_zero", "command": ["{python}", "-m", "unittest", "-q"]},
        {"type": "command_run", "pattern": "unittest|pytest", "name": "ran the tests"}
      ],
      "rubric": "Minimal fix; runs the tests and reports the result; claims nothing it did not check."
    }
  ],
  "near_miss": ["A prompt that shares words with the skill but should not use it", "..."]
}
```

- `skill` is the name in both versions' front matter. `dimensions` is optional.
- `files` are written into the session's empty workspace. `allow` is optional: the tools the
  session may use, in the agent CLI's own syntax. Without it, the profile's `default_allow`
  applies.
- Check types: `file_exists`, `file_absent`, `file_unchanged` (`path`, one of the task's
  `files`: still there, byte for byte), `file_contains`, `file_not_contains` (`path`,
  `pattern`), `output_contains`, `output_not_contains` (the final reply), `command_run`
  (a regex matching a shell command that ran, even if it failed; a refused request does not
  count), `command_not_run` (fails on any matching request, refused or not), and `exit_zero` (an
  argv run in the workspace after the session; `{python}` is the running interpreter). Patterns
  are Python regexes, case-sensitive unless they start with `(?i)`. A check may carry a `name`.
- Write checks a script can decide and a short rubric for the rest. A check the A version
  already fails tells you about the skill, not the change.
- Guard what a session could delete or weaken to pass: a `file_unchanged` check on each
  supplied test file. A deleted suite can still exit 0 and match `command_run`.
- Near-miss prompts share words or a domain with the skill but should not use it.
- `python scripts/skill_eval.py check <task set>` validates it without running anything.

## 2. Prove the isolation

Once per agent CLI and machine, run box-audit's probe with the same command, credentials and
work root you will use (see `../box-audit/SKILL.md`, step 1). Do not run an eval whose sessions
have not passed it: a session that reads the owner's instructions measures them, not the skill.

## 3. Run A vs B

```
python scripts/skill_eval.py run --tasks <task set> --a <folder of A> --b <folder of B> \
    --out <new folder> [--profile profiles/<cli>.json] [--model <name>] [--judge-model <name>] \
    [--repeats 3] [--max-cost-usd 10] [--copy-home <CLI login file>] [--keep-env <API key var>] \
    [--work-root <folder outside your home>]
```

- `--a` and `--b` are skill folders holding `SKILL.md`. Copy each version out first, for
  example with `git worktree` or `git show <ref>:path`; the harness never reads git.
- Both are installed under the skill's name, so a session cannot tell which it has.
- Prefer a judge model other than the session model, and keep both fixed across runs you compare.
- Exit 0: all ran. Exit 1: some sessions or judge calls failed; the report lists them (see
  Failures below). Exit 3: the cost cap stopped the run; the report covers what ran and says so.
- Budgets are whole cents of at least 0.01 USD; anything else (NaN, infinity, zero, 0.026) is
  refused. The amount reserved against `--max-cost-usd` is the amount the CLI is given.
- `python scripts/skill_eval.py report <out>` rebuilds the report from the records.

The scripts: `skill_eval.py` (command line and the run), `runner.py` (profiles, isolated
sessions, checks), `blind.py` (pairing, the random order, the judge's input and reply),
`report.py` (the maths and the report). The judge's instructions are `judge-prompt.md`.

## 4. Read the verdict

| Signal | Compares | Worse or better when |
|---|---|---|
| completion | share of task sessions that completed, B minus A | the 95% interval excludes 0 |
| checks | share of task sessions completing and passing every check, B minus A | the 95% interval excludes 0 |
| judge | B's share of pairwise outcomes, a tie counting half | the 95% interval excludes one half |
| trigger | share of right picks (picked on tasks, not on near-misses), B minus A | the 95% interval excludes 0 |

Failures. Task sessions are compared in pairs (one task, one repeat, A and B):

- A session that failed after the agent started (timed out, crashed, no reply) counts against its
  version: not completed, failing every check, and its pair's judge outcome goes to the side
  that completed (two failures tie). The harness cannot tell a skill that hangs the agent from
  an outage, so an outage can make a version read worse; rerun after one.
- A session the harness could not start (agent command not found, workspace error) says nothing
  about the skill. It and its partner are left out and listed, as is an unreadable judge reply.

The verdict is **worse** if any signal is worse. Otherwise it is **inconclusive** when completion
is insufficient (fewer than 80% of the planned pairs completed on both sides) or asymmetric (A and
B completed different numbers of sessions): a version cannot read better or no different by
failing. Otherwise it is **better** if at least one signal is better, and **no detectable
difference** if none is. Read it as follows:

- **No detectable difference is not "the same".** At N=3 and 5 tasks, a judge needs B to win
  about 12 of 15 pairs to read better. Small effects need more repeats.
- **Up to ~5% false alarms per signal.** Each interval is 95% (a judge picking at random reads
  worse or better in 3.5% of runs at 15 pairs), and there are four signals (completion rarely
  moves when both versions finish), so up to about one run in seven can read worse or better by
  chance. Before acting on a verdict that surprises you, run again with a new seed.
- Sessions of the same task are not independent, so the intervals are a little narrow.
- Open the per-task table: one task flipping can carry the whole result. Read the judge's
  prompts and replies in `<out>/judge/` for the pairs that decided it.
- The judge is a model. Its reasons are leads; the checks are facts.

## 5. Cost

Every session runs under a cap the agent CLI enforces (`--run-budget-usd`, default 0.50;
`--judge-budget-usd` 0.25; `--trigger-budget-usd` 0.15), and the run under `--max-cost-usd`
(default 10). A session starts only if its cap fits under what is left. A session that reports no
cost counts at its cap. The default run is 5 tasks x 3 repeats x 2 versions = 30 sessions, 15
judge calls and 18 near-miss sessions; `run` prints the worst case before it starts, and the
report records the spend per part. The sessions dominate; cut repeats or tasks first, not the
judge.

## Profiles: other agent CLIs

A profile is a JSON file describing one CLI; `profiles/claude-code.json` is the first. To add
another, copy it and change:

- `command`: non-interactive mode reading the prompt on stdin, printing JSON events (JSON lines
  or one document). A list of strings, one per argument.
- `budget_args` with `{budget}`: the CLI's own spend cap, also a list of strings. Required: no
  cap, no run.
- `model_args`, `allow_args` (with `allow_join`), `default_allow`, and `judge_args` (for
  example, no tools for the judge).
- `skills_dir`: where the CLI finds user skills, relative to its home.
- `result`, `cost`: `{"match": {...}, "field": "a.b"}` picking the final reply and the spend in
  USD from the events. `result` may be `"stdout"`; `cost` may not.
- `commands`, `skill_used`: lists of the same specs, for shell commands requested (each with
  `id`, the field holding the request's ID) and for the event that shows the skill was picked
  (`contains`, default `{skill}`, must appear in the field). Without `commands`, command checks
  are refused; without `skill_used`, the trigger check is skipped.
- `command_results`: `{"match", "id", "output", "error", "denied"}`, the event holding a
  command's result, joined to its request by ID. `error` names a field that is true when the
  command ran and failed; `denied` is a regex on the output that means it never ran. Required
  with `commands`: a request is not an execution.
- `command_denials`: specs whose field is the ID of a refused request.

A CLI that reaches its model through a cloud provider needs that provider's variables passed
with `--keep-env`. Nothing in the harness assumes a code host.

## Limits

- Isolation covers startup context, not the filesystem: a session could read a path it is told
  about, and its shell commands run as you. Keep tasks synthetic and allow only the tools a task
  needs.
- Needs `../box-audit/` beside it (the isolation code).
- The trigger check counts the events the profile names. A CLI that reads the skill some other
  way is counted as not picking it.
- The harness reports. It never edits a skill or opens a PR.
