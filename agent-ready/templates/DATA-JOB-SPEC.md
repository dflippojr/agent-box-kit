# Data job spec — <job name>

Status: draft | reviewed by <owner> on <date>

## Purpose
<Why this job exists and what problem it solves.>

## Environments
- Development / staging target: <how configured>
- Production: run by the owner only, after reviewing dry-run output.
- Refuses to run when the environment is unset or ambiguous: yes / no (must be yes)

## Selection
- Records: <table or object, exact criteria>
- Expected count per run: <number or range> · abort if more than: <threshold>

## Change
- Old to new: <precise description or SQL-level statement>
- Why: <reason>

## Idempotency
<How a second run, or a re-run after partial failure, avoids repeating the change. State the
marker or criterion.>

## Limits
- Batch size: <n> · Max rows per run: <n> · Statement timeout: <s>

## Safety
- Dry-run by default; explicit flag applies changes: yes / no (must be yes)
- Transaction per batch: yes / no (must be yes)
- Parameterized queries only: yes / no (must be yes)
- Before-values captured in: <table or log>
- Rollback procedure (tested on <date>): <steps>

## Schedule
- When: <cron or interval> · Timezone: <tz>
- Overlap policy: <lock or lease, skip or queue>
- Missed-run detection: <how>

## Failure handling
- Exit codes: 0 success, <n> nothing to do, <n> aborted by circuit breaker, <n> failed
- Alert to: <who or where> · Retry policy: <what and how many times>

## Logging
- Per-run summary line: selected / changed / skipped / failed / duration / dry-run or applied
- Logs contain identifiers and counts, never values.

## Tests (each is a Verify command in the plan)
- [ ] Selection and transformation unit tests (synthetic fixtures)
- [ ] Integration against a disposable database with edge-case fixtures
- [ ] Idempotency: second run changes nothing
- [ ] Dry-run writes nothing
- [ ] Rollback on mid-batch failure
- [ ] Circuit breaker on oversized selection
- [ ] Environment guard

## Rollout approvals
- [ ] Development · [ ] Staging · [ ] Production dry-run · [ ] Production small limit ·
  [ ] Full limit · [ ] Schedule enabled
