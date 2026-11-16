# Box audit: sample-lib (2026-11-16)

- Repo: sample-lib at 08e781a93d6b, default branch main
- Remote: none
- Host evidence: unavailable (no remote)
- Judge: isolated: fresh session started by the harness from prompt.md only; probe not run
- Score: `G ✗ · R ✗ · J ✗ · W ~ · P – · D ✗ → 5`
- Proven: 1.0

## Summary

sample-lib scores 5: only W is partial, P is n/a for an undeployed library, and G, R, J and D are absent. There is no CI, no `ready` script, no outside oracle and no defect record. AGENTS.md names a test command and a definition of done, but nothing runs it as a gate. The change that would raise the score most is a `ready` script that runs the full gate on the head commit and refuses tampering. With no hosted VCS, that script is the only thing that can make G meet the bar, and W, J and R checks would plug into it.

## G: Enforced gate

**Mark:** ✗

### Evidence

**Verified**
- "no CI configuration found" (git ls-files)
- "no one-command local gate found (Makefile, package.json, justfile, scripts/ready*, scripts/ci*, tox.ini, noxfile.py)" (git ls-files)
- "Remote: none (host evidence unavailable: no remote)". Without a host there is no branch protection to read. Host evidence would have settled whether any check is required, whether default-branch runs get cancelled, and who applied approval labels. Here none of those can exist without a host or a `ready` script. (git remote)

**Read only**
- AGENTS.md has a "Definition of done": "Tests pass with visible output; diff is minimal and in scope; you have stated what you did not run or verify." That is an instruction to the worker, not an enforced check. (AGENTS.md, "Definition of done" section)

### Gap

- A change that breaks `tests/test_wordcount.py` can be committed and merged to main. Nothing runs the tests before the merge.
- A change that deletes or skips the only test file goes to main with no flag and no owner approval.
- A worker can report "tests pass" without running them. No mechanical check compares the claim with the head commit.

### Proposed issues

#### Add a ready script that runs the gate on the head commit

Labels: tier:standard, ready, P0
Open decisions: none

**Problem**
The repo has no remote, no CI and no one-command gate (verified: "no CI configuration found", "no one-command local gate found"). Nothing stops a red change from reaching main.

**Want**
- `scripts/ready` exists. It checks out or verifies the head commit of the branch being merged, runs `python3 -m pytest -q`, and exits non-zero on any failure.
- The script refuses to run, and exits non-zero, when the working tree has uncommitted changes, so the commit it judges is the one that merges.
- AGENTS.md says merges to main go only through `scripts/ready` with exit 0. It records that no hosted VCS enforces this.
- A test or a recorded demo shows the script exiting non-zero on a branch with a failing test and zero on a clean one.

**Constraints**
- Do not change `src/wordcount` behaviour.
- Attach the output of both the red run and the green run to the PR.

**Dependencies**
none

**Out of scope**
Choosing a host and setting up hosted CI.

#### Add a tamper guard that flags test deletions and gate edits

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
Nothing flags a change that deletes or skips tests, adds retries, or edits gate config. With no CI there is not even a diff review step.

**Want**
- `scripts/tamper_guard` compares the branch with main. It exits non-zero and lists the reasons when a test file is deleted, when `skip`/`xfail` markers or retry decorators are added, or when `scripts/ready`, `pyproject.toml` test settings or AGENTS.md gate text change.
- An override needs an explicit owner marker, such as a signed tag naming the head commit, documented in AGENTS.md.
- Tests cover each trigger with a fixture branch or diff.

**Constraints**
- Keep it a standalone script that `scripts/ready` can call. Put the tests under `tests/`.
- Attach the guard's output on a diff that deletes a test.

**Dependencies**
none

**Out of scope**
Moving the guard outside the repo so a PR cannot edit it (a 10 need).

#### Choose a host and require the gate on the head commit

Labels: tier:frontier, needs-refinement, P2
Open decisions: Which host will hold the repo, if any? Will the owner accept the local `ready` script as the permanent gate instead?

**Problem**
With no remote, branch protection and required checks cannot exist (host evidence unavailable: no remote). The gate depends on the person who merges choosing to run a script.

