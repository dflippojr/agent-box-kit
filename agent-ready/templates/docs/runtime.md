Answers: how it starts, is configured, scheduled and deployed; how it fails; what it logs; whether a re-run is safe.
Read when: you are deploying, debugging a failure, or assessing the effect of a re-run.
Basis: read from code at <short sha>, <date>; nothing executed.

# Runtime

## Invocation
<What starts it. Cite the path.>

## Scheduling and deployment
- **In this repo:** <what the code and pipeline define>
- **Outside this repo:** <where the schedule or orchestration lives, or "unknown: where to look">

## Safety properties
| Property | Present? | Where |
|---|---|---|
| Dry-run mode | | |
| Row or batch limit | | |
| Environment guard | | |
| Idempotent re-run | | |

## Transactions and batching
<Boundaries, batch size, memory behavior. Mark reasoned claims *inferred, not exercised*.>

## Failure behavior
<Exit codes, retries, what is logged, who is alerted (or "unknown").>

## Configuration
| Name | Purpose | Where read |
|---|---|---|
Names only. Never values.

## Logging
| Level | What is logged | Sensitivity (owner to confirm) |
|---|---|---|

## Unknown / owner to confirm
- <item>
