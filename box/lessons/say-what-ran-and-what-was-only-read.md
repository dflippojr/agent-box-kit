# Say what ran and what was only read

**Rule:** In docs an agent writes, mark each command or claim as run or not run, and call nothing "verified" that was only read. Evidence row: [A doc says what was run and what was only read; "verified" only for what ran (modules 01, 11)](../../EVIDENCE.md)

**Why:** A reader trusts a "verified" claim and skips the check that would have found it false.

**Incident:** One generated AGENTS.md claimed every command was "run and verified" while listing a write path that was never run. Generated docs on another run said `Verified against: <sha>` for code that was only read.

**Enforced by:** none

**Evidence:** observed

**Status:** open
