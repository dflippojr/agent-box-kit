# AGENTS.md — <project name>

> Instructions for any coding agent working in this repo. Keep it short. Commands marked "run"
> were executed on <date>; those marked "not run" were read from the code only. If something here
> is wrong, fix it in the same change.

## What this project is
<One or two sentences. Link to the README for more.>

## Commands
| Purpose | Command | Success looks like |
|---|---|---|
| Build | `<cmd>` | <exit 0> |
| Full test suite | `<cmd>` | <N passed> |
| One test | `<cmd>` | |
| Lint / format | `<cmd>` | |
| Run | `<cmd>`, or **Do not run** (writes to <target>) | <or "not run; read from code"> |

Baseline recorded <date>: <pass/fail counts, pre-existing failures>.

## How to verify a change
- <area A>: `<cmd>`
- <area B>: `<cmd>`

## Boundaries
- Do not edit: <generated code, vendored deps, production config>.
- Ask the owner first: <schema changes, new dependencies, anything irreversible>.
- Never: merge, deploy, close issues, publish, or delete things you did not create.
- Work on a branch or worktree, not the default branch or the owner's live checkout.

## Safety
- Secrets come from <env vars / .env (git-ignored)>. Never print or commit them.
- Sensitive data: <what counts, as stated by the owner (do not infer it from names), and how it is kept out of the repo, logs and prompts>.
- Guardrails in place: <CI check, or a pre-commit hook if the owner wants one>. Never bypass them.
- Write paths (do not run): <jobs, migrations, deploy scripts and the target each affects>.

## Conventions not obvious from the code
- <naming, layout, error handling, test style>

## Known quirks
- <intentionally red tests, flaky tests, slow or dangerous commands>

## Definition of done
Builds; the task's Verify command passes with visible output; diff is minimal and in scope; no
secrets or sensitive data; docs updated; you have stated what you did not run or verify.

## Pointers
- Design docs: <path>
- Current plan / state: <path>
- Decisions and rejected options: <path or issue>
