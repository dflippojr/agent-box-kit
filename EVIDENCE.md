# Evidence

Where each rule came from and how well it is evidenced.

Evidence levels:
- **observed**: visible in code, history or artifacts the maintainer read.
- **asserted**: stated in project docs; not seen demonstrated.
- **hypothesis**: reasonable but untested; needs validation on real work.

All three source projects were built with heavy AI assistance, including their docs. "Observed"
means visible in the artifacts, not "proven to improve outcomes". Nothing here has been
A/B-tested.

Sources: **H** = a private project built for an internal hackathon, and the kit
of skills it was built with; **L** = [agent-loop](https://github.com/dflippojr/agent-loop);
**A** = [agent-harness](https://github.com/dflippojr/agent-harness) (design and CI docs). File
names are given for L and A, which are public. Dates are when the evidence was recorded. Issue
and PR numbers referred to a private tracker and are omitted; commit IDs named in notes are
from that private history.

| Rule (module) | Source | Evidence | Notes |
|---|---|---|---|
| Every requirement has a Verify; every task has a runnable Verify and risk flag (02) | H: requirements and plan-breakdown skills; the project's real `REQUIREMENTS.md` and `PLAN.md` | observed | Real plan follows the format throughout. Templates: `agent-ready/templates/REQUIREMENTS.md`, `agent-ready/templates/PLAN.md`. |
| Plan review pass reorders and catches hazards (02) | H: a "revise PLAN per review" commit; the PLAN header lists the hazards | observed | The value of the pass itself is asserted, not measured. |
| Ordering: safety before ingestion; create thing before capturing fixture; non-sensitive trigger; negative fixture (02) | H: real `PLAN.md` tasks 3-5 | observed | |
| Plan is living; record deviations (02) | H: PLAN tasks 8 and 9 "reframed", "built ahead of Task 8" | observed | |
| Facts confirmed against reality, with dates and confirmed/unconfirmed (02) | H: REQUIREMENTS "confirmed facts", one item "not yet confirmed" | observed | |
| Smoke-test external dependency first (02) | H: a smoke test passed before building | observed | |
| "Ready" = zero further decisions; else list unresolved, never guess (02) | L: `refine-issue.sh` prompt contract, README | asserted | Read the README, not the script's runtime behavior. |
| Issue-spec shape (02, template) | L: README | asserted | Template: `agent-ready/templates/ISSUE-SPEC.md`. |
| Baseline before changes; run commands, don't trust README (01) | H: RUNBOOK notes on an intentional red test; a stale RUNBOOK status | observed (stale doc), hypothesis (baseline practice) | The baseline step itself is the maintainer's addition. |
| Work on branch/worktree, not live checkout (01, 03) | L, and the owner's own work notes ("do NOT work in that checkout") | observed | |
| Default lane / deliberate lane; stop conditions (03) | H: autopilot and task-cycle skills; history shows one commit per task | observed | One `feat:` commit per task plus `docs:` tick commits. |
| Effort ceiling per task, stop and report if exceeded (03) | H: implementer and autopilot skill briefs | asserted | Written in skills; adherence not verified. |
| Red before green for tests (03) | H: implementer skill | asserted | |
| Never weaken a Verify (03) | H: autopilot rules | asserted | |
| Machine-readable result line; confirm from git, not self-report (03) | L: README sentinels; a known quirk where one agent CLI opened a PR despite the rule and printed result lines inconsistently | observed | |
| One commit per task, referencing task/requirement (03) | H: commit log | observed | |
| Enforce, don't request; layers not dependent on the agent (04) | H: harness hooks and deny rules; the secret guard fires in any permission mode | observed | The "git pre-commit first" layering is a generalization; the source used harness hooks. |
| Secrets guard: staged diff, placeholder allowlist, whole-tree scan (04) | H: the project's secret guard | observed | Rewritten as `scripts/secret_guard.py`; tested (see Script evidence). Transcript-leak guard not ported (harness-specific). |
| Audit logger fails open (04) | H: audit logger docstring | asserted | |
| Deny reads of real `.env` (04) | H: harness deny list | observed | |
| Model reviewer advisory; no tools; shadow before live; fail closed (04) | A: `docs/smart-approvals.md`, staging `allowed_logins` behavior in `CI-CD.md` | asserted | Docs read; behavior not tested. |
| Explicit staging paths + assertion; state the trust model (04) | A: `CI-CD.md` staging section | asserted | |
| Mechanical gate is authority; evaluator advisory, cannot override (05) | H: REQUIREMENTS "mechanical gate is the reproduction authority"; the red/green check and refine scripts | observed | |
| Gate must assert clean tree (05) | H: demo notes on a "false red from half-reverted patch" | asserted (problem); observed (fix) | The original script did not check. `scripts/red_green_gate.py` does, with tests. |
| Gate must test current source despite stale bytecode (05) | Module 05 evaluator experiment (`experiments/05-evaluator/`); `tests/test_red_green_gate.py` | observed | Same-size edits with identical timestamp seconds reproduced false still-red verdicts, with and without a pre-existing cache. Each run uses an empty temporary cache prefix and disables writes; existing repository caches are preserved. Disabling writes alone does not prevent stale cache reads. |
| Refine loop capped at 2-3; honest incomplete at the cap (05) | H: evaluate-test skill, requirements, an "insufficient" fixture | observed | |
| Grounding instruction, escape hatch, name the anti-pattern in the prompt, JSON-only output (05) | H: reconstruct, generate and evaluate prompt files | observed | Whether prompt wording drives results is untested. |
| Evaluator scoped to what the gate cannot check (05) | H: evaluate prompt | observed | |
| Prompts in files; version token in cache key (05) | H: project instructions file; the version token was a stretch task | observed (files); hypothesis (token) | Token not built. |
| Record/replay cache; offline mocked tests + separate live smoke (05) | H: plan task 7, RUNBOOK ("43 passed, all mocked") | observed | |
| Discovered API contract facts recorded with dates (05) | H: REQUIREMENTS confirmed facts | observed | Vendor-specific specifics removed. |
| Evaluator adds value only when several inputs pass the gate (05) | H: demo notes, honest reflection; `experiments/05-evaluator/RESULTS.md` (2026-10-08) | observed (synthetic) | 8 grounded cases + 2 controls, one run each: evaluator 8/8 and 0 false endorsements; literal-value heuristic 6/8. Small, easy decoys, same model family as author; not shown on real tasks. |
| State file: goal, facts, errors with dead_end, next_step; files from git (06) | L: README and the merged state-file PR | observed (design and code merged) | Effect on retry rates: the baseline metrics exist, the comparison had not been run. Template: `agent-ready/templates/STATE.json`. |
| Refresh takes the diff range from git; an option-like `--base` is rejected, never passed to git (06) | Reproduced with git 2.56 | observed | Before the fix, `--base=--output=x` made git write a file and exit 0 with an emptied list. Now exit 2 before the state file is touched; the range also follows `--end-of-options`. |
| Commit after each discrete step (06) | L: prompt contract | asserted | |
| Review-round cap of 3; fresh session; fix the class (06, 08) | L: `run-pr.sh` README; the owner's review-round policy | observed (implemented); hypothesis (that it improves outcomes) | |
| Context hygiene list (06) | H: orchestration budget tactics | asserted | Written for cost; benefit unmeasured. |
| Handoff brief: objective, done, repo and branch, uncommitted files, checks, next step (06) | none recorded | hypothesis | Template: `agent-ready/templates/HANDOFF.md`. No source was recorded when it was written; not yet checked against a real handoff. |
| State side effects before starting shared-resource work (06) | L/A: a dated lesson in the owner's work notes (2026-09-20) | observed | A real incident recorded by the owner. |
| Append-only dated records; mark superseded (06) | The owner's own work notes | observed | |
| Null is unknown, never zero; baseline before optimizing (06) | L: session-quality metrics README | observed | |
| Design doc + threat model skeletons (07) | A: `marketplace-design.md`, `marketplace-threat-model.md` headings | observed (structure) | Content quality not assessed. Template: `agent-ready/templates/DESIGN.md`. |
| Results doc shape; record rejected options (07) | A: `phase0-results.md`, backlog entries | observed | Template: `agent-ready/templates/RESULTS.md`. |
| Decision record: dated, with status accepted, superseded or rejected, and the rejected options (07, 11) | Applies the append-only, mark-superseded rule (06) and the record-rejected-options rule (07) to one file per decision | hypothesis | Template: `agent-ready/templates/docs/decision.md`. Not part of the module 11 run; not used on a real project. |
| Study doc: what changes, things not to copy, verification rule (07) | A: `orca-study.md`, `phase6a-hermes-study.md` headings | observed | |
| Backlog kinds, stable key (07) | A: `docs/backlog.yaml` header | observed | |
| Track unrun live checks openly (07) | L/A: a verification-tracking issue | observed | |
| Ship dark: off, shadow, live (04, 07) | A: smart approvals | asserted | |
| All-gates-green definition; owner merges (08) | L/A: agent-loop standing rules; the owner's work notes | observed | Owner's rule. |
| Full review before merge; incremental only when range is safe; do not mark truncated as complete (08) | A: `CI-CD.md` review section | asserted | |
| CI principles: SHA not branch; no PR code with secrets; pin actions; rollback; verify auth where it runs (08) | A: `CI-CD.md` | asserted | Documented; not audited. |
| PR description: what and why, how verified, what was not verified, risks and rollback, follow-ups (08) | none recorded | hypothesis | Template: `agent-ready/templates/PR-DESCRIPTION.md`. The not-verified section echoes the row on saying what was run versus only read (modules 01, 11). |
| Weekly dependency updates and guard-script analysis (repository CI) | Owner decision, 2026-10-06 | asserted | Actions and pip manifests; SonarCloud on main and same-repository PRs, including Dependabot with its own secret. Missing-token notice permits setup before activation; live analysis remains unverified until owner setup. |
| Every module and template in agent-ready/ is named by a row here, by module number or path, with a known evidence level (AGENTS.md, `tests/test_evidence_provenance.py`) | Owner decision on the provenance-check issue (2026-11-06); AGENTS.md "every rule has a reason and a source" | observed (16 templates had no row); hypothesis (that it stops unsourced rules) | Static check, no diff: a new rule in a module that already has rows passes. |

## First real use (2026-09-21): module 01 on another project

The owner ran module 01 only, on a scheduled job that writes stored data on startup. The generated
`AGENTS.md` followed the template well (commands with success criteria, baseline, quirks,
boundaries). Findings, and what changed in the playbook:

| Finding | Change |
|---|---|
| The header claimed every command was "run and verified", but the list included a "Run locally" row for an app that writes data on startup. Running a write path to "verify" it is unsafe, and if it was not run the claim was false. | Module 01 and the template: run only build/test/lint; run commands and write paths are recorded as *not run* with the target they affect; commands are marked run / not run. |
| The agent wrote boundaries and "do not fix" policies the owner had not stated. The owner reviewed them and judged them valid. | None. The template invites generic filling-in, so the owner must review every policy line. |
| The owner declined to reference `secret_guard.py` or add `.secret-guard.json` in the project: other agents may not have the skill, and a repo in another language should not depend on a Python script. | Module 04: `--staged` run by the agent before commit is the default, the hook is optional, and the script is never copied or referenced into the target repo. The project `AGENTS.md` template carries no guard command. |

Evidence level: one project, one run, output only (the process was not observed). It shows module
01's template works; it also shows module 01 originally invited a write-path run.

## Module 11 and the docs layer (2026-09-21)

The owner's goal was to improve an existing project for agent traversal generally, not to create
setup artifacts for one new project. A first-pass prompt asked an agent to write `docs/` (index,
architecture, data-model, runtime, testing) with a three-line header, read-only, uncommitted. The
run followed the process (read all source and fixtures, ran nothing, edited only the Pointers
section, listed unknowns). Reviewing four of the generated docs found problems that shaped module 11:

| Finding in the generated docs | Change in module 11 |
|---|---|
| The header said `Verified against: <sha>` though code was only read, never run. | Header uses `Basis: read from code at <sha>; nothing executed.` |
| `runtime.md` promised "how it is invoked and scheduled" but where scheduling lives was neither stated nor marked unknown. | Every `Answers` item is a promise: deliver it or write `unknown: <where to look>`. |
| A strong transaction claim was reasoned from code, not observed. | Reasoned behavior is marked *inferred, not exercised*, and listed in the final report. |
| Data-classification and policy statements were written as fact. | Such items go under `Owner to confirm`. |
| Sensitive identifiers appeared in a doc. | Keep sensitive identifiers out by default; say where they are configured. |
| Test names differed between documents. | A consistency pass across `AGENTS.md`, docs and code before finishing. |
| An ambiguous statement about where configuration values come from. | Rule to cite and disambiguate; owner review checklist. |
| External library packages were named but not their owning repos. | Architecture template has an external dependencies table (owner, what to read there). |

What the maintainer could not check: the docs' factual accuracy (the repo was not shared) and
`docs/README.md`. Evidence: one project, one run.

The owner's answers to those findings (same day) supported the rules to disambiguate, to write
`unknown: <where to look>` when the answer lives outside the repo, and to ask for data
classification rather than infer it (the agent had over-flagged; rule added to modules 01, 11 and
the template). The owner allowed the sensitive identifiers in that project, so the rule became a
default the owner can override. Two answers disagreed with the generated docs (a key and a
transaction boundary); only naming the constraint or a test can settle them.

| Rule (module) | Source | Evidence | Notes |
|---|---|---|---|
| Docs-layer skeletons: an Answers / Read when / Basis header, then the sections each doc promises (11) | The module 11 run above: index, architecture, data-model, runtime and testing docs, and the findings from reviewing four of them | observed | One project, one run. Templates: `agent-ready/templates/docs/README.md`, `agent-ready/templates/docs/architecture.md`, `agent-ready/templates/docs/data-model.md`, `agent-ready/templates/docs/runtime.md`, `agent-ready/templates/docs/testing.md`. |

## Modules 09 and 10 (added 2026-09-21)

Written for a planned task: adapt an existing scheduled data job, then build a new one modeled on
it. **Both are `hypothesis`.** Neither comes from the three source projects.

| Rule (module) | Source | Evidence | Notes |
|---|---|---|---|
| Reference project is evidence, not truth; verify by running (09) | Same stance as the study docs in A (`orca-study.md`: findings are hypotheses until verified) | hypothesis | Applied to a reference project rather than an external one. |
| Reuse mode (copy / adapt / conventions-only), write the delta, cite the docs you borrow from (09) | none | hypothesis | Originally a one-off "reference map"; replaced by reading the reference's own docs layer (11) after the owner said one-off setup artifacts were the wrong shape. |
| Keep the reference read-only; docs-only changes with owner OK (09) | Scope-discipline rules in 03 | hypothesis | |
| Plan tasks cite their source file; commits say what they were modeled on (09) | none | hypothesis | Intended to help reviewers diff old vs new. |
| Agent never gets production write access; owner runs prod (10) | Consistent with the owner-controls-irreversible-actions rule (03, 08), which is observed in L | hypothesis | The data-specific application is new. |
| Dry-run default; idempotent; bounded with circuit breaker; per-batch transactions; captured before-values; parameterized SQL; no overlapping runs (10) | General data-job engineering practice; the dry-run/shadow/live staging echoes A smart-approvals | hypothesis | Check against your organization's standards. Template: `agent-ready/templates/DATA-JOB-SPEC.md`. |
| Refuse to run with ambiguous environment (10) | The fail-closed principle in 04 (observed in A: empty allow-list) | hypothesis | |
| Test list and staged rollout (10) | Adapted from 03/05 verification practice | hypothesis | |

## Script evidence (added 2026-09-21)

Ported from H's secret guard and red/green check script and L's state-file design. They were
rewritten, not copied: language-agnostic, agent-agnostic, stdlib-only. Dropped because they are
harness-specific: the audit logger and the transcript-leak guard.

What was done to test them:

1. **55 automated tests at v0.1 (now 61, see below)** (`tests/`, real git in temp repos, no mocks). Covers each secret pattern,
   placeholder and allow-marker behavior, staged-only scanning and line numbers, the installed
   pre-commit hook with real `git commit` (blocked, allowed, `--no-verify` bypass, foreign-hook
   refusal, linked worktree), the gate's PASS / false-reproduction / still-red / wrong-reason /
   dirty-tree / bad-patch / missing-command / timeout cases (tree restored each time), and the
   state validator and git-derived file list (add, modify, delete, rename).
2. **One real bug found by the tests:** `raise SystemExit("msg")` exits with code 1, which collided
   with the documented meaning "findings". A broken config would have looked like a secret hit.
   Fixed to exit 2.
3. **Improvements over the originals, each with a test:** the placeholder allowlist applies to the
   matched value, not the whole line (the original would skip a real key on a line containing
   "sample"); findings never print the full secret; the gate refuses a dirty tracked tree and treats
   a missing command or timeout as a harness error, not "red".
4. **Real-repo trial, secret guard (read-only `--tree`):** 244, 22, 83 and 62 tracked files in four
   real repos. 3 clean; 1 with 2 findings, both deliberate fake secrets in that project's own tests
   for secret handling. Says the guard is not noisy on these repos. It says nothing about recall
   (missed real secrets); only the synthetic patterns in the tests exercise that.
5. **Real-repo trial, red/green gate:** 7 small historical bug-fix commits from one project
   (test committed as base, source diff as patch). 6 PASS. 1 FAIL ("test passes on the buggy tree");
   reading that diff, the fix appears to change behavior only for `None` and the test uses `""`.
   Tree was clean after every run.
6. **Bare vendor key formats (2026-10-05):** `secret_guard.py` now also flags Google API keys,
   Hugging Face tokens, npm tokens, AWS `ASIA` temporary key ids and `sk_live_`/`rk_live_` payment keys without an
   assignment. Before, a bare value of each of these matched no pattern. Each rule has a word boundary and a
   minimum length, a positive test in staged and tree modes, negative tests (too short, wrong prefix),
   a placeholder test, and a check that only the label and first four characters are printed. Exercised only on
   synthetic values built at runtime; no real credential was used, so recall against real keys is unmeasured.

## Cross-platform decisions (2026-10-01)

- OS priority: all three, via a GitHub Actions matrix (an agent cannot test macOS locally; CI is repeatable).
- Runners: no runner-specific config. The gate runs the command after `--` without a shell and uses only its
  exit code, so unittest and a shell script are tested as the contract; nose2 and others are out of scope.
- Python versions: 3.10 on all OSes, 3.8 on Linux only. If 3.8 fails, fix compat or correct the header claim.
- Test consolidation (2026-10-08): the five ordinary verdict tests (three direct-Python, `test_unittest_runner`,
  `test_sh_script_runner`) became one `test_verdict_matrix` over a shared three-row scenario table and three runners.
  Observed: `tests/test_red_green_gate.py` 187 -> 155 lines; collection shows the same nine verdict combinations
  (IDs like `pass-python`); locally on Windows, Python 3.10, 99 passed + 3 skipped (the three `sh` cases). No coverage change; the `sh` cases were not run locally this time.

What this does not establish:

- Verified locally (2026-10-01): Windows, Python 3.10, 58 passed + 3 skipped (the `sh` runner tests skip on
  Windows; run by hand under Git-for-Windows `sh`, they passed). CI (2026-10-02, `.github/workflows/tests.yml`):
  all four jobs green: ubuntu-latest, macos-latest and windows-latest on Python 3.10, and ubuntu-22.04 on 3.8.
  The first 3.8 run caught a 3.10-only API in a new test (`Path.write_text(newline=)`), fixed in the same change.
  Python 3.9 is untested.
- The gate's real-repo trial used only `python -m pytest`. Tests now also drive it with `python -m unittest`
  and a POSIX `sh` script (PASS, false-reproduction, still-red). It uses only the command's exit code, so
  other runners (Maven, npm, Go) are expected to work but are untested. The `sh` runner is not tested on Windows.
- The gate trial used pre-existing human-written commits, not agent-generated tests, which is the
  case it was designed for.
- The hook's behavior with `core.hooksPath` set, in submodules, or under other Git front-ends is
  untested.
- Nothing shows that using these scripts improves review outcomes.

## Box standard (`box/STANDARD.md`, added 2026-10-19)

Source: the owner's own verification review, on 2026-10-15, of 14 projects and the box around
them. The review's rubric has the eight audit questions, the six dimensions with a "Meets" bar, the
9/10 and 10/10 definitions, a per-project score table, and the follow-up issues filed from the
review. Restated generically; no project names.

| Rule (STANDARD.md section) | Source | Evidence | Notes |
|---|---|---|---|
| Eight audit questions; six dimensions G R J W P D (questions, dimensions) | The review's rubric | observed | Five reviewers used the questions on 14 projects. The dimensions were derived from the questions afterwards. |
| "9 needs" bar per dimension (each dimension) | The rubric's "Meets" column | observed (that the gaps existed) | Restated: a host-specific ready check and plan became "host protection, else a mechanical `ready` script". Nothing shows that meeting the bar reduces defects yet. |
| 9/10 overall: all met, one partial allowed with a written external blocker; 10/10 adds two clean bug-hunt passes (overall score, D) | The review's rubric | asserted | The owner's definition. Nothing has scored 9 yet. |
| "10 needs" for G, R, J, W, P (each dimension) | Follow-up issues filed from the review: judge from base branch, labels tied to the head, floor ratchet, PR-body lint, contract and drift checks, verifier, production sweep | hypothesis | The rubric defined 10 only overall. Requiring every dimension at ★ is stricter than the source. |
| Overall rule 3: 3 + dimensions at ~, ✓ or n/a, max 8 (overall score) | Calibrated on the rubric's 14 scored rows | observed | Recomputed on 2026-10-19: within 1 of every holistic score (5 equal, 7 one higher, 2 one lower). Holistic scores are judgments, so this is fit, not validation. |
| Read-only evidence scores partial at best; green-while-skipping is absent (per dimension) | Review finding: a skipping static-analysis job showed green | observed (the incident); hypothesis (the rule) | |
| n/a rules: G, J, W, D never n/a; R and P only when their subject does not exist (not applicable) | The box row scored R as n/a in the rubric | hypothesis | |
| Failure stories (each dimension) | Score-table reasons and follow-up issues | observed | Told generically; counts kept approximate. |
| Host equivalents table, model access, IDE (host-agnostic mechanisms) | GitHub mechanisms used in the review's follow-up work | observed (GitHub); asserted (other hosts) | GitLab, Bitbucket and Azure DevOps entries were not configured or tested. |

## Box audit skill (`box/skills/box-audit/`, added 2026-10-19)

Source: the same review, which five one-off reviewers ran by hand; nothing could rerun it.

| Rule (where) | Source | Evidence | Notes |
|---|---|---|---|
| Scripts gather the evidence before any model judges it (SKILL.md, `collect.py`) | The standard's "do not ask the model to judge itself" | observed | Calibration runs on 2026-10-19. The test, oracle and production collectors match keywords; they find leads, not facts. |
| Every evidence item is `verified` or `read` (`collect.py`, card format) | The standard: read-only evidence is partial at best | observed | `card.py check` rejects ✓ or ★ on a dimension with no verified evidence. |
| The judge runs with an empty home, a working directory outside the home and a reduced environment, and is probed before use (`judge.py`) | The owner's judge-isolation work, restated without a vendor | observed | On 2026-10-19 the first isolated run still quoted the owner's global instructions: the CLI read them from a folder above its working directory, which sat inside the home. The work root must now be outside the home and free of instruction files above it; the probe then passed (baseline quoted 298 eight-word runs, isolated 0). Covers startup context only, not the filesystem. |
| A script, not the judge, recomputes the overall score and checks the card (`card.py`) | The standard's overall rule | observed | The rule is checked against `tests/test_box_standard.py` for all 15,625 mark rows. |
| Proposed issues use Problem / Want / Constraints / Dependencies / Out of scope, one tier label, `ready` only without open decisions (card format) | The owner's issue-authoring guide | asserted | Restated without its model-routing tables. |
| Filing is a dry run first and stops on a missing label (`file_issues.py`) | The owner controls outward-facing actions | asserted | GitHub only. Not yet run with `--apply` against a real repo. |
| A card proposes each issue title once, and filing reads labels and open issues to the last page (card format, `card.py`, `file_issues.py`) | Independent review of the box-audit change | observed | Against a stand-in `gh`, a card with one title under two dimensions created it twice in one run, and a label or open issue past the tenth page was missed. |
| Report mode runs as `python -B`, runs git without the caller's `GIT_*` variables and with trace2 off, picks its temp dir without writing in it, refuses a `--copy-home` file that resolves into the checkout or has other hard links, and sweeps only judge folders it marked and that neither overlap the checkout nor are, hold or sit inside any git checkout, whichever command starts the judge (SKILL.md one-line summary; the detail in `audit.py`'s docstring, `collect.py`, `judge.py`) | Independent review of the box-audit change | observed | On 2026-10-20, fresh-process tests on synthetic repos, before the fix: the sweep deleted 34 paths of a checkout inside an old judge-named folder; a refreshed login was written back through a linked home folder, or changed a tracked file's link count; `GIT_TRACE*` created five log files in the checkout; temp-dir selection wrote and deleted a file in a checkout folder; without `-B` the script's own imports wrote bytecode under an in-checkout `PYTHONPYCACHEPREFIX`. Interpreter startup before the first line is not closable from the script: `-B` is the documented entry point. A later review found `judge.py run` and `probe` still swept without the checkout guard; before the fix, 9 fresh-process cases (`run`, `probe`, `audit.py`, each with a marked folder that is, holds or sits inside a checkout no caller named) deleted all or part of it. |
| A merged PR is judged by its head's checks as of `merged_at`, from the full run and status history, and is unknown without it; the head's current results are a separate snapshot, kept when the merge verdict is unknown (`collect.py`, SKILL.md) | Independent reviews of the change | observed | On fixtures that serve GitHub's endpoints from one history, the earlier collector, which read only each check's latest run and the combined status, called a green merge with a later failed rerun red and dropped a red merge with a later passing rerun, for check runs and commit statuses alike. On 2026-10-22, live reads confirmed run and status timestamps and that statuses come newest first; no real head with a rerun after its merge was found to compare `filter=all` against the default. A later review showed the first fix dropped a known current failure when every merge verdict was unknown (an untimed older run, or an unreadable `merged_at`); fixture tests for both now keep it. |
| The skill is installed by symlinking its folder, not copying it, and its relative paths (`../../STANDARD.md`, `scripts/judge.py` and the rest) resolve through the link on POSIX (box-audit SKILL.md) | Owner decision of 2026-11-06, in place of an A/B eval for a change that only moves text | observed (synthetic) | `test_skill_paths_resolve_from_a_symlinked_install` links the folder into a temp skills folder and opens every relative path SKILL.md names through the link; read lexically, `../../STANDARD.md` leaves the tree. Not run on Windows, which applies `..` before following the link. |

## Skill eval (`box/skills/skill-eval/`, added 2026-10-22)

Source: the owner's decision of 2026-10-22 to build the harness here, reusing box-audit's judge.
Read for reuse on 2026-10-22: the skill-creator skill's blind comparator (`agents/comparator.md`)
and trigger runner (`scripts/run_eval.py`), and the agent CLI's `plugin eval` command (its
`--help` only; not run).

