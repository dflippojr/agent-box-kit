# Box audit: sample-lib (2026-11-16)

- Repo: sample-lib at 89407e705ae0, default branch main
- Remote: none
- Host evidence: unavailable (no remote)
- Judge: isolated: fresh session started by the harness from prompt.md only; probe not run
- Score: `G ~ · R ~ · J ✗ · W ~ · P – · D ✗ → 7`
- Proven: 3.0

## Summary

sample-lib scores 7 (`G ~ · R ~ · J ✗ · W ~ · P – · D ✗`). The repo has most of the box on paper: a single gate command, a tamper guard, a PR-body lint, a proof section in AGENTS.md, a verify skill and a docs layer. But there is no remote, so nothing about enforcement, CI results or merge history could be verified. The weakest dimensions are J, which has no oracle for word counting that the author did not write, and D, where the one fix on main ("Fix apostrophe") changed no test. The change that would raise the score most is a differential test of the word counter against an independent reference on a fixed corpus, run on every PR. That moves J off ✗.

## G: Enforced gate

**Mark:** ~

### Evidence

**Verified**
- none. Branch protection, required checks, CI run history and merged PRs are all unavailable because the repo has no remote. Host evidence would have settled whether `gate`, `tamper-guard` and `pr-body` are required on the head commit, whether a red PR was ever blocked, whether main runs were ever cancelled, and who applied any approval. (git remote / --remote)

**Read only**
- The gate workflow runs `python scripts/check.py` on `pull_request` and `push`. (.github/workflows/gate.yml:36)
- `cancel-in-progress: ${{ github.event_name == 'pull_request' }}` cancels only PR runs, so a push to main is never cancelled by a newer push. (.github/workflows/gate.yml:19)
- The tamper guard runs `python scripts/tamper_guard.py --base "$BASE_SHA" "$@"`, with `--approved` passed when `$APPROVED` is true. (.github/workflows/pr-checks.yml:27-28)
- AGENTS.md claims: "CI runs the same command as the required check `gate` on every PR and on every push to `main`, so a red head commit cannot merge". This is unverifiable without a host. (AGENTS.md, "Proving a change")
- I found no automated review job and no rule that review findings block "ready". (.github/workflows)

### Gap

- With no remote and no `ready` script, nothing stops a commit that fails `scripts/check.py` from landing on main. The "required check" exists only as a sentence in AGENTS.md.
- A PR can rewrite its own judge. Both workflows trigger on `pull_request` and run `scripts/check.py`, `scripts/tamper_guard.py` and `scripts/pr_body_lint.py` from the PR's head. A PR that edits `tamper_guard.py` to exit 0, or makes `check.py` print `GATE_PASS` without running pytest, judges itself green.
- The source of `$APPROVED` is not shown. If it comes from a label that anyone with write access can apply, or one that survives a later push, the PR author can approve their own gate edit.
- A change with a review finding (for example, a word-boundary regex that drops hyphenated words but is covered by an updated expected value) merges, because no reviewer exists to block it.

### Proposed issues

#### Add a ready script that runs the gate on the head commit before any merge

Labels: tier:standard, ready, P0
Open decisions: none

**Problem**
The repo has no remote, so no host enforces the `gate`, `tamper-guard` or `pr-body` checks. AGENTS.md says a red head commit cannot merge, but nothing mechanical makes that true. The standard's fallback for an unenforced host is a `ready` script that every merge goes through.

**Want**
- `scripts/ready.py BRANCH` checks out the branch's head commit, runs `python scripts/check.py`, `python scripts/tamper_guard.py --base main` and `python scripts/pr_body_lint.py` against a supplied description file. It exits 0 only if all three pass, and prints the head SHA it judged.
- The script runs the guard and lint from main's copy of `scripts/`, not the branch's. A branch that edits `scripts/tamper_guard.py` to always pass is still flagged.
- AGENTS.md states that merges to main go only through `scripts/ready.py`, and records the enforcement gap (no host protection).
- Tests in `tests/` show `ready.py` exits non-zero for a branch with a failing test, and for a branch that edits `scripts/check.py` without approval.

**Constraints**
- Do not change what `scripts/check.py` runs. Tests go in `tests/`. Attach the output of `ready.py` on one passing branch and one failing branch.

**Dependencies**
none

**Out of scope**
Pushing the repo to a host and configuring branch protection.

#### Add tests proving the tamper guard flags test deletions, skips, retries and gate edits

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
The tamper guard is wired into `pr-checks.yml`, but the evidence shows no test of what it catches. A guard that silently passes everything would look the same as a working one.

