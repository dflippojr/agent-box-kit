# Trace each defect to the change that introduced it

**Rule:** Record, for every escaped defect, the change that introduced it; a finding without one is not filed. Evidence row: [A bug-hunt finding has a `Bug hunt:` title, the `bug` label, and `Found by`, `Introducing change` and `CI-catchable` lines; one run files one pass (`hunt.py`)](../../EVIDENCE.md)

**Why:** Without the introducing change nobody can tell which gate let the defect through, so no gate gets stronger.

**Incident:** Several hundred bug-hunt issues were filed and none was traced back to the change that caused it.

**Enforced by:** `tests/test_queue_fill.py::test_a_bad_finding_stops_the_run`; `tests/test_box_audit.py::test_only_a_named_introducing_change_counts_as_traced`

**Evidence:** observed

**Status:** enforced
