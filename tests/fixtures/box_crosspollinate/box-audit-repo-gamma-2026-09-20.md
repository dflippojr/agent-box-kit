# Box audit: repo-gamma (2026-09-20)

- Repo: repo-gamma at c3d4e5f6a1b2, default branch main
- Remote: example/repo-gamma
- Host evidence: available
- Judge: isolated: synthetic test card, no judge ran
- Score: `G ~ · R ✗ · J ~ · W ✓ · P – · D ✓ → 8`
- Proven: 6.0

## Summary

A synthetic card for box-crosspollinate's tests. The repo, its evidence and its marks are invented.

## G: Enforced gate

**Mark:** ~

### Evidence

**Verified**
none

**Read only**
- The README asks contributors to run tests first (README.md:40)

### Gap

- A red PR merges because no check is required.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## R: Real-thing tests

**Mark:** ✗

### Evidence

**Verified**
none

**Read only**
- All tests mock the database (tests/test_store.py:1)

### Gap

- A migration that crashes on a populated database passes every gate.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## J: Outside judge

**Mark:** ~

### Evidence

**Verified**
none

**Read only**
- A JSON schema validates the export (schemas/export.json)

### Gap

- A wrong value of the right type passes the schema.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## W: Worker-runnable proof

**Mark:** ✓

### Evidence

**Verified**
- Workers attached `make proof` output on the last 6 PRs (CI run 77)

**Read only**
- AGENTS.md has a proving section (AGENTS.md:12)

### Gap

- A PR that skips the UI journey still attaches green proof.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## P: Real-use feedback

**Mark:** –

**Reason:** A library with no running service.

### Evidence

none

### Gap

none

### Proposed issues

none

## D: Defect ratchet

**Mark:** ✓

### Evidence

**Verified**
- Each of the last 8 fixes added a regression test that failed first (git log)

**Read only**
- The bug form asks for the introducing change (.github/ISSUE_TEMPLATE/bug.yml:10)

### Gap

- A defect class with no test template recurs in a new module.

### Proposed issues

No issue: a synthetic test card proposes nothing.
