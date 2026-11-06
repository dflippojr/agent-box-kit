# Score card format

`scripts/card.py check` enforces everything below. A card that fails the check is not finished.

```markdown
# Box audit: <repo> (<YYYY-MM-DD>)

- Repo: <repo> at <12-character commit>, default branch <branch>
- Remote: <OWNER/NAME, or none>
- Host evidence: <available, or unavailable (reason)>
- Judge: <isolated: how the scoring session was started>
- Score: `G ✓ · R ~ · J ✗ · W ~ · P – · D ~ → 8`
- Proven: 5.0

## Summary

<Two to five sentences: the overall score, the weakest dimensions, and the one change that would
raise the score most.>

## G: Enforced gate

**Mark:** ✓

### Evidence

**Verified**
- <What you observed in a system's state, quoting it.> (<source: api ..., CI run, git log>)

**Read only**
- <What a file says should happen, quoting it.> (<path:line>)

### Gap

- <A concrete kind of breakage that would pass every gate today.>

### Proposed issues

#### <Issue title in the imperative>

Labels: tier:standard, ready
Open decisions: none

**Problem**
<What is wrong today, with the evidence.>

**Want**
- <Observable, checkable outcome.>

**Constraints**
- <What must not change; where the tests go; what proof to attach.>

**Dependencies**
none

**Out of scope**
<The tempting neighbour.>

## R: Real-thing tests
...the same parts for R, J, W, P and D, in that order.
```

## Rules

- **Score row.** One mark per dimension, in the order G R J W P D, from `✗ ~ ✓ ★ –`. The number
  after `→` follows the overall rule in the standard. A 9 with one `~` needs a line starting
  `**Blocker:**` in that dimension's section, naming the external blocker.
- **Proven.** The `- Proven:` line follows the standard's Proven definition for the score row.
  `audit.py` computes it and writes it in place of any the judge gave; `card.py proven "ROW"`
  prints it. A card without the line still passes the check, so a card scored before Proven, or
  by a harness's own judge, stays valid.
- **Mark.** Each section's `**Mark:**` equals its mark in the score row.
- **n/a.** Only R and P may be `–`, and the section then has a `**Reason:**` line. Its Evidence,
  Gap and Proposed issues parts may each say `none`.
- **Evidence.** `**Verified**` and `**Read only**` both appear, each followed by a list or by
  `none`. A dimension whose Verified list is `none` is marked `~` or `✗`: read-only evidence counts
  as partial at best.
- **Host evidence unavailable.** Say so in each item that needed it, rather than guessing.
- **Gap.** Concrete. "A migration that crashes on a populated database" is a gap. "Some edge cases"
  is not.
- **Proposed issues.** A dimension below `★` has at least one issue, or a line starting
  `No issue:` with the reason. Each issue, under any mark including `–`, has:
  - a `####` title, used once in the whole card: merge proposals that would share a title;
  - `Labels:` with exactly one of `tier:mechanical`, `tier:standard`, `tier:frontier`, plus
    `ready` only when `Open decisions:` is `none`. With an open decision, use `needs-refinement`
    and list the decisions. Optional: up to two of `review:security`, `review:concurrency`,
    `review:migration`, `review:perf`, and a priority `P0`, `P1` or `P2`;
  - `Open decisions:` `none`, or the questions;
  - `**Problem**`, `**Want**`, `**Constraints**`, `**Dependencies**` and `**Out of scope**`, in
    that order. Dependencies is `none` or `Dependencies: #N`.
- **Tiers.** `tier:frontier` when there is an open design decision, the change spans more than one
  subsystem or repo, it is security-sensitive design, or an earlier attempt failed.
  `tier:mechanical` when the whole change fits in two sentences and the check is obvious.
  `tier:standard` otherwise.
- **No private detail.** No personal names, hostnames, local paths, credentials or tokens. Quote
  configuration, not secrets.
