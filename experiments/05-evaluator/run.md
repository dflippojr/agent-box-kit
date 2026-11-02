# Run steps: module 05 evaluator-value experiment

Question: when several candidate tests all pass `red_green_gate.py`, does an advisory evaluator
pick the one grounded in the source? Synthetic cases only. No production data.

## Layout

`cases/NN-slug/` holds `source.md`, `target.py` (buggy), `fix.patch`, `candidates/test_a.py`,
`test_b.py`, `test_c.py`, and `meta.json` (`{"grounded": "b"}` or `null` for a negative control).
Cases 01-08 each have one grounded candidate. Cases 09 and 10 are negative controls.

## Steps

1. **Gate every candidate.** From the repo root:
   `python experiments/05-evaluator/run_gates.py`
   It builds a throwaway repo per candidate, runs the gate with `--red-pattern AssertionError`
   and pytest, and writes `gate-log.txt`. Exit 0 means all 30 candidates are red-to-green, so
   the gate alone cannot separate them.
2. **Baseline.** `python experiments/05-evaluator/heuristic.py --csv heuristic.csv`
3. **Evaluator, one fresh session per case.** For each case run
   `python experiments/05-evaluator/build_input.py experiments/05-evaluator/cases/NN-slug`
   and give the output as the whole input of a new session with no tools and no shared context.
   `build_input.py` never prints `meta.json`. Keep only the returned JSON.
4. **Score.** Fill `results.csv` (case, candidates passing the gate, evaluator pick, grounded id,
   correct, heuristic pick, model, notes). For a control, `none` is correct.
5. **Decide** with the rule in `RESULTS.md`. Do not commit raw transcripts.

## Re-running

The numbers depend on the model. Record the model and the number of runs for every repeat.
