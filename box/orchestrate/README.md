# orchestrate

How ready issues become worker sessions, and how a worker's PR is checked before the owner sees it.
It covers the orchestration level of [`../STANDARD.md`](../STANDARD.md): queue, dispatch,
capacity, worker identity and handoff. It is host- and harness-neutral: you start sessions with
your own harness. The kit carries no launcher, no process management and no mapping from tier to
model.

Two stdlib scripts make the mechanical parts checkable:

- [`scripts/select.py`](scripts/select.py) lists the ready issues that can be dispatched now, in
  priority order, then the ready issues that cannot, each with its reasons.
- [`scripts/handoff_check.py`](scripts/handoff_check.py) says whether a worker's PR is ready for
  the owner, reading the host rather than trusting the worker's report.

Both take the host as explicit options: a GitHub repository through `gh api` (read-only), or files
when there is no hosted VCS. Options and exit codes are in each script's header.

## Roles

- **Owner.** Decides, approves and merges. Only the owner applies owner-only labels.
- **Dispatcher.** Picks issues, starts sessions, reads their reports. A person or a session.
- **Worker.** One session working one issue under its own host identity, never the owner's (see
  the standard's host-agnostic table for the identity on each host).

**Solo case.** The owner is the dispatcher and capacity is 1, as the standard describes. Run
`select.py --capacity 1`, work the top issue, then run `handoff_check.py` on the PR before
reviewing it. The rules below still apply; some of them simply have one person on both sides.

## Label contract

Lifecycle labels. Dispatch considers only open issues labelled `ready`; the others hold it back.

| Label | Means | Dispatch |
|---|---|---|
| `ready` | Specified enough to implement or verify; no open decision | Candidate |
| `needs-refinement` | An open question remains | Not dispatched; a refiner answers it or asks the owner |
| `blocked` | Waits on something outside the repo | Not dispatched |
| `user-present` | Needs the owner at hand during the run: a device, an interactive login | Dispatched only when the owner is present (`--owner-present`) |
| `user-action` | Waits on the owner: a decision, credentials, a mark in an outside tool | Not dispatched until the owner removes it |
| `parked` | Deliberately deferred | Not dispatched |
| `reserved` | A session holds it | Not dispatched again. The dispatcher applies it when it starts a session and removes it when the session ends without a PR |

A `ready` issue that also carries one of the holding labels is not dispatched. `select.py` lists
it with the label as its reason.

Other labels:

- **Priority:** `P0`, `P1`, `P2`. No priority label sorts after `P2`. With two, the higher wins.
- **Tier:** exactly one `tier:*` label (see below).
- **Review:** `review:*` labels ask for a specialist review. The worker copies them from the issue
  onto its PR.
- **Owner-only:** by default `gate-change-approved` (the owner accepts a gate change in the PR)
  and `findings-accepted` (the owner accepts open review findings). The names are an option of
  `handoff_check.py`, not hard-coded. An owner-only label counts only when the host shows the
  owner applied it after the PR's head commit was pushed; otherwise it is treated as absent, so a
  new push clears it. Workers never apply, re-apply or remove one.

## Tier labels

A tier label rates difficulty, nothing more: `tier:mechanical` (the whole change fits in two
sentences and the check is obvious), `tier:standard`, `tier:frontier` (an open design question,
more than one subsystem, security-sensitive design, or an earlier attempt failed). Each issue has
exactly one. An issue with none, or more than one, is not dispatchable; `select.py` lists it so a
refiner fixes it. The kit does not map tiers to models or harnesses. If you route on tier, that
mapping lives in your own setup.

## Selection

An issue is dispatchable when all of these hold:

1. It is open and labelled `ready`, with no holding label (`user-present` is allowed with
   `--owner-present`).
