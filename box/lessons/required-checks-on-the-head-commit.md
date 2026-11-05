# Require checks on the head commit

**Rule:** Make every merge need the gate's checks to pass on the exact head commit, enforced by the host or by a `ready` script that every merge goes through. Evidence row: ["9 needs" bar per dimension (each dimension)](../../EVIDENCE.md)

**Why:** A check nobody is required to pass is a suggestion. Green then means nothing, because red never stopped anything.

**Incident:** CI had never once been red, yet a separate reviewer found about 40 defects at green heads. Nothing was required to merge.

**Enforced by:** [G: Enforced gate](../STANDARD.md#g-enforced-gate); `tests/test_box_audit.py::test_no_rules_means_nothing_is_required`

**Evidence:** observed

**Status:** enforced
