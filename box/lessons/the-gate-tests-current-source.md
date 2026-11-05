# The gate tests the current source, not stale bytecode

**Rule:** Make a red/green gate run the source as it is now, never a bytecode cache left from an earlier version of the file. Evidence row: [Gate must test current source despite stale bytecode (05)](../../EVIDENCE.md)

**Why:** A cache that matches the old file's size and timestamp is reused, so the gate judges code that is no longer there.

**Incident:** A fix that kept the file's size, written within the same timestamp second, was reported still red because the old bytecode ran.

**Enforced by:** `tests/test_red_green_gate.py::test_same_size_fix_in_same_timestamp_second`

**Evidence:** observed

**Status:** enforced
