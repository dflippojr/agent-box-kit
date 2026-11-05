# An approval belongs to the head commit

**Rule:** Count an owner-only approval only when the owner gave it after the head commit was pushed; a new push clears it. Evidence row: [An owner-only label counts only when the owner applied it after the head commit was pushed, timed by push activity, not the commit date (handoff, `handoff_check.py`)](../../EVIDENCE.md)

**Why:** An approval that outlives a push approves code the owner never saw.

**Incident:** An approval label stayed on a PR after more commits were pushed, so code the owner never saw counted as approved.

**Enforced by:** `tests/test_orchestrate.py::test_accept_label_applied_before_the_last_push_does_not_count`; `tests/test_box_bootstrap.py::test_ready_needs_the_owners_tag_for_a_gate_change`

**Evidence:** asserted

**Status:** enforced
