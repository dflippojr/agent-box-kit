Answers: how to start a throwaway instance with synthetic data, drive it and tear it down.
Read when: you need to prove a change in the running product without touching real data.
Basis: stub written by box-bootstrap; replace each `<...>` and this line.

# Disposable instance

| Step | Command | Notes |
|---|---|---|
| Start | `<cmd>` | synthetic data only; no real data or credentials |
| Seed synthetic data | `<cmd>` | |
| Drive | `<cmd or URL>` | |
| Tear down | `<cmd>` | leaves nothing behind |

## What it must never touch
- <production database, real accounts, paid or rate-limited APIs>

## Unknown / owner to confirm
- <item>
