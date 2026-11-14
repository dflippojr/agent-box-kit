# Box audit: repo-beta (2026-11-05)

- Repo: repo-beta at b2c3d4e5f6a1, default branch main
- Remote: example/repo-beta
- Host evidence: available
- Judge: isolated: synthetic test card, no judge ran
- Score: `G ✓ · R ~ · J ✓ · W ★ · P ~ · D ✗ → 8`
- Proven: 6.7

## Summary

A synthetic card for box-crosspollinate's tests. The repo, its evidence and its marks are invented.

## G: Enforced gate

**Mark:** ✓

### Evidence

**Verified**
- Ruleset `protect-main` requires `gate` and a pull request (api repos/example/repo-beta/rulesets)

**Read only**
- The gate workflow runs the full suite (.github/workflows/gate.yml:9)

### Gap

- A gate workflow change can merge on the author's own approval.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## R: Real-thing tests

**Mark:** ~

### Evidence

**Verified**
none

**Read only**
- Integration tests use an in-memory fake of the queue (tests/test_queue.py:3)

### Gap

- A message the real broker rejects for size passes the fake.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## J: Outside judge

**Mark:** ✓

### Evidence

**Verified**
- An independent review workflow ran on the last 15 merged PRs (CI run 455)

**Read only**
- Golden files for the report renderer are checked in (tests/golden/report.txt; tests/test_golden.py:12)

### Gap

- A golden file regenerated with the bug in it passes.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## W: Worker-runnable proof

**Mark:** ★

### Evidence

**Verified**
- A worker ran `scripts/verify.py` from a fresh clone and attached its output on 9 of 9 PRs (CI run 460)

**Read only**
- `docs/testing.md` gives the one command and its expected output (docs/testing.md:4)

### Gap

- none: every applicable case is covered

### Proposed issues


## P: Real-use feedback

**Mark:** ~

### Evidence

**Verified**
none

**Read only**
- A health endpoint is defined (src/app/health.py:8)

### Gap

- An outage at night is noticed only when a user reports it.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## D: Defect ratchet

**Mark:** ✗

### Evidence

**Verified**
none

**Read only**
- No defect label exists (git log)

### Gap

- The same bug can return with no test to catch it.

### Proposed issues

No issue: a synthetic test card proposes nothing.