**Want**
- Tests that build throwaway git histories and assert `scripts/tamper_guard.py --base BASE` exits non-zero for each of these: a deleted test file, an added `pytest.mark.skip`, an added retry decorator, an edit to `.github/workflows/*.yml`, an edit to `scripts/*.py`, and an edit to pytest or coverage settings in `pyproject.toml`.
- A test that the same diffs exit 0 with `--approved`.
- A test that a diff touching only `src/` exits 0.

**Constraints**
- Tests only. Do not change the guard's behaviour unless a test exposes a miss, and list any such change under `### Gate changes`.

**Dependencies**
none

**Out of scope**
Deciding where `$APPROVED` comes from on a hosted setup.

#### Add an automated review step whose findings block ready

Labels: tier:frontier, needs-refinement, P2
Open decisions: Which reviewer (human owner checklist or a model from a different family)? How does the owner accept a finding so it stops blocking?

**Problem**
No review step exists in CI or in AGENTS.md's definition of done. The standard needs review findings to block "ready" unless the owner accepts them.

**Want**
- One review step reads the PR description's acceptance criteria and the diff, and writes findings to a file.
- `scripts/ready.py` (or CI) exits non-zero while any finding is unaccepted.
- One recorded example of a PR held back by a finding.

**Constraints**
- Must not edit the existing gate jobs. The reviewer's definition lives outside the PR's reach.

**Dependencies**
none

