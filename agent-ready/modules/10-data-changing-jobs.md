# 10 — Data-changing and scheduled jobs

Applies to any script or service that modifies stored data (database records, files, external
systems) or runs unattended on a schedule. A bug here does not just fail a test; it can quietly
corrupt real data, repeatedly, on a timer. Treat every job like this as risky (see 02) and give the
owner a chance to review before it touches anything real.

**Evidence note:** these rules are general engineering practice for data jobs. They are **not**
derived from the source projects, so they are `hypothesis` in the playbook's evidence notes.
Only the rollout staging and the dry-run/shadow idea echo patterns from 04 and 07. Check them
against your organization's own standards.

## Access and environments

- **The agent works against a development or staging database, or a disposable copy, never
  production.** Do not give an agent production write credentials. If it needs production data
  shape, ask the owner for a read-only, bounded extract or a sanitized copy.
- The owner (not the agent) runs anything against production, after reading the dry-run output.
- Configuration comes from environment variables. The job must **refuse to run when the target
  environment is unspecified or ambiguous**, and require an explicit extra flag to touch production.
- Never put connection strings or credentials in code, fixtures or logs (see 04).

## Define the job before writing it

Fill in `templates/DATA-JOB-SPEC.md` first. It forces the decisions that cause incidents:

- **Selection:** exactly which records, by what criteria, and the expected count.
- **Change:** exactly what changes, and why. Old value to new value, stated precisely.
- **Idempotency:** how a second run (or a re-run after a partial failure) avoids repeating or
  worsening the change.
- **Limits:** batch size, maximum rows per run, and what count triggers an abort.
- **Rollback:** how to undo a bad run.
- **Schedule:** when, what timezone, what happens if a run overlaps or is missed.
- **Failure handling:** who is alerted, and what a retry does.

## Design rules

- **Dry-run by default.** The job prints what it would change (counts, and a small sample of
  identifiers) and writes nothing. A separate explicit flag applies changes. The owner sees dry-run
  output before the first real run.
- **Idempotent.** Exclude already-processed rows in the selection (a status, a timestamp, a marker
  column), or make the update a pure function of current state. Prove it by running twice.
- **Bounded, with a circuit breaker.** Cap rows per run and per batch. If the selection returns far
  more rows than expected, abort and report instead of proceeding.
- **Transactions per batch.** Commit a batch fully or roll it back; no half-applied batches. Keep
  transactions short to avoid long locks.
- **Reversible.** Before the first real run, capture before-values (an audit table or a log of
  identifier, old value, new value), or confirm a tested backup. Know the undo procedure before you
  need it.
- **Parameterized SQL only.** Never build SQL by string concatenation. Review every `WHERE` clause
  as if it were the whole safety system, because it is.
- **No schema changes as a side effect.** Migrations are a separate, approved task.
- **No overlapping runs.** Use a lock or lease so a slow run and the next scheduled run cannot
  both execute. Set timeouts.
- **Retry only what is safe.** Retries are acceptable for idempotent operations; otherwise fail and
  alert.

## Scheduling and observability

- State the schedule, timezone and overlap policy explicitly in the plan and in the deployment
  config; do not rely on defaults.
- Use meaningful exit codes: zero for success, distinct non-zero codes for "nothing to do", "aborted
  by circuit breaker" and "failed".
- Log **identifiers and counts, not values**. Emit one summary line per run: selected, changed,
  skipped, failed, duration, dry-run or applied. Make it machine-readable (see 03).
- Alert on failure **and on a missing run**. A job that silently stops is a common failure.
- Sensitive data stays out of logs, fixtures and prompts (see 04).

## Testing

Write tests before the job touches any real database, and make each a `Verify:` command in the plan:

- Unit tests for the selection logic and the transformation, using synthetic fixtures.
- An integration test against a **disposable database** seeded with fixtures that include the
  awkward cases: nulls, duplicates, rows already processed, rows just outside the criteria, and an
  empty selection.
- **Idempotency:** run twice; the second run changes nothing.
- **Dry-run writes nothing:** compare the table before and after.
- **Rollback:** force a failure mid-batch; confirm no partial change remains.
- **Circuit breaker:** feed an oversized selection; confirm the abort.
- **Environment guard:** confirm it refuses to run with no environment set or with production and no
  explicit flag.

## Rollout

Promote in stages, with the owner approving each step and reading the output:

1. Tests pass against a disposable database.
2. Run in development, dry-run then applied.
3. Run in staging with production-like data and volume if available.
4. Production dry-run.
5. Production applied with a small row limit; verify the result and the rollback path.
6. Full limit, then enable the schedule.

Turning the schedule on is its own step. Do not enable it in the same change as the first real run.

## Review checklist for the owner

- Do the selection criteria match the spec, and is the expected count plausible?
- Is every query parameterized, with a `WHERE` you have read yourself?
- Is the run idempotent, bounded, and transactional?
- Are before-values captured, and is the rollback tested?
- Does it refuse to run against production by accident?
- What happens on overlap, timeout, partial failure and a missed run?
