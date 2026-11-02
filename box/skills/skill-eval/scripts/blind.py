"""Blind pairwise judging for skill-eval. Stdlib only. Imported by skill_eval.py; it has no
command line of its own.

Each judged pair is one task and one repeat: version A's run against version B's. The pair is
shown as Output X and Output Y in an order drawn from a seeded random generator, so the judge
cannot learn which version is which from position, and the prompt never says that a version,
a skill or a change exists. The order is recorded and undone after the judge answers.

Only pairs where both sessions completed go to the judge. A pair where one or both failed is
scored by rule in report.py, so a failure is never silently dropped.
"""
import json
import random
import re
from pathlib import Path

PROMPT = Path(__file__).resolve().parent.parent / "judge-prompt.md"
SCORES = (1, 2, 3, 4, 5)


def pairs(records, seed):
    """[(task, repeat, a_record, b_record, x_is_a)] for every task and repeat where both versions
    ran without a failure, in a stable order, with a seeded coin per pair."""
    runs = {}
    for r in records:
        if r.get("kind") == "task" and not r.get("error"):
            runs[(r["task"], r["repeat"], r["version"])] = r
    rng = random.Random(seed)
    out = []
    for task, repeat in sorted({(t, i) for t, i, _ in runs}):
        a, b = runs.get((task, repeat, "A")), runs.get((task, repeat, "B"))
        if a and b:
            out.append((task, repeat, a, b, rng.random() < 0.5))
    return out


OUTCOME = {"ran": "ran", "failed": "ran and failed", "denied": "refused; it did not run",
           "no result": "no result seen"}
OUTPUT_SHOWN = 800  # characters of each command's output, from the end


def render(record):
    """What the judge sees of one run: the reply, each shell command with what became of it, and
    the files it created, changed (as a diff) or deleted."""
    parts = ["Final reply:", "", (record.get("result") or "(no reply)").strip(), ""]
    commands = record.get("commands") or []
    parts += ["Shell commands requested:" if commands else "Shell commands requested: none seen"]
    for c in commands[:40]:
        if isinstance(c, str):  # a record from before outcomes were read
            c = {"command": c, "status": "no result", "output": ""}
        parts.append("- `%s`: %s" % (c["command"].replace("\n", " ")[:300],
                                     OUTCOME.get(c["status"], c["status"])))
        output = (c.get("output") or "").strip()
        if output:
            parts += ["  ````", "  " + output[-OUTPUT_SHOWN:].replace("\n", "\n  "), "  ````"]
    files, diffs = record.get("files") or {}, record.get("diffs") or {}
    deleted = record.get("deleted") or []
    parts += ["", "Files deleted: %s" % (", ".join(deleted) if deleted else "none")]
    paths = sorted(set(files) | set(deleted))
    parts += ["", "Files created, changed or deleted (files the task supplied are shown as a diff):"
              if paths else "Files created, changed or deleted: none"]
    for path in paths:
        if path in deleted:
            parts += ["", "#### %s (deleted)" % path, "````diff",
                      diffs.get(path, "(contents not kept)").rstrip(), "````"]
        elif path in diffs:
            parts += ["", "#### %s (edited)" % path, "````diff", diffs[path].rstrip(), "````"]
        else:
            parts += ["", "#### %s" % path, "````", files[path].rstrip(), "````"]
    return "\n".join(parts)


def prompt(task, dimensions, x, y):
    """The judge's whole input. `dimensions` is {name: what it means}."""
    dims = "\n".join("- **%s**: %s" % (k, v) for k, v in dimensions.items())
    return "\n".join([
        PROMPT.read_text(encoding="utf-8").rstrip(), "",
        "## Task given to both agents", "", "````", task["prompt"].strip(), "````", "",
        "## Rubric", "", task["rubric"].strip(), "",
        "## Dimensions to score (1 to 5, or null where it does not apply)", "", dims, "",
        "## Output X", "", render(x), "",
        "## Output Y", "", render(y), ""])


def parse(text, dimensions):
    """The judge's verdict as {"winner": "X"|"Y"|"tie", "reason", "scores"}, or None."""
    text = text or ""
    for m in reversed(list(re.finditer(r"\{", text))):
        try:
            data, _ = json.JSONDecoder().raw_decode(text[m.start():])
        except ValueError:
            continue
        if not isinstance(data, dict) or "winner" not in data:
            continue
        winner = str(data["winner"]).strip().upper()
        winner = {"TIE": "tie", "X": "X", "Y": "Y"}.get(winner)
        if not winner:
            return None
        scores = {}
        raw = data.get("scores") if isinstance(data.get("scores"), dict) else {}
        for side in ("X", "Y"):
            given = raw.get(side) if isinstance(raw.get(side), dict) else {}
            scores[side] = {d: given.get(d) if given.get(d) in SCORES else None
                            for d in dimensions}
        return {"winner": winner, "reason": str(data.get("reason", ""))[:500], "scores": scores}
    return None


def unblind(verdict, x_is_a):
    """Map X/Y back to A/B."""
    a, b = ("X", "Y") if x_is_a else ("Y", "X")
    winner = {"tie": "tie", a: "A", b: "B"}[verdict["winner"]]
    return {"winner": winner, "reason": verdict["reason"],
            "scores": {"A": verdict["scores"][a], "B": verdict["scores"][b]}}