| Rule (where) | Source | Evidence | Notes |
|---|---|---|---|
| Judge a skill change by running A and B on a task set, not by reading it (SKILL.md) | The issue | hypothesis | Not yet run on a real change: the proof run in `experiments/06-skill-eval/run.md` waits for the owner, because the building session could not start nested agent sessions. |
| Sessions reuse box-audit's isolation: empty home holding only the skill, scratch workspace, reduced environment, safe work root (`runner.py`) | box-audit's `judge.py` | observed (synthetic) | Tests run a stand-in CLI and check it sees only the skill and the copied login, not the owner's instruction file or environment. Startup context only, not a sandbox. |
| Deterministic checks first, and the judge does not see them (`runner.py`, `blind.py`) | The standard's "do not ask the model to judge itself" | asserted | Keeps the two signals separate, so a check failure is not counted twice. |
| The judge sees X and Y in a seeded random order and is never told versions exist (`blind.py`, `judge-prompt.md`) | skill-creator's blind comparator, which labels outputs without saying which skill made them | observed (synthetic) | With a stand-in judge that always picks X on a tie, the order kept a no-op change at no detectable difference (seed 7, 15 pairs). A real judge's position bias is unmeasured. |
| Trigger check: picked on the task prompts, not picked on 3-5 near-miss prompts (`report.py`) | skill-creator's trigger eval: near-misses are the useful negatives | asserted | Detects the skill from tool events, as skill-creator's runner does. |
| Verdict: a signal reads worse or better only when its 95% interval excludes no change; Wilson for the judge's share, Newcombe's hybrid score for differences; worse wins over better (`report.py`) | Wilson (1927), Newcombe (1998) | observed | Unit-tested against Newcombe's worked example. Sessions of one task are treated as independent, which narrows the intervals a little. |
| Every session runs under a cap the CLI enforces, the run under a total cap, and a session with no readable cost counts at its cap (`skill_eval.py`, `runner.py`) | The issue's constraint | observed (synthetic) | A profile without `{budget}` or a readable cost is refused. |
| A session that fails after the agent starts counts against its version (not completed, every check failed, its judged pair lost); one the harness could not start is left out with its partner; a verdict needs 80% of planned pairs complete on both sides and equal completion, or it is inconclusive unless something reads worse (`report.py`, `runner.py`) | Independent review | observed (synthetic) | Before the fix, B failing all 15 task sessions read no detectable difference, and B failing 3 with the judge preferring its other 12 read better. Both are now regression tests. The 80% floor is a hypothesis. |
| `command_run` credits only a command whose result shows it ran; a refused or unanswered request does not count, and the judge sees each command's outcome and output (`runner.py`, `blind.py`, the profile) | Independent review | observed (synthetic) | Before the fix, a denied request passed `command_run`. The event shapes in `profiles/claude-code.json` (`tool_result`, `is_error`, the `permission_denied` event, the refusal text) were read from the CLI's bundled code, not from a run. |
| The judge sees deleted files and a diff for each supplied file; `file_unchanged` guards a supplied test file (`runner.py`, `blind.py`, `tasksets/agent-ready.json`) | Independent review | observed (synthetic) | Before the fix, a session that fixed `calc.py` and deleted `test_calc.py` passed every bug-fix check and the judge could not see the deletion. |
| Budgets are finite whole cents of at least 0.01, normalized once and used for the reservation, the CLI argument, the record and the charge; a reported spend that is not finite and nonnegative counts at the cap (`runner.py`, `skill_eval.py`) | Independent review | observed (synthetic) | Before the fix, `--max-cost-usd nan` never stopped a run, a NaN reported spend disabled the cap, and a 0.026 cap reserved 0.026 but passed 0.03 to the CLI. |
| Not wrapping the CLI's `plugin eval` | Its `--help`: it compares a plugin with no plugin, not two versions, and runs in one vendor's CLI | observed | Its case format was not adopted either, to keep the harness CLI-neutral. |
| Not wrapping skill-creator's scripts | `run_eval.py` writes a command file into the project's own settings folder and runs in the owner's environment; the comparator is a subagent brief, not a script | observed | Its ideas (blind comparison, near-miss negatives, 3 runs per query) are reused. |