**Out of scope**
The independent falsifying verifier (J's 10-need).

## R: Real-thing tests

**Mark:** ~

### Evidence

**Verified**
- none. The repo has 19 tracked files with 5 `.py`; no container files or vendored copies (git ls-files). I put little weight on this: it hints that the product depends on nothing beyond the Python runtime, but does not show it.

**Read only**
- There is 1 test file, classed as plain unit: `tests/test_wordcount.py`. The keyword scan found no mock or fake usage, but that is a keyword scan, not an inventory. (git ls-files + keyword scan)
- CI runs on `ubuntu-latest` only, with no OS or Python-version matrix. (.github/workflows/gate.yml:23)
- Product shape guess: "library or tool (no deploy, container or health endpoint found)". (derived from production items)

### Gap

- Text with Windows line endings (`\r\n`) or a non-UTF-8 default locale encoding (Windows `cp1252` when reading a file without `encoding=`) miscounts or raises `UnicodeDecodeError` on Windows. The only CI run is on Linux, where both pass.
- Behaviour that differs between Python versions (for example, Unicode database changes to `str.isalpha` or `\w` matching for newer code points) passes on the single unpinned CI Python and breaks for users on another version.

### Proposed issues

#### Run the gate on Linux, macOS and Windows for each supported Python version

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
The product appears to need only the Python runtime, but the standard says to test on each OS users run. CI runs `ubuntu-latest` only, with no Python matrix.

**Want**
- `gate.yml` runs `python scripts/check.py` in a matrix of `ubuntu-latest`, `macos-latest` and `windows-latest`, and every Python version allowed by `requires-python` in `pyproject.toml`.
- A test in `tests/test_wordcount.py` counts a fixture with `\r\n` line endings and one with non-ASCII text read from a file. Both pass on all three OSes.
- The PR shows a green run for every matrix cell.

**Constraints**
- This is a gate change: list it under `### Gate changes`. Do not loosen `cancel-in-progress` for push runs.

**Dependencies**
none

**Out of scope**
A scheduled run against pre-release Python versions.

## J: Outside judge

**Mark:** ✗

### Evidence

**Verified**
- none

**Read only**
- "no candidate outside oracle found by name or keyword". (keyword scan)
- The core promise, inferred from the name and test file: given text, return the correct word count. The only check is `tests/test_wordcount.py`, written by the same author as the code. (git ls-files + keyword scan)

### Gap

- A change to the word-boundary rule that miscounts contractions, hyphenated words or curly apostrophes (U+2019) passes, if the author updates the expected values in `tests/test_wordcount.py` to match. Nothing outside the author's own expectations checks the count. The recent "Fix apostrophe" commit shows this class is real.
- Double counting across whitespace runs, tabs or non-breaking spaces (U+00A0) passes if the author's tests never include them.

### Proposed issues

#### Add a differential test of word counts against an independent reference on a fixed corpus

Labels: tier:frontier, needs-refinement, P0
Open decisions: Which reference defines a word: GNU `wc -w`, Unicode UAX #29 word boundaries (for example via the `regex` package's `\b{w}`), or an owner-labelled corpus? Where the chosen reference and the documented definition differ (apostrophes, hyphens), which wins?

**Problem**
No oracle for the core promise exists that the author did not write. Every expected count in `tests/test_wordcount.py` comes from the author, so the tests can only confirm the code agrees with its author.

**Want**
- A fixed corpus under `tests/corpus/` with at least 20 texts, including contractions, curly apostrophes, hyphens, tabs, non-breaking spaces, CJK and empty input.
- A test compares the library's count for each text with the chosen reference's count. Each documented divergence is listed in one table with its reason.
- The test runs in `scripts/check.py`, so it runs on every PR.

**Constraints**
- The reference must not import or reuse the library's own code. Tests go in `tests/`.

**Dependencies**
none

**Out of scope**
Property-based tests written by the author; they belong to D.

#### Add an owner-labelled golden corpus of word counts

Labels: tier:standard, ready, P2
Open decisions: none

**Problem**
Even with a differential reference, divergences need a human ruling. No expected values exist that come from anyone but the authoring session.

**Want**
- `tests/golden/counts.csv` holds text and an expected count. Its header names the owner as the source, and the file is listed among the tamper guard's protected paths.
- A test asserts the library matches every row, and runs in `scripts/check.py`.

**Constraints**
- Workers may not edit `tests/golden/counts.csv` without the owner's approval. The tamper guard must flag edits to it.

**Dependencies**
none

**Out of scope**
Generating expected counts by running the library.

## W: Worker-runnable proof

**Mark:** ~

### Evidence

**Verified**
- Instruction file `AGENTS.md` is tracked. (git ls-files)
- A verify skill `.agents/skills/verify/SKILL.md` and a disposable-instance contract `docs/disposable-instance.md` are tracked. (git ls-files)
- A docs layer is tracked: `docs/README.md`, `docs/architecture.md`, `docs/data-model.md`, `docs/runtime.md`, `docs/testing.md`. (git ls-files)

**Read only**
- One command is named: "Run the whole gate locally, with one command ... `python scripts/check.py` ... It runs every step CI runs and ends with `GATE_PASS`." The probe was not run, so this is unconfirmed. (AGENTS.md, "Proving a change")
- AGENTS.md says what to attach: "a `## Proof` table with one row per acceptance criterion ... then `### Not verified` and `### Gate changes`, and the closing reference", and "A bug fix starts with a test that fails on the base branch; paste its failing output." (AGENTS.md, "Proving a change")
- The PR template mentions Proof, Not verified, Gate changes and Closes. (.github/pull_request_template.md)
- The PR body is linted: `printf '%s\n' "$PR_BODY" | python scripts/pr_body_lint.py -`. (.github/workflows/pr-checks.yml:40)
- AGENTS.md "How to verify a change" gives `python3 -m pytest -q` for src/wordcount, which conflicts with the one gate command. (AGENTS.md, "How to verify a change")
- CI runs `pip install pytest` and `pip install -r requirements.txt` before `check.py`. Whether `check.py` covers those steps locally is not shown. (.github/workflows/gate.yml:33-34)

### Gap

- A worker follows "How to verify a change" and runs only `python3 -m pytest -q`. They report done while any lint or other step in `scripts/check.py` fails, and only CI catches it.
- Someone adds a step to `gate.yml` and not to `scripts/check.py` (or the reverse). Local and CI results drift, and nothing detects it.
- A worker with an extra package installed locally passes `check.py`, while CI fails for a dependency missing from `requirements.txt`.
- No PR history was available, so nothing shows the PR-body lint has ever rejected a description.

### Proposed issues

#### Add a test that scripts/check.py covers every step in gate.yml

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
AGENTS.md claims `scripts/check.py` "runs every step CI runs", but nothing checks it. The two can drift silently.

**Want**
- A test parses `.github/workflows/gate.yml` and asserts each `run:` step other than dependency installs maps to a step that `scripts/check.py` runs. The test fails when a step is added to one but not the other.
- The test asserts `check.py` exits non-zero and does not print `GATE_PASS` when any step fails or is skipped.
- The test runs as part of `scripts/check.py`.

**Constraints**
- Do not change which steps CI runs. Attach the test's failing output after a deliberately removed step, then the passing output.

**Dependencies**
none

**Out of scope**
Running the workflow in a local Actions emulator.

#### Point AGENTS.md's verify section at the one gate command

Labels: tier:mechanical, ready, P2
Open decisions: none

**Problem**
"How to verify a change" says `python3 -m pytest -q`, while "Proving a change" says `python scripts/check.py`. A worker can follow the first and skip gate steps.

**Want**
- "How to verify a change" names `python scripts/check.py` as the command that proves a change, and keeps `pytest -q` only as a fast inner loop.
- `grep -n "pytest -q" AGENTS.md` shows no line that presents it as sufficient proof.

**Constraints**
- Edit only AGENTS.md.

**Dependencies**
none

**Out of scope**
Restructuring the rest of AGENTS.md.

#### Add tests that the PR-body lint rejects descriptions missing each required part

Labels: tier:standard, ready, P2
Open decisions: none

**Problem**
`scripts/pr_body_lint.py` runs on every PR, but no PR history was available, and the evidence shows no test of what it rejects.

**Want**
- Tests feed `scripts/pr_body_lint.py` descriptions that each omit one part: the `## Proof` table, a row per acceptance criterion, `### Not verified`, `### Gate changes`, or the closing reference. Each must exit non-zero with a message naming the missing part.
- A test that the PR template filled in correctly exits 0.

**Constraints**
- Tests only, unless a test exposes a miss. List any lint change under `### Gate changes`.

**Dependencies**
none

**Out of scope**
Checking that the claimed evidence is true.

## P: Real-use feedback

**Mark:** –

**Reason:** The evidence shows a library or tool that is not deployed, ships no installer, vendors nothing and has no known dependents. No deploy or release workflows, health endpoints, container files, installer tooling, vendored copies or copies into other repos were found.

### Evidence

**Verified**
- Container files: none. Vendored copies: none. (git ls-files)

**Read only**
- "deploy or release workflows: none", "installer tooling: none", "health or version endpoints in source: none found", "copies of this repo's build into another repo or site: none found". (.github/workflows, keyword scan)

### Gap

none

### Proposed issues

No issue: P is n/a. If the library gains a published package or known dependents, P applies and needs a scheduled dependent build against head.

## D: Defect ratchet

**Mark:** ✗

### Evidence

**Verified**
- Of the last 5 non-merge commits on main, 1 looks like a fix, and it touched no test file: "89407e705a 2026-11-16 Fix apostrophe (no test file changed)". (git log)
- No reverts. (git log)

**Read only**
- AGENTS.md requires "A bug fix starts with a test that fails on the base branch; paste its failing output". The verified fix commit did not follow this. (AGENTS.md, "Proving a change")
- No bug-hunt pass record and no trace of the apostrophe defect to its introducing change was found. Defect and merged-PR host evidence is unavailable (no remote); it would have settled whether the fix had an issue and an introducing PR.

### Gap

- A change that reverts or breaks the apostrophe fix passes every gate, because the fix added no test.
- Defects in the same class (curly apostrophe U+2019, hyphenated words, possessives at end of input) pass, because no class-level check such as a property test over word boundaries exists.
- A future fix PR changes no test and still passes. Neither the tamper guard nor the PR-body lint is shown to require a changed test for a bug fix.

### Proposed issues

#### Add a class-level word-boundary test for the apostrophe fix and trace its origin

Labels: tier:standard, ready, P0
Open decisions: none

**Problem**
Commit 89407e705a "Fix apostrophe" landed on main with no test change. The defect was not traced to the commit that introduced it, and nothing stops the class from recurring.

**Want**
- A parametrized or property-based test over word boundaries covers ASCII and curly apostrophes, contractions, possessives, apostrophes at start and end of input, and hyphens. It fails on the commit before 89407e705a and passes on head. The failing output is pasted in the PR.
- A line in `docs/testing.md` names the commit that introduced the apostrophe defect, found with `git log -S` or `git bisect`, and the test that now guards the class.

**Constraints**
- Do not change the counting code unless the new test exposes another defect; file any such defect as its own issue. Tests go in `tests/`.

**Dependencies**
none

**Out of scope**
Defining the word rule against an outside reference (J).

#### Reject fix PRs that change no test file

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
AGENTS.md requires bug fixes to start with a failing test, yet the one fix on main changed no test. No check enforces the rule.

**Want**
- `scripts/pr_body_lint.py`, or the tamper guard, exits non-zero when the PR title or body marks it as a fix (`Fix`, `fix:`, or a `bug` label passed in) and the diff against base touches no file under `tests/`.
- Tests cover a fix PR with a test change (passes), a fix PR without one (fails) and a non-fix PR without one (passes).

**Constraints**
- This is a gate change: list it under `### Gate changes`.

**Dependencies**
none

**Out of scope**
Checking that the test fails on the base branch.

#### Run and record a dated bug-hunt pass on main

Labels: tier:standard, ready, P2
Open decisions: none

**Problem**
No bug-hunt pass exists, so the D need "at most 2 CI-catchable defects per pass" cannot be measured.

**Want**
- `docs/bug-hunts/2026-11-<day>.md` records the commit hunted, the inputs tried and each finding. Each finding is marked CI-catchable or not, with its introducing commit.
- Each finding is filed as an issue in the repo's issue list (or listed in the file while there is no remote).

**Constraints**
- Do not fix findings in this PR.

**Dependencies**
none

**Out of scope**
Automating the bug hunt.
