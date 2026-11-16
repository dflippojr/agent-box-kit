# Box audit: sample-corp (2026-11-16)

- Repo: sample-corp at 29768e11b406, default branch main
- Remote: none
- Host evidence: unavailable (skipped with --no-remote)
- Judge: isolated: fresh session started by the harness from prompt.md only; probe not run
- Score: `G ~ · R – · J ✗ · W ~ · P – · D ✗ → 7`
- Proven: 2.5

## Summary

The box scores 7 (Proven 2.5). The repo has the documents a box needs: an AGENTS.md proof section, a one-command gate (`scripts/check.py`), a `ready` script with a tamper guard and PR-body lint, a verify skill, a disposable-instance contract and a docs layer. But this audit saw none of them run, so G and W are partial at best. J and D are absent: no outside oracle checks the word counts, and no bug-hunt pass or defect trace exists. Adding an outside oracle for the core promise (a fixed corpus whose word totals the code did not produce, run by `check.py`) would move J from ✗ to ~ or ✓ and raise the score most.

## G: Enforced gate

**Mark:** ~

### Evidence

**Verified**
- "no CI configuration found". The host enforces nothing, so the `ready` script fallback is the only possible gate. (git ls-files)
- "Remote: none". Host evidence (protection settings, CI runs, merged PRs, label actors) is unavailable, so nothing shows that a red change was ever blocked. (git remote / --remote)
- "HEAD is 29768e11b406 on main, 4 commits". This audit saw no record that any of these commits went through `ready.py`. (git rev-parse / rev-list)

**Read only**
- "ready script present: scripts/ready.py" (scripts/ready.py)
- "The host does not enforce required checks here, so a change merges only through `python scripts/ready.py --body FILE`. It runs the gate, the tamper guard and the PR-body lint on the head commit, and the person who merges merges only on exit 0." The fallback and its gap are written down, but this audit did not run the script. (AGENTS.md)
- "Do not delete, skip or loosen a test, add a retry, or edit gate config (CI config, the scripts in `scripts/`, coverage, pytest or lint settings) ... the tamper guard flags it, and it needs the owner's explicit approval." The audit saw no tamper-guard output on a real change. (AGENTS.md)
- Nothing says that review findings block `ready`, and the evidence names no reviewer. (AGENTS.md)

### Gap

- A commit merged with plain `git merge` or committed directly to main, without running `ready.py`. Nothing records or checks that merges went through the script.
- A change that edits `scripts/ready.py` or `scripts/tamper_guard.py` to skip a step, then runs the edited script as its own judge, because the script lives in the repo it judges.
- A change whose tamper guard runs but misses a test renamed out of pytest's collection pattern (for example `tests/test_x.py` to `tests/x_test.py`), if the guard looks only for deletions and skip markers.
- A change merged over an open review finding, because nothing makes findings block `ready`.

### Proposed issues

#### Record each ready.py pass against the head commit it judged

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
AGENTS.md says merges go only through `scripts/ready.py`. Git history shows 4 commits on main and no record that any of them passed the script. There is no remote, so no host record exists either. Nobody can tell a gated merge from a direct commit.

**Want**
- On exit 0, `ready.py` writes a git note (or annotated tag) on the head commit. The note holds the commit SHA, the date, and the pass/fail of the gate, the tamper guard and the PR-body lint.
- A new `scripts/check_merges.py` lists every first-parent commit on main after a stated start commit that has no passing note, and exits non-zero if any exist.
- Tests in `tests/` cover a commit with a note, a commit without one, and a note whose SHA does not match its commit.

**Constraints**
- Do not change what `ready.py` checks, only what it records.
- List the change under `### Gate changes` in the PR body.
- Attach the output of `check_merges.py` on the current main.

**Dependencies**
none

**Out of scope**
Moving `ready.py` outside the repo, or adding a hosted remote with branch protection.

#### Prove the tamper guard flags deleted, skipped and renamed tests

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
AGENTS.md says `scripts/tamper_guard.py` flags deleted or loosened tests, retries and gate-config edits. The evidence shows no output from it, and no test of it was found (the only test file is `tests/test_wordcount.py`). A guard that misses a case reports green while it skips, which counts as absent.

