# Box audit: sample-lib (2026-11-16)

- Repo: sample-lib at 0566dffa61d5, default branch main
- Remote: none
- Host evidence: unavailable (no remote)
- Judge: isolated: fresh session started by the walker harness from prompt.md only; probe not run
- Score: `G ~ · R ~ · J ✗ · W ~ · P – · D ✗ → 7`
- Proven: 3.0

## Summary

sample-lib scores 7 (Proven 3.0). The repo has a lot of gate machinery on paper: a `gate` workflow, a tamper guard, a PR-body lint, a one-command local gate and a proof section in AGENTS.md. But there is no remote, so no host enforces any of it and none of it could be verified. J and D are the weakest dimensions. No oracle the author did not write checks the core promise (counting words correctly), and no bug-hunt pass has ever been recorded. The change that would raise the score most is an outside oracle for word counts, run by `scripts/check.py` on every change. It moves J off ✗. A local `ready` script that enforces the gate on the head commit while there is no host would do the most to make G real.

## G: Enforced gate

**Mark:** ~

### Evidence

**Verified**
- "Remote: none (host evidence unavailable: no remote)". With no host there is no branch protection or required check, and no run history showing a red PR blocked. The protection, ci_runs and merged_prs sections were unavailable and would have settled the head-commit and no-cancellation items. (git remote)
- HEAD 0566dffa61d5 on main, 4 commits. Host evidence unavailable, so nothing shows how those commits reached main. (git rev-parse / rev-list)

**Read only**
- `gate.yml` triggers on `pull_request, push` and runs `python scripts/check.py` as job `gate`. (.github/workflows/gate.yml:36)
- `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`. Runs are cancelled only for PRs, so pushes to main should get a full run. This is config only; the host evidence that would show no cancellations on main was unavailable. (.github/workflows/gate.yml:19)
- Tamper guard: `python scripts/tamper_guard.py --base "$BASE_SHA" "$@"`, with `--approved` passed when `$APPROVED` is `true`. The evidence does not show who or what sets `APPROVED`. (.github/workflows/pr-checks.yml:27-28)
- AGENTS.md says gate edits are "flagged" by the tamper guard and need "the owner's explicit approval", and that the required check `gate` means "a red head commit cannot merge". (AGENTS.md, "Proving a change")
- No `ready` script and no review step appear anywhere in the evidence. Nothing makes review findings block "ready".

### Gap

- A commit with failing tests merged or pushed straight to main. No host exists to require `gate`, and no `ready` script stands in for it, so nothing stops it.
- A PR that edits `scripts/tamper_guard.py` so it exits 0. The `pull_request` workflow runs the guard from the PR's own checkout, so the guard being judged can disable itself.
- A PR whose review found a defect is merged anyway. No review exists, and nothing ties review findings to "ready".

### Proposed issues

#### Add a local ready script that enforces the gate on the head commit

Labels: tier:standard, ready, P0
Open decisions: none

**Problem**
The repo has no remote (verified), so the "required check `gate`" that AGENTS.md promises is enforced by nothing. No `ready` script exists, so a red commit can reach main.

**Want**
- `scripts/ready.py BRANCH` checks out the branch's head commit in a clean temporary worktree. It runs `python scripts/check.py`, then `scripts/tamper_guard.py --base main`, then `scripts/pr_body_lint.py` on a given description file, and prints the head SHA it judged.
- It exits non-zero when any step fails or when the branch head moved during the run, and exits 0 only when all steps pass.
- AGENTS.md says merges to main go only through `scripts/ready.py`, and states the gap: there is no host enforcement while the repo has no remote.
- A test makes a throwaway branch with a failing test and shows `ready.py` exits non-zero on it.

**Constraints**
- Do not change `scripts/check.py`, `tamper_guard.py` or `pr_body_lint.py` behaviour. List the new script under `### Gate changes`.
- Tests go in `tests/`. Attach the red and green `ready.py` output to the PR.

**Dependencies**
none

**Out of scope**
Setting up a hosted remote and branch protection.