## Orchestration spec (`box/orchestrate/`, added 2026-10-23)

Source: the owner's private dispatcher and its worker brief, restated without its IDE, host or
model routing. Owner decision (2026-10-22): the kit carries the spec and two checking
scripts; no launcher; tier stays a difficulty label.

| Rule (where) | Source | Evidence | Notes |
|---|---|---|---|
| Lifecycle labels and what dispatch does with each (label contract) | The owner's queue labels | observed (in use); hypothesis (that the set is complete) | `ready`, `user-present`, tier and priority labels were on the private repo's own issues. |
| One `tier:*` label per issue, difficulty only, no model mapping; none or two holds the issue (tier labels, `select.py`) | Owner decision; box-audit's card check already needs exactly one | asserted | |
| Dispatchable: ready, one tier, dependencies closed, capacity; P0, P1, P2, unlabelled, oldest first (selection, `select.py`) | The issue's acceptance criteria | asserted | On 2026-10-23 `select.py --repo` listed the private repo's queue; held issues named their open dependency. An unreadable dependency counts as open. |
| Worker brief: never apply, re-apply or remove owner-only labels, approve or merge; stop and ask the owner (worker brief) | The owner's worker brief | observed | Restated without harness commands. |
| An owner-only label counts only when the owner applied it after the head commit was pushed, timed by push activity, not the commit date (handoff, `handoff_check.py`) | The standard, G 10 needs | asserted (rule); observed (the API) | The commit date is set by whoever commits, so it cannot time a push. The push activity list was read for the private repo on 2026-10-23. |
| The handoff is checked against the host: checks, review threads, owner-only labels, proof table, closing reference (handoff, `handoff_check.py`) | The standard, W 10 needs | observed (runs); hypothesis (value) | On 2026-10-23, run on a merged PR in the private repo: READY. Nothing yet shows it catches what a reviewer would miss. |
| No-hosted-VCS forms: issue folder, gate-result file, findings task list, signed acceptance tag (issue folder, handoff) | The standard's host-agnostic table | hypothesis | Tested on runtime git repos only; not used on a real project. |
| An acceptance tag counts only when signed with `--owner-key`; the signing programs are pinned, not read from the checkout's config (handoff, `handoff_check.py`) | Independent review (blocking finding) | observed | On 2026-10-23 a worker-signed tag naming the owner as tagger gave READY, and so did a checkout whose `gpg.program` always reports the owner's key. Tests build both with runtime GPG keys; SSH keys are tested the same way. |
| An OpenPGP acceptance signature counts only on one signature with `GOODSIG` and `VALIDSIG` in gpg's status lines, not on `git verify-tag`'s exit code (handoff, `handoff_check.py`) | A Windows CI run; owner decision | observed | On 2026-10-26, Git for Windows 2.56 exited 0 for a tag signed by an expired key (`EXPKEYSIG` with `VALIDSIG`), and the check gave READY; Linux and macOS exit 1. Reproduced locally with runtime GPG keys; a revoked key gives `REVKEYSIG` with `VALIDSIG`. |
| A `Dependencies:` line with no `#n` reference and not `none`, or with a bare number, holds the issue; issue links are read (selection, `select.py`) | Independent review | observed | A link and a bare number pointing at an open issue were both listed to dispatch before. |
| An acceptance tag counts only when the signed tag object names the acceptance tag, the head commit and the issue the note closes, not by its ref name (handoff, `handoff_check.py`) | Security re-review | observed | On 2026-10-23, an owner-signed `gate-change-approved/<branch>` tag, and a release tag, copied to the acceptance ref gave READY. |
| References on the lines below a bare `Dependencies:`, `**Dependencies**` or `## Dependencies` are read (selection, `select.py`) | Security re-review | observed | `Dependencies:` then `- #1`, and the box-audit card's `**Dependencies**` then `#1`, were read as no dependency, and the issue was listed to dispatch with #1 open. |
| Under a `## Dependencies` heading, references run to the next heading of the same or a higher level; a loose list under a bare key or label is read across its blank lines; a key with nothing readable under it, or a key shape not recognised, holds the issue (selection, `select.py`) | Round-3 security re-review | observed | At e0698dc, `**Dependencies**` then a loose list `- #2`, blank, `- #1`, and `## Dependencies` then `### Blocking` then `- #1`, were read as `[#2]` and `[]`, and the issue was listed to dispatch with #1 open. So were `Dependencies (blocking): #1` and `Dependencies: -`. |
| A `Dependencies: <value>` line also reads the list items below it; `none` with a reference under the same key holds the issue; a line of only references continues a list past a blank line; Unicode space or a byte-order mark before the key and `Dependency:` are recognised (selection, `select.py`) | Round-4 security re-review | observed | At ede797c, `Dependencies: #2` then `- #1`, and `Dependencies: none` then `- #1`, were read as `[#2]` and none, and the issue was listed to dispatch with #1 open. So were `**Dependencies**` then `#2`, blank, `#1`, a body starting with a byte-order mark, and `Dependency: #1`. |
| After a `Dependencies: <value>` line, a line of its paragraph that names an issue, and the nested list under a sub-label item with nothing after its colon, are read (selection, `select.py`) | Round-5 security re-review | observed | At 61cd32d, `Dependencies: #2` then `Also #1`, and `Dependencies: #2` then `- Hard:` then `  - #1`, were read as `[#2]`, and the issue was listed to dispatch with #1 open. |
| The `Dependencies` key is recognised as any list item (`1.`, `1)`, `+`, `•`, a checkbox), and a table, HTML or code key line with a digit holds the issue; a sub-label with nothing after its colon does not end the key; `none` under a sub-label over a nested reference, and a paragraph line with a digit but no reference, hold the issue (selection, `select.py`) | Round-6 security re-review | observed | At dafbaff, `1. Dependencies: #1`, `- [ ] Dependencies: #1`, `| Dependencies | #1 |`, `Dependencies: #2` then `Hard:` then `- #1`, and `Dependencies: #2` then `- Hard:`, `  - #2`, a blank, `- Soft:`, `  - #1`, were read as no dependency or `[#2]`, and the issue was listed to dispatch with #1 open. |

