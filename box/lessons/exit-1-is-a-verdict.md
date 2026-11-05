# Exit code 1 is a verdict, not an error

**Rule:** Where a script's exit 1 means a verdict such as "findings", make errors like a bad config exit 2. Evidence row: [A script's exit 1 is its verdict; a bad config or other error exits 2 (AGENTS.md, `agent-ready/scripts/`)](../../EVIDENCE.md)

**Why:** A caller that reads exit 1 as "findings" cannot tell a broken config from a real hit.

**Incident:** A script stopped with a message on a broken config, which exits 1, the code its docs gave for "secret found". Its own tests caught it.

**Enforced by:** `tests/test_secret_guard.py::test_invalid_config_values_exit_2_not_1`; `tests/test_secret_guard.py::test_bad_config_is_an_error_not_a_silent_pass`

**Evidence:** observed

**Status:** enforced
