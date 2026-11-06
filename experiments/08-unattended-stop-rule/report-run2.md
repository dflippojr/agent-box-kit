# skill-eval: agent-ready, A vs B

- A (current): `agent-ready`, SKILL.md sha256 81562a609b2d
- B (change): `agent-ready`, SKILL.md sha256 1da39df1de9e
- Task set: `agent-ready.json` (sha256 d7471868102f), 6 tasks, 5 near-miss prompts
- Runner: profile `claude-code`, model haiku, judge model sonnet, 3 repeats per version, seed 18
- Caps: 0.50 USD per session, 0.25 per judge call, 0.15 per near-miss session, 10.00 in all
- Date: 2026-11-06

**Verdict: no detectable difference** between A and B at N=3 repeats per version. That is not proof they are equal.

Signals: checks same, completion same, judge same, trigger same.

## Overall

| Measure | A | B | Effect [95% CI] | Reading |
|---|---|---|---|---|
| Task sessions completed | 18/18 (100%) | 18/18 (100%) | B−A +0 pts [-18, +18] | same |
| Task runs passing every check | 11/18 (61%) | 10/18 (56%) | B−A -6 pts [-34, +24] | same |
| Blind judge: B wins / ties / A wins | | 9 / 4 / 5 | B share 61% [39%, 80%] | same |
| Trigger right (picked on tasks, not on near-misses) | 21/33 (64%) | 21/33 (64%) | B−A +0 pts [-22, +22] | same |
| Judge score: execution (mean, 1-5) | 3.5 | 3.4 | | |
| Judge score: intent (mean, 1-5) | 4.2 | 4.3 | | |

Completion: 18 of 18 planned task pairs completed on both sides (a verdict other than worse needs 80%, and the same number of completed sessions for A and B).

## Per task

| Task | A checks | B checks | Judge B/tie/A | execution A/B | intent A/B |
|---|---|---|---|---|---|
| agents-md | 0/3 (0%) | 2/3 (67%) | 3/0/0 | 2.7 / 3.0 | 3.7 / 4.0 |
| fix-bug | 1/3 (33%) | 0/3 (0%) | 1/2/0 | 3.0 / 3.0 | 4.0 / 4.0 |
| plan-risky-job | 3/3 (100%) | 3/3 (100%) | 1/0/2 | 3.7 / 3.7 | 4.3 / 4.3 |
| red-suite | 2/3 (67%) | 0/3 (0%) | 2/0/1 | 3.0 / 2.7 | 4.0 / 4.3 |
| unattended | 3/3 (100%) | 3/3 (100%) | 1/0/2 | 4.0 / 3.3 | 4.3 / 4.0 |
| unclear-request | 2/3 (67%) | 2/3 (67%) | 1/2/0 | 4.7 / 5.0 | 5.0 / 5.0 |

## Trigger

| | A | B |
|---|---|---|
| Picked on task prompts | 6/18 (33%) | 6/18 (33%) |
| Picked on near-miss prompts | 0/15 (0%) | 0/15 (0%) |

## Cost and time

| Part | Sessions | Spend (USD) | Time |
|---|---|---|---|
| A sessions | 18 | 0.12 | 5m 56s |
| B sessions | 18 | 0.12 | 5m 25s |
| Near-miss sessions | 30 | 0.05 | 1m 42s |
| Judge sessions | 18 | 0.45 | 1m 20s |
| **Total** | 84 | **0.74** of 10.00 cap | 14m 23s |

## Reading this

A session that failed after the agent started counts against its version; one the harness could not start is left out with its partner. Intervals are 95%: Newcombe's hybrid score interval for the differences, Wilson's for the judge's share. A signal reads worse or better only when its whole interval is on one side. Runs of the same task are treated as independent, which they are not quite, so the intervals are a little narrow. No detectable difference means this N could not see one; more repeats can.
