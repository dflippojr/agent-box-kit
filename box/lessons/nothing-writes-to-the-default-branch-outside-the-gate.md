# Nothing writes to the default branch outside the gate

**Rule:** Let no automation push to the default branch outside the gate, docs bots and release jobs included; tooling works on a branch and opens a change. Evidence row: ["10 needs" for G, R, J, W, P (each dimension)](../../EVIDENCE.md)

**Why:** A direct push changes the default branch without running the checks that every other change must pass.

**Incident:** A docs-regeneration job pushed straight to the default branch, so it changed it without running the gate.

**Enforced by:** [G: Enforced gate](../STANDARD.md#g-enforced-gate); `tests/test_box_bootstrap.py::test_the_work_is_on_a_new_branch_and_main_is_unchanged`

**Evidence:** hypothesis

**Status:** enforced