**Want**
- Either the repo is pushed to a host, with one always-run CI job required on main and on the head commit, or AGENTS.md records the decision to stay local and names the `ready` script as the gate.
- If hosted, the protection settings read back from the host API show the required check.

**Constraints**
- Do not add automation that writes to main outside the gate.

**Dependencies**
none

**Out of scope**
SonarCloud or other static analysis.

## R: Real-thing tests

**Mark:** ✗

### Evidence

**Verified**
- 6 tracked files: .md 2, .py 2, .toml 1. The source is one small Python package with one test file. (git ls-files)
- "no CI configuration found", so no test runs on any OS automatically. (git ls-files)

**Read only**
- "1 test files: plain unit 1", example `tests/test_wordcount.py`. This comes from a keyword scan. I give it moderate weight for the count and low weight for what the test exercises. (keyword scan)
- "product shape guess: library or tool". This is derived, not observed. (derived)

### Gap

- If wordcount reads files or stdin, a file in a non-UTF-8 encoding, with CRLF line endings, or larger than memory can crash it or miscount. The one plain unit test may never touch a real file.
- A Windows or macOS user hits a platform difference, such as line endings or the default encoding, that no test run on that OS would reveal, because no test runs on any OS automatically.

I did not mark R n/a. The evidence does not show that wordcount touches nothing beyond the Python runtime. And the standard asks even an n/a library to be tested on each OS its users run, and that part is absent.

### Proposed issues

#### Test wordcount against real files on disk

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
The only test is one plain unit test found by keyword scan. Nothing shows wordcount exercised against real files, encodings or line endings.

**Want**
- `tests/test_files.py` writes real temporary files: UTF-8, UTF-8 with BOM, Latin-1, CRLF, empty, and one larger than 10 MB. It asserts the count for each file, or the documented error.
- AGENTS.md or `docs/testing.md` lists wordcount's outside dependencies (filesystem, stdin, encodings) and which tests cover each.

**Constraints**
- Use `tmp_path`. Do not use mocked file objects for these cases.
- Attach the pytest output.

**Dependencies**
none

**Out of scope**
Performance tuning for large files.

#### Run the test suite on each OS users run

Labels: tier:standard, needs-refinement, P2
Open decisions: Which operating systems and Python versions do users run? Where do the runs happen without a hosted CI?

**Problem**
No test runs automatically on any OS (no CI configuration found).

**Want**
- The supported OS and Python versions are written in AGENTS.md.
- A recorded run of `python3 -m pytest -q` on each supported OS and Python version is attached, and the way to repeat it is documented.

**Constraints**
- Pin the Python versions that users run.

**Dependencies**
none

**Out of scope**
Packaging and installers.

## J: Outside judge

**Mark:** ✗

### Evidence

**Verified**
none

**Read only**
- "no candidate outside oracle found by name or keyword". This comes from a keyword scan, so I give it moderate weight. With only six tracked files, a missed oracle is unlikely. (keyword scan)
- Core promise, inferred from the project name and the test path: given text, report its word count correctly. The repo states no oracle for it. (AGENTS.md, "What this project is" heading; tests/test_wordcount.py)

### Gap

- A change in how wordcount splits words, such as on tabs, non-breaking spaces, Unicode whitespace or hyphens, passes every test as long as the author updates the expected values to match the new output.
- Expected counts written by the same agent that wrote the splitter share its wrong idea of what a word is.

### Proposed issues

#### Compare wordcount against a reference word counter

Labels: tier:standard, needs-refinement, P1
Open decisions: Which reference defines a word for this project: `wc -w` (POSIX whitespace) or Python's `str.split()`? How should inputs where the two disagree be handled?

**Problem**
No outside oracle checks the core promise (keyword scan found none). Every expected count was written by the author.

**Want**
- A property test generates random text and asserts that wordcount's count equals the chosen reference's count on every input.
- The test runs as part of `python3 -m pytest -q`, so the local gate runs it on every change.
- Known, intended divergences are listed in the test with the reason.

**Constraints**
- The reference must be code the author did not write.
- Attach the test's output and the number of generated cases.

**Dependencies**
none

**Out of scope**
Model-based judges.

