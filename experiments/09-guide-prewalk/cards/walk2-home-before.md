# Box audit: sample-lib (2026-11-16)

- Repo: sample-lib at 6de3778b079e, default branch main
- Remote: none
- Host evidence: unavailable (no remote)
- Judge: isolated: fresh session started by the walker harness from prompt.md only; probe not run
- Score: `G ✗ · R ✗ · J ✗ · W ~ · P – · D ✗ → 5`
- Proven: 1.0

## Summary

sample-lib scores 5 (Proven 1.0). The only working part is W, and only partly: AGENTS.md names a test command and a definition of done. P is n/a for a library that is not deployed. G, R, J and D are absent. There is no CI, no ready script, no outside oracle and no bug-hunt record, and the repo has no remote, so no host enforcement could be checked. The change that would raise the score most is a local `ready` script that runs the gate on the head commit and that every merge must go through. G, J and D can all be built on top of it.

## G: Enforced gate

**Mark:** ✗

### Evidence

**Verified**
- "no CI configuration found" (source: git ls-files)
- "no one-command local gate found (Makefile, package.json, justfile, scripts/ready*, scripts/ci*, tox.ini, noxfile.py)" (source: git ls-files)
- "Remote: none (host evidence unavailable: no remote)". Branch protection, required checks, run cancellation and owner-label history could not be read. Host evidence would have settled whether any merge gate exists outside the repo. (source: git remote)

**Read only**
- AGENTS.md has a "Definition of done" ("Tests pass with visible output; diff is minimal and in scope"), but nothing enforces it at merge time. (AGENTS.md, "Definition of done" section; the evidence gives no line number)

### Gap

- A commit that breaks word counting can land on main, because no check runs before a merge and nothing requires one.
- A change that deletes `tests/test_wordcount.py`, or adds `pytest.mark.skip` to it, merges unflagged, because nothing compares the test set against the base branch.
- A worker can commit straight to main under the owner's git identity, and nothing tells that apart from an owner decision.

### Proposed issues

#### Add a ready script that runs the gate on the head commit and gates every merge

Labels: tier:standard, ready, P0
Open decisions: none

**Problem**
The repo has no remote, no CI configuration and no one-command local gate (git ls-files). Nothing runs the tests before a merge to main, so green has no meaning and red cannot block anything.

**Want**
- `scripts/ready` exists. It refuses to run on a dirty working tree, prints the head commit SHA, runs `python3 -m pytest -q`, and exits non-zero if any test fails.
- A test that is deliberately broken on a branch makes `scripts/ready` exit non-zero. Attach the transcript to the PR.
- AGENTS.md states that merges to main happen only after `scripts/ready` exits 0 on the head commit being merged.
- AGENTS.md records the gap: with no hosted VCS, enforcement depends on the person merging running the script.

**Constraints**
- Do not change `src/wordcount` behaviour.
- The script runs from a command line with only Python and git.
- Put a test of the script's exit codes under `tests/`.
- Attach one green run and one red run to the PR.

**Dependencies**
none

**Out of scope**
Setting up a hosted remote and CI. That is a separate decision for the owner.

#### Add a tamper guard that flags gate and test weakening against the base branch

Labels: tier:frontier, ready, review:security, P1
Open decisions: none

**Problem**
Nothing detects a change that deletes tests, adds skips or retries, or edits gate configuration such as pytest settings in `pyproject.toml` or the gate script itself. A worker could weaken its own judge and still report done.

**Want**
- `scripts/tamper_guard.py BASE HEAD` exits non-zero and lists each finding for a diff that does any of these: deletes or renames a test file; removes a test function; adds `skip`, `xfail` or retry markers; edits `scripts/ready*`, `scripts/tamper_guard.py` or the pytest and coverage sections of `pyproject.toml`.
- The guard passes only if the owner has made an annotated git tag, `gate-approved/<HEAD sha>`, naming that exact head commit. A tag on an older commit does not count.
- Tests under `tests/` cover each finding type, and cover a stale approval tag being rejected.

**Constraints**
- The guard is standalone, so the ready script can call it once that script exists.
- The guard takes the base and head commits as arguments and never trusts a list of files supplied by the PR.
- Attach the guard's output on a branch that deletes a test.

**Dependencies**
none

**Out of scope**
Moving the guard outside the repo so a PR cannot edit it. That is a 10-level need.

## R: Real-thing tests

**Mark:** ✗

### Evidence

**Verified**
- none. With no CI and no recorded runs, no test run could be observed. CI run history was unavailable (no remote).

