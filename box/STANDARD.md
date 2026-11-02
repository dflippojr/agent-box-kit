# Box standard

What "9/10" and "10/10" mean for a project's **agent box**: everything around agent-written code
that proves the code is correct and does what it is meant to do. Use it to build a box to the bar,
or to audit one and score it.

The bar comes from a review of about a dozen projects built mostly by agents. Its guiding rule is
**do not ask the model to judge itself**. A worker that writes the code and the tests that judge it,
then reports "done", is grading its own work. Each dimension below exists because that self-grading
let real defects through.

## What a box is

**Repo level.** These live in the project's repository:

- **AGENTS.md router.** It says how to build, test and prove a change, and points to deeper docs.
  It does not hold everything itself.
- **Docs layer.** Architecture, data model, runtime and testing notes that a new session can find
  its way through.
- **Verify skill.** One documented command that proves a change works in the running product and
  records the evidence.
- **Disposable-instance contract.** A throwaway instance with synthetic data that a session can
  start, drive and tear down without touching real data.
- **CI gate.** One always-run check that every merge needs, on the exact head commit.
- **Review.** An automated or human reviewer that reads the change against the issue's acceptance
  criteria, not just the diff.
- **Labels and issue shape.** Issues state Problem, Want, Constraints and acceptance criteria. Labels
  mark readiness, priority and risk, and some labels only the owner may apply.

**Orchestration level.** These live around the repos and decide how work reaches them:

- **Queue.** The list of issues that are ready to work, meaning no open decision remains.
- **Dispatch.** How a ready issue becomes a worker session, and which work runs in parallel without
  conflict.
- **Capacity.** Limits on concurrent workers and shared resources such as RAM, GPU and runners.
- **Worker identity.** Workers act under their own identity, never the owner's, so the host can tell
  an owner decision from a worker action.
- **Handoff.** The worker's final report, and the mechanical check that decides whether a PR is
  ready for the owner.

A solo setup still has all five. The owner is the dispatcher, the queue is the issue list and
capacity is one. Score the parts that exist; missing ones count against the dimensions they feed
(identity and handoff feed G and W).

## How to score

### Per dimension

Each dimension below gets one of four marks, or n/a:

| Mark | Meaning |
|---|---|
| ✗ absent | None of the "9 needs" items is in place. |
| ~ partial | Some items are in place and working, but not all. |
| ✓ meets | Every "9 needs" item is in place, with evidence. |
| ★ 10 | Meets, plus every "10 needs" item. |
| – n/a | The dimension has nothing to measure (see below). |

**Evidence decides the mark.** For each item, record whether you **verified** it (you ran the
command, saw the check block a merge, read the API result) or **only read** it (a doc or config
says so). An item backed only by reading counts as partial at best. A check that reports green
while it skips counts as absent.

### Overall score

1. **10/10**: every applicable dimension is ★.
2. **9/10**: every applicable dimension is ✓ or better. One ~ is allowed if an external blocker is
   written down, such as hardware not yet owned or a hosting plan that cannot enforce checks.
3. **Otherwise**: 3 + the number of dimensions marked ~, ✓, ★ or n/a. The maximum is 8.

A box with nothing in place scores 3. Rule 3 never gives 9, so a 9 always means the whole bar is met.
In the original review, which scored by holistic judgment, rule 3 lands within one point of the
score given to every project. Write the per-dimension row next to the score, for example
`G ✓ · R ~ · J ✓ · W ✓ · P – · D ~ → 8`, so anyone can recompute it.
Upgrading a mark never lowers the score: `G ✓ · R ~ · J ✗ · W ✗ · P – · D ✗ → 6` becomes
`G ★ · R ~ · J ✗ · W ✗ · P – · D ✗ → 6`, because ★ counts like ✓ under rule 3.

### Not applicable

Mark a dimension n/a only when its subject does not exist. Write down the reason. An auditor who
can name a part of the dimension that applies scores that part instead.

- **G, J, W and D are never n/a.** Every project has a merge, a core promise, a worker and defects.
- **R** is n/a only when the product runs against nothing beyond its language runtime: no database,
  browser, OS feature, hardware or upstream API. Even then, test on each OS the users run.
