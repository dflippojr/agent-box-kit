# 04 — Guardrails

Goal: make the safe behavior the default behavior, using mechanisms that fire regardless of how
carefully the agent reads its instructions.

## Principle: enforce, don't request

An instruction in `AGENTS.md` is a request. A hook, a permission rule, a CI check or a
sandbox is enforcement. For anything where a mistake is costly (secrets, sensitive data, destructive
commands, production access), use enforcement and keep the instruction as documentation.

Prefer layers that do not depend on which agent is running:

1. **Git pre-commit hook** or CI check: works for every agent and for humans. Use a hook only
   where the owner accepts the tooling it needs; do not add a Python hook to a repo whose stack has
   no Python. Otherwise the agent runs the check itself before each commit. That is a request, not
   enforcement, so keep CI and human review as the backstop.
2. **Filesystem and permission rules** of the harness (deny-lists, allow-lists) where supported.
3. **Harness hooks** (pre-tool-use, post-tool-use) where supported, as an extra layer.

Only allow broad auto-approval of edits and commands when the enforcement layers are in place and
tested.

## What a useful secrets/sensitive-data guard does

`scripts/secret_guard.py` implements this (stdlib Python, works with any agent or a human):

```
python scripts/secret_guard.py --staged         # the agent runs this before every commit; exit 1 on findings
python scripts/secret_guard.py --tree           # whole-tree scan; run it in CI as well if the repo matters
python scripts/secret_guard.py --install-hook   # optional: only where the owner wants a git hook and Python is acceptable
```

Running it yourself before each commit depends on the agent doing it, so it is weaker than a
hook. A hook is also skipped by `git commit --no-verify`, so neither is enforcement. Keep CI and
review as the backstop.

The script lives with this skill, not in the target repo. Do not copy it into a repo, add it to a
repo's `AGENTS.md`, or make the repo depend on it: other agents may not have the skill, and a
non-Python repo should not need Python. Optional config `.secret-guard.json` (in the repo root,
only if the owner accepts a new file there) adds patterns (for example sensitive-data shapes for
your domain), allowed substrings and ignored paths; a single line can carry
`secret-guard: allow <reason>`.

Behavior to keep if you write your own:

- Scans the **staged diff's added lines** on commit; blocks on a match with a clear reason.
- **Never prints the full secret** in its own output (file, line, label, first four characters).
- Applies the placeholder allowlist to the **matched value**, not the whole line, so a real key on
  a line that also says "example" is still caught.
- Detects credential shapes (cloud keys, API tokens, private-key blocks, JWTs, "assigned secret"
  patterns) plus sensitive-data shapes relevant to your domain.
- Keeps a **placeholder allowlist** (`example`, `changeme`, `<...>`, `os.environ`) low-noise. A
  noisy guard gets bypassed.
- Offers an on-demand **whole-tree scan** for final checks.
- Is a safety net, not a substitute for keeping secrets out of the repo in the first place.

**Not implemented by the script: the transcript guard.** The source project also blocked commands
that print secret material into the session log (reading a `.env`, echoing a `*KEY*` variable),
because a leak into a shared or exported transcript is a leak even if nothing is committed. That
needs a harness pre-tool hook, which is harness-specific. If your harness supports one, add it; if
not, deny the agent read access to `.env` and key files and instruct it never to print them.

## Rules

- **Never bypass.** No `--no-verify`, no disabling the hook, no editing the guard to let a change
  through. A block is a defect to fix (remove the secret, use a placeholder, use an env var).
- **Secrets live in environment variables or a git-ignored `.env`.** Commit only `.env.example`
  with placeholders. Deny the agent read access to real `.env` and key files.
- **Log identifiers, not values.** Never log a full record or a raw prompt that may contain
  sensitive data.
- **Synthetic data only** in fixtures, tests and prompts when the real data is sensitive.
  Redact or tokenize before data reaches an LLM or a log line, and test the redaction.
- **Fail closed on authorization.** An empty allow-list must admit nobody, not everybody.
  Missing config should refuse to start, not fall back to permissive defaults.
- **Fail open on observability.** An audit logger or metrics hook must never break the build;
  wrap it so an error there is swallowed and logged.
- **Audit trail.** Optionally append a redacted one-line record per tool call to a git-ignored
  file. Log the tool name and a short redacted summary, never file contents.

## Model reviewers are advisory

If a model reviews or approves things (a smart approver, a code reviewer, an evaluator):

- The deterministic policy and the sandbox are the security boundary. The model is not.
- Give it no tools, no write access, and only the minimum context it needs.
- It may recommend; it must not be the only thing standing between a change and production.
  Prefer that it never auto-denies or auto-approves on its own authority at first.
- Roll out in stages: **off by default → shadow mode** (records recommendations, a human still
  decides) **→ live**, with an explicit exit checklist that says what must be true to advance.
- Restrict who can change its mode.

## Separate environments deliberately

When staging shares a host with production:

- Spell out every staging path, port, task and credential explicitly; do not derive them by
  appending `-staging` at runtime.
- Add an assertion function that refuses to operate on anything that is or sits inside a
  production location.
- State the trust model in one sentence. "Isolation here prevents accidents (wrong checkout, wrong
  port), not hostile code, because only trusted code runs" is a valid statement; hiding the
  assumption is not.
- Never copy production data or credentials into staging.

## Threat-model risky features

Before building anything with real authority (installs code, runs untrusted input, handles other
people's data, grants access), write a short threat model. See 07.