## Box profiles (`box/profiles/`, added 2026-10-23)

Source: the owner's decisions on the kit's roadmap (2026-10-19: corporate means models through AWS
Bedrock, source control and IDE unknown; home is unconstrained) and (2026-10-22:
machine-readable profiles, chosen per repo by a one-line file).

| Rule (where) | Source | Evidence | Notes |
|---|---|---|---|
| A repo chooses its profile with `.box-profile`; no file means unset, anything malformed is an error, never a fallback (`profile.py`, box README) | Owner decision, option A; fail-closed defaults set in the issue | asserted | Choosing per repo means workers on different machines read the same answer. Exit codes tested in `tests/test_profiles.py`. |
| `corporate` sets every host mechanism to the "No hosted VCS" fallback and names no editor or GitHub (`corporate.json`) | Owner decision; STANDARD.md's host-agnostic table | hypothesis | The fallback column is the only one sure to run when the host is unknown. Not yet run in a corporate setting. |
| box-audit reads the profile first; under `corporate` it audits with `--no-remote` and files by pasting `--offline` dry-run text (box-audit SKILL.md) | The issue | asserted | Both flags existed and were tested before this change; the skill only routes to them. |
| `profile.py` runs as `python -B` wherever it is documented, sets `sys.dont_write_bytecode` before its other imports, and refuses (exit 2) a `PYTHONPYCACHEPREFIX` inside REPO without `-B`; box-audit stops and reports an invalid `.box-profile` rather than editing it (`profile.py`, box README, box-audit SKILL.md) | Independent review | observed | On 2026-10-23 the review reproduced it: before the fix, step 1 under an in-checkout `PYTHONPYCACHEPREFIX` wrote 55 `.pyc` files into the audited repo; with `-B` it wrote none. `test_box_audit_step_one_leaves_the_audited_repo_untouched` runs the command as SKILL.md documents it and compares the repo before and after. |

