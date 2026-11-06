# 03 — The build loop

Goal: execute a plan one verified task at a time so that the resulting history is easy for a human
to review. This is the default working mode.

## Two lanes

- **Default lane**: routine tasks run back to back without asking permission between them. The
  verification gate, not approval, decides whether each task is committed. The owner reviews in
  batch afterward (`git log`, `git diff`).
- **Deliberate lane**: for a task marked `Risky: yes`, or one that turns out to need judgment.
  State the approach in five bullets or fewer and wait for a go before writing code. Then run the
  same loop.

If a task marked routine turns out risky, switch lanes rather than pushing on.

## The loop, per task

1. **Self-brief.** Restate in a few lines: the objective (one task, verbatim from the plan), the
   files you expect to touch (paths, not pasted contents), what is out of scope, the `Verify:`
   command, and an effort ceiling ("small: about 5 tool calls", "medium: about 10", "hard: about
   15"). If you blow the ceiling, stop and report; the task is probably mis-scoped.
2. **Red first for tests.** For a task that adds or changes a test, watch it fail before the fix
   (red), then pass after (green). Report both. A test you only saw pass proves nothing.
3. **Implement the smallest change** that satisfies the task. Match neighboring style. Handle the
   obvious error paths (bad input, missing file, empty result); do not swallow exceptions.
4. **Review your own diff** (`git diff`) as if someone else wrote it:
   - scope creep or drive-by edits
   - missed error paths
   - hardcoded secrets, credentials, connection strings, sensitive data
   - prompts inlined that belong in files (see 05)
   - anything not covered by the task
5. **Run the task's `Verify:`** and read the real output.
   - Pass: continue.
   - Fail: one focused fix, re-run. Still failing: **stop**, report the failure and your
     diagnosis. Do not commit red.
6. **Commit small.** Stage only this task's files. Message states intent and references the
   task or requirement (`feat: reconstruct input from log only (Task 9, R4)`). Before committing, run
   the secret guard on the staged diff if it is available (see 04). If a hook or the guard blocks
   the commit, fix the cause; never bypass.
7. **Tick the task** in the plan and move on.

## Stop conditions (only these)

- The next task is `Risky: yes`.
- A `Verify:` fails after one retry.
- A guardrail or hook blocks you.
- A real ambiguity the requirements cannot answer. Ask **one** concise question with a
  recommended default. If your instructions say no human will answer (an unattended run), write
  that question on the issue, or wherever the repo says the owner reads, then stop and say
  where. Do not guess, wait, or end your reply on a question.
- The MVP marker is reached.
- You are about to take an action that is irreversible, outside your worktree, or affects
  something shared (see 06 on stating side effects before you start).

Otherwise keep going. Pausing for approval between passing tasks defeats the purpose.

## Rules

- Never skip or weaken a `Verify:` to make a task pass. A red gate is information.
- One task, one commit. Do not start the next task inside the same commit.
- If a task is secretly two tasks or the plan is wrong, stop and say so.
- For a hard reasoning blocker (a design call, a bug you circle on twice), raise your reasoning
  effort for that one problem with a tight, focused prompt. Do not spend it on routine steps.
- Do not work on the default branch or the owner's live checkout.
- Do not merge, deploy, close issues or open external side effects (see 08).

## Definition of done for a task

- It compiles or builds.
- The plan's `Verify:` passes with visible output.
- The diff is minimal and in scope.
- No secrets or sensitive data introduced.
- Any new LLM prompt lives in a file.
- Docs or plan updated if behavior changed.

## When you stop, for any reason

Write a compact summary the owner can review in a minute:

- tasks completed this run, each with its commit subject
- current test status (whole suite)
- what stopped the loop and the exact next action
- **what you did not verify**, and any check that needs a human or a device
- reminders: `git log --oneline` to review, scan for secrets before pushing

For work that will be checked by a script or another session, also print one machine-readable
result line, for example `TASK_7_RESULT: DONE tests=all-pass`. Then confirm the outcome from git or
CI, not just from your own report: agents sometimes do things they were told not to (open a PR)
or omit the line.
