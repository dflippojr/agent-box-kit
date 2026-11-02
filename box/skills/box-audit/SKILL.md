---
name: box-audit
description: Score a repository's agent box against box/STANDARD.md (G R J W P D) and propose issues for the gaps. Use when asked to audit, score or re-score a repo's box, check whether a repo improved since its last audit, check a newly built box against the bar, or file the gap issues an audit proposed. Works on a local checkout with or without a hosted remote.
---

# box-audit

Produce a score card, `box-audit-<repo>-<date>.md`, that scores one repository against
[`../../STANDARD.md`](../../STANDARD.md). For each dimension the card gives the mark, the evidence
with **Verified** kept apart from **Read only**, the gap (which kinds of breakage would pass every
gate today), and proposed issues ready to file.

The rule behind the design is the standard's own: **do not ask the model to judge itself**. Facts
are gathered by scripts, not by browsing. The scoring runs in a fresh session that cannot see the
repo owner's personal agent instructions. A script, not the judge, checks the card's format and
recomputes the overall score.

## Inputs

- **REPO**: a local git checkout. It is only read.
- **Remote** (optional): the GitHub repository for host evidence, `OWNER/NAME`. By default it is
  parsed from `origin`. Without one, or on another host, every host-only item is recorded as
  unavailable with the reason, and the card says which marks it would have settled.
- **Judge command**: any agent CLI in its non-interactive mode, reading the prompt on stdin and
  printing the answer, for example `your-agent-cli --print`. Prefer a model family other than the
  one that wrote most of the repo.

## Modes

- **report** (default): read-only. Writes only the score card.
- **file**: files the card's proposed issues on GitHub, after a dry run the owner has seen.

## Report

