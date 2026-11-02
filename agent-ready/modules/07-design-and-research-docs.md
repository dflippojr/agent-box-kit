# 07 — Design and research docs

Goal: decide expensive or risky things on paper first, and leave a record that stops the same
decision from being reopened.

## When to write a design doc

Write one before implementing anything that is security-sensitive, cross-cutting, hard to reverse,
gives software new authority, or has several plausible shapes. Skip it for routine changes.

### Design doc skeleton (`templates/DESIGN.md`)

1. **Product boundary**: what this is and, importantly, what it is not.
2. **Roles**: who does what (owner, operator, user, reviewer, automation).
3. **Trust boundaries**: what is trusted, what is not, and where the enforcement lives.
4. **Architecture**: objects, identifiers, data flow, forward compatibility.
5. **Permission model**: tiers or scopes, and what each allows.
6. **Lifecycle**: states and allowed transitions.
7. **Failure and revocation**: how to turn it off, roll it back, recover.
8. **Audit and retention**.
9. **Open decisions**, each with what input resolves it.

### Threat model (for anything with real authority)

- **Assets** to protect.
- **Attacker classes** (malicious user, compromised account, compromised dependency, insider).
- **Risks the design cannot solve.** Say so plainly. This section prevents false confidence.
- **Control owners**: for each mitigation, who enforces it (code, sandbox, CI, human process).
- **Abuse cases**, one per short subsection: scenario, what stops it, residual risk.

## Results docs: measure, then decide

For an experiment, benchmark or bake-off, write down: what was tested and how, the numbers
(including on a **hard** case, not just the easy one), the **decision**, and what evidence would
change it. A decision without the measurement behind it gets re-argued. Record why a rejected
option was rejected (license, cost, memory limits, no current need).

## Study docs: learning from other projects

When you study an existing project for ideas, write it up as:

- what it is, in one paragraph;
- findings mapped to the parts of *your* plan they affect;
- **what this changes in the plan**;
- **things not to copy**, and why (different product, different constraints);
- a **verification rule**: a finding is a hypothesis until you have checked it in your context.

Do not import a design wholesale because it worked elsewhere.

## Backlog and follow-ups

- Give each item a **kind**: `check` (verify something already built), `deferred` (part of built
  work, not done), `feature` (not scheduled).
- Use a **stable key** per item so syncing to an issue tracker is idempotent and never files
  duplicates.
- **Track unverified work openly.** If a live check has not been run (a device, a real environment,
  a production-like run), keep it as an unticked item in a visible verification list. Never let "the
  code merged" stand in for "it was verified." One issue that collects every unrun live check,
  ticked off by the owner, works well.

## Ship risky things dark

New features with authority start **off by default**, then **shadow** (observe and record), then
**live**, with a written exit checklist for each step (see 04). Record who may flip each switch.

## Record decisions

Dated, short, with the reason and the rejected alternatives. Put the durable ones where the next
agent will find them (design doc, `AGENTS.md`, or the issue), not only in a chat.
