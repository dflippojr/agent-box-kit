# GitHub API responses for the box-audit tests

Every value here is invented: issue numbers, titles and bodies, labels, branch names, commit ids
(small counters), dates and the `example/app` ruleset source. Only the shapes follow GitHub's
responses, trimmed to the fields the collectors read. This repository is public, so never paste a
recorded response in; `test_fixtures_are_synthetic` checks for the obvious leaks.

| File | Shape of | Cases it carries |
|---|---|---|
| `runs.json` | `repos/{repo}/actions/runs` | 40 runs: 14 pushes to main, 2 dynamic runs, 2 failed PR runs, 1 re-attempt |
| `labels.json` | `repos/{repo}/labels` | two defect labels (`bug`, `regression`) among ordinary ones |
| `issues_bug.json` | `repos/{repo}/issues?labels=bug` | two closed bugs, neither naming the change that introduced it |
| `rules_required.json` | `repos/{repo}/rules/branches/main` | a ruleset requiring a PR and two checks, `build` and `lint / lint` |

Update them by hand when GitHub changes a response shape the collectors depend on.