**Want**
- Tests that build throwaway git repos and run the tamper guard on diffs that: delete a test file, add a `pytest.mark.skip`, rename a test out of the collection pattern, add a retry, and edit a file under `scripts/` or the pytest config. Each case must be flagged with a non-zero exit or a named finding.
- A clean diff that touches only `src/` passes.
- `check.py` runs these tests.

**Constraints**
- Tests go in `tests/`, and they use temporary directories, not the working repo.
- Attach the test output, including one case shown failing before any guard fix.

**Dependencies**
none

**Out of scope**
Changing what counts as gate config.

#### Make ready.py refuse unaccepted review findings

Labels: tier:standard, needs-refinement, P2
Open decisions: Where do review findings live without a hosted remote (a file next to the PR body, or a section of it)? How does the owner record that a finding is accepted?

**Problem**
G needs review findings to block "ready" unless the owner accepts them. The evidence names no reviewer, and nothing in `ready.py`'s documented steps reads review findings.

**Want**
- `ready.py` reads the review findings for the change and exits non-zero while any finding is open and not marked accepted by the owner.
- Tests cover no findings, an open finding and an accepted finding.

**Constraints**
- List the change under `### Gate changes`.
- Attach `ready.py` output for an open-finding case.

**Dependencies**
none

**Out of scope**
Picking or building the reviewer itself.

## R: Real-thing tests

**Mark:** –

**Reason:** The evidence shows a small Python word-count tool ("product shape guess: library or tool"; 6 `.py` files; no container, database, browser, deploy or upstream API found). It runs on its language runtime and nothing else. The standard still asks for tests on each OS the users run, and that part is covered by the issue below.

### Evidence

**Verified**
- "container files: none" (git ls-files)

