# Run the baseline before trusting the README

**Rule:** Before changing a repo, run its build and tests yourself and record the result; do not take a README's or runbook's status as fact. Evidence row: [Baseline before changes; run commands, don't trust README (01)](../../EVIDENCE.md)

**Why:** A stale status line makes a failure that was already there look like one the change caused, or hides it.

**Incident:** A project's runbook reported a status that was no longer true, and an intentionally red test was explained only in its notes.

**Enforced by:** none

**Evidence:** hypothesis

**Status:** open
