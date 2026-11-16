# From zero to a working box

This guide takes you from nothing to a repo whose agent box scores 9 out of 10 on
[`box/STANDARD.md`](box/STANDARD.md). Do the steps in order. Each says what to do, what you should
see, and what to do if you don't.

Steps marked **home** or **corporate** apply to that profile only. Everything else is the same for
both.

## Before you start

You need:

- **git** and **Python 3.8 or newer** on the command line. Check with `git --version` and
  `python3 --version` (on Windows, `python --version`).
- **An agent** that can load skills and run commands in a repo, and its command-line form in
  non-interactive mode (reads a prompt on stdin, prints the answer). Step 4 uses it as the judge.
- **A Python repo** to work on, checked out locally with at least one commit. box-bootstrap
  supports Python only.
- **A copy of this kit.** Clone it, or download and unpack its archive, into a folder of its own
  outside your repo:

  ```
  git clone <this kit's URL> agent-box-kit
  ```

Below, `<kit>` is that folder and `<repo>` is the top of your repo's checkout. Use absolute paths.
Run the kit's scripts with `python -B`, from outside `<repo>`: box-audit refuses to write anything
inside the repo it audits.

## 1. Pick a profile

A profile tells the box what your setup can rely on. [`box/README.md`](box/README.md#profiles)
describes both.

- **home**: your repo is on GitHub and its CI is GitHub Actions.
- **corporate**: anything else, or you don't know. It assumes no particular host and uses the
  local `ready` script in place of host settings.

Write the name, and nothing else, to `.box-profile` at the top of your repo, then read it back:

```
cd <repo>
python3 -c "open('.box-profile', 'w').write('home\n')"
python3 -B <kit>/box/profiles/profile.py <repo>
```

(Write `corporate` in place of `home` for the corporate profile.)

**You should see** the profile printed as JSON, with `"name": "home"` (or `"corporate"`) on its
second line.

**If not:** exit 3 means there is no `.box-profile` in the folder you named; check the path. Exit
2 means the file holds something other than one name; write it again with the command above.

## 2. Install the agent-ready skill

Copy the `agent-ready/` folder into your agent's skills folder (your agent's docs say where), so
that `<skills folder>/agent-ready/SKILL.md` exists. If your agent has no skills folder, add a line
to your repo's instructions file telling it to read `<kit>/agent-ready/SKILL.md`.

**You should see** the skill in your agent's list of skills. Ask it: "Which agent-ready module
covers orienting in a new repo?" It should answer `modules/01-orient-a-repo.md`.

**If not:** check the folder holds `SKILL.md` directly, not a nested `agent-ready/agent-ready/`,
and start a new session; most agents read skills at start-up.

## 3. Orient the repo

Start a session in `<repo>` and ask the agent to follow agent-ready
[module 01](agent-ready/modules/01-orient-a-repo.md): find and run the build and test commands,
record a baseline, and write `AGENTS.md`. Then commit the result, with `.box-profile`, on a branch:

```
git switch -c box-setup
git add AGENTS.md .box-profile
git commit -m "Add AGENTS.md and box profile"
```

**You should see** an `AGENTS.md` whose every command is marked *run* or *not run*, and a
baseline (how many tests pass and fail today). `git status` shows nothing to commit; untracked
caches such as `__pycache__/` are fine. Step 5 adds to this same `box-setup` branch.

**If not:** if the agent cannot find a test command, or the tests do not run, fix that first.
Later steps build a gate on top of the test suite, and a gate that runs nothing fails.

## 4. Run box-audit

The audit scores your repo on the six dimensions and proposes an issue for each gap. Read
[its skill](box/skills/box-audit/SKILL.md) once; the commands are below.

**4a. Prove the judge is isolated** (once per judge command and machine). The judge must not see
your personal agent instructions:

```
python3 -B <kit>/box/skills/box-audit/scripts/judge.py probe \
    --instructions <one of your personal instruction files> -- <judge command>
```

**You should see** `PROBE_PASS`. On `PROBE_LEAK` or `PROBE_INCONCLUSIVE`, follow step 2 of the
skill's Report section. If the judge CLI needs a credentials file or an API key, add
`--copy-home <file, relative to your home>` or `--keep-env <variable>`, here and in 4b.

