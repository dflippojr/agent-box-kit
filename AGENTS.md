# AGENTS.md — maintaining agent-box-kit

This repo is documentation. Editing it well means keeping it short, honest and portable.

## Rules for edits

- **Agent-agnostic.** No vendor, model, harness or tool names in `agent-ready/`. Use "agent",
  "session", "owner", "harness".
- **Single-agent** in `agent-ready/`. `box/` is the exception: it defines the whole agent box,
  orchestration included, and stays host- and vendor-neutral. In `agent-ready/`, do not add orchestration, model routing, usage pools or parallel-worker
  guidance. If an idea only works with several agents, it does not belong here.
- **Sanitized.** No employer names, customer or personal data, credentials, hostnames, personal
  file paths or infrastructure detail. Examples use generic domains. `EVIDENCE.md` is public: cite
  sources there generically (an internal project, the owner's work notes), never by private name.
- **Every rule has a reason and a source.** Add or change a rule together with an
  `EVIDENCE.md` row. Mark the evidence honestly: `observed`, `asserted` or `hypothesis`.
  `tests/test_evidence_provenance.py` fails when a module or template in `agent-ready/` has no
  row (by module number, or by the template's repo-relative path in backticks), when a row names
  a path that does not exist, or when its evidence is not one of those three. It reads only
  plain tables, so keep `EVIDENCE.md` free of code fences, indented lines and HTML, and write a
  literal pipe in a cell, even inside backticks, as `\|`.
- **Short.** A module a session cannot read quickly will not be followed. Prefer cutting to
  adding. Rule, why, how.
- **Verify claims.** Do not describe what a tool or command does unless you ran it.
- **Skill self-contained.** `agent-ready/` must work when copied alone: no links outside it.
- **Scripts are code.** Anything in `agent-ready/scripts/` is stdlib-only, has tests in `tests/`,
  and its header states its options and exit codes. Run `python -m pytest tests -q` before saying
  a script change is done. Exit code 1 must not double as "error" where it already means a verdict.
- Test files must not contain secret-shaped literals; build them at runtime (see the existing
  tests) so the guard does not flag its own repo.
- Do not commit or push without the owner's go-ahead.

## Adding a rule

1. Find the evidence (a run, a file, a failure). If there is none, label it `hypothesis`.
2. Put it in the right module, in the imperative, with the reason.
3. Add the `EVIDENCE.md` row.
4. Check it does not conflict with an existing rule and is not a vendor detail.