## Box bootstrap skill (`box/skills/box-bootstrap/`, added 2026-10-23)

Source: the owner's decision (2026-10-22, option A: done means every repo-level item
bootstrap can create is present by box-audit's collectors; Python only) and the fail-closed
defaults the issue sets.

| Rule (where) | Source | Evidence | Notes |
|---|---|---|---|
| Done is "every repo-level item present by the collectors", not "9 on the first audit"; D's bug-hunt history and P's deploy signals are named as what is left (SKILL.md) | Owner decision; STANDARD.md's never-n/a and overall rules | asserted | A fresh repo has no bug-hunt pass, so D is at best `~`, and rule 2's one `~` needs an external blocker. |
| No profile, or a stack other than Python, stops bootstrap (exit 2); it never guesses (`bootstrap.py`) | The issue's defaults | observed | `tests/test_box_bootstrap.py` runs each case and checks the default branch is untouched. |
| `github` mechanisms get workflows; `elsewhere` and `none` get steps in `scripts/ready.py`, and `elsewhere` prints the host setting as an owner step (SKILL.md, `bootstrap.py`) | The issue; STANDARD.md's host-agnostic table | observed (generation and the scripts); hypothesis (the workflows on a hosted runner) | The tests run the generated gate, tamper guard, PR-body lint and ready script in sample repos; the generated workflows were parsed by box-audit, not run on a hosted service. |
| Bootstrap is judged by box-audit's collectors and reuses them rather than forking (`bootstrap.py`, tests) | The issue's constraints; the standard's "do not ask the model to judge itself" | observed | The tests restate each expectation against `collect.collect` output, independently of bootstrap's own report. `collect.py` now also exposes the docs, PR templates, PR-body-lint workflows and disposable-instance contract it already found. |
| The generated gate fails when pytest collects no tests (`templates/scripts/check.py`) | STANDARD.md: a check that is green while it skips counts as absent | observed | On the empty sample, `check.py` exits 1 with `GATE_FAIL: tests`. |
| Bootstrap never overwrites a file, writes to the default branch, pushes, merges, changes protection or applies owner-only labels or tags; it prints them as owner steps (SKILL.md, `bootstrap.py`) | The issue | observed | Tests check main's commit, the absence of tags and remotes, and that existing files are kept. |
| Bootstrap checks every target before a round writes anything and refuses (exit 3) one behind a link or resolving outside the repo; a failed write, `git add` or commit removes the round's files and unstages them (`bootstrap.py`) | Review finding 1 | observed | The review reproduced a tracked `docs -> ../outside` and an untracked `scripts -> ../outside2` writing outside the repo and leaving a half-applied branch. `test_a_linked_folder_is_refused_before_anything_is_written` checks the outside folder's mtime is unchanged; `test_a_failed_commit_leaves_nothing_behind` uses a failing pre-commit hook. |
| Bootstrap appends to AGENTS.md only when git tracks it; an untracked or ignored one is left alone and its item reported missing (`bootstrap.py`) | Review finding 3 | observed | An ignored AGENTS.md left the run half-staged; an untracked one had its private text committed. `test_an_agents_md_git_does_not_track_is_left_alone` covers both. |
| The PR-body lint does not count a closing-reference line as a section's content, and the PR template puts `Closes` under "What and why" (`templates/scripts/pr_body_lint.py`, `templates/pull_request_template.md`) | Review finding 2 | observed | With `Closes` under `### Gate changes`, an empty Gate changes section passed. `test_pr_body_lint_on_the_filled_in_template` fills in the real template. |
| `gate.yml` gives each default-branch push its own concurrency group (its commit); only a PR's runs share one (`templates/github/gate.yml`) | Review finding 4; GitHub's documented concurrency behaviour (a newly queued run cancels a pending run in its group) | asserted | The cancel-pending behaviour is the review's reading of GitHub's docs; the generated workflow is checked by text, not run on a hosted runner. |
| The approval for a gate change on a host-neutral profile is the owner's tag `gate-change-approved/<head commit>` (`templates/neutral/ready.py`) | STANDARD.md's "Owner-only labels" row, "No hosted VCS" column | hypothesis | Unsigned unless the owner signs it; who can create tags on the merging machine is the trust boundary. Not yet used in a real corporate setting. |

