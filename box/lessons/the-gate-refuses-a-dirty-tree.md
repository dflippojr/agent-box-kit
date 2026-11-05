# The gate refuses a dirty tree

**Rule:** Refuse to run a red/green gate on a working tree with uncommitted tracked changes, and leave the tree as it was. Evidence row: [Gate must assert clean tree (05)](../../EVIDENCE.md)

**Why:** Leftover edits change what the red step runs, so the verdict describes a tree nobody committed.

**Incident:** A half-reverted patch gave a false red during a demonstration.

**Enforced by:** `tests/test_red_green_gate.py::test_dirty_tracked_tree_is_refused_and_left_untouched`; `tests/test_red_green_gate.py::test_staged_change_counts_as_dirty`

**Evidence:** asserted

**Status:** enforced