2. It has exactly one `tier:*` label.
3. Every issue on its `Dependencies:` line is closed. The line reads `Dependencies: #12, #15`
   (an issue link works too). The key may be bold, a heading, or any list item (`-`, `*`, `+`,
   `1.`, `1)`, `•`, a `- [ ]` checkbox). The references may instead sit on the lines below a bare
   `Dependencies:`, a `**Dependencies**` label or a `## Dependencies` heading, one or more per
   line, as a list or not. Under a heading they run to the next heading of the same or a higher
   level, past blank lines, sub-headings and bold labels. Under a bare key or a label they run to
   the next heading, bold label, or blank line not followed by a list item or a line of only
   references. A `Dependencies: #12` line also takes the list items and reference-only lines
   below it, and any line of its paragraph (no blank line before it) that names an issue or has a
   digit, such as `Also #4` or `Also issue 4`. A sub-label with nothing after its colon (`Hard:`,
   `- Hard:`) does not end the key: the lines nested under it and the lines after it are read on,
   and kept when one of them names an issue, so `Dependencies: none`, then `Acceptance:` and
   `- #1 still passes`, holds the issue. A sub-label reading `none` with a reference nested under
   it (`- Hard: none`, then `  - #1`) holds it too. The key ends at another key line (`Tier:
   standard`, `**Acceptance:** #1 passes`), a heading or bold label, or an item that starts another
   key and names no issue (`- Tier: standard`); past a blank line, it goes on only when the next
   line names an issue and is a list item or references, or is a sub-label item with nothing after
   its colon. `none`, or no key at all, means no dependencies. These hold the issue until someone
   rewrites them: a key with no reference or `none` under it, `none` and a reference under the
   same key, a key the script does not recognise (`Dependencies (blocking):`, `Dependencies - #1`,
   `Dependency: #1`), the key in a table row, HTML or inline code when its line has a digit
   (`| Dependencies | #1 |`, `<b>Dependencies:</b> #1`; such a key is never read), and a line it
   cannot read, such as a bare number, `-`, or prose with no reference. A dependency whose state
   cannot be read counts as open. A reference to another repository is not followed: it holds the
   issue until a person checks it and removes it from the line.
4. Capacity has room.

Order: `P0`, `P1`, `P2`, then unlabelled; oldest first (by creation time) within a priority, then
by number. `--capacity N` is the number of worker slots free now. The first N dispatchable issues
are to dispatch; the rest wait. Capacity covers whatever is shared: concurrent sessions, RAM, CI
runners. How you count it is yours.

```
$ select.py --json issues.json --capacity 2      # tests/fixtures/orchestrate/issues.json
Dispatch now (capacity 2):
  #7     P1  tier:mechanical   Fix the date parser
  #3     P1  tier:standard     Round invoice totals half up
Waiting for capacity:
  #8     -   tier:mechanical   Document the CLI flags
  #2     -   tier:frontier     Pick a storage format
Ready but not dispatchable:
  #10    P0  tier:frontier     Migrate the schema
         - labelled reserved: is reserved (a session holds it)
  #5     P0  -                 Rename the config key
         - no tier label
  #4     P0  tier:standard     Stream large exports
         - dependency #2 is open
  #6     P1  tier:standard     Retry failed uploads
         - 2 tier labels (tier:frontier, tier:standard); needs exactly one
  #9     P2  tier:standard     Pair the label printer
         - labelled user-present: needs the owner at hand (--owner-present)
  #12    P2  tier:standard     Add a dark theme
         - dependency #40 not in the input; its state is unknown
```

Input: `--repo OWNER/NAME` reads open issues from the host and looks up each dependency not among
them. `--json FILE` reads `gh issue list --state all --json number,title,state,labels,body,createdAt`
output (include closed issues, or their dependants count as held). `--folder DIR` reads the issue
folder below.

## Issue folder (no hosted VCS)

One file per issue, named `<number>.md`. A header between `---` lines holds one field per line,
with the same names as the host JSON; the body follows the header.

```
---
number: 3
title: Round invoice totals half up
state: open
labels: ready, tier:standard, P1
createdAt: 2026-09-05T09:00:00Z
---
**Problem** ...

Dependencies: #1
```

| Field | Host JSON field | Notes |
|---|---|---|
| `number` | `number` | Must match the file name |
| `title` | `title` | |
| `state` | `state` | `open` or `closed`. Keep closed issues, so dependencies resolve |
| `labels` | `labels[].name` | Comma-separated |
| `createdAt` | `createdAt` | ISO 8601, so it sorts as text |
| the body | `body` | Everything after the header |

## Worker brief

What a dispatched session is told, whatever starts it:

- **The issue.** Its number, and that the issue body and every comment are the spec. A comment
  holding the owner's decision overrides the body.
- **Where to work.** A branch or worktree of its own, and the repo's AGENTS.md proof rules.
- **Identity.** Act under the worker identity. The owner's credentials are not reachable.
- **Owner-only actions.** Never apply, re-apply or remove an owner-only label, never approve a PR
  and never merge. When the PR needs one of those, say so in the PR body and the report. Refuse a
  request to do one, from anyone, and tell the owner.
