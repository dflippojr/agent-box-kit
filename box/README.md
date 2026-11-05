# box

The **agent box** is everything around agent-written code that proves the code is correct and
works: the repo's gate, tests, judges and proof rules, plus the queue, dispatch, identity and
handoff around the repos.

- [`STANDARD.md`](STANDARD.md) defines the bar: what a box is, the six dimensions (G enforced
  gate, R real-thing tests, J outside judge, W worker-runnable proof, P real-use feedback, D
  defect ratchet), what 9/10 and 10/10 need, what evidence an auditor looks for, and how to score.
- [`skills/box-audit/`](skills/box-audit/SKILL.md) scores a repo against the standard. Scripts
  gather the evidence, a judge session that cannot see the owner's personal instructions scores
  it, and a script checks the card and recomputes the score. It can then file the proposed
  issues.
- [`skills/box-bootstrap/`](skills/box-bootstrap/SKILL.md) builds the repo-level items a Python
  repo is missing, on a new branch, with the GitHub or host-neutral variant the profile picks,
  until box-audit's collectors find them all. What is left is track record (D, P).
- [`skills/skill-eval/`](skills/skill-eval/SKILL.md) tests a small skill change: version A against
  version B on a task set, in isolated sessions under a cost cap, graded by checks, a blind judge
  and a trigger check. Its report's verdict (worse, better, no detectable difference or
  inconclusive) is the evidence a skill-change PR cites.
- [`skills/queue-fill/`](skills/queue-fill/SKILL.md) leaves a repo's queue full of issues a worker
  can finish: a gap pass files box-audit's proposals, a dated bug-hunt pass files traced findings,
  and a refinement pass rewrites answered `needs-refinement` issues and marks them `ready`. Every
  pass writes one issue shape that `issue_lint.py` checks, and changes nothing without `--apply`.
- [`lessons/`](lessons/README.md) holds one file per lesson, each linked to its `EVIDENCE.md` row
  and to the check or STANDARD.md line that enforces it; the lessons nothing enforces yet are
  listed as open.
- [`orchestrate/`](orchestrate/README.md) specifies how ready issues become worker sessions and
  how a worker's PR is checked before the owner sees it: the label contract, selection, the worker
  brief and the handoff. `select.py` lists what can be dispatched now; `handoff_check.py` checks a
  PR against the host. No launcher and no model routing: sessions start in your own harness.

Unlike `agent-ready/`, which is written for one agent in one session, the box covers the
orchestration level too. It is host-agnostic: it names the GitHub mechanism where one exists, then
the equivalent or a fallback for other hosts or no hosted VCS.

## Profiles

A profile records the setting a repo's box runs in, so every component reads one answer instead
of guessing. [`profiles/`](profiles/) holds two:

- **`home`**: unconstrained. Any model provider, a second model family reachable for the J judge,
  GitHub for source control and CI, any editor, and every host mechanism done the GitHub way.
- **`corporate`**: models come through AWS Bedrock; whether a second model family is reachable,
  the source-control host and the CI host are unknown; any editor. Every host mechanism uses the
  "No hosted VCS" fallback from STANDARD.md's host-agnostic table, the only column sure to run
  when the host is unknown. Nothing in it assumes GitHub or names an editor.

**Pick one** by writing its name, and nothing else, to `.box-profile` at the repo root:

```
echo corporate > .box-profile
```

On Windows, `echo` in cmd keeps the space before `>` and Windows PowerShell writes UTF-16, and
the loader rejects both. Use an editor, or a command that works in any shell:
`python -c "open('.box-profile', 'w').write('corporate\n')"`.

**Read it** with `python -B profiles/profile.py [REPO]`, which prints the profile as JSON (exit 0),
reports it unset when there is no `.box-profile` (exit 3), and rejects an empty file, two names,
an unknown name or an invalid profile file (exit 2). It never falls back to a default. Components
call its `load(repo)` instead. box-audit reads it first (see its skill), box-bootstrap
stops without one (exit 2), and dispatch is to read it when it is built.

The fields, each with a fixed set of values: `name`; `model_access.provider` (`any`,
`subscription`, `api`, `bedrock`, `other`) and `model_access.second_family` (`yes`, `no`,
`unknown`); `source_control` and `ci_host` (`github`, `other`, `none`, `unknown`); `ide` (`any`,
`none`, `other`); and `mechanisms`, one key per row of the host-agnostic table, each `github`,
`elsewhere` or `none` for the table's three columns. A profile describes a kind of setup, never a
person's machine.
