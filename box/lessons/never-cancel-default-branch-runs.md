# Never cancel a default-branch run

**Rule:** Give every push to the default branch its own CI run that a newer push cannot cancel; only a PR's runs may share a concurrency group. Evidence row: [`gate.yml` gives each default-branch push its own concurrency group (its commit); only a PR's runs share one (`templates/github/gate.yml`)](../../EVIDENCE.md)

**Why:** A cancelled run reports no result, so a broken merge hides under the next commit.

**Incident:** Every push to the default branch cancelled the run before it. A broken merge sat under a newer commit whose run was also cancelled, and nobody saw a red result.

**Enforced by:** `tests/test_box_bootstrap.py::test_the_gate_workflow_gives_each_default_branch_push_its_own_group`; `tests/test_box_audit.py::test_summarize_runs_flags_cancellations_reruns_and_flakes`

**Evidence:** asserted

**Status:** enforced