**Read only**
- "1 test files: plain unit 1", example `tests/test_wordcount.py`. This is a keyword scan, and it does not say whether the test reads real files or in-memory strings. I give it little weight. (tests/test_wordcount.py)
- "product shape guess: library or tool". The evidence does not show what the product touches beyond the Python runtime, such as the filesystem, stdin or text encodings, so R cannot be marked n/a. Even if it could, each OS users run would still need testing. (derived production evidence)

### Gap

- Counting a real file that has CRLF line endings, a BOM or non-UTF-8 bytes could crash or miscount while every test passes, if the tests feed only in-memory strings.
- A Python version or OS that users run but the author never ran (for example Windows, or an older 3.x that `pyproject.toml` claims to support) could break unseen, because tests run in one place and only by hand.

### Proposed issues

#### Test wordcount against real files on disk

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
The one test file is classed as plain unit (keyword scan), and nothing shows the counting path meeting real files. File reading and decoding are the riskiest paths for a word-count tool.

**Want**
- Tests write real temporary files and count them through the public entry point. The files cover an empty file, CRLF and LF endings, a UTF-8 BOM, non-UTF-8 bytes and a file larger than 10 MB.
- Each case asserts either a count or a documented error, never a crash with a traceback.
- `python3 -m pytest -q` runs the new tests. Attach the output to the PR.

**Constraints**
- Use pytest's `tmp_path`. Write nothing outside it.
- Do not mock `open` or the filesystem.
- Change source only where a new test exposes a defect, and call that out in the PR.

**Dependencies**
none

**Out of scope**
Performance tuning for large files.

#### Run the tests on every supported Python version and OS

Labels: tier:standard, needs-refinement
Open decisions: Which Python versions and operating systems are supported? Where should the matrix run, given there is no remote: local tox/nox, or hosted CI once a remote exists?

**Problem**
Nothing records which Python versions or OSes the product supports, or that the tests ran on any of them. Supported-version breakage would pass every gate.

**Want**
- The supported versions and OSes are written in `pyproject.toml` (`requires-python`) and in AGENTS.md.
- One command runs the suite on each supported Python version, and its output for every version is attached to the PR.

**Constraints**
- Do not raise `requires-python` to dodge a failure without the owner's agreement.

**Dependencies**
none

**Out of scope**
Packaging and publishing releases.

## J: Outside judge

**Mark:** ✗

### Evidence

**Verified**
- none. CI runs were unavailable (no remote), so no scheduled or per-PR judge could be observed.

**Read only**
- "no candidate outside oracle found by name or keyword" (keyword scan)
- Core promise, inferred from the name: given text, report the correct word count. No check of that promise comes from anyone but the author, as far as the evidence shows. (AGENTS.md, "What this project is" heading)

### Gap

- Counting rules can be wrong while every test passes, because the expected counts come from the same author as the code. Examples: hyphenated words, punctuation-only tokens, tabs, non-breaking spaces and other Unicode whitespace.

### Proposed issues

#### Add a differential test of word counts against an independent reference

Labels: tier:standard, needs-refinement, P1
Open decisions: Should wordcount match `wc -w` (whitespace-delimited words) exactly, or follow its own documented definition, in which case who writes the reference corpus of expected counts?

**Problem**
No oracle the author did not write checks the core promise. Every expected count in the tests was written by the code's author.

**Want**
- A test compares wordcount's output with an independent reference on a corpus of at least 20 files. The corpus covers ASCII, Unicode whitespace, punctuation, empty input and very long lines. The reference is either `wc -w` or counts written by someone other than the author, depending on the decision above.
- Every documented divergence from the reference is listed with its reason in the test file. Any other divergence fails the test.
- The test runs as part of the one gate command, so it runs before every merge.

**Constraints**
- The corpus lives under `tests/`, and its source and capture date are recorded.
- If `wc` is the reference, skip only where `wc` is absent, and print the skip loudly so the gate output shows it.

**Dependencies**
none

**Out of scope**
Character and line counts.

## W: Worker-runnable proof

**Mark:** ~

### Evidence

**Verified**
- "no one-command local gate found" (source: git ls-files)
- "verify skill or UI-testing contract: none found". The product has no UI, so a verify skill is not required. (source: git ls-files)
- "docs layer: none of docs/architecture, data-model, runtime, testing" (source: git ls-files)

**Read only**
- AGENTS.md "How to verify a change": "src/wordcount: `python3 -m pytest -q`". With no CI, this one command is in effect the whole gate. I did not run it on a clean checkout. (AGENTS.md, "How to verify a change" section)
- AGENTS.md "Definition of done": "Tests pass with visible output; diff is minimal and in scope; you have stated what you did not run or verify." This names some proof to attach, but not the head commit or a per-criterion table. (AGENTS.md, "Definition of done" section)
- "workflows that read the PR body for proof: none" (keyword scan)

### Gap

