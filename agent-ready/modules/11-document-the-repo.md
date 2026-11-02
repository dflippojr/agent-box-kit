# 11 — Document the repo for agent traversal

Goal: leave a small set of docs so any later session, or person, can answer a question about this
repo without re-reading the code. Do this once per repo, after 01, and keep it current. It
describes the project **as it is**. It is not a setup step for any particular task; later work
(including building something modeled on the project, see 09) simply reads it.

**Evidence note:** the structure and procedure come from one real run on one project (2026-09-21).
The process worked. Reviewing the output found the problems that shaped the rules below. Treat this
as a hypothesis until it has been tried on more repos.

## Layout

Create only the docs that have real content. Skeletons are in `templates/docs/`.

```
AGENTS.md            router and rules; its Pointers section lists each doc in one line
docs/
  README.md          index: one line per doc (what it answers, when to read it)
  architecture.md    purpose, data flow, components and what each owns, external dependencies
  data-model.md      what data is read and written, keys, meaning of important fields
                     (or interfaces.md for a service: APIs, messages, files)
  runtime.md         how it starts, is configured, scheduled, deployed, fails and is observed
  testing.md         how the tests work, how to add one, baseline, coverage gaps
  decisions/         one short dated file per decision, including rejected options
```

## Header on every doc

```
Answers: <the questions this doc answers>
Read when: <when to open it>
Basis: read from code at <short sha>, <date>; nothing executed.
```

Use `Basis`, not `Verified`. Reading code is not verifying it. If you did run something, say so:
`Basis: checked by running <command> on <date>`.

Every item in `Answers` is a promise. Deliver it, or write `unknown: <where to look>` under a
heading that names it. A doc that promises "how it is scheduled" and only says "the app has no
scheduler" has not answered.

## Rules

- **Cite a file path for every claim** (in backticks). Describe structure, not line numbers.
- **Write `unknown`, never guess.** List unknowns in the doc and in your final report.
- **Behavior that you reasoned out rather than observed** (framework semantics such as
  transaction rollback, exit codes, retry behavior) is marked *inferred, not exercised*. Better,
  point to a test that exercises it, or note that none exists.
- **Owner-to-confirm items are marked as such.** Do not write data classifications ("this may be
  personal data"), policies ("must not be enabled in production") or ownership as fact. Put them
  under an `Owner to confirm` heading. When the owner answers, replace the marker with
  `Owner-confirmed <date>: <answer>`. Never infer a data classification from table or field names.
- **Keep sensitive identifiers out by default.** Never credentials or data values. Cloud account
  IDs and internal hostnames stay out unless the owner says they may be included. Say where they
  are configured, not what they are.
- **Link, do not duplicate.** Commands live in `AGENTS.md`; overview lives in the README.
- **Small.** About 150 lines per doc. Split rather than grow.
- **External dependencies:** list each one, the repo or team that owns it, and what to read there.
  An agent that hits a package boundary with no pointer has hit a wall.

## Procedure

1. Work on a feature branch, uncommitted. Read only. Do not run the application or any write path
   (see 01).
2. Read the source, configuration, fixtures, and CI files. Answer, from the code: what data is
   read and written and in which direction; how writes are made and their transaction and batch
   boundaries; whether a re-run is safe and whether any dry-run, limit or environment guard
   exists; how the job is started, scheduled and deployed (including where that lives if outside
   the repo); failure behavior and logging; how configuration and secrets are wired; what the
   tests cover and what is missing.
3. Write the docs with the header and rules above. Edit only the Pointers section of `AGENTS.md`.
4. **Consistency pass.** Anything named in more than one place must agree: test names against
   fixture folder names, environment variable names, commands, paths. Every cited path must exist.
   Every `Answers` promise is delivered or marked unknown.
5. Final report: everything marked unknown, every owner-to-confirm item, and every behavior claim
   marked inferred.

## Owner review

1. Open five cited paths at random and check the claim.
2. Read each inferred behavior claim. Those are where a plausible reading is most often wrong.
3. Answer the unknowns; confirm or delete the owner-to-confirm items.
4. Check that no sensitive identifier slipped in.
5. Check that names agree across `AGENTS.md`, the docs and the code.

## Maintenance

Update the affected doc in the same change as the code. Update its `Basis` sha only when you
re-read the code it describes. A stale doc that looks current is worse than none.

## Exit criteria

- `docs/README.md` indexes every doc; `AGENTS.md` Pointers lists them.
- Every doc has the header; every claim cites a path or is marked unknown or inferred.
- The consistency pass is done and the final report delivered.
- The owner has reviewed it.
