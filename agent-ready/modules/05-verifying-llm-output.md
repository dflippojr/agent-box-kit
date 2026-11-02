# 05 — Verifying LLM output

Applies when (a) the product you are building calls an LLM, or (b) you must decide whether
model-generated code, tests or text can be trusted. The main lesson: a plausible result is not a
correct one, and a model asked to check itself often agrees with itself.

## The mechanical gate is the authority

- Decide correctness with something you can **observe**: a compiler, a test run, a schema
  validator, a script with an exit code. Do not ask a model whether the test reproduces the bug;
  run it on the buggy code (must fail), apply the fix, run again (must pass).
- A model evaluator is **advisory**. Scope it to what the mechanical gate cannot check (is the
  input grounded in the source? does it target the right code path?). Tell it explicitly not to
  re-judge what the gate already decided. It can steer the next attempt; it can **never** override a
  mechanical failure.
- **The check must verify its own preconditions.** A red/green script that ran on a
  half-reverted tree produced a false red. Assert a clean tree and a clean baseline before running
  the gate, and restore state afterward even on error.
- **Test the gate on a known bad case.** A test that is green before the fix must be rejected;
  confirm that it is.

`scripts/red_green_gate.py` implements this for any language (you supply the test command):

```
python scripts/red_green_gate.py --fix fix.patch [--red-pattern REGEX] -- <test command>
```

It requires no tracked changes (an untracked new test file is fine), checks the patch applies,
runs the command on the buggy tree (must fail), applies the patch, runs it again (must pass), and
always reverts and verifies the tree. Exit 0 = red then green, 1 = the test does not reproduce the
bug, 2 = the harness itself failed (missing command, timeout, unappliable patch). It never treats a
broken harness as red. Use `--red-pattern` to require that the red failure is the *expected*
failure, since a test can also be red because of a typo.

A real trial: run against seven small historical bug-fix commits from one project (test
committed as the base, source change as the patch), it reported red-then-green for six. For the
seventh it reported that the test already passed on the buggy code; reading the diff, the "fix"
appears to change behavior only for a `None` value the test never used. Treat a FAIL as a prompt to look, not as proof the fix was
wrong: some fixes are refactors or cleanups, not behavior bugs.

## The refine loop

Generate → run the gate → feed the **failing output** and the previous attempt back → regenerate.

- **Cap iterations at two or three.** An uncapped loop is a silent cost and time sink.
- On hitting the cap, emit an **honest incomplete** result (for example, a disabled test with a
  reason) rather than the last attempt dressed up as success.
- Report each iteration in one line (verdict and reason) so a reviewer can see the loop worked.

## Grounding and honesty

- Tell the model to use **only values that appear literally in the source** (log, document, code)
  and never fill in "typical" values from its own knowledge. Say why: a test built from invented
  inputs can pass before the fix and hide the bug it claims to catch.
- Give it an explicit **escape hatch**: if required information is missing, mark the result
  not-recoverable and list what is missing. Make the escape hatch a real, tested path with a
  negative fixture where the information truly is absent.
- Call out the **failure you have seen or fear** by name in the prompt ("do not write the
  assertion backwards; the test must fail now and pass after the fix"). Concrete anti-patterns
  work better than general advice.
- Send the complete relevant context in one call rather than pre-summarizing it, unless it is too
  large.
- Ask for **structured output** (a strict JSON shape, "return only the JSON") and parse it
  defensively.
- Where the platform supports it, prefer mechanical grounding (citations tied to source lines)
  over instruction alone. Confirm the feature exists on your deployment before planning around it.

## Prompts are code

- Keep prompts in files (for example `prompts/*.md`) with named placeholders, loaded by a small
  loader. Never inline them as string literals. They are reviewable, diffable and testable.
- If results are cached by input, include a **prompt-version token** in the cache key so changing
  the prompt invalidates stale results instead of replaying them.
- One role per call is a reasonable default (reconstruct, generate, evaluate as separate calls
  with single-purpose prompts). It is a design choice that made the prompts easier to reason
  about; it is not proven better than a single call.

## Testing without paying or flaking

- **Record and replay** model calls so development and demos do not re-bill or flake on the
  network. Cache by input hash and prompt version.
- Unit-test the pipeline **offline with mocked clients**; keep a separate, small **live smoke
  test** that proves credentials and endpoints work.
- Record **API contract facts** you discover the hard way, with the date (unsupported parameters,
  required client libraries, deprecated options). They will not be in your training data.

## Known limitation to design for

When there is only one input that triggers the failure, the mechanical gate and the model evaluator
will always agree, so you cannot tell whether the evaluator adds value. To see the difference
you need a case where several inputs turn the test red-to-green but only one is grounded in the
source. Seed one deliberately before claiming the evaluator earns its cost.
