---
name: box-bootstrap
description: Build the repo-level box items a Python repo is missing (AGENTS.md router and docs layer, one-command gate, CI gate, tamper guard, PR template and PR-body lint, a ready script where the host cannot enforce checks, verify-skill and disposable-instance stubs) on a new branch, chosen by the repo's box profile, until box-audit's collectors find them all. Use when asked to bootstrap, set up or build a repo's agent box, or to close the repo-level gaps a box-audit card found.
---

# box-bootstrap

Build every repo-level box item that templates can create, for a new or existing **Python**
repo, on a branch, and check the result with box-audit's own collectors. The bar is
[`../../STANDARD.md`](../../STANDARD.md); the auditor is [box-audit](../box-audit/SKILL.md).

## Done

Done means every repo-level item bootstrap can create is present, as box-audit's collectors
find it. The only gaps left on the card are then track-record items, which no template creates:

- **D: bug-hunt history.** D's 9 needs a dated bug-hunt pass and every escaped defect traced to
  its PR with a class-level check. A new box has no passes, so D is at best `~`.
- **P: deploy signals.** Health and errors an agent can fetch, a silence alarm, vendored-copy
  freshness and installer smoke tests come from what the repo deploys or ships. P is n/a for an
  undeployed library.

So the first audit after bootstrap does not score 9: the standard allows one `~` only with an
external blocker, and D's missing history is not one.

## Inputs

- **REPO**: a local git checkout, at its top, with at least one commit and no uncommitted
  changes to tracked files.
- **Profile**: from REPO's `.box-profile`, or `--profile home|corporate`. With neither it stops
  (exit 2); it never guesses. An explicit profile is recorded in `.box-profile` on the branch.
- **Stack**: Python only. Another stack, a mixed repo, or one with no stack marker stops it
  (exit 2) and names the supported stacks. A mixed repo whose gate is Python can pass
  `--stack python`.

## Steps

1. **Audit first.** Run box-audit on REPO (its skill, report mode) and keep the card: it is the
   "before".
2. **Build on a branch:**

   ```
   python -B scripts/bootstrap.py <REPO> [--profile NAME] [--base BRANCH] [--branch NAME]
   ```

   Each round runs box-audit's collectors (`collect.py`, no host), writes the template files of
   each missing item, and commits them on the branch (default `box-bootstrap`, created from the
   default branch). It repeats for at most 3 rounds, then re-audits once more and prints each
   item as found or missing, the stubs to fill in, the track-record items and the owner steps.
   Exit 0: every item is present. Exit 1: items are still missing, each with the reason (a
   git-ignored target, an AGENTS.md git does not track, or an existing file the collectors do
   not accept); fix those by hand and run it again. Exit 2: usage error. Exit 3: git or I/O
   error, or a target behind a link or outside the repo, refused before the round writes
   anything. A round whose write or commit fails removes its files again.
3. **Run the new gate locally** on the branch: `python scripts/check.py`. On a project with no
   tests yet it fails, because a gate that runs nothing is not a gate. Say so in the change
   description; do not add a placeholder test to turn it green. On a host-neutral profile, run
   `python scripts/ready.py --body <description file>` too.
4. **Re-audit** with box-audit. Compare with the "before" card: every G and W item bootstrap
   wrote should now be evidence. If the card names a repo-level gap bootstrap could create,
   go back to step 2 (at most 3 rounds in all), then report what is still missing.
5. **Hand over.** Push the branch and open the change for review the way the repo's host does,
   with the bootstrap output's owner steps in the description. The bootstrap branch adds gate
   config, so its own tamper-guard run flags it: it needs the owner's approval like any gate
   change.

Bootstrap never writes to the default branch, never overwrites an existing file (it only adds a
proof section to a tracked AGENTS.md that lacks one), never writes through a link or outside the
repo, never pushes or merges, never changes protection
settings and never applies owner-only labels or tags. Those are printed as **owner steps**, for
example "Require the checks `gate`, `tamper-guard` and `pr-body` on main".

## What it builds

Each mechanism follows its row of STANDARD.md's host-agnostic table, as the profile sets it.
`github` gets the GitHub variant. `elsewhere` and `none` get the host-neutral variant, steps in
`scripts/ready.py`; `elsewhere` also prints the host-side setting as an owner step.

| Item | GitHub variant | Host-neutral variant |
|---|---|---|
| AGENTS.md router (`templates/AGENTS.md`, from agent-ready's) | "Proving a change" says CI requires the gate | it says merges go only through `scripts/ready.py` |
| Docs layer (`templates/docs/`, agent-ready's) | `docs/` index, architecture, data model, runtime, testing | same |
| One-command gate | `scripts/check.py`: every CI step; fails when no tests run | same |
| CI gate | `.github/workflows/gate.yml` on PRs and pushes; never cancels a default-branch run | `scripts/ready.py` runs the gate on the head commit |
| Tamper guard | `scripts/tamper_guard.py` in `.github/workflows/pr-checks.yml`; approval is the owner's `gate-change-approved` label | a step in `scripts/ready.py`; approval is the owner's tag `gate-change-approved/<commit>` |
| PR template and PR-body lint | `.github/pull_request_template.md`; `scripts/pr_body_lint.py` in `pr-checks.yml` | `docs/pull_request_template.md`; a step in `scripts/ready.py` |
| `ready` script | not written: the host enforces required checks | `scripts/ready.py` |
| Verify skill, disposable-instance contract | stubs: `.agents/skills/verify/SKILL.md`, `docs/disposable-instance.md` | same |

The stubs, AGENTS.md and the docs hold `<...>` placeholders. They count as present for the
collectors, but they prove nothing until a worker fills them in from the code.

## Limits

- Python only. The gate runs pytest; add lint, type-check or coverage steps to
  `scripts/check.py`, never to the CI config alone.
- The tamper guard matches file paths and added lines. It flags deleted or skipped tests, added
  retries and gate-config edits; a test weakened some other way (a looser assertion) passes it.
- The collectors match file names and keywords, so "present" means the item exists where the
  audit looks, not that it is right. The re-audit's judge and the owner's review decide that.
- The generated workflows were not run on a hosted CI service by these tests: the tests check
  them with box-audit's workflow parser and run the scripts they call.
