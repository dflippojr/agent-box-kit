---
name: queue-fill
description: Fill a repo's issue queue with well-shaped issues a worker can finish. Three passes - gap (file box-audit's proposals), bug hunt (a dated, adversarial search whose findings become traced issues) and refinement (rewrite an answered needs-refinement issue and mark it ready) - all writing one issue shape that issue_lint.py checks. Use when the queue is empty or full of drafts, after a box audit, for a scheduled bug hunt, or when the owner has answered open questions.
---

# queue-fill

A dispatcher with a queue of drafts either sits idle or hands out work that fails review. This
skill leaves the queue full of issues a worker can finish: each has a testable Want, one tier
label, and either `ready` or an open question the owner can answer.

Every pass is a **dry run by default**: it prints what it would file or change and touches
nothing. It files or relabels only with `--apply`, and only after the owner has seen the dry run
and given the go-ahead. Issues are visible to everyone who watches the repo.

Each pass writes to a GitHub repository (`--repo OWNER/NAME`) or, for a project with no hosted
VCS, an issue folder (`--folder DIR`): one `<number>.md` per issue, the format
[`../../orchestrate/README.md`](../../orchestrate/README.md#issue-folder-no-hosted-vcs) defines
and `select.py` reads.

## The issue shape

Every pass writes this shape, and `scripts/issue_lint.py` checks it with box-audit's own card
rules (`card.py`'s `check_labels` and `check_parts`):

```markdown
## Problem
<What is wrong today, with the evidence.>

## Want
- <A testable outcome: a named test or check that fails today and passes after.>

## Constraints
- <What must not change; where tests go; what proof to attach.>

## Dependencies
Dependencies: #12, #15

## Out of scope
<The tempting neighbour.>

## Open questions
<Only with needs-refinement: each question the owner must answer.>
```

- The five parts in that order, each once and none empty. Other sections may sit between them.
- `## Dependencies` holds only `Dependencies: #N, ...` or `Dependencies: none`: `select.py`
  reads every line under it, so a note there holds the issue.
- Exactly one tier label (`tier:mechanical`, `tier:standard`, `tier:frontier`; see the
  orchestrate README), at most two `review:*` labels.
- A heading starting with `Open question` if and only if the issue is labelled
  `needs-refinement`. `ready` only with no open question, a Want that CI can verify, and no need
  for hardware or the owner.
- No host, account, employer, client or private repo names, hostnames, personal paths or
  credentials in titles or bodies.

```
python -B scripts/issue_lint.py body.md --labels "tier:standard, ready"   # or --issue-file 3.md
```

`ISSUE_OK` exits 0; `ISSUE_INVALID` and one problem per line exits 1; a usage error exits 2.
Pass `--allow-label NAME` for a repo's own topic labels.

The lint is deliberately conservative, because a question it misses gets promoted to `ready`.
It reads each line bluntly: HTML comments and tags stripped, link destinations dropped,
character references decoded, Unicode compatibility forms folded, Cyrillic and Greek look-alike
letters read as Latin, everything but letters and digits dropped. A line that then
contains `openquestion`, or two adjacent lines that do together, counts as open anywhere,
code blocks and comments included, so `## **Open** question` and `reopen questions` are both
flagged. It also rejects Markdown it does not model: HTML blocks (a comment that closes on its
own line, such as a tool's marker, is fine), Setext headings (text underlined with `=` or `-`),
and any line that looks like a code fence but is not an exact one at column 0 with plain
spaces (in a list item, a quote or indented, or with a non-breaking or other Unicode space),
and any U+0085, U+2028 or U+2029, which the host does not read as a line end.
To fix a flagged body, delete each answered question rather than marking it answered, reword
prose that says "open question", use `##` headings, put a blank line before a `---` rule, move
code blocks out of lists to column 0, retype fence lines with plain spaces and delete stray
line separators.

## Gap pass

**When:** after a box audit, or when the queue has no work for a dimension below the bar.

1. Run box-audit in report mode ([`../box-audit/SKILL.md`](../box-audit/SKILL.md)) and read the
   card.
2. `python -B ../box-audit/scripts/file_issues.py <card> --repo OWNER/NAME` (or `--folder DIR`)
   prints every proposal in the issue shape, skips titles already open and checks each label
   exists. A proposal that fails `issue_lint.py` stops it: the card check alone is looser. Show
   it to the owner.
3. With the go-ahead, rerun with `--apply`.

## Bug-hunt pass

**When:** on a schedule (the standard's D dimension counts passes), and after a run of escapes.

1. Note the date and the default branch's commit. Hunt adversarially on that commit: craft inputs
   against each script's documented contract, and report only what you reproduced by running it.
   Skip anything already open.
2. For each finding, find the change that introduced it (`git log -L`, `git blame`,
   `git log -S`) and decide whether CI could have caught it: yes when a test of a kind the repo
   already runs would have.
3. Write each finding as a draft file in a folder of its own, outside the repo:

   ```markdown
   ---
   title: Bug hunt: <what is wrong>
   labels: bug, tier:mechanical, ready
   ---
   ## Problem
   Found by: bug hunt 2026-10-27 at 0123456789ab
   Introducing change: #57
   CI-catchable: yes

   <What is wrong, the reproduction, observed against expected.>

   ## Want
   ...the rest of the shape.
   ```

   `Introducing change` is a PR (`#57` or its link), a commit, or `unknown`. The `bug` label and
   the `Bug hunt:` title let box-audit's D collector count the finding as a defect, by pass, and
   as traced when the change is named.
4. `python -B scripts/hunt.py <drafts> --repo OWNER/NAME` (or `--folder DIR`) checks every
   finding (the shape, the three lines, one pass, distinct titles), then prints them through
   `file_issues.py`'s filing: labels must exist, open titles are skipped. Show it to the owner.
5. With the go-ahead, rerun with `--apply`.

## Refinement pass

**When:** the owner has answered a `needs-refinement` issue's open question.

1. `python -B scripts/refine.py list --repo OWNER/NAME [--owner LOGIN]` lists the open
   `needs-refinement` issues: those with a comment by the owner first, quoting it, then the
   rest. In a folder, the owner answers under a heading starting with `Owner answer` in the
   issue file.
2. For an answered issue, read the issue and every comment. Rewrite the body in the issue shape
   around the answer: record the decision (who, when, what) in its own section, and fold it into
   Want and Constraints. If anything is still open, keep it under `## Open questions`. Keep the
   title.
3. `python -B scripts/refine.py apply <number> <new body> --repo OWNER/NAME` lints the new body.
   With no open question left, the new labels drop `needs-refinement` and add `ready`, and the
   body must pass with them. With a question left, the labels stay. If the lint fails, nothing
   changes: the issue keeps its body, its question and `needs-refinement`. Show the dry run to
   the owner.
4. With the go-ahead, rerun with `--apply`.

The owner's rule for this pass (2026-10-09): the refinement pass applies `ready` itself when the
lint passes and no open question remains, and only within a write the owner has approved.

## Owner-only labels

No pass ever adds, re-adds or removes an owner-only label (`gate-change-approved`,
`findings-accepted`). `refine.py` only removes `needs-refinement` and adds `ready`; every other
label stays as it is. `hunt.py` rejects a finding that carries one, and box-audit's card
check rejects a proposal that does. Creating a
missing label is the owner's call too: a missing label stops the pass before anything is filed.

## Limits

- Host passes are GitHub-only; elsewhere, use `--folder` or paste a dry run.
- The lint checks shape, not sense: whether a Want is really testable, or a finding real, is the
  author's job and the owner's review.
- In a folder, anyone who can edit the file can write an `Owner answer`; the folder's history,
  not the script, says who did.
- An owner comment is listed as an answer whatever it says. Read it before rewriting.
