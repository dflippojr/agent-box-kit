# 08 — Review and merge

Goal: make the human's review fast and trustworthy, and keep irreversible decisions with the human.

## The owner decides irreversible things

Do not merge, deploy, close issues, publish releases or delete shared resources unless explicitly
told to. Your job is to bring a change to "all gates green" and then say it is ready.

### "All gates green"

- The change is mergeable and up to date with the base branch (merge the base into your branch;
  do not rebase or force-push shared history unless told to).
- The full test suite passes on the **exact head commit**.
- Static analysis and linting pass, or a failure is documented as a false positive with a reason.
- Every review finding is fixed or answered with an explanation.
- A **full-diff** review at the final head is clean or has only accepted, tracked items.

## Handing a change to a reviewer

Write the description for someone who will read every line (`templates/PR-DESCRIPTION.md`):

- **What and why**, in a few sentences, with the issue or requirement reference.
- **How it was verified**: the commands and their results.
- **What was not verified**, and why. Include anything needing a device, a real environment or a
  person.
- **Risks and rollback.**
- **Follow-ups** filed as issues, not buried in prose.
- Attribution lines your organization or tool requires.

Keep commits small and readable so the reviewer can follow the story; do not squash the narrative
away before review.

## Handling review findings

- Fix real findings. Answer the ones you disagree with, with evidence.
- Distinguish new findings from old by timestamp against your last push.
- When each round surfaces one more edge case in the same area, stop patching the instance and fix
  the class (see 06). After three rounds, escalate to the owner.
- Re-review after each push; read the result before declaring ready.
- Use a **full** review for the final pre-merge pass. Incremental reviews (only commits since the
  last review) are fine between pushes if the range is safe (an ancestor of the head, no merge
  commits, same target branch); fall back to a full pass otherwise.

## Automated reviewers

If you run or design an automated reviewer:

- Give it a **read-only** view. The wrapper, not the model, writes the final comment.
- Embed the diff in the prompt so the reviewer does not need network access; state clearly when
  files were omitted.
- Mark what range was reviewed so later runs can be incremental, and **do not mark a truncated
  review as complete**.
- Fail closed on invalid options and on missing output; fall through to a fallback reviewer on
  quota or empty results.

## CI and deployment principles

Only relevant if the repo has CI/CD. These held up in a real pipeline:

- **One** test workflow. Publish and deploy only after it succeeds for the **exact commit**.
- Check out the reported **commit SHA**, never a branch name, in follow-on jobs.
- Never run pull-request code in a job that has secrets or deploy authority.
- Pin third-party actions to commit SHAs. Give each job the minimum permissions.
- Serialize deployments; a newer commit supersedes an older queued one.
- Deploy with **rollback**: verify before changing anything, swap side by side, health-check, and
  restore the previous version on failure.
- **Fail before changing anything** when preconditions are not met (dirty checkout, wrong branch,
  unavailable dependency).
- Optional optimizations (caches) must never block the pipeline.
- Verify a tool is authenticated **in the environment where it will actually run**. A desktop login
  is not evidence that a service account is logged in.
- Keep CI and infrastructure documented next to the code and update the doc in the same change;
  undocumented pipelines drift.
