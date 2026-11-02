---
name: verify
description: Prove a change to @@PROJECT@@ works in the running product and record the evidence. Use before reporting a change done.
---

# verify

Stub written by box-bootstrap. Replace each `<...>` with this project's real commands, then
delete this paragraph. Until then this skill proves only what the gate proves.

1. Run the gate: `python scripts/check.py`. Keep its output.
2. Start a disposable instance as [docs/disposable-instance.md](../../../docs/disposable-instance.md)
   says: `<start command>`.
3. Drive the change: `<command, script or browser steps>`. Record `<output, screenshot or log>`.
4. Tear the instance down: `<stop command>`.
5. Put the evidence in the change description's `## Proof` table, one row per acceptance
   criterion. Say what you could not drive under `### Not verified`.