- A worker can report done with pasted pytest output from a different commit, or from a tree with uncommitted changes. Nothing ties the proof to the head commit or checks the report.
- The documented command may fail on a clean checkout, for example because pytest or the package itself is not installed and no setup step is documented. A worker's "tests pass" claim could then rest on a machine-specific environment.

### Proposed issues

#### Add a proof section to AGENTS.md naming the evidence each change attaches

Labels: tier:mechanical, ready, P1
Open decisions: none

**Problem**
AGENTS.md says to run `python3 -m pytest -q` and to show visible output. It does not say what to attach: the head commit, one row per acceptance criterion, a "not verified" section, or any gate changes.

**Want**
- AGENTS.md has a "Proof to attach" section listing: the head commit SHA; the full gate command output; a table with one row per acceptance criterion; a "not verified" section; and a "gate changes" section, written as `none` when there are none.
- A test under `tests/` fails if that section or any listed item is missing from AGENTS.md.

**Constraints**
- Keep AGENTS.md a router. Put long guidance in a linked doc, not inline.

**Dependencies**
none

**Out of scope**
Linting PR bodies on a host. There is no remote.

#### Document a clean-checkout setup so the gate command runs anywhere

Labels: tier:standard, ready, P2
Open decisions: none

**Problem**
Nothing shows that `python3 -m pytest -q` works on a fresh clone. No setup step or test dependency declaration appears in the evidence.

**Want**
- `pyproject.toml` declares test dependencies, for example a `test` extra containing pytest.
- AGENTS.md gives the exact commands from a fresh clone to a green gate run.
- The PR attaches a transcript of those commands, in a new virtual environment on a fresh clone, ending with the test summary.

**Constraints**
- Do not add runtime dependencies to the library.

**Dependencies**
none

**Out of scope**
Containerising the development environment.

## P: Real-use feedback

**Mark:** –

**Reason:** sample-lib appears to be a library or tool. It is not deployed, ships no installer and vendors nothing, and no copy of its build into another repo or site was found. Known dependents and published releases could not be checked because host evidence is unavailable (no remote).

### Evidence

**Verified**
- "container files: none" (source: git ls-files)
- "vendored copies: none" (source: git ls-files)

**Read only**
- "health or version endpoints in source: none found"; "deploy or release workflows: none"; "installer tooling: none" (keyword scan)
- "copies of this repo's build into another repo or site: none found" (git ls-files + keyword scan)

### Gap

none

### Proposed issues

none

## D: Defect ratchet

**Mark:** ✗

### Evidence

**Verified**
- "last 1 non-merge commits on main: 0 look like fixes, 0 of those touched a test file, 0 reverts" (source: git log)
- Merged PRs and defect issues were unavailable (no remote). Host evidence would have shown whether any escaped defect was traced to an introducing change.

**Read only**
- No bug-hunt pass, defect log or bug-report form appears in the tracked files (6 tracked files; git ls-files).

### Gap

- A defect fixed with a one-instance patch and no test can recur in the same class. For example, after fixing a miscount for one punctuation character, the same bug reappears for another, because nothing requires a class-level check or traces the fix to its cause.
- With no bug-hunt pass on record, the number of CI-catchable escapes is unknown, so the "at most 2" bar cannot be shown.

### Proposed issues

#### Run and record a dated bug-hunt pass on main

Labels: tier:standard, ready, P1
Open decisions: none

**Problem**
No bug-hunt pass has ever been recorded, so the repo cannot show how many CI-catchable defects reach main.

**Want**
- `docs/bug-hunts/2026-11-16.md` (or the date of the pass) lists each finding with: a reproduction, whether it is CI-catchable and why, and the commit that introduced it, found with git log or bisect.
- Each finding is also filed as an issue, or as an entry in the issue list the owner reads.
- The file ends with the count of CI-catchable escapes.

**Constraints**
- Search adversarially against the default branch head, and name that commit in the file.
- Fix nothing in this PR. Fixes are separate issues.

**Dependencies**
none

**Out of scope**
Fixing the findings.

#### Require every fix to name its introducing commit and add a class-level test

Labels: tier:standard, ready, P2
Open decisions: none

**Problem**
Nothing requires a fix to trace its defect to the change that introduced it, or to add a check that catches the whole class. Git history has no fix commits yet, so the rule can be set before the first one.

**Want**
- AGENTS.md states that a fix commit names its introducing commit (`Introduced-by: <sha>`) and adds or changes a test that covers the defect's class, such as a parametrised or property-based test, not just the one input.
- A check run by the gate command fails when a commit whose message starts with `fix` has no `Introduced-by:` trailer or touches no file under `tests/`. Tests cover both cases.

**Constraints**
- The check reads commit messages and diffs from git, not from text the worker supplies.

**Dependencies**
none

**Out of scope**
Rewriting past commit messages.
