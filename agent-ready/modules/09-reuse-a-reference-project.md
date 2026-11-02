# 09 — Reuse a reference project

Applies when you are building something new (a service, job or tool) that should follow an
existing project: same stack, same conventions, same operational shape. Goal: get the benefit of
what already works without copying its accidents, and leave the reviewer able to compare old and
new side by side.

**Evidence note:** this is a hypothesis. It has not been validated on a real build yet.

## The reference's docs are the map

Do not write a separate one-off map. If the reference project has an `AGENTS.md` and a `docs/`
layer (see 11), read those. If it does not, do 01 and 11 on the reference first, on a branch,
documentation only, and with the owner's OK before committing anything to the reference. Then the
knowledge stays in the reference for every later reader, not only for this task.

## The reference is evidence, not truth

An existing project works, but it may also contain bugs, dead code, old workarounds and copy-pasted
mistakes. Its docs may be inferred rather than verified. Before relying on a claim, check its
`Basis` line and any `unknown`, `inferred` or `owner to confirm` marks, and settle the ones that
matter to your task.

## Steps

1. **Read the reference's docs**, index first, then only the source files your task needs.
2. **Write the delta** in the new project's requirements (see 02): exactly what the new thing
   must do differently. Everything outside the delta is a candidate to reuse.
3. **Look for what the reference lacks that the new thing needs.** Its runtime doc lists safety
   properties (dry-run, limits, environment guard, idempotency). A missing one is not something
   to inherit; design it in (see 10 for data-changing jobs).
4. **Choose the reuse mode and record why** in the plan:
   - *Copy and adapt* (start from a copy of the reference). Default for a small job.
   - *Follow conventions only* (fresh code, same layout and style). Use when the reference is
     tangled or the new thing is small.
   - *Extract a shared library.* Only if the owner asks. It changes the reference and is a
     separate task.
5. **If several existing projects are candidates,** pick the closest and record why. Compare at
   most two; more is a research task.
6. **Plan against the docs** (see 02). Each task that reuses a pattern names the doc section or
   source file it borrows from. Commit messages say what the code was modeled on, so a reviewer
   can diff new against old.
7. **Keep the reference read-only** during the build. Copy out of it; never edit it as a side
   effect.

## What not to carry over

- Real hostnames, connection strings, credentials, cloud account IDs, customer or environment IDs.
- Hardcoded values that were configuration in disguise.
- TODO hacks, commented-out code, and workarounds for problems the new thing does not have.
- Tests that pass only because of the reference's data. Rebuild fixtures for the new behavior.

Run the secret guard (04) before the new project's first commit, since copied files are the usual
way a credential travels.

## Verify parity

- Run the reference's test suite as your baseline before copying anything.
- Every adapted part needs an equivalent test. Copying code without its tests transfers the risk
  but not the safety net.
- Where behavior should match the reference, run the same fixture through both and compare.
  Record intentional differences in the plan.

## Keep context small

Do not paste the reference into the session. Work from its docs and file paths, and open only the
files the current task needs.

## Exit criteria

- The reference has an `AGENTS.md`, a docs layer and a recorded baseline.
- The delta and the reuse mode are written down, with the reason.
- The plan's tasks cite the doc sections or files they borrow from.
- Nothing environment-specific or secret came across, and the reference is unchanged apart from
  approved documentation.
