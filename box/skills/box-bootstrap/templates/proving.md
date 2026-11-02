## Proving a change
Run the whole gate locally, with one command, before you say a change is done:

```
python scripts/check.py
```

It runs every step CI runs and ends with `GATE_PASS`. @@MERGE_GATE@@

Attach the proof to the change description, from the template at `@@PR_TEMPLATE@@`: a
`## Proof` table with one row per acceptance criterion (criterion, how you verified it,
evidence), then `### Not verified` and `### Gate changes`, and the closing reference.
@@PR_CHECKS@@

- Verify, don't assert: evidence is output you saw, not a claim.
- A bug fix starts with a test that fails on the base branch; paste its failing output.
- Do not delete, skip or loosen a test, add a retry, or edit gate config (CI config, the
  scripts in `scripts/`, coverage, pytest or lint settings) unless the issue asks for it. List
  each such change under `### Gate changes`: the tamper guard flags it, and it needs the
  owner's explicit approval.
- To prove behaviour in the running product, follow the verify skill
  (`.agents/skills/verify/SKILL.md`) on a disposable instance (`docs/disposable-instance.md`).

