# AGENTS.md — @@PROJECT@@

> Instructions for any coding agent working in this repo. Keep it short. Commands marked "run"
> were executed on <date>; those marked "not run" were read from the code only. If something here
> is wrong, fix it in the same change.

## What this project is
<One or two sentences. Link to the README for more.>

## Commands
| Purpose | Command | Success looks like |
|---|---|---|
| Build | `<cmd>` | <exit 0> |
| Full test suite (the whole gate) | `python scripts/check.py` | `GATE_PASS`, exit 0 |
| One test | `python -m pytest <path>::<test name> -q` | |
| Lint / format | `<cmd>` | |
| Run | `<cmd>`, or **Do not run** (writes to <target>) | <or "not run; read from code"> |

Baseline recorded <date>: <pass/fail counts, pre-existing failures>.

## How to verify a change
- <area A>: `<cmd>`
- <area B>: `<cmd>`

@@PROVING@@
## Boundaries
- Do not edit: <generated code, vendored deps, production config>.
- Ask the owner first: <schema changes, new dependencies, anything irreversible>.
- Never: merge, deploy, close issues, publish, or delete things you did not create.
- Never give the owner's approval yourself: the `gate-change-approved` label or tag is the
  owner's alone.
- Work on a branch or worktree, not the default branch or the owner's live checkout.

## Safety
- Secrets come from <env vars / .env (git-ignored)>. Never print or commit them.
- Sensitive data: <what counts, as stated by the owner (do not infer it from names), and how it is kept out of the repo, logs and prompts>.
- Guardrails in place: the gate (`scripts/check.py`) and the tamper guard. Never bypass them.
- Write paths (do not run): <jobs, migrations, deploy scripts and the target each affects>.

## Conventions not obvious from the code
- <naming, layout, error handling, test style>

## Known quirks
- <intentionally red tests, flaky tests, slow or dangerous commands>

## Definition of done
Builds; `python scripts/check.py` passes with visible output; diff is minimal and in scope; no
secrets or sensitive data; docs updated; the change description's proof is complete; you have
stated what you did not run or verify.

## Pointers
- Docs index: [docs/README.md](docs/README.md)
- Verify skill: [.agents/skills/verify/SKILL.md](.agents/skills/verify/SKILL.md)
- Disposable instance: [docs/disposable-instance.md](docs/disposable-instance.md)
- Current plan / state: <path>
- Decisions and rejected options: <path or issue>