## W: Worker-runnable proof

**Mark:** ~

### Evidence

**Verified**
- Instruction file present: AGENTS.md. (git ls-files)
- "no one-command local gate found". The only command is the pytest line in AGENTS.md. (git ls-files)
- "verify skill or UI-testing contract: none found". The product has no UI, so no verify skill is needed. (git ls-files)
- "docs layer: none of docs/architecture, data-model, runtime, testing" (git ls-files)

**Read only**
- "## How to verify a change / - src/wordcount: `python3 -m pytest -q`" (AGENTS.md, "How to verify a change" section)
- "## Definition of done / Tests pass with visible output; diff is minimal and in scope; you have stated what you did not run or verify." This names some evidence, but there is no proof format or required attachment. (AGENTS.md, "Definition of done" section)
- "workflows that read the PR body for proof: none" (keyword scan)

### Gap

- A worker attaches a one-line "tests pass" with no output, and nothing rejects it.
- A worker runs pytest from a stale or dirty working tree, and the evidence does not match the commit being merged.

### Proposed issues

#### Add a proof section to AGENTS.md

Labels: tier:mechanical, ready, P1
Open decisions: none

**Problem**
AGENTS.md gives a test command and a definition of done but no required evidence format (read: "Tests pass with visible output…"). Each worker can attach different proof or none.

**Want**
- AGENTS.md has a "Proof to attach" section. It requires the full output of the one gate command at the head commit, the commit SHA it ran on, one row per acceptance criterion, and a "Not verified" list.
- The section names `scripts/ready` as the one command once that script exists, and `python3 -m pytest -q` until then.

**Constraints**
- Keep AGENTS.md a router: link to deeper docs instead of growing it past a screen.

**Dependencies**
none

**Out of scope**
A mechanical PR-body lint (a 10 need).

## P: Real-use feedback

**Mark:** –

**Reason:** sample-lib looks like a library or tool that is not deployed, ships no installer and vendors nothing. No copies of its build into another repo or site were found. With no remote, I could not check for known dependents.

### Evidence

**Verified**
- "container files: none", "vendored copies: none" (git ls-files)

**Read only**
- "health or version endpoints in source: none found", "deploy or release workflows: none", "installer tooling: none", "copies of this repo's build into another repo or site: none found" (keyword scan)

### Gap

none

### Proposed issues

none

## D: Defect ratchet

**Mark:** ✗

### Evidence

**Verified**
- "last 1 non-merge commits on main: 0 look like fixes, 0 of those touched a test file, 0 reverts". The history is 2 commits. (git log)
- Host evidence unavailable (no remote): the issue list, merged PRs and CI history would have shown escaped defects and any bug-hunt passes. None can be checked.

**Read only**
none

### Gap

- A defect found later, such as a miscount on Unicode whitespace, gets a one-instance fix. No record traces it to the introducing commit, and no class-level test is added, so the same class of input-handling bug can come back.
- No bug-hunt pass has ever run, so the count of CI-catchable escapes is unknown.

### Proposed issues

#### Run a dated bug-hunt pass on main and record each finding

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
No bug-hunt pass is recorded. The history shows no fixes (git log), so nobody knows how many CI-catchable defects sit on main.

**Want**
- `docs/bug-hunts/2026-11-<dd>.md` records the date, the commit hunted, the method, and each finding with whether it is CI-catchable.
- Each finding is filed as a tracked item with a failing test where possible.

**Constraints**
- The hunter must not be the session that wrote the code under test.
- Do not fix the findings in the same PR.

**Dependencies**
none

**Out of scope**
Fixing the findings.

#### Add a defect ledger that traces each fix to its introducing commit

Labels: tier:mechanical, ready, P2
Open decisions: none

**Problem**
Nothing records where escaped defects came from or which class-level check their fix added.

**Want**
- `docs/defects.md` has a table: defect, introducing commit, fixing commit, and the class-level check added (a property test, an invariant or a lint rule).
- AGENTS.md says every bug fix adds a row and a test that fails on the base commit.

**Constraints**
- Documentation and AGENTS.md only. No code changes.

**Dependencies**
none

**Out of scope**
Automating the ledger.
