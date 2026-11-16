# GUIDE.md pre-walk on a fresh box (2026-11-15 to 2026-11-16)

Before an outside user walks [`GUIDE.md`](../../GUIDE.md), an agent walked it on a fresh,
disposable environment, followed it literally, and fixed the gaps it hit (issue #8). This is the
record. Not part of the skill.

There were two walks. Walk 1 (`logs/`) wrote the gap list below. Walk 2 (`logs-walk2/`, at the
end) re-walked the fixed guide after the first review: every home step that runs without a GitHub
account, in a new container whose setup is logged, plus the corporate step 5 fix.

# Walk 1

## Environment

- A new container from the public `python:3.12-slim` image: Python 3.12, git 2.47 (installed in the
  container as a prerequisite the guide names), a new unprivileged user with an empty home.
- None of this kit's skills or tooling installed. The kit was copied in as an unpacked archive of
  the branch, as a new user would download it.
- No agent CLI, no `gh`, no GitHub account and no personal instruction files.
- The repo walked: a two-function Python library with two pytest tests and one commit, made for the
  walk (`logs/00-setup.log`). pytest was installed for the user, as the guide's prerequisites now
  say.
- Logs are sanitized: the container's home is written `~`. Each entry is the command as run, its
  output and its exit code. The agent-driven steps (orienting, filling stubs, writing descriptions,
  the bug hunt) were done by the walking agent, following the installed skill copy.
- The judge: no agent CLI exists in the box, so every audit used the guide's `--bundle-only` form,
  and a fresh session started by the walker's harness, given only `prompt.md`, wrote the card.
  `card.py check` then ran in the box. The judge was the same model family as the walker.

## Steps

| Step | Home | Corporate |
|---|---|---|
| Before you start | pass (`home-0-prereqs`) | pass (same box) |
| 1 Pick a profile | fix G2 (`home-1-profile`) | pass (`corp-1-profile`) |
| 2 Install the skill | pass, copied and read; no agent CLI to ask (`home-2-skill`) | pass (`corp-2-skill`) |
| 3 Orient the repo | fix G3 (`home-3-orient`) | pass (`corp-3-orient`) |
| 4a Probe the judge | not walked: no agent CLI or instruction file (`home-4a-probe`) | not walked: same |
| 4b Audit | pass, bundle form; card `CARD_OK`, score 5 (`home-4b-audit`) | pass, bundle form, `--no-remote` (`corp-4b-audit`) |
| 5 Bootstrap | fix G1, then pass: `BOOTSTRAP_DONE`, `GATE_PASS` (`home-5-bootstrap`) | pass (`corp-5-bootstrap`) |
| 5 Merge | not walked: no GitHub; local fast-forward instead (`home-5-merge`) | fix G4, G5, G6, then `READY` and merged (`corp-5-owner`, `corp-5-merge`) |
| 6 Re-audit | pass, `CARD_OK`, score 5 to 7 (`home-6-reaudit`) | pass, `CARD_OK`, score 7 (`corp-6-reaudit`) |
| 6.2 File the proposals | fix G7; `--repo` needs `gh`, so `--offline` dry run instead (`home-6-file`) | pass, `--folder` dry run, 11 proposals (`corp-6-file`) |
| 6.3 Work an issue | not walked | pass: red test, fix, `READY`, merged (`corp-6-fix`) |
| 6.4 Bug-hunt pass | not walked | pass, one finding filed to the folder; gap G8 (`corp-6-bughunt`) |
| 6.5 Re-audit | not walked | bundle written; D still unavailable (G8) (`corp-6-reaudit`) |
| Final walk at the fixed guide | | pass, steps 1 to 5 end to end (`final-corp-walk`) |

The loop to 9 was not finished on either profile. On a fresh library repo it needs work no walk
can fake: an outside oracle for J, track record for D, and, on home, a GitHub host enforcing
the checks for G.

## Gaps found and how each was fixed

| # | Gap | Fix |
|---|---|---|
| G1 | Bootstrap without `--branch` started a new branch from the default branch, so the step-3 `AGENTS.md` and `.box-profile` were not on it and bootstrap wrote a blank `AGENTS.md` template. | Step 5 runs `bootstrap.py <repo> --branch box-setup` and says why. |
| G2 | "You should see" said the JSON starts `{"name": ...`; it is printed indented, the name on line 2. | Reworded. |
| G3 | "`git status` shows a clean tree" was false: pytest leaves untracked `__pycache__/`. | Says nothing to commit, untracked caches are fine. |
| G4 | The guide said merge when `ready.py` exits 0, but the bootstrap branch's own tamper guard ends `NOT_READY ... tamper guard` until the owner approves the gate files (home: the `tamper-guard` check). | Step 5 says so for both profiles and gives the approval: the owner's tag (corporate) or label (home). |
| G5 | `ready.py --body <file>` named a description file without saying what goes in it. | Step 5 points at the PR template bootstrap writes and its required parts. |
| G6 | No merge command for the corporate path. | `git switch main` then `git merge --ff-only <commit>`, the commit `READY` names. |
| G7 | The home path needs `gh` signed in (audit host evidence, filing), and pytest is needed for the gate; neither was a prerequisite. | Both added to Before you start. |
| G8 | On a repo with no hosted VCS, the audit's D collector reads no issue folder, so a bug-hunt pass can never count, and a red-test commit followed by its fix commit is read as a fix with no test. | Too large for this PR: issue #29. Step 6 says D stays ✗ on corporate until it lands. |
| G9 | The guide runs `card.py`, whose `--help` exited 2. | `card.py --help` prints usage and exits 0, with a test. |
| G10 | The guide named a nested `agent-ready/agent-ready/` path that does not exist (caught by the new `tests/test_guide.py`). | Reworded without a path. |

Walker errors, not guide gaps, are marked in the logs: a quoted `title:` in a bug-hunt draft
(the skill's example has none) and a typo in a filled stub.

## Not walked, and why

- 4a, and 4b with a real judge command: no agent CLI or personal instruction file in the box.
- Home: host evidence, the pull request with required checks, the `gate-change-approved` label,
  filing with `--repo` and `--apply`: no GitHub account in the box.
- Corporate model access through a cloud provider: no account; nothing in the guide's steps
  calls it except the judge.
- Windows and macOS.

# Walk 2: after the first review (2026-11-16)

Scope, from issue #8 as amended by the owner on 2026-11-16: walk every home-profile step that can
run without a GitHub account, and name each step not walked. The home profile's GitHub-account
steps (opening a PR, its checks, the approval label, filing issues, and the loop to 9) are left to
the outside-user walk the owner arranges.

## Environment

A second new container from `python:3.12-slim`, set up and checked in
`logs-walk2/00-environment.log`: git installed as root in the container, a new user `dev`, its
home holding only the shell's default dotfiles, no agent CLI, no `gh`, no pytest. The kit was
unpacked from an archive of the branch head with the round-1 fixes. The sample repo was made from
scratch (`01-sample-repo.log`); every file the walking agent wrote was written again in this
container, nothing carried over from walk 1.

## Steps (home profile)

| Step | Result | Log |
|---|---|---|
| Before you start | pass; pytest was missing and the guide's new install command fixed it (G11) | `home-0-prereqs` |
| 1 Pick a profile | pass | `home-1-profile` |
| 2 Install the skill | pass, copied; no agent to ask | `home-2-skill` |
| 3 Orient the repo | pass | `home-3-orient` |
| 4a Probe the judge | **not walked**: needs an agent CLI and a personal instruction file | `home-4a-probe` |
| 4b Audit | pass, bundle form; no `origin`, so host evidence unavailable; card `CARD_OK`, `G ✗ · R ✗ · J ✗ · W ~ · P – · D ✗ → 5` | `home-4b-audit` |
| 5 Bootstrap, gate, fill stubs | pass: `BOOTSTRAP_DONE`, `GATE_PASS`, no placeholders left | `home-5-bootstrap` |
| 5 Write the description | pass, from `.github/pull_request_template.md` | `home-5-merge` |
| 5 Push, open the PR, required checks, approval label, merge | **not walked** (GitHub account). Stand-in: the commands `pr-checks.yml` runs, locally: `tamper_guard.py` fails on the bootstrap branch (7 gate changes) and passes with `--approved`; `pr_body_lint.py` passes; then a local fast-forward | `home-5-merge` |
| 6 Re-audit | pass, bundle form; card `CARD_OK`, `G ~ · R ~ · J ✗ · W ~ · P – · D ✗ → 7`; `--offline` filing dry run lists 10 proposals | `home-6-reaudit` |
| 6.2 File the proposals | **not walked** as written: `file_issues.py --repo` stops with `gh CLI not found`. Stand-in: the `--offline` dry run | `home-6-file` |
| 6.3 Work an issue | walked up to the PR: red test (`GATE_FAIL`), fix (`GATE_PASS`), tamper guard `no gate change`, body lint pass. **Not walked**: the PR and merge on green; local fast-forward instead | `home-6-fix` |
| 6.4 Bug-hunt pass | walked: dated pass, finding reproduced and traced, draft checked. **Not walked** as written: `hunt.py --repo` stops with `gh CLI not found`; `--offline` dry run instead | `home-6-bughunt` |
| 6.5 Re-audit | bundle written; D is unavailable without a remote, and the red-test-then-fix commits read as a fix with no test (#29) | `home-6-reaudit` |
| Loop to 9 | **not walked** (GitHub account, per the amendment) | |

Corporate step 5, re-walked for G12 (`corp-5-description.log`): with the description saved inside
the checkout, `ready.py` ended `NOT_READY: the working tree has changes that are not in the head
commit` listing `?? box-setup.md`; after the guide's `mv` it went on to the tamper-guard
`NOT_READY`, then `READY` after the owner tag, and merged.

## Gaps found in walk 2 and the first review

| # | Gap | Fix |
|---|---|---|
| G11 | "install pytest if they don't" gave no command, and a fresh box has no pytest. | `python3 -m pip install --user pytest` in Before you start. |
| G12 | The corporate description file had no location; saved inside the checkout, `ready.py` refuses the working tree (found by the review, reproduced here). | Step 5 says to save it outside the repo, with `~/notes/box-setup.md` as the example, and gives the recovery. |
| G13 | `tests/test_guide.py` matched flags as prefixes, so `--out2` passed as `--out` (found by the review). | It compares whole option names with the help's options; a negative test proves `--out2`, `--outdir` and `--out2=...` fail it. |

Walker error, marked in the log: the bug-hunt draft first named the wrong introducing commit.

# Walk 3: steps 2 and 4a with a real agent (2026-11-16, stopped)

The second review asked for step 2 (the agent finds the skill) and step 4a (the isolation probe)
to be walked with a real agent installed the way the guide says. `logs-walk3/`: a third new
container, set up as before, empty home, no agent and no key or token variables.

- The guide named no way to get an agent or sign it in (G14). Fixed: Before you start now says
  to install one from its own docs, sign it in, and check it answers a one-line prompt.
- Installing an agent CLI's public installer inside the container was refused by the walker's
  harness. It was not worked around.
- Both steps also need the agent signed in, with a login or an API key inside the container. The
  walk must not copy one from the host, so steps 2 and 4a are **not walked** and wait for the
  owner (see issue #8).

| # | Gap | Fix |
|---|---|---|
| G14 | No pointer for getting the agent prerequisite installed and signed in. | Added to Before you start. |