- **P** is n/a for a library that is not deployed, ships no installer and vendors nothing. If it
  has known dependents, a scheduled build of a dependent against the library's head is its real-use
  signal, so P applies.
- For the orchestration level alone, R is usually n/a.

## The eight audit questions

An auditor answers these for each repo, then marks the dimensions.

| # | Question | Feeds |
|---|---|---|
| 1 | **Merge gate:** what protects the default branch, which checks are required, and can a red PR merge? | G |
| 2 | **CI contents:** what does each job run (lint, type checks, coverage floors, static analysis, automated review)? | G, W |
| 3 | **Test depth:** how much is unit tests against fakes, how much real dependencies, how much end to end? Do mocks dominate? | R |
| 4 | **Outside judges:** is there any oracle the authoring agent did not write? | J |
| 5 | **Agent-facing verification:** can a worker run the full check locally, and does AGENTS.md say what proof to attach? | W |
| 6 | **Post-merge and production feedback:** deploy checks, monitoring, errors an agent can fetch, freshness of vendored copies. | P |
| 7 | **Track record:** across the last 30 to 200 CI runs, how many flakes, and which defects reached the default branch past CI? | D, G |
| 8 | **Gaps:** which kinds of breakage would pass every gate today? | all |

Answer question 8 concretely, because it shows each dimension's real score. "A migration that
crashes on a populated database" is an answer. "Some edge cases" is not.

## G: Enforced gate

The merge needs the checks to pass, and the change being judged cannot weaken or bypass them.

**9 needs:**
- Required checks on the **head commit**, enforced by the host's branch protection. Where the host
  or plan cannot enforce them, a mechanical `ready` script does it. Merges go only through that
  script, and the gap is written down.
- A **tamper guard**. A PR that deletes or skips tests, adds retries, or edits gate config
  (workflows, coverage floors, static-analysis config) is flagged and needs the owner's explicit
  approval.
- Default-branch CI runs are **never cancelled** by a newer push. Every merge gets a full run.
- Review findings **block** "ready" unless the owner accepts them.

**10 needs:**
- The judge's definition comes from the base branch or another place the PR cannot change, so a
  PR cannot rewrite its own judge.
- Owner-only approvals and labels are tied to the head commit the owner saw, and a new push clears
  them.
- No automation writes to the default branch outside the gate, including docs bots and release
  jobs.
- Coverage and quality floors only go up. Lowering one is treated like any other gate edit.

**Evidence:** the protection settings read from the host's API, or the `ready` script and the record
that merges go through it. A PR that was blocked while red. The tamper guard's output on a PR that
deleted a test. Default-branch run history with no cancellations. Who applied each owner-only label,
and on which commit.

**Failure stories:**
1. CI had never once been red, yet a separate reviewer found about 40 defects at green heads.
   Nothing was required, so green meant nothing.
2. Every push to main cancelled the run before it. A broken merge sat under a newer commit whose
   run also got cancelled, and nobody saw a red result.
3. A static-analysis job showed green on every PR because, without its token, it skipped the
   analysis and exited 0.
4. A docs-regeneration job pushed straight to main, so it changed the default branch without
   running the gate.
5. An approval label stayed on a PR after more commits were pushed, so code the owner never saw
   counted as approved.

## R: Real-thing tests

The riskiest paths run against the real dependency, not a fake the author wrote.

**9 needs:**
- The riskiest paths run against the **real dependency, at the version production uses**: the real
  database, the browser engines users have, the real OS or hardware, the real upstream contract.

**10 needs:**
- Every path that a defect has escaped through now runs against the real thing.
- Version drift is caught automatically. Tests pin the production version, and a scheduled job
  runs against the dependency's latest version and opens an issue when it breaks.
- Any fake that remains passes the same contract suite as the real dependency.

**Evidence:** the test inventory split into real, fake and mock. CI jobs that start the real
database, browser or service, with the version they use next to the production version. Recorded
fixtures with their capture date and source. The contract suite and its last run against the real
dependency.

