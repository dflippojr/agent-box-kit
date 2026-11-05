# Lessons

One file per lesson learned building and running agent boxes, each tied to the check or rubric
line that stops it happening again. A note records what went wrong; a lesson here also says
whether anything now enforces it.

`EVIDENCE.md` stays the ledger of where each rule came from. A lesson's **Rule** links its row
there by the exact text of the row's first cell, and **Enforced by** names the check: a test or
script in this repo, a workflow, or a heading of [`STANDARD.md`](../STANDARD.md) that the box audit
scores. A lesson is `enforced` only when it names one; otherwise it is `open` and says `none`.

The seed lessons come from STANDARD.md's failure stories and `EVIDENCE.md`. Incidents are retold
generically.

## Adding a lesson

1. Copy [`TEMPLATE.md`](TEMPLATE.md) to a short, lowercase, hyphenated name.
2. Link the `EVIDENCE.md` row the rule comes from. If the rule has none, add the row first
   (AGENTS.md, "Adding a rule"); never move or delete one.
3. Name the check, or write `none` and mark it `open`. Writing the missing check is its own issue.
4. Add the lesson to the table below, and to **Open** if it is open. `python -m pytest tests -q`
   runs `tests/test_lessons.py`, which fails on a missing field, a value outside its set, a row
   that does not exist, a dead path, test name or anchor, a status that does not match its check,
   or a table that does not list exactly the lesson files.

## All lessons

| Lesson | Status | Enforced by |
|---|---|---|
| [A check that skips is not green](a-skipped-check-is-not-green.md) | enforced | [Per dimension](../STANDARD.md#per-dimension); `tests/test_box_bootstrap.py::test_the_gate_passes_with_tests_and_fails_without` |
| [A placeholder word does not hide a secret](a-placeholder-word-does-not-hide-a-secret.md) | enforced | `tests/test_secret_guard.py::test_placeholder_word_elsewhere_on_line_does_not_hide_a_real_secret` |
| [AGENTS.md says what proof to attach](agents-md-says-what-proof-to-attach.md) | enforced | [W: Worker-runnable proof](../STANDARD.md#w-worker-runnable-proof); `tests/test_box_audit.py::test_agents_md_without_proof_section_is_reported` |
| [Alarm when a deployed thing goes silent](alarm-on-silence.md) | enforced | [P: Real-use feedback](../STANDARD.md#p-real-use-feedback) |
| [An approval belongs to the head commit](approval-belongs-to-the-head-commit.md) | enforced | `tests/test_orchestrate.py::test_accept_label_applied_before_the_last_push_does_not_count`; `tests/test_box_bootstrap.py::test_ready_needs_the_owners_tag_for_a_gate_change` |
| [An outside oracle judges the core promise](an-outside-oracle-judges-the-core-promise.md) | enforced | [J: Outside judge](../STANDARD.md#j-outside-judge); `tests/test_box_audit.py::test_oracles_proof_rules_and_production` |
| [Exit code 1 is a verdict, not an error](exit-1-is-a-verdict.md) | enforced | `tests/test_secret_guard.py::test_invalid_config_values_exit_2_not_1`; `tests/test_secret_guard.py::test_bad_config_is_an_error_not_a_silent_pass` |
| [Flag a change that weakens the gate](flag-gate-weakening.md) | enforced | `tests/test_box_bootstrap.py::test_tamper_guard_flags_gate_weakening`; [G: Enforced gate](../STANDARD.md#g-enforced-gate) |
| [Never cancel a default-branch run](never-cancel-default-branch-runs.md) | enforced | `tests/test_box_bootstrap.py::test_the_gate_workflow_gives_each_default_branch_push_its_own_group`; `tests/test_box_audit.py::test_summarize_runs_flags_cancellations_reruns_and_flakes` |
| [Nothing writes to the default branch outside the gate](nothing-writes-to-the-default-branch-outside-the-gate.md) | enforced | [G: Enforced gate](../STANDARD.md#g-enforced-gate); `tests/test_box_bootstrap.py::test_the_work_is_on_a_new_branch_and_main_is_unchanged` |
| [Require checks on the head commit](required-checks-on-the-head-commit.md) | enforced | [G: Enforced gate](../STANDARD.md#g-enforced-gate); `tests/test_box_audit.py::test_no_rules_means_nothing_is_required` |
| [The gate refuses a dirty tree](the-gate-refuses-a-dirty-tree.md) | enforced | `tests/test_red_green_gate.py::test_dirty_tracked_tree_is_refused_and_left_untouched`; `tests/test_red_green_gate.py::test_staged_change_counts_as_dirty` |
| [The gate tests the current source, not stale bytecode](the-gate-tests-current-source.md) | enforced | `tests/test_red_green_gate.py::test_same_size_fix_in_same_timestamp_second` |
| [Trace each defect to the change that introduced it](trace-each-defect-to-its-change.md) | enforced | `tests/test_queue_fill.py::test_a_bad_finding_stops_the_run`; `tests/test_box_audit.py::test_only_a_named_introducing_change_counts_as_traced` |
| [Run the baseline before trusting the README](baseline-before-trusting-the-readme.md) | open | none |
| [Say what ran and what was only read](say-what-ran-and-what-was-only-read.md) | open | none |

## Open

Nothing enforces these yet. Each needs its own issue for the check.

- [Run the baseline before trusting the README](baseline-before-trusting-the-readme.md)
- [Say what ran and what was only read](say-what-ran-and-what-was-only-read.md)
