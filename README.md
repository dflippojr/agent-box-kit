# agent-box-kit

A guide, and an installable skill (`agent-ready/`), for doing agentic engineering on existing
codebases in a way a human owner can review and trust. It distills lessons from three projects
built agent-first. It is written for a **single agent in a single session** and is
agent-agnostic: it names no vendor, model or harness.

**Status:** v0.1 draft. Every rule needs to be tested on real work before it is trusted; see
`EVIDENCE.md` for how well each one is evidenced.

## Why this exists

Model output on real tasks improves when the agent works inside a structure: a verified
baseline, requirements that can be checked, small planned tasks, objective gates, guardrails that
fire on their own, and state that survives the session. The owner remains responsible for every
change, so the guide is organized around making output **reviewable, verified and honest**.

## Use it

- **As a skill:** copy the `agent-ready/` folder into your agent's skills directory (or reference
  `agent-ready/SKILL.md` from a repo's `AGENTS.md`). `SKILL.md` holds the always-on rules and a
  table that loads one module at a time.
- **As a guide:** read `agent-ready/modules/` in order.
- **In a repo:** copy the templates you need from `agent-ready/templates/`.

## Layout

```
agent-ready/
  SKILL.md                     entry point: rules that always apply + module router
  modules/
    01-orient-a-repo.md        recon, baseline, writing AGENTS.md
    02-spec-and-plan.md        "ready" bar, requirements with Verify, verified plan
    03-build-loop.md           the gated single-agent loop, stop conditions, done
    04-guardrails.md           enforce rather than request; advisory model reviewers
    05-verifying-llm-output.md mechanical gates, capped refine loops, grounding
    06-context-and-continuity.md state files, dead ends, handoffs, patch-loop escape
    07-design-and-research-docs.md design docs, threat models, results, backlog
    08-review-and-merge.md     all-gates-green, review handling, CI principles
    09-reuse-a-reference-project.md  read the reference's docs, write the delta, copy vs adapt (hypothesis)
    10-data-changing-jobs.md   dry-run, idempotency, limits, rollback, rollout (hypothesis)
    11-document-the-repo.md    a docs/ layer so later sessions can navigate a repo (hypothesis)
  templates/                   AGENTS, REQUIREMENTS, PLAN, STATE, HANDOFF, ISSUE-SPEC,
                               DESIGN, RESULTS, PR-DESCRIPTION, DATA-JOB-SPEC,
                               docs/ (index, architecture, data-model, runtime, testing, decision)
  scripts/                     secret_guard.py, red_green_gate.py, state_check.py (stdlib Python)
box/
  README.md                    what the agent box is; links the standard
  STANDARD.md                  the 9/10 and 10/10 bar: six dimensions (G R J W P D), evidence, scoring
  profiles/                    home and corporate setups a repo picks with `.box-profile`, and a
                               loader that reads the choice (stdlib Python)
  skills/box-audit/            score a repo against the standard: evidence collectors, an isolated
                               judge, a card check, and filing the proposed issues (stdlib Python)
  skills/box-bootstrap/        build a Python repo's missing repo-level items on a branch, from
                               templates chosen by the profile, checked by box-audit's collectors
  skills/skill-eval/           test a skill change A vs B: isolated sessions, checks, a blind judge,
                               a trigger check and a verdict, under a cost cap (stdlib Python)
  lessons/                     one file per lesson, linked to its EVIDENCE.md row and the check that
                               enforces it; a README lists them and the open ones
  orchestrate/                 dispatch spec: labels, selection, worker brief, handoff; two scripts
                               check the queue and a worker's PR (stdlib Python)
tests/                         pytest suite for the scripts, the box audit, box-bootstrap, skill-eval,
                               orchestrate and the evaluator heuristic (real git, temp repos); not part
                               of the skill
experiments/05-evaluator/      synthetic experiment behind module 05's evaluator claim; not part of the skill
experiments/06-skill-eval/     skill-eval's proof run on agent-ready (harmful and no-op edits)
experiments/07-rule-mining/    reading pass over four public skill bundles: coverage, contradictions,
                               up to 10 proposed rules; proposals only, not part of the skill
ci/                            pinned test and coverage requirements used by CI and Dependabot
EVIDENCE.md                    where each rule came from and how well it is evidenced
LICENSE                        MIT
AGENTS.md                      how to maintain this repo
```

## Tests

```
python -m pip install -r ci/requirements-test.txt
python -m pytest tests -q      # needs pytest; takes tens of seconds; 5 `sh` tests skip on Windows
```

The scripts are stdlib-only. CI (`.github/workflows/tests.yml`) runs them on GitHub-hosted Linux,
macOS and Windows runners (Python 3.10) and on Ubuntu 22.04 with Python 3.8 and 3.14. See
`EVIDENCE.md` for what the tests do and do not establish.

Dependabot checks Actions and the pip manifests in `ci/` weekly. The SonarCloud workflow
analyses both script trees, `agent-ready/scripts/*.py` and `box/**/*.py`, treats `tests/` as tests, imports subprocess coverage from a Python 3.12 test run (`.coveragerc`), and waits for the quality gate.
Same-repository PRs, including Dependabot, are eligible; fork PRs are skipped. Without
`SONAR_TOKEN`, the job succeeds with a notice and does not run analysis.

Owner setup: create the SonarCloud project and organization named in `sonar-project.properties`,
link this repository, disable automatic analysis, and store authorized tokens as `SONAR_TOKEN`
in both Actions and Dependabot repository secrets. After setup, verify a main push, an ordinary
PR and a real Dependabot PR against their head commits, and record the workflow and SonarCloud
result links. A missing-token notice is not scan evidence.

## What is deliberately not here

A launcher or process management for parallel sessions, usage or cost routing, a mapping from
model tier to model, and any vendor- or harness-specific mechanics. Those depend on infrastructure
a single-agent workflow does not have. Ideas that came from that work are included only where they
hold for one agent (for example the state file, the review-round cap and the mechanical-gate
principle). The orchestration level lives in `box/` only: `box/STANDARD.md` sets the bar, and
`box/orchestrate/` carries a host- and harness-neutral spec (labels, selection, the worker brief,
the handoff) with two checking scripts. You start sessions with your own harness, and `tier:*`
labels rate difficulty without choosing a model.

## Caution

The source projects were built with heavy AI assistance, including their documentation. Treat
the rules as well-motivated hypotheses, not established fact, until they have paid off on your own
work. Do not put employer-confidential material, credentials or personal infrastructure detail
in this repo.

## License

MIT. See `LICENSE`.