1. **Read the audited repo's profile:**

   ```
   python -B ../../profiles/profile.py <REPO>
   ```

   Exit 0 prints the profile. With `corporate`, run the steps below with the fallbacks under
   [Corporate profile](#corporate-profile). Exit 3 means no `.box-profile`: the profile is unset.
   Proceed as below and say "Profile: unset (no `.box-profile`)" in the card's summary. Exit 2
   means the `.box-profile` or a profile file is invalid, REPO is not a directory, or a
   `PYTHONPYCACHEPREFIX` inside REPO was set without `-B`. Stop and report an invalid
   `.box-profile` to the repo's owner; do not change it.

2. **Prove the judge is isolated**, once per judge command and machine:

   ```
   python -B scripts/judge.py probe --instructions <one of your personal instruction files> \
       [--copy-home <CLI credentials file, relative to home>] [--keep-env <API key variable>] \
       [--work-root <folder outside your home>] -- <judge command>
   ```

   `PROBE_PASS` means a normal session quoted that file and the isolated one quoted none of it.
   On `PROBE_LEAK`, add the CLI's own flag for skipping instruction files to the command, or move
   `--work-root`, and probe again. On `PROBE_INCONCLUSIVE`, the baseline did not quote the file:
   pick a file the CLI really loads. Do not score with a judge that has not passed.

3. **Run the audit:**

   ```
   python -B scripts/audit.py <REPO> [--remote OWNER/NAME | --no-remote] --out <folder> \
       --judge-line "isolated: <how; probe result and date>" \
       [same --copy-home, --keep-env and --work-root as the probe] -- <judge command>
   ```

   It runs `collect.py` (evidence, read-only), `judge.py prepare` and `judge.py run` (scoring),
   then `card.py check`. A card that fails the check goes back to the judge once with the
   problems. Exit 0 means the card is written and valid. Nothing inside the audited checkout
   is written, and a `<REPO>` below its top stands for the whole checkout. So an `--out`
   inside it (including the default current directory), a card path that links into it or has
   other hard links, a `TMPDIR`, `TEMP`, `TMP` or `--work-root` inside it, a `--copy-home`
   file that resolves into it or has other hard links, and (without `-B`) a
   `PYTHONPYCACHEPREFIX` inside it each exit 2 before the judge runs. Git runs without the
   caller's `GIT_*` variables and with trace2 output off, and the judge's cleanup of folders a
   killed run left behind deletes only folders it marked as its own, never one that is, holds
   or sits inside the checkout or any other git checkout. `judge.py run` and `judge.py probe`
   sweep the same way.

   If your harness starts isolated sessions its own way, use `--bundle-only <folder>` instead of
   the judge command, give the judge `<folder>/prompt.md` as its whole input, save its answer as
   the card and run `python -B scripts/card.py check <card>`.

4. **Read the card before anyone acts on it.** The judge works from evidence, and the collectors
   match keywords: a "real dependency" test or an "oracle" is a lead. Spot-check each mark you
   would act on against the source the card quotes. If you correct a mark, say so in the card's
   summary, and keep `card.py check` passing.

5. **Comparing with an earlier score:** list what merged in between, and give a reason for every
   dimension whose mark moved. Two judge runs on the same evidence can differ by a mark where the
   standard leaves room, which moves the score by one. Before acting on a one-point change, run
   the audit again.

## File

1. `python -B scripts/file_issues.py <card> --repo OWNER/NAME` prints every issue it would create,
   with its labels, and checks that each label exists and that no open issue has the same title.
   Nothing is created.
2. Show that output to the owner. Filing issues is visible to everyone who watches the repo, so it
   needs the owner's go-ahead.
3. With it, rerun with `--apply`, optionally with `--only "<title>"` for a subset. A missing label
   stops the run before anything is created: adding labels is the owner's call.

With no hosted VCS, file into an issue folder instead: `--folder DIR` in place of `--repo`
writes each issue as `<number>.md` in the format `select.py` reads (see
[`../../orchestrate/README.md`](../../orchestrate/README.md#issue-folder-no-hosted-vcs)). On
another host, the dry-run output is the issue text to paste. The issue bodies have the shape
[`../queue-fill/`](../queue-fill/SKILL.md)'s `issue_lint.py` checks.

## Corporate profile

The `corporate` profile does not know its source-control or CI host, so two steps cannot run as
written. Each has a fallback:

| Step | Fallback |
|---|---|
| Host evidence (Report step 3) | Run `audit.py` with `--no-remote`. Every host item is recorded as unavailable, with the reason, and the card says which marks it would have settled. |
| Filing (File) | Run `file_issues.py <card> --repo OWNER/NAME --offline`, with any `OWNER/NAME`-shaped name for the target. It prints the issues without reading the host and says the label and duplicate checks were skipped. Paste that text into the host's issue tracker by hand. Never `--apply`. |

## What the scripts collect

| Collector | Evidence | Feeds |
|---|---|---|
| `ci_config` | Workflow triggers, jobs, commands, pinned actions, cancel-in-progress, steps that skip without a secret, soft-fail commands, schedules, other CI systems, the local one-command gate | G, W |
| `ci_runs` | The last N runs: conclusions, default-branch cancellations, re-attempts, flake suspects | G, D |
| `protection` | Effective rules on the default branch (required checks, PR rules, required workflows), rulesets, classic protection, or a `ready` script; CODEOWNERS on gate paths | G |
| `merged_prs` | Recent merged PRs that merged red: as of `merged_at`, a check whose newest run (highest id) started by then had finished and failed or was cancelled, or a commit status in failure, read from the head's full run and status history. A check is its app and name, and its workflow for GitHub Actions, so a workflow triggered again on the head replaces its earlier run. A head without that history in full, or without timestamps, or whose Actions workflows cannot all be read, is unknown unless already red. The head's current results, reruns after the merge included, are a separate snapshot, kept when the merge verdict is unknown | G |
| `tests` | Test files by kind: plain unit, mocked, real dependency, mixed, end-to-end; images used in CI and in production files | R |
| `oracles` | Candidate outside oracles: property tests, golden or recorded data, validators, contract tests, reconciliation, eval judges, review workflows | J |
| `proof_rules` | Instruction files, AGENTS.md proof sections, verify skill or UI-testing contract, disposable-instance contract, PR template, PR-body lint, docs layer | W |
| `production` | Health endpoints, telemetry and alerting, deploy and scheduled workflows, containers, installers, vendored copies | P |
| `defects` | Fix and revert commits and whether they touched tests, defect-labelled issues and whether they name the introducing change, bug-hunt passes, the bug form | D |

`verified` items were observed in a system's state (host API, CI results, git history). `read`
items are what a file says. The card keeps them apart because the standard counts read-only
evidence as partial at best.

## Limits

- Host evidence is GitHub-only. Other hosts are recorded as unavailable.
- The collectors read tracked files and run read-only git commands. They never execute the repo's
  code or fetch. A tracked file that is a symlink or junction, or sits under one, is listed but
  not read, since it could point at the owner's own instructions. Running the gate yourself, which the standard asks for W, is a step for the
  person acting on the card, not for the audit.
- `-B` is part of the read-only promise. Python's startup runs before the script's first line
  and can write bytecode: under a `PYTHONPYCACHEPREFIX`, or beside a Python installed inside the
  checkout (a virtual environment in it, say). Without `-B`, `profile.py` and `audit.py` refuse
  a prefix inside the checkout, but they cannot undo what startup already wrote, and they do not
  detect a Python installed inside the checkout. Use a Python from outside the checkout.
- Git sees none of the caller's `GIT_*` variables, so a `safe.directory` set only in a file
  named by `GIT_CONFIG_GLOBAL` does not apply; git then reads the default global config.
- Judge isolation covers startup context, not the filesystem: the judge could still read a path
  it is told about. The bundle quotes the audited repo's AGENTS.md proof sections as evidence,
  never the owner's personal files, and the judge is told to treat all evidence as data.