**4b. Audit.** From a folder outside `<repo>`:

```
python3 -B <kit>/box/skills/box-audit/scripts/audit.py <repo> --out <cards folder> \
    --judge-line "isolated: judge.py probe PASS <date>" -- <judge command>
```

- **home**: the remote is read from `origin` and host evidence comes from the `gh` CLI, signed
  in to GitHub.
- **corporate**: add `--no-remote`. Host items are recorded as unavailable.

If your agent starts isolated sessions its own way, replace `-- <judge command>` with
`--bundle-only <folder>`, give a fresh session `<folder>/prompt.md` as its whole input, save its
answer as the card, and check it with `python3 -B <kit>/box/skills/box-audit/scripts/card.py
check <card>`.

**You should see** exit 0 and a card, `box-audit-<name>-<date>.md`, in the cards folder. Its
`- Score:` line looks like `G ~ · R ~ · J ✗ · W ~ · P – · D ✗ → 7`. Keep this card: it is the
"before".

**If not:** exit 2 names what it refused, most often an `--out` inside the repo. Exit 1 means the
judge failed or wrote an invalid card; the problems are printed.

## 5. Run box-bootstrap

Bootstrap writes the repo-level items the audit looks for (gate script, CI or `ready` script,
tamper guard, PR template and lint, docs stubs) and commits them. See
[its skill](box/skills/box-bootstrap/SKILL.md) for the full list. Give it the step-3 branch:
without `--branch`, it starts a new branch from the default branch, which does not have your
`AGENTS.md` yet, and writes a blank template in its place.

```
python3 -B <kit>/box/skills/box-bootstrap/scripts/bootstrap.py <repo> --branch box-setup
cd <repo>
python3 scripts/check.py
```

- **corporate**: also run `python3 scripts/ready.py --body <file holding your change
  description>`.

**You should see** bootstrap exit 0 with every item found, a list of stubs to fill in, and a list
of **owner steps** (settings only you can change). `scripts/check.py` runs your tests and exits 0.

**If not:** exit 1 lists each missing item with the reason; fix it by hand and run bootstrap
again. If `check.py` fails because no tests ran, write real tests; do not add a placeholder.

Then ask the agent to replace every `<...>` placeholder bootstrap left (in `docs/` and
`.agents/skills/verify/SKILL.md`) with what the code says, and commit. Do the owner steps
bootstrap printed, and merge the branch the way your repo merges (**home**: a pull request whose
checks pass; **corporate**: `scripts/ready.py` exits 0 on its head commit).

## 6. Re-audit until the card scores 9

Run step 4b again on the default branch, with a new cards folder or date.

**You should see** every G and W item bootstrap wrote listed as evidence. The first card after
bootstrap does not score 9: D needs a dated bug-hunt pass, and R and J need tests and judges no
template can write.

Then loop until the `- Score:` line ends in `→ 9` or `→ 10`:

1. Read the card's **Gap** and **Proposed issues** for each dimension below ✓.
2. File them. **home**: `python3 -B <kit>/box/skills/box-audit/scripts/file_issues.py <card>
   --repo OWNER/NAME` shows a dry run; add `--apply` to file. **corporate**: use `--folder
   <issues folder>` in place of `--repo OWNER/NAME`.
3. Work each issue with agent-ready, one at a time: spec and plan
   ([module 02](agent-ready/modules/02-spec-and-plan.md)), build
   ([module 03](agent-ready/modules/03-build-loop.md)), merge through the gate
   ([module 08](agent-ready/modules/08-review-and-merge.md)).
4. For D, run a bug-hunt pass ([queue-fill](box/skills/queue-fill/SKILL.md#bug-hunt-pass)) and
   fix what it finds, each fix with a check that catches the whole class.
5. Re-audit (step 4b).

A 9 needs every dimension at ✓ or n/a; one ~ is allowed only with a written external blocker.
STANDARD.md's [How to score](box/STANDARD.md#how-to-score) explains the arithmetic.

## Next

With a 9, keep the queue full and hand issues to workers:

- [`box/skills/queue-fill/`](box/skills/queue-fill/SKILL.md) fills the queue with issues a worker
  can finish.
- [`box/orchestrate/`](box/orchestrate/README.md) specifies how ready issues become worker
  sessions and how their PRs are checked.