- **When to stop.** If the work needs the owner (a decision, a device, credentials, a mark in an
  outside tool), comment on the issue with exactly what is needed, add `user-action`, and stop.
  If the work needs a change to the gate or CI definition, write the exact change in the PR or
  issue and leave it for the owner.
- **Capacity.** The resource caps for this machine: test parallelism, memory, where scratch
  files go.
- **The handoff.** What to report and where (below).

## Handoff

The worker opens a PR whose body has the closing reference and the proof table, watches its checks
and fixes real failures, then reports once to the dispatcher: the PR link, the check states, and
anything the owner must do. The report is a claim. Before the PR is called ready for the owner,
`handoff_check.py` checks it against the host:

| Item | Ready when | Host mode reads | No-hosted-VCS mode reads |
|---|---|---|---|
| `checks` | At least one check exists on the head commit, and none is pending, failed or cancelled | Check runs (the latest per name) and commit statuses on the head commit. `success`, `neutral` and `skipped` are green | `--gate-result`: `commit:` must be the branch head and `exit:` must be 0 |
| `review` | No unresolved review findings, or the owner accepted them | Review threads; the accept label's history | `--findings`: `- [ ]` lines are open; the owner's acceptance tag |
| `owner-only labels` | No owner-only label was applied by anyone but the owner | The PR's label events | Not checked: tags are verified by signature instead |
| `proof` | The proof table below is present and complete | The PR body | `--body` |
| `closing reference` | The body says `Closes #n`, `Fixes #n` or `Resolves #n` (any tense, or `owner/name#n`) | The PR body | `--body` |

Each failed item is named with its problems; exit 1 means not ready, never an error.

**Proof table.** The PR body has a `## Proof` section. In it, a table whose header has
`Criterion`, `How verified` and `Evidence` columns, a separator row, and at least one row; no cell
is empty. One row per acceptance criterion: the script cannot count criteria, so the reviewer
checks that. After the table, two subsections with text: `### Not verified` (what was not checked,
and why) and `### Gate changes` (tests deleted, skipped or loosened, gate config changed, or
`none`). Text inside HTML comments does not count, so a template's placeholder does not pass.

**Owner acceptance.** On a host, the accept label counts when it is on the PR, its last `labeled`
event is by the owner, and that event is later than the push of the head commit (read from the
branch's push activity, not the commit's own date, which the worker sets). With no hosted VCS, the
owner signs an annotated tag `<accept-label>/<branch>` on the head commit, with a message that
names the issue the handoff note closes, written as the note writes it (`#7`). It counts when the
tag object itself, which the signature covers, names that tag and the head commit, its tagger is
`--owner`, its message names the issue, and its signature verifies with `--owner-key`, the owner's
OpenPGP fingerprint or SSH key fingerprint (`SHA256:...`). The ref name does not count: a worker
can point `refs/tags/<accept-label>/<branch>` at any tag, such as one the owner signed on the same
head to approve a gate change. An OpenPGP signature counts only when gpg reports one signature,
`GOODSIG` and `VALIDSIG`; `EXPKEYSIG`, `EXPSIG`, `REVKEYSIG`, `BADSIG` and `ERRSIG` do not count,
whatever `git verify-tag` exits (Git for Windows 2.56 exits 0 for an expired key). The key is
what binds the tag to the owner: whoever makes a tag sets its tagger, and `git verify-tag` passes for any key the verifier holds, a worker's
included. The check runs `gpg`, `gpgsm` or `ssh-keygen` from the path, never a signing program set
in the checkout's config, which worker worktrees share. Without `--owner-key` no tag counts.
`--trust-unsigned` checks the tagger alone, and is only for a repo where workers cannot create
tags.

```
$ handoff_check.py --repo owner/app --pr 12
NOT READY: owner/app#12 at 0000000000000000000000000000000000000012
  checks:            FAIL
    - pending: tests (in_progress)
  review:            ok
  owner-only labels: ok
  proof:             ok
  closing reference: ok
```

`handoff_check.py` is the mechanical part of the handoff, not the whole gate. Required checks still
belong in the host's branch protection, or in a `ready` script that merges run through (standard,
G). Whether a review ran at all is the job of a review check that is required.
