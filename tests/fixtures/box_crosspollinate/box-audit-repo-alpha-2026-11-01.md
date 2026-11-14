# Box audit: repo-alpha (2026-11-01)

- Repo: repo-alpha at a1b2c3d4e5f6, default branch main
- Remote: example/repo-alpha
- Host evidence: available
- Judge: isolated: synthetic test card, no judge ran
- Score: `G ✓ · R ✓ · J ~ · W ~ · P – · D ~ → 8`
- Proven: 7.0

## Summary

A synthetic card for box-crosspollinate's tests. The repo, its evidence and its marks are invented.

## G: Enforced gate

**Mark:** ✓

### Evidence

**Verified**
- Required check `gate` on main blocks merging (api repos/example/repo-alpha/rules/branches/main)

**Read only**
- The gate runs `make check` on every pull request (.github/workflows/gate.yml:14)

### Gap

- A change to the gate workflow itself merges without a second reviewer.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## R: Real-thing tests

**Mark:** ✓

### Evidence

**Verified**
- The migration test ran against a populated Postgres service in the last 20 CI runs (CI run 812)

**Read only**
- `tests/test_migrations.py` loads a recorded production-shaped dump before migrating (tests/test_migrations.py:22)

### Gap

- A query that only fails on the production engine's collation passes the test database.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## J: Outside judge

**Mark:** ~

### Evidence

**Verified**
none

**Read only**
- A property test checks the parser round trip (tests/test_parser_props.py:5)

### Gap

- A wrong total that the code and its tests agree on passes every gate.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## W: Worker-runnable proof

**Mark:** ~

### Evidence

**Verified**
none

**Read only**
- AGENTS.md says to attach the gate output to each PR (AGENTS.md:30)

### Gap

- A PR without the proof it should attach still merges.

### Proposed issues

No issue: a synthetic test card proposes nothing.

## P: Real-use feedback

**Mark:** –

**Reason:** A command-line library with no deployment of its own.

### Evidence

none

### Gap

none

### Proposed issues

none

## D: Defect ratchet

**Mark:** ~

### Evidence

**Verified**
none

**Read only**
- Fix commits mostly touch tests (git log)

### Gap

- A fix without a regression test merges unflagged.

### Proposed issues

No issue: a synthetic test card proposes nothing.
