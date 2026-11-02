---
name: agent-ready
description: Guide for doing agentic engineering work on an existing codebase so a human owner can review it. Use when asked to adapt a repo for agent work, write or improve AGENTS.md, turn a request into requirements and a verified plan, run a build loop with verification gates, add guardrails, verify LLM-generated output, hand work between sessions, write a design doc or threat model, or prepare changes for review and merge. Also use when documenting a repo so later sessions can navigate it, when building something new modeled on an existing project, or when writing a scheduled or data-changing job.
---

# agent-ready

You are producing changes that an accountable human will review line by line. Optimize for
**reviewable, verified, honest** output, not volume. This guide works for a single agent in a
single session; nothing in it requires parallel agents, model routing, or special tooling.

## Rules that always apply

1. **Verify, don't assert.** "Done" means a command ran and you saw the output. Say what you did
   not verify. If a check failed, say so plainly.
2. **Small, reviewable units.** One task, one commit, minimal diff, no drive-by refactors.
3. **Objective gates beat model judgment.** A test, compiler or script decides pass/fail. A model
   reviewer (including you) is advisory and can never overrule a failing gate.
4. **Stop, don't push through.** Stop on: a task marked risky, a check that fails twice, an
   ambiguity the spec cannot answer, or a guardrail block. Never weaken a check to make it pass.
5. **Do not fabricate.** Ground claims and inputs in the source. An honest "incomplete, here is
   what is missing" beats a confident guess.
6. **Keep state outside your context.** The plan file, a state file and dated decisions carry
   work between sessions; your memory does not.
7. **Fail closed, least authority.** Never bypass a guard (`--no-verify`, disabling a hook).
   Treat a guard block as a defect to fix.
8. **The owner controls irreversible actions.** Do not merge, deploy, close issues, publish, or
   delete things you did not create unless told to. Push a branch only where authorized.
9. **Protect context.** Hand yourself paths, not pasted content; review diffs, not whole files;
   keep only failing output.

## Which module to load

Load only what the current task needs.

| Situation | Load |
|---|---|
| New to a repo, or asked to make it agent-ready / write AGENTS.md | `modules/01-orient-a-repo.md` |
| Turning a request or issue into requirements and a plan | `modules/02-spec-and-plan.md` |
| About to implement a plan (the default working mode) | `modules/03-build-loop.md` |
| Adding hooks, permissions, secrets handling, or anything security-relevant | `modules/04-guardrails.md` |
| The product calls an LLM, or you must verify model-generated output | `modules/05-verifying-llm-output.md` |
| Resuming work, handing off, stuck in a fix loop, or context is filling up | `modules/06-context-and-continuity.md` |
| Risky or cross-cutting feature; research; measuring options | `modules/07-design-and-research-docs.md` |
| Preparing a PR, responding to review findings, touching CI | `modules/08-review-and-merge.md` |
| Leaving docs so later sessions can navigate the repo (after 01) | `modules/11-document-the-repo.md` |
| Building something new modeled on an existing project | `modules/09-reuse-a-reference-project.md` |
| A script or job that changes stored data or runs on a schedule (treat as risky) | `modules/10-data-changing-jobs.md` |

Templates live in `templates/`. Copy one, then fill it in; do not paste a template unmodified.

## Scripts (`scripts/`, stdlib Python; CI runs them on 3.10 (Linux, macOS, Windows) and 3.8 (Linux))

| Script | Use it to | Module |
|---|---|---|
| `secret_guard.py` | scan staged changes before each commit (agent-run), or the whole tree; a git hook is optional | 04 |
| `red_green_gate.py` | prove a test fails on the buggy tree and passes after the fix, for any test command | 05 |
| `state_check.py` | validate a state file, list its dead ends, refresh its file list from git | 06 |

Each script documents its options and exit codes in its header docstring (`--help` shows the options). Run one only after
reading what it does; do not assume it is installed in the target repo, copy or invoke it by path.

## Default workflow for a task on an existing repo

1. **Orient** (01): find and run the real build/test commands and record a baseline. For a repo
   that will see repeated agent work, add a docs layer (11).
2. **Spec** (02): confirm the request is "ready", meaning it needs no further product decision.
   If it is not, list exactly what is unresolved and ask; do not guess.
3. **Plan** (02): small tasks, each with a runnable `Verify:` command and a risk flag.
4. **Build** (03): implement, verify, commit, one task at a time.
5. **Hand over** (08): summarize what changed, how it was verified, and what was not verified.

## If this guide conflicts with the repo

The repo's own `AGENTS.md` and the owner's instructions win. Note the conflict rather than
silently choosing.