#### Run the tamper guard from the base commit, not the PR's checkout

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
`pr-checks.yml` runs `python scripts/tamper_guard.py` from the PR's own tree (pull_request trigger), so a PR can weaken the guard that judges it.

**Want**
- The tamper guard that judges a change is the copy at the base commit: CI runs `git show "$BASE_SHA":scripts/tamper_guard.py` to a temp file and executes that, and the `ready` script does the same.
- A test shows that a change which rewrites `scripts/tamper_guard.py` to always exit 0 is still flagged by the base copy.
- A change that touches `scripts/tamper_guard.py` is itself flagged as a gate change.

**Constraints**
- The guard's rules stay as they are. This is a gate change, so list it under `### Gate changes` for owner approval.
- Attach the guard's output on the self-rewriting test change.

**Dependencies**
none

**Out of scope**
Moving the guard to a separate protected repository.

#### Add tests that prove the tamper guard and PR-body lint go red

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
The only test file is `tests/test_wordcount.py`. `scripts/tamper_guard.py` and `scripts/pr_body_lint.py` have no tests, so a guard that never flags anything, or a lint that accepts every description, would pass unnoticed.

**Want**
- Tests in `tests/` build throwaway git repos where a change deletes a test, adds `@pytest.mark.skip`, adds a retry, or edits `.github/workflows/gate.yml`. The tamper guard exits non-zero on each without `--approved` and exits 0 with it.
- Tests feed `pr_body_lint.py` a description missing the `## Proof` table, `### Not verified`, `### Gate changes` or the closing reference. Each is rejected, and a complete description passes.
- `python scripts/check.py` runs these tests.

**Constraints**
- Do not change the guard's or the lint's rules to make tests pass. Report any defect found as a separate issue.
- Attach the pytest output.

**Dependencies**
none

**Out of scope**
Adding review-finding blocking to the gate.

## R: Real-thing tests

**Mark:** ~

### Evidence

**Verified**
none

**Read only**
- One test file, classified "plain unit": `tests/test_wordcount.py`. The keyword scan found no real-dependency or end-to-end tests. (git ls-files + keyword scan)
- CI runs only on `ubuntu-latest`. No other OS, and the evidence shows no Python version matrix. (.github/workflows/gate.yml:23)
- Product shape guess: "library or tool (no deploy, container or health endpoint found)". (derived, production section)
- Why ~ and not n/a: the evidence cannot show that the library touches nothing beyond the Python runtime. Even if it touches nothing else, the standard still asks for tests on each OS users run, and CI covers only Linux. I give the keyword-based "plain unit" classification moderate weight.

### Gap

- A default-encoding or line-ending bug that shows up only on Windows, such as reading text as cp1252 or counting `\r\n` differently. It passes on ubuntu-only CI.
- A failure on a Python version users run but CI does not, such as the oldest supported version declared in the `.toml` file.

### Proposed issues

#### Run the gate on Windows and macOS as well as Linux

Labels: tier:mechanical, ready, P1
Open decisions: none

**Problem**
`gate.yml` runs only on `ubuntu-latest`, so OS-specific encoding and newline behaviour is never tested.

**Want**
- The `gate` job matrix includes `ubuntu-latest`, `windows-latest` and `macos-latest`, and each runs `python scripts/check.py`.
- `tests/test_wordcount.py` gains a case with CRLF line endings and non-ASCII text that passes on all three.

**Constraints**
- This edits gate config, so list it under `### Gate changes` for owner approval.
- Attach the matrix run results, or local output where CI cannot run.

**Dependencies**
none

**Out of scope**
Testing against more Python versions.

#### Test every Python version the package declares support for

Labels: tier:mechanical, ready, P2
Open decisions: none

**Problem**
The evidence shows no Python version matrix in CI, so a version the package claims to support may never run.

**Want**
- The `gate` job matrix lists the oldest and newest Python versions allowed by the `requires-python` field (or equivalent) in the `.toml` file.
- A test fails if the `.toml` field and the CI matrix name different versions.

**Constraints**
- This is a gate change; list it under `### Gate changes`. Attach the run results.

**Dependencies**
none