**Failure stories:**
1. A fake and the code it tested used the same wrong field name, so both drifted together and every
   test passed against a contract the real service never had.
2. Migrations were tested only on an empty database. The first one to meet populated data crashed.
3. UI tests ran only in one desktop browser engine, and phone-layout bugs reached users of another
   engine.
4. The app reported success after setting an OS feature, but no test asked the OS whether it
   happened. On some platforms it never did.
5. The real service under test was pinned hundreds of commits behind, so tests passed against
   behaviour that production had already changed.

## J: Outside judge

At least one check of the product's core promise comes from somewhere other than the author.

**9 needs:**
- At least one oracle for the product's **core promise** that the author did not write. Examples: a
  reference implementation, an official validator, reconciliation against real data, an eval judge
  from a different model family, an independent verifier.
- It runs on **every PR**, or nightly with an issue opened automatically on failure.

**10 needs:**
- The judge runs on every PR and covers every part of the core promise, not one slice of it.
- Before "ready", an independent verifier from a different model family runs the product at the
  head commit and tries to falsify each acceptance criterion.
- Review reads the change against the issue's acceptance criteria and asks whether the tests are
  adequate, not just whether the diff looks right.

**Evidence:** name the core promise in one sentence, then the oracle that checks it and who wrote
that oracle. Its CI job or schedule, and the issue it opened the last time it failed. For a model
judge, its model family next to the author's.

**Failure stories:**
1. The tests were rigorous, but every expected output was generated by the code under test, so the
   tests could only confirm the code agreed with itself.
2. The product was a prompt, and CI checked only that certain phrases appeared in it. Behaviour was
   never judged.
3. The one real outside judge ran weekly, was optional, and made unauthenticated calls that never
   reached the paths that mattered.
4. In a finance app, nothing compared computed balances with a source the code didn't produce.
   Double counting across sources and a wrong net worth were found only later, by hand.
5. A parity check between two implementations covered only the dozen shipped scenarios, so
   divergence on any other input went unseen.

## W: Worker-runnable proof

A worker can run the whole gate itself and knows what proof to attach.

**9 needs:**
- **One command** runs the whole gate locally.
- AGENTS.md says **how to prove a change works** and **what evidence to attach**.
- Where there is a UI, a **verify skill** exists that drives the running product and records
  evidence.

**10 needs:**
- A test confirms the local command covers every CI step, so the two cannot drift.
- The PR body's proof is linted: a proof table with one row per acceptance criterion, a "not
  verified" section, a "gate changes" section, the closing reference, and for bug fixes a test
  that changed.
- Bug fixes start with a test that fails on the base branch, and its failing output is in the PR.
- The worker's final report is checked mechanically against the host (checks, review, proof) rather
  than trusted.

**Evidence:** run the one command yourself on a clean checkout. The AGENTS.md section on proof. The
verify skill and an example of its evidence in a recent PR. The PR-body lint and a PR it rejected.

**Failure stories:**
1. "Done" meant green checks plus the worker's own report, and nothing measured whether the merged
   work was correct.
2. The local CI script was missing steps that CI ran, so a worker's clean local run went red in CI.
   Worse, CI was green on steps the worker never ran.
3. Behaviour evals existed but ran only by hand, and only for one of several commands.
4. AGENTS.md had no proof section, so each worker attached different evidence or none, and the
   reviewer could not tell what had been checked.

## P: Real-use feedback

What runs in the world reports back, and silence is treated as a failure.

**9 needs:**
- Deployed things expose **health and errors an agent can fetch**, with an **alarm when they go
  silent**.
- **Vendored copies** are checked for freshness against their source.
- **Shipped installers are smoke-tested** on a clean machine: install, launch, uninstall.

**10 needs:**
- Every deployed failure becomes an issue automatically, with the deployed commit attached.
- The deployed commit is visible, for example in a health endpoint, and a post-deploy check confirms
  it matches what was merged.
- The silence alarm has been tested by making the thing go silent on purpose.

