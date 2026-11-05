# Flag a change that weakens the gate

**Rule:** Flag any change that deletes or skips tests, adds retries, or edits gate config such as workflows, coverage floors or static-analysis settings, and let it pass only with the owner's approval. Evidence row: [A tamper guard flags a change that deletes or skips tests, adds retries or edits gate config, and only the owner's approval passes it (STANDARD.md G, `templates/scripts/tamper_guard.py`)](../../EVIDENCE.md)

**Why:** The change being judged can otherwise lower the bar it is judged by, and the gate accepts it.

**Incident:** A coverage floor was lowered in passing during an unrelated change, and the gate accepted it.

**Enforced by:** `tests/test_box_bootstrap.py::test_tamper_guard_flags_gate_weakening`; [G: Enforced gate](../STANDARD.md#g-enforced-gate)

**Evidence:** observed

**Status:** enforced
