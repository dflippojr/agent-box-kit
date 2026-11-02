# Host responses for the orchestrate tests

Every value here is invented: the `owner/app` repository, logins (`owner`, `worker-bot`,
`reviewer-bot`), issue and PR numbers, titles and bodies, branch names, commit ids (small counters)
and dates. Only the shapes follow GitHub's responses, trimmed to the fields the scripts read. This
repository is public, so never paste a recorded response in; `test_fixtures_are_synthetic` checks
for the obvious leaks.

| File | Shape of | Cases it carries |
|---|---|---|
| `issues.json` | `gh issue list --state all --json number,title,state,labels,body,createdAt` | 12 issues: a closed dependency, an open one, one missing from the list, no tier, two tiers, P0 to unlabelled, `reserved`, `user-present`, `needs-refinement` |
| `pr_cases.json` | `base`: the routes for one ready PR, keyed by the `gh api` path (or `graphql`, plus ` after=CURSOR` for later pages): the PR, its label events, check runs, commit status, review threads and branch push activity. `cases`: the routes each case replaces | all green; a pending, failed or cancelled check; a failed status; a rerun that passed; no checks; an unresolved thread (also on page 2); the accept label by the owner after the push, by a non-owner, by the owner before the push, and removed; an owner-only label applied by a worker; a missing proof table; an empty proof cell; a missing closing reference |

Update them by hand when GitHub changes a response shape the scripts depend on.
