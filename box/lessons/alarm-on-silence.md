# Alarm when a deployed thing goes silent

**Rule:** Give each deployed thing health and errors an agent can fetch, and an alarm that fires when it goes silent. Evidence row: ["9 needs" bar per dimension (each dimension)](../../EVIDENCE.md)

**Why:** Monitoring that only reports failures says nothing when the thing stops reporting at all.

**Incident:** A production canary had been dark for days, and nothing noticed because no alarm watched for silence.

**Enforced by:** [P: Real-use feedback](../STANDARD.md#p-real-use-feedback)

**Evidence:** observed

**Status:** enforced
