# 06 — Context and continuity

Goal: keep long or interrupted work coherent. A session's context is temporary and degrades;
files survive.

## Put state in files

The plan file (ticked, with recorded deviations) is the primary state. For work that may span
sessions, add a small **state file** per work item (`templates/STATE.json`):

```json
{
  "goal": "...",
  "facts": ["things learned that the next session should not re-derive"],
  "files_modified": [{"path": "...", "change": "..."}],
  "errors": [{"what": "...", "cause": "...", "dead_end": true}],
  "next_step": "..."
}
```

- **Update it before you stop, even if you stop early or blocked.**
- **Record dead ends** (`dead_end: true`) with the cause. The next session should treat them as a
  do-not-retry list. Repeating an identical failed call is a common waste in long sessions.
- `files_modified` should come from `git diff --name-status <base>...HEAD`, not from your memory.
  Agent-reported lists drift. `python scripts/state_check.py refresh-files FILE --base <ref>`
  rewrites it from git (and empties it if git cannot answer, so it is never stale).
- Keep entries short. If the file grows, trim it; a bloated state file defeats its purpose.
- Keep it outside the source tree or git-ignored unless the owner wants it committed.
- Validate its shape so a malformed file is noticed, not trusted:
  `python scripts/state_check.py validate FILE` (prints `STATE_OK` / `STATE_INVALID`), and
  `python scripts/state_check.py dead-ends FILE` prints the do-not-retry list to seed a new session.

## Commit as checkpoints

Commit after every discrete step, not only at the end, so an interruption loses little and the
diff between checkpoints is reviewable. Push a branch at a clean checkpoint only where authorized.

## Handoffs

When ending a session, or when another session or person will continue, write a **handoff brief**
(`templates/HANDOFF.md`): objective, what is done, repo and branch, uncommitted files, checks
already run, blockers, and the exact next action. Link the state file rather than repeating it.

Warning signs that call for a handoff instead of pushing on: the session has compacted repeatedly,
you are repeating actions, or you are patching symptoms.

## Escape the patch loop

Review findings and CI failures tend to produce "one more edge case" each round. A session that
keeps patching accumulates context and drifts from the goal.

- After **three rounds** on the same item, stop patching in the same context.
- Options: start a **fresh session** from a handoff brief and fix the **class** of problem
  behind the findings (a closed grammar, one transition function, a model-based test) instead
  of the newest instance; or, if only small edge cases remain (no crash, data loss or security
  impact), recommend merging and track the rest as follow-ups.
- Tell the owner; do not loop indefinitely.

## Context hygiene

- Hand yourself **paths**, not pasted content. Pasted text stays in context permanently.
- Review **diffs**, not re-read files.
- Run checks in the terminal and keep **only failures**; do not narrate passing output.
- Bound searches and command output. A single 10,000-line result costs more than it is worth;
  narrow the query first.
- Keep the stable prefix (instructions, plan) stable; do not reorder or rewrite it for trivia.
- Summarize or compact at **phase boundaries** (after requirements, after the plan), not
  mid-task.
- Do not re-derive facts already established in the session or the state file.

## Say what a task will do to shared things

Before launching something that occupies a shared resource, blocks others, restarts a service or
holds a device, tell the owner and get an explicit OK. One session stalled the owner's merges
because it started a long job that required holding a resource and did not say so first.

## Keep records append-only and dated

Status docs, backlogs and memory files: add a dated entry; mark old entries **superseded** rather
than rewriting them. Later dated entries beat earlier ones. Record rejected options with the
reason so they are not re-proposed.

## Measure before optimizing

If you want to improve how sessions run (cost, retries, context size), record a baseline first.
When a metric cannot be measured, store **unknown (null), never zero**, and exclude unknowns from
averages. Do not change several things at once.
