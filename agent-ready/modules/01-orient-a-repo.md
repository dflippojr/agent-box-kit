# 01 — Orient in an existing repo

Goal: know how to build, test and run the project, know what "normal" looks like before you
change anything, and leave an `AGENTS.md` that lets the next session skip this work.

## Recon checklist

Do this by **running** the safe things (build, test, lint), not only by reading the README.
Documentation drifts; a command that fails today is a fact. Do not run anything that writes to a
shared system (see the run-commands and write-paths bullets below).

- **Build / test / lint commands.** Find them (README, CI config, Makefile, scripts, package
  manifests), run each, and record the exact command and what success looks like.
- **Run commands and entrypoints.** Find them, but do **not** run one that writes to a database,
  an external service, or any shared system. Work out what it would do by reading it, and record
  it as *not run* with the reason.
- **Baseline.** Run the full test suite before touching anything. Record pass/fail counts and any
  failures that already exist. Without a baseline you cannot tell your breakage from old breakage.
- **Intentional oddities.** Note tests that are red on purpose, slow suites, flaky tests, checks
  that need credentials, and commands that must not be run casually. Write these down; the next
  session will otherwise "fix" them.
- **Write paths.** Identify anything that modifies data, sends messages or calls external systems
  (batch jobs, migrations, deploy scripts). Record each as do-not-run, with the target it would
  affect.
- **Structure.** Entry points, module boundaries, where configuration and secrets come from,
  where prompts, fixtures and generated files live.
- **Conventions.** Read one or two neighboring files before adding a new one. Match naming,
  layout, comment density and error handling.
- **Where decisions live.** Design docs, ADRs, issue tracker, changelog. Prior decisions and
  rejected options stop you re-proposing them.
- **Automation.** CI workflows, pre-commit hooks, review bots, static analysis. Know which gates
  your change must pass.
- **Off-limits.** Generated code, vendored dependencies, production config, anything the owner
  says not to touch.

## Work somewhere disposable

Use a branch or a separate worktree, never the owner's live checkout or the default branch.
Check `git status` first and do not disturb uncommitted work you did not make.

## Check the docs against reality

Docs written earlier (including by an agent) can be stale. A run book that says "only tasks 1-2
are done" after all tasks landed is a real example. When a doc contradicts what you observe,
trust the observation, then fix the doc or flag it.

## Write or update `AGENTS.md`

Use `templates/AGENTS.md`. Put in it only what an agent cannot infer from the code:

1. **Commands**: build, test (whole suite and one test), lint, run. Exact. Mark each as *run*
   (verified) or *not run* (read from the code).
2. **How to verify a change** by area (which tests, which script).
3. **Boundaries**: what not to touch, what needs the owner's approval, irreversible actions.
4. **Safety rules**: secrets, personal or regulated data, where credentials come from. Ask the
   owner what counts as sensitive; do not infer data classifications from table or field names.
5. **Conventions** that are not obvious from neighboring files.
6. **Definition of done** for a task in this repo.
7. **Known quirks**: intentional red tests, flaky tests, slow commands.
8. **Pointers** to design docs, the plan, and the state file, not copies of them.

Keep it short and current. Link to longer docs instead of duplicating them. Name the file
`AGENTS.md`; if a specific tool insists on its own instructions file name, make that file a
one-line pointer to `AGENTS.md` so there is one source.

## Exit criteria

- You can state the build and test commands from memory of having run them.
- A baseline is recorded.
- `AGENTS.md` exists; every command in it is marked run or not run, and no write path was
  executed.
- You know which gates your change must pass and what you must not touch.

For a repo that will see repeated agent work, continue with 11 to leave a `docs/` layer behind.