## Queue-fill skill (`box/skills/queue-fill/`, added 2026-10-27)

Source: the owner's analysis and refinement passes in their private orchestration repo, and the
owner's issue-authoring guide, restated without their prompts or routing. Owner decision
(2026-10-09): the refinement pass applies `ready` itself when the lint passes and no question is
open, and only behind `--apply`.

| Rule (where) | Source | Evidence | Notes |
|---|---|---|---|
| Three passes (gap, bug hunt, refinement), each a dry run unless `--apply`, after the owner's go-ahead (SKILL.md, `file_issues.py`, `hunt.py`, `refine.py`) | The issue; the owner controls outward-facing actions | observed (synthetic) | Tests run each pass against a stand-in `gh` and an issue folder and check nothing is created or edited without `--apply`. Dry runs on the private repo on 2026-10-27. Not yet run with `--apply` against a real repo. |
| One issue shape for every pass, checked by `issue_lint.py` with card.py's own label and part rules, not a copy (SKILL.md, `card.py`, `issue_lint.py`) | The issue; box-audit's card format | observed | On 2026-10-27 the original and the refactored `card.check` gave identical problem lists on 60,000 randomly mutated cards. |
| An `Open question` heading if and only if `needs-refinement`; `ready` never with one (`issue_lint.py`) | The owner's issue-authoring guide, rules 3 and 4 | asserted | The card check keeps its one-way rule, so card results are unchanged. |
| `## Dependencies` holds only the `Dependencies:` line (`issue_lint.py`) | Found while building the skill | observed | `select.py` read a note under `## Dependencies` ("Both land the money type first.") as an unreadable dependency line and held the issue. |
| The lint fails closed: an `Open question` line anywhere blocks `ready`, and HTML blocks, Setext headings and fences off column 0 are rejected (`issue_lint.py`, `refine.py`) | Independent reviews, rounds 1 and 2 | observed | A four-backtick fence, a fence in a list item, a fence in an HTML comment and a Setext heading each hid a visible `Open question` from the parser, and `refine.py` promoted the issue to `ready`. Chasing CommonMark form by form kept missing cases, so the lint now rejects what it does not model. |
| The question scan reads normalized text (markup stripped, references decoded, NFKC, letters and digits only), and fence lines must be exact, with ASCII spaces or tabs only (`issue_lint.py`) | Independent review, round 3; a maintainer decision | observed | `## <!-- marker -->Open question`, `## **Open** question` and `## &#79;pen question` passed the prefix scan, and a closer ending in U+00A0 or U+2003 kept a CommonMark fence open while the lint closed it; each was promoted to `ready`. The owner chose a blunt rule over more form-by-form fixes. |
| Lines end only at LF, CR or CRLF, and U+0085, U+2028 or U+2029 anywhere fails; the question scan also drops link destinations and folds Cyrillic and Greek look-alikes to Latin (`issue_lint.py`) | Independent review, round 4; the issue | observed | On 789da23, a U+2028, U+2029 or U+0085 before a fence marker split it into a clean opener for `splitlines()` while CommonMark read paragraph text, so the closer hid `## Want` onward; `## Оpen question` (Cyrillic O), `## Open[](x) question` and `## [Open](https://x) question` passed the scan. Each gave `ISSUE_OK`. |
| Gap-pass bodies use `## Dependencies` and `## Open questions` headings (`file_issues.py`) | The issue: every pass writes one shape | observed | Before the change, `file_issues.py` wrote a bare `Dependencies:` line and `## Open decisions`, which the lint rejects. It now lints every proposal before filing: a card with `needs-refinement` and `Open decisions: none`, or an empty Want, passes `card.check` but filed an issue the lint rejects. |
| A bug-hunt finding has a `Bug hunt:` title, the `bug` label, and `Found by`, `Introducing change` and `CI-catchable` lines; one run files one pass (`hunt.py`) | STANDARD.md's D dimension; box-audit's D collector | observed | Tests check the collector's `INTRODUCED` pattern matches a named change and not `unknown`, and that `bug` and the title match its defect and hunt patterns. |
| Refinement only removes `needs-refinement` and adds `ready`; every other label stays (`refine.py`) | The issue's constraint; the org contributing guide's owner-only labels | observed (synthetic) | A stand-in `gh` test checks the edit command's only label flags, with `gate-change-approved` on the issue. |
| Without a hosted VCS, passes write issue files `select.py` reads; an owner answer is an `Owner answer` section (`file_issues.py --folder`, `refine.py`) | The issue; the orchestration spec's issue-folder format | observed (synthetic) for the files; hypothesis for the answer convention | Tests round-trip filed and refined issues through `select.py`. Who wrote an answer is only as trustworthy as the folder's history. |