**Read only**
- "1 test files: plain unit 1", "tests/test_wordcount.py" (git ls-files + keyword scan)
- "product shape guess: library or tool (no deploy, container or health endpoint found)" (derived from the evidence's production items)

### Gap

- Line-ending or default-encoding differences (CRLF input, a non-UTF-8 locale on Windows) that change the count. The tests run only on whatever machine the worker uses, and no OS is named as supported.

### Proposed issues

#### Run the gate on each supported operating system

Labels: tier:standard, needs-refinement, P2
Open decisions: Which operating systems do users run? With no hosted CI, where do the non-local runs happen?

**Problem**
R's n/a still asks for tests on each OS the users run. No CI exists, and nothing names the supported operating systems or shows the tests running on more than one.

**Want**
- `docs/testing.md` names the supported operating systems.
- `python scripts/check.py` passes on each one, with the output attached.
- Tests cover CRLF input and non-UTF-8 input on each.

**Constraints**
- Do not weaken any existing test.
- Attach one gate log per OS.

**Dependencies**
none

**Out of scope**
Packaging or installers.

## J: Outside judge

**Mark:** ✗

### Evidence

**Verified**
none

**Read only**
- "no candidate outside oracle found by name or keyword". This is a keyword scan, so a lead and not proof, but nothing else in the evidence names an oracle. (keyword scan)
- The core promise, as far as the evidence shows: wordcount reports the correct word count for its input. The only test, `tests/test_wordcount.py`, is a "plain unit" test the author wrote. (git ls-files + keyword scan)

### Gap

- A change to word splitting (for example treating hyphens, apostrophes, Unicode whitespace or punctuation-only tokens differently) that also updates the expected values in the author's own unit test. Nothing outside the author checks the counts.
- An off-by-one on input with a missing trailing newline or leading whitespace that the author's test fixtures do not contain.

### Proposed issues

#### Add a word-count corpus with independently sourced totals

Labels: tier:standard, ready, P0
Open decisions: none

**Problem**
No oracle the author did not write checks the core promise. The one test file is a plain unit test whose expected values came from the same author.

**Want**
- `tests/corpus/` holds at least 10 text files: empty input, whitespace only, CRLF, no trailing newline, tabs, Unicode whitespace, punctuation runs and one long public-domain text. Each has an expected count from a source other than this code (GNU `wc -w` output captured with its version, or a published count), recorded in a manifest with the source and capture date.
- A test asserts that wordcount matches each manifest count, and `check.py` runs it.
- Wherever this project's definition of a word intentionally differs from the source, the manifest says so for that file.

**Constraints**
- Never generate expected counts by running wordcount.
- Tests go in `tests/`. Attach the test output and the manifest.

**Dependencies**
none

**Out of scope**
Changing the definition of a word.

#### Differential-test wordcount against a reference counter on generated input

Labels: tier:frontier, needs-refinement, P2
Open decisions: Which reference defines a word for this project (GNU `wc -w`, a Unicode word-boundary rule, or something else)? Run it on every gate, or on a schedule that writes to the issue list?

**Problem**
A fixed corpus covers only the inputs someone thought of. Divergence on other inputs goes unseen, as in J's failure story 5.

**Want**
- A property test generates random text (whitespace, Unicode and punctuation mixes) and compares wordcount with the chosen reference. Every mismatch outside the documented differences fails with the input shown.
- It runs where the open decision puts it, and a failure becomes an issue or a log entry the owner reads.

**Constraints**
- The reference is not code from this repo.
- Attach a run log, plus one deliberately injected divergence that the test caught.

**Dependencies**
none

**Out of scope**
Performance benchmarking.

## W: Worker-runnable proof

**Mark:** ~

### Evidence

**Verified**
- "instruction files: AGENTS.md" (git ls-files)
- "verify skill or UI-testing contract: .agents/skills/verify/SKILL.md" (git ls-files)
- "disposable-instance contract: docs/disposable-instance.md" (git ls-files)
- "docs layer: docs/README.md, docs/architecture.md, docs/data-model.md, docs/runtime.md, docs/testing.md" (git ls-files)
- These are file existence only. This audit did not run `scripts/check.py` on a clean checkout (probe not run).

**Read only**
- "Run the whole gate locally, with one command ... `python scripts/check.py` ... It runs every step CI runs and ends with `GATE_PASS`." No CI exists, so nothing can show that the claim "every step CI runs" holds. (AGENTS.md)
- "Attach the proof to the change description ... a `## Proof` table with one row per acceptance criterion ... `### Not verified` and `### Gate changes`, and the closing reference." (AGENTS.md, docs/pull_request_template.md)
- "A bug fix starts with a test that fails on the base branch; paste its failing output." (AGENTS.md)
- "workflows that read the PR body for proof: none". The lint is said to run inside `ready.py` (`scripts/pr_body_lint.py`), but no output of it was seen. (keyword scan, AGENTS.md)
- AGENTS.md also lists `python3 -m pytest -q` under "How to verify a change", a second, narrower command that a worker might run instead of `check.py`. (AGENTS.md)

### Gap

- `check.py` prints `GATE_PASS` after a step that silently did nothing (for example pytest collecting zero tests, or a missing linter skipped), so a worker's local green proves nothing.
- A worker follows "How to verify a change" and runs only `python3 -m pytest -q`, skipping the lint, tamper guard and PR-body lint steps, then reports done.
- A PR body with an empty proof table, or a "Closes" line with no number, passes because the lint itself is untested.

### Proposed issues

#### Make check.py fail when a gate step runs nothing

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
AGENTS.md says `scripts/check.py` runs the whole gate and ends with `GATE_PASS`. Nobody has shown it on a clean checkout, and nothing shows that it refuses to pass when a step is skipped or collects nothing. A green that skips counts as absent.

**Want**
- `check.py` exits non-zero and does not print `GATE_PASS` when pytest collects zero tests, when a step's tool is missing, or when any step exits non-zero.
- Tests run `check.py` in a temporary clean clone: one passing run, and one failing run for each of those cases.
- `GATE_PASS` is printed with the list of steps that ran.

**Constraints**
- Do not remove any existing step. List the change under `### Gate changes`.
- Attach the clean-clone output, passing and failing.

**Dependencies**
none

**Out of scope**
Adding hosted CI.

#### Test that pr_body_lint.py rejects incomplete proof

Labels: tier:standard, ready, P2
Open decisions: none

**Problem**
`ready.py` is said to lint the PR body with `scripts/pr_body_lint.py`. The only test file in the evidence is `tests/test_wordcount.py`, so the lint has no tests, and no rejected body was seen.

**Want**
- Tests that feed the lint bodies missing each of these: the `## Proof` table, a criterion row, `### Not verified`, `### Gate changes`, and the closing reference. Each body is rejected with a message naming what is missing.
- The filled-in `docs/pull_request_template.md` example passes.
- For a body marked as a bug fix, the lint requires a changed test and the pasted failing output.

**Constraints**
- Tests go in `tests/` and `check.py` runs them.
- Attach the test output.

**Dependencies**
none

**Out of scope**
Linting commit messages.

#### Point How to verify a change at the one gate command

Labels: tier:mechanical, ready, P2
Open decisions: none

**Problem**
AGENTS.md's "How to verify a change" says `python3 -m pytest -q`, while "Proving a change" says `python scripts/check.py`. A worker who reads only the first runs a subset of the gate.

**Want**
- "How to verify a change" names `python scripts/check.py` as the command to prove a change, and keeps pytest only as a quick inner-loop step labelled as not sufficient.

**Constraints**
- Docs-only change. Attach the diff.

**Dependencies**
none

**Out of scope**
Rewriting other AGENTS.md sections.

## P: Real-use feedback

**Mark:** –

**Reason:** Nothing is deployed, installed or vendored. The evidence verifies "vendored copies: none" and "container files: none", and reads no deploy workflow, health endpoint, installer tooling or copies of this build elsewhere. No dependents are named.

### Evidence

**Verified**
- "vendored copies: none" (git ls-files)
- "container files: none" (git ls-files)

**Read only**
- "deploy or release workflows: none", "installer tooling: none", "copies of this repo's build into another repo or site: none found" (.github/workflows, keyword scan)

### Gap

none

### Proposed issues

No issue: nothing is deployed, installed or vendored, so there is nothing to report back. Revisit if the tool is packaged or gains dependents.

## D: Defect ratchet

**Mark:** ✗

### Evidence

**Verified**
- "last 4 non-merge commits on main: 0 look like fixes, 0 of those touched a test file, 0 reverts". Zero known escapes, but no bug-hunt pass has looked for any, so this does not show the ratchet working. (git log)

**Read only**
- No bug-hunt pass, bug-hunt issue list or bug-report form appears in the evidence. Host defect evidence (issues, merged PRs) is unavailable because of --no-remote. It would have shown whether any defects were filed and traced. (defects section)

### Gap

- A word-splitting defect already on main, such as a miscount on CRLF or Unicode whitespace. Nothing has searched for it, and once found, nothing ties it to its introducing commit or requires a class-level check.
- A fix that patches one input and adds a single-case test, leaving the same class (other whitespace characters) open.

### Proposed issues

#### Run and record a dated bug-hunt pass on main

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
D needs a bug-hunt pass that finds at most 2 CI-catchable defects. None has been run. Git history shows 4 commits and no fixes, which only means nobody has looked.

**Want**
- `docs/bug-hunts/2026-11-16.md` (or the run date) lists each adversarial input tried against the tool at a named commit, each defect found, whether it is CI-catchable, and the commit that introduced it.
- Each defect becomes an entry in the issue list. The CI-catchable count is stated.

**Constraints**
- Do not fix defects in the same PR. Findings only.
- Attach the commands run and their output.

**Dependencies**
none

**Out of scope**
Fixing the defects found.

#### Add a bug-report template that asks for the introducing commit

Labels: tier:mechanical, ready, P2
Open decisions: none

**Problem**
Nothing asks a defect report to name the change that introduced it, so escapes cannot be traced back to the gate that let them through.

**Want**
- `docs/bug_report_template.md` asks for the introducing commit, the class of the defect and the class-level check the fix will add. AGENTS.md says that bug fixes link the introducing commit.

**Constraints**
- Docs-only change. Attach the diff.

**Dependencies**
none

**Out of scope**
Automating the trace with `git bisect`.
