# A check that skips is not green

**Rule:** Treat a check that reports green while it skips its work, or runs no tests, as absent; make the gate fail when it ran nothing. Evidence row: [Read-only evidence scores partial at best; green-while-skipping is absent (per dimension)](../../EVIDENCE.md)

**Why:** A check that exits 0 without doing its work looks exactly like a pass.

**Incident:** A static-analysis job showed green on every PR because, without its token, it skipped the analysis and exited 0.

**Enforced by:** [Per dimension](../STANDARD.md#per-dimension); `tests/test_box_bootstrap.py::test_the_gate_passes_with_tests_and_fails_without`

**Evidence:** hypothesis

**Status:** enforced