## Lessons registry (`box/lessons/`, added 2026-11-05)

Each lesson in `box/lessons/` links one row of this file by the exact text of its first cell. The
seed lessons come from STANDARD.md's failure stories and the rows above; these rows are the rules
a seed lesson needed that had no row yet.

| Rule (where) | Source | Evidence | Notes |
|---|---|---|---|
| A lessons registry: one file per lesson, its Rule linked to a row here, its check named, `open` when nothing enforces it (`box/lessons/`, `tests/test_lessons.py`) | The owner's decision on the registry issue (2026-10-22): a note records what went wrong but not whether anything now stops it | hypothesis | The test checks the links, paths, anchors and statuses. Nothing shows yet that a registry stops a lesson recurring. |
| A tamper guard flags a change that deletes or skips tests, adds retries or edits gate config, and only the owner's approval passes it (STANDARD.md G, `templates/scripts/tamper_guard.py`) | STANDARD.md D failure story 4: a coverage floor lowered in passing | observed | `tests/test_box_bootstrap.py` flags each kind of change on a sample repo and passes it with `--approved`. |
| A script's exit 1 is its verdict; a bad config or other error exits 2 (AGENTS.md, `agent-ready/scripts/`) | Script evidence item 2: `raise SystemExit("msg")` exited 1, the documented code for findings | observed | `tests/test_secret_guard.py` checks that bad config exits 2, not 1. |
| A doc says what was run and what was only read; "verified" only for what ran (modules 01, 11) | First real use: a header claimed every command "run and verified"; the module 11 run: `Verified against: <sha>` on code only read | observed | Two runs. Module 01's template now marks commands run / not run and module 11's header says `Basis: read from code`. No check reads a generated doc for this, so the lesson is `open`. Template: `agent-ready/templates/AGENTS.md`. |

