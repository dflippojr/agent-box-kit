# 02 — Spec and plan

Goal: turn a rough request into requirements that can be checked, then into small tasks that can
be verified one at a time. Vague specs produce confident wrong work.

## The "ready" bar

A request is **ready** when an agent could implement it with **zero further product or design
decisions**. "Clear enough for a person to muddle through" is not ready.

- **Ready:** write it up as an issue spec (`templates/ISSUE-SPEC.md`): outcome, scope
  boundaries, dated decisions, real dependencies by number, acceptance checklist.
- **Not ready:** do not guess the missing decision. Write down exactly what is unresolved and what
  input each open point needs, then ask. When you do ask, ask once, concisely, with a recommended
  default, and keep going on whatever does not depend on the answer.
- Ground the spec in the repo: real paths, real conventions. Do not invent scope.
- Re-check live state (the issue, dependencies, the branch) before acting on a snapshot.

## Requirements

Use `templates/REQUIREMENTS.md`.

- **Every requirement has a verification step**: one concrete command or observable result. No
  exceptions. If you cannot say how it would be checked, it is not a requirement yet.
- Separate **MVP** from **stretch**. Keep the MVP short; a small MVP that works end to end beats a
  large one that does not.
- State **non-goals** explicitly. They prevent scope creep and settle later arguments.
- State safety handling up front: what data is sensitive and how it stays out of the repo, logs
  and prompts.
- Record **facts you confirmed against reality**, with the date, and mark unconfirmed ones as such.
  Example: "External API rejects parameter X (confirmed 2026-07-17)" versus "prompt caching:
  not yet confirmed; the smoke test was too small to prove it". Future sessions should not
  have to rediscover these.
- **Smoke-test external dependencies before planning around them** (credentials, an API, a model
  endpoint, a feature you have only read about). If it cannot be confirmed, plan a fallback.

## Plan

Use `templates/PLAN.md`. Each task has:

- **Delivers**: one small, coherent unit of working behavior.
- **Verify**: a command that runs non-interactively and returns a clear pass/fail (exit code).
  "Eyeball the output" is not a Verify. The build loop gates commits on it.
- **Risky**: yes or no. Yes for architectural judgment, security-sensitive logic, tricky external
  contracts, or first-time integration. The loop stops before a risky task so it gets a plan
  first.
- **Est**: aim for 30 minutes or less. Split anything larger.

### Ordering rules

- Task 1 stands up the skeleton: the project builds and an empty test passes.
- Land the **thinnest end-to-end slice** early so something demonstrable exists sooner. Add
  richness afterward.
- Put safety and data-handling tasks **before** any task that ingests real-world-shaped data.
- Create the thing before capturing evidence from it. Capture fixtures from a **real run**, not
  by hand-typing them.
- Design test data so safety handling cannot delete the value the test needs (for example,
  make the failure trigger a non-sensitive field so redaction never removes it).
- Include a **negative fixture** where the needed information is provably absent, so the
  "cannot do this honestly" path is exercised by a real case.
- Put stretch tasks below a `--- MVP complete above this line ---` marker.

### Review the plan before building

Do one deliberate pass (with extra reasoning effort if available): what will bite in the time
available, which tasks are secretly risky or secretly two tasks, and what reordering gets a
working core soonest. Apply the changes and commit the revised plan. In the reference project
this pass caught real ordering hazards before any code was written.

### The plan is living

Tick tasks as they finish. When you deviate (built a task early, reframed one, split one),
record it in the plan with a one-line reason. A plan that quietly stops matching reality is worse
than none.

## Exit criteria

- `REQUIREMENTS` has a verification step per requirement and an explicit non-goals list.
- `PLAN` tasks each have a runnable Verify and a risk flag; MVP marker is present.
- External dependencies are smoke-tested or have a fallback.
- The owner has seen the plan if any task is risky.