**Out of scope**
Changing the supported version range.

## J: Outside judge

**Mark:** ✗

### Evidence

**Verified**
none

**Read only**
- "no candidate outside oracle found by name or keyword". I give this keyword scan moderate weight, but nothing else in the evidence suggests an oracle. (oracles keyword scan)
- The core promise, inferred from the name and test file: given text, wordcount returns the correct number of words. The only check is `tests/test_wordcount.py`, which the author wrote. (tests section)

### Gap

- A change in how words are split, for example on punctuation, Unicode whitespace or hyphens, that miscounts real text. The author's tests agree with the author's definition, and nothing independent compares the counts.

### Proposed issues

#### Check word counts against an independent reference on every change

Labels: tier:frontier, needs-refinement, P0
Open decisions: Which reference counts as the oracle (GNU `wc -w`, Python's `len(s.split())`, or a published corpus with known counts)? On which inputs does the library's definition of a word agree with that reference, so that a mismatch means a defect?

**Problem**
No oracle the author did not write checks the core promise. The only tests are author-written unit tests, which can only confirm the code agrees with itself.

**Want**
- A test compares the library's count with the chosen reference over a fixed corpus of at least 50 varied texts, covering ASCII, Unicode whitespace, punctuation and empty input, and fails on any mismatch inside the agreed domain.
- `python scripts/check.py` runs it, so it runs on every PR and push.
- `docs/testing.md` names the reference, who wrote it, and the domain where it applies.

**Constraints**
- Expected counts must come from the reference, never from the library's own output.
- Attach the comparison output, including a run where a deliberate miscount makes the test fail.

**Dependencies**
none

**Out of scope**
Changing the library's definition of a word.

## W: Worker-runnable proof

**Mark:** ~

### Evidence

**Verified**
- Instruction file `AGENTS.md`, verify skill `.agents/skills/verify/SKILL.md` and disposable-instance contract `docs/disposable-instance.md` are tracked. (git ls-files)
- Docs layer tracked: `docs/README.md`, `docs/architecture.md`, `docs/data-model.md`, `docs/runtime.md`, `docs/testing.md`. (git ls-files)
- The one command was not run on a clean checkout ("probe not run"), so it is not verified to work or to end with `GATE_PASS`.

**Read only**
- "Run the whole gate locally, with one command ... `python scripts/check.py` ... It runs every step CI runs and ends with `GATE_PASS`." (AGENTS.md, "Proving a change")
- Proof to attach: "a `## Proof` table with one row per acceptance criterion ... then `### Not verified` and `### Gate changes`, and the closing reference". The PR template mentions Proof, Not verified, Gate changes and Closes. (AGENTS.md; .github/pull_request_template.md)
- PR body is linted: `printf '%s\n' "$PR_BODY" | python scripts/pr_body_lint.py -`. (.github/workflows/pr-checks.yml:40)
- "A bug fix starts with a test that fails on the base branch; paste its failing output." (AGENTS.md)
- Contradiction: "How to verify a change" says `python3 -m pytest -q`, while "Proving a change" says `python scripts/check.py`. (AGENTS.md)
- CI installs `pytest` and `requirements.txt` before running `check.py`. The evidence does not say whether `check.py` covers the `pr-checks` steps (tamper guard, body lint). (.github/workflows/gate.yml:33-36)

### Gap

- A change that passes `python scripts/check.py` locally but fails the tamper guard or body lint in `pr-checks`, if `check.py` does not run those steps. Nothing tests the claim that it "runs every step CI runs".
- A worker that follows "How to verify a change" runs only `pytest -q`, skips the rest of the gate, and reports done.

### Proposed issues

#### Test that scripts/check.py covers every CI step

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
AGENTS.md says `check.py` "runs every step CI runs", but nothing checks it. `gate.yml` and `pr-checks.yml` can drift from the local command.

**Want**
- A test in `tests/` parses every `run:` step in `.github/workflows/*.yml` and fails if a step other than dependency installation has no matching step in `scripts/check.py`, or in an explicit allow-list with a reason for each entry.
- Adding a new `run:` step to a workflow without updating `check.py` makes the test fail. Show this in the PR.

**Constraints**
- Do not change what CI runs. Attach the red and green test output.

**Dependencies**
none

**Out of scope**
Making `check.py` run the PR-body lint without a description file.

#### Make AGENTS.md name one verify command

Labels: tier:mechanical, ready, P2
Open decisions: none

**Problem**
AGENTS.md says `python3 -m pytest -q` under "How to verify a change" and `python scripts/check.py` under "Proving a change", so a worker can run only part of the gate.

**Want**
- "How to verify a change" says `python scripts/check.py` and links to "Proving a change". No section offers bare `pytest` as the way to verify.

**Constraints**
- Docs-only change. Attach the diff and a `check.py` run showing `GATE_PASS`.

**Dependencies**
none

**Out of scope**
Restructuring the rest of AGENTS.md.

## P: Real-use feedback

**Mark:** –

**Reason:** sample-lib is a library or tool with nothing deployed, no installer, no vendored copies and no copies of its build in another repo or site. No known dependents were found, so there is no real-use signal to measure.

### Evidence

**Verified**
- Container files: none. Vendored copies: none. (git ls-files)

**Read only**
- No health or version endpoints, no telemetry or alerting terms, no deploy or release workflows, no scheduled workflows, no installer tooling. (keyword scan; .github/workflows)
- No copies of this repo's build in another repo or site were found. (git ls-files + keyword scan)

### Gap

none

### Proposed issues

No issue: P is n/a. Nothing is deployed, installed or vendored. If the library is published or gains dependents, a scheduled dependent build becomes the real-use signal.

## D: Defect ratchet

**Mark:** ✗

### Evidence

**Verified**
- "last 4 non-merge commits on main: 0 look like fixes, 0 of those touched a test file, 0 reverts". No escaped defect has been traced or ratcheted, and none is visible to trace. The issue list and merged PRs were unavailable (no remote), and they would have settled whether escaped defects exist. (git log)

**Read only**
- The evidence shows no dated bug-hunt pass anywhere in the repo.
- The PR template asks for Proof, Not verified, Gate changes and Closes. It does not ask which change introduced a defect. (.github/pull_request_template.md)
- AGENTS.md asks that a bug fix "starts with a test that fails on the base branch". That is per instance, not class-level. (AGENTS.md)

### Gap

- An input-handling bug, such as miscounting text with tabs, that is fixed with one example test. The next variant, such as non-breaking spaces, escapes the same way because no class-level check exists.
- Defects already on main stay unknown, because no adversarial bug-hunt pass has ever been run.

### Proposed issues

#### Run and record a dated bug-hunt pass on main

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
No bug-hunt pass has been recorded, so the D bar of at most 2 CI-catchable escapes per pass cannot be measured.

**Want**
- `docs/bug-hunt/2026-11-<day>.md` records the commit hunted, the method and every finding.
- Each finding is marked CI-catchable or not, with the reason, and becomes its own issue linked from the file.
- The file states the count of CI-catchable escapes.

**Constraints**
- Do not fix findings in this PR. Each fix is its own issue.
- The hunt targets the default branch at a named commit.

**Dependencies**
none

**Out of scope**
Fixing any of the defects found.

#### Require bug fixes to name the introducing change and a class-level check

Labels: tier:standard, ready, P2
Open decisions: none

**Problem**
Nothing asks which change introduced a defect or whether its fix covers the whole class. The PR template and `pr_body_lint.py` check only Proof, Not verified, Gate changes and Closes.

**Want**
- The PR template gains `Introduced by:` (a commit or PR) and `Class check:` (the test or check that catches the whole class) for bug fixes.
- `scripts/pr_body_lint.py` rejects a description that closes an issue labelled `bug` but leaves either field empty. A test shows the rejection and an accepted example.
- An issue template for bug reports asks for the suspected introducing change.

**Constraints**
- This edits a gate script, so list it under `### Gate changes`. Tests go in `tests/`. Attach the lint output.

**Dependencies**
none

**Out of scope**
Tracing past defects back to their changes.
