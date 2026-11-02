The host does not enforce required checks here, so a change merges only through
`python scripts/ready.py --body FILE`. It runs the gate, the tamper guard and the PR-body lint
on the head commit, and the person who merges merges only on exit 0.