**Evidence:** fetch the health and error endpoints yourself. Find the alarm and its last firing. The
freshness check on each vendored copy. The installer smoke job and the clean image it uses.

**Failure stories:**
1. A live site served a bug that main had already fixed, because the bundle copied into it was
   never refreshed and nothing compared it with its source.
2. The production canary had been dark for days, and nothing noticed because no alarm watched for
   silence.
3. Release installers were built and published but never launched.
4. A merge deployed straight to production, and nothing watched the live site afterwards.

## D: Defect ratchet

Each escaped defect makes the gate stronger, so the same kind of bug cannot escape again.

**9 needs:**
- Every escaped defect is **traced to the PR that introduced it** and gets a check that catches its
  **whole class**, not just the one instance.
- The next bug-hunt pass finds **at most 2 defects per repo that CI should have caught**.

A **bug-hunt pass** is a dated, adversarial search for defects on the default branch. Each finding
becomes an issue. A defect is **CI-catchable** if a test or check of a kind the repo already runs
could have caught it. A defect that needs a device or a person to find does not count.

**10 needs:**
- **Two consecutive** bug-hunt passes find **zero** CI-catchable escapes.
- The bug-report form asks which change introduced the defect, and fixes link to it.

**Evidence:** the last two bug-hunt passes and their issue lists. For each escaped defect, the
introducing PR and the class-level check its fix added, such as a property test, a state-machine
test, an invariant over every screen, or a lint rule. The count of CI-catchable escapes per pass.

**Failure stories:**
1. Several hundred bug-hunt issues were filed, and none was traced back to the PR that caused it,
   so nobody learned which gate had let it through.
2. One bug hunt found twelve bugs in one repo. Each fix patched its instance, and the same class of
   input-handling bug kept reappearing.
3. Layout bugs were fixed screen by screen. No invariant ran over every screen, so the next screen
   broke the same way.
4. A coverage floor was lowered in passing during an unrelated change, and the gate accepted it.

## Host-agnostic mechanisms

The bar does not depend on one host. Where a mechanism above is host-specific, use the equivalent,
or the fallback when the host has none. The host names below are pointers to check against your
host's docs. They are not tested configurations.

| Need | On GitHub | Elsewhere | No hosted VCS |
|---|---|---|---|
| Required checks on the head commit | Rulesets or branch protection with required status checks | GitLab protected branches with "pipelines must succeed"; Bitbucket merge checks; Azure DevOps branch policies with build validation | A local `ready` script that runs the gate on the head commit. The person who merges runs it, and merges only on exit 0 |
| A PR cannot rewrite its own judge | `pull_request_target`, or a reusable workflow pinned by commit SHA from a protected repo. The pin protects only the called workflow. The caller must also come from the base branch or a required workflow, with its conditions and inputs out of the PR's reach, or the PR can skip the judge with a false `if` | Keep the judge's pipeline definition in a separate, protected project or path that the PR cannot edit | The `ready` script lives outside the repo it judges |
| Worker identity separate from the owner | A GitHub App | A bot user, project access token or service principal | A separate OS user and git identity for workers; the owner's credentials are not reachable from a worker session |
| Owner-only labels | Labels checked by actor and timestamp through the API | Approval rules, or protected labels where the host has them | A signed note or tag from the owner naming the head commit |
| Tamper guard and PR-body lint | A required workflow | A required pipeline job | Steps in the `ready` script |
| Scheduled judges and drift checks | Scheduled workflows that open an issue | Scheduled pipelines | A scheduled task on the build machine that writes to the issue list or a log the owner reads |

**Model access.** The standard does not depend on how models are reached: subscriptions, the
Anthropic API, AWS Bedrock or another provider. Two things touch it. A model judge for J or the
independent verifier needs access to a **second model family**, and a cost cap per PR. And
worker identity (G) is about the host account, not the model account: a worker on the owner's API
key can still act under its own host identity. Many outside judges are not models at all. A
reference implementation, an official validator or real data often makes a better oracle.

**IDE.** Nothing here needs an IDE. The gate, the verify skill, the `ready` script and the audit all
run from a command line, so a worker in any editor, or none, gets the same result.