## Excluded on purpose

- Agent pools, tier routing, usage snapshots, effort routing, review-backend fallthrough
  (L, A). Multi-agent infrastructure.
- Orchestrator/worker split, parallel worker rules, model-cost tables and budget caps (H).
- Rubric-driven advice: narrating to judges, transcript export, usage snapshots as scoring signals,
  demo scripts, one-day timelines, submission checklist (H).
- Domain-specific rules (domain data specifics, log-to-test pipeline, cloud-model access
  details). Generalized where useful.
- Personal infrastructure and paths.

## Gaps to fill from real use

- No evidence yet that following this guide beats not following it. Track outcomes (review time,
  rework, defects found in review) on a few real tasks.
- Module 05's "evaluator value" experiment ran on synthetic cases on 2026-10-08 (8/8, 0 false endorsements; see `experiments/05-evaluator/RESULTS.md`). Untested: harder decoys, repeat runs, other models, real tasks.
- Whether a git pre-commit hook is enough where harness hooks are unavailable: untested.
- Scripts exist (see "Script evidence") but are untested on agent-generated tests, runners beyond pytest/unittest/sh,
  and unusual git setups (`core.hooksPath`, submodules).
- Only one worked example (project H). Add others from work as they happen.
- Modules 09 and 10 are unvalidated; the first work task is their test. Record what was missing or wrong.
