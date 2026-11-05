# AGENTS.md says what proof to attach

**Rule:** Give AGENTS.md a section on how to prove a change works and what evidence to attach to it. Evidence row: ["9 needs" bar per dimension (each dimension)](../../EVIDENCE.md)

**Why:** Without a stated proof, each worker attaches different evidence or none, and the reviewer cannot tell what was checked.

**Incident:** A repo's AGENTS.md had no proof section, and its workers' PRs carried different evidence or none.

**Enforced by:** [W: Worker-runnable proof](../STANDARD.md#w-worker-runnable-proof); `tests/test_box_audit.py::test_agents_md_without_proof_section_is_reported`

**Evidence:** observed

**Status:** enforced
