"""Report maths and the report for skill-eval. Stdlib only. Imported by skill_eval.py; it has no
command line of its own.

Task sessions are compared in pairs: the A and B sessions of one task and repeat. Failures:
  - A session that failed after the agent started (timed out, crashed, no reply) is the
    version's outcome: it counts as not completed and as failing every check, and its pair's
    judge outcome is decided by rule: the completed side wins, two failures tie. The harness
    cannot tell a skill that makes the agent hang from an outage, so it counts both; rerun after
    an outage.
  - A session the harness could not start (infra: command not found, workspace error) says
    nothing about the skill. It and its partner are left out and listed.
  - A judge reply that could not be read is left out and listed.

Four signals compare version B (the change) with version A (the current skill):
  completion  share of task sessions that completed, B minus A, with a Newcombe hybrid score
              interval (difference of two proportions)
  checks      share of task sessions passing every deterministic check, B minus A, Newcombe
  judge       B's share of pairwise outcomes, a tie counting half, with a Wilson score interval
  trigger     share of trigger observations that were right (picked on a task prompt, not
              picked on a near-miss prompt), B minus A, Newcombe
A signal is worse or better only when its whole 95% interval is on one side (of 0, or of a half
for the judge). The verdict is worse if any signal is worse. Otherwise it is inconclusive when
completion is insufficient (fewer than MIN_COMPLETE of the planned pairs had both sessions
complete) or asymmetric (A and B completed different numbers of sessions). Otherwise it is better
if any signal is better, and no detectable difference if none is.
"""
import math

Z = 1.959963984540054  # two-sided 95%
MIN_COMPLETE = 0.8  # share of planned pairs that must complete on both sides for a verdict


def wilson(k, n, z=Z):
    """Wilson score interval for k successes in n (k may be fractional)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe(k1, n1, k2, n2, z=Z):
    """p2 - p1 with Newcombe's hybrid score interval (his method 10)."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1, z)
    l2, u2 = wilson(k2, n2, z)
    d = p2 - p1
    return d, d - math.sqrt((p2 - l2) ** 2 + (u1 - p1) ** 2), d + math.sqrt(
        (u2 - p2) ** 2 + (p1 - l1) ** 2)


def direction(lo, hi, null=0.0):
    return "worse" if hi < null else "better" if lo > null else "same"


def failed(record):
    return bool(record.get("error"))


def infra(record):
    """A failure before the agent started: the harness's, not the version's."""
    return failed(record) and bool(record.get("infra"))


def passed(record):
    """True when the session completed and every check passed; False otherwise."""
    return not failed(record) and all(c["pass"] is True for c in record.get("checks", []))


def tally(records, judgments, dimensions, planned=None, judged=None):
    """Every number the report shows, as a dict. `planned` is the number of task pairs the run
    meant to make (default: the pairs seen); `judged` whether the judge ran (default: whether any
    judgment exists)."""
    task = {}
    for r in records:
        if r["kind"] == "task":
            task[(r["task"], r["repeat"], r["version"])] = r
    keys = sorted({(t, i) for t, i, _ in task})
    pairs = [(t, i) for t, i in keys if all((t, i, v) in task and not infra(task[(t, i, v)])
                                            for v in "AB")]
    paired = {(t, i, v): task[(t, i, v)] for t, i in pairs for v in "AB"}
    unpaired = [r for k, r in sorted(task.items()) if k not in paired and not infra(r)]
    out = {"tasks": {}, "signals": {}, "unpaired": unpaired,
           "infra": [r for r in records if infra(r)],
           "failed": [r for r in records if failed(r) and not infra(r)]}
    judged = bool(judgments) if judged is None else judged
    by_pair = {(j["task"], j["repeat"]): j for j in judgments}

    def outcome(t, i):
        """B, tie or A for one pair; None when not judged or the reply was unreadable."""
        fa, fb = failed(paired[(t, i, "A")]), failed(paired[(t, i, "B")])
        if fa or fb:
            return ("tie" if fa and fb else "A" if fb else "B") if judged else None
        j = by_pair.get((t, i))
        return j["verdict"]["winner"] if j and j.get("verdict") else None

    def count(rows, test):
        return sum(1 for r in rows if test(r)), len(rows)

    outcomes = {p: outcome(*p) for p in pairs}
    verdicts = [j for j in judgments if j.get("verdict") and (j["task"], j["repeat"]) in outcomes]
    for t in sorted({t for t, _ in keys}):
        row = {}
        for v in ("A", "B"):
            row[v] = count([paired[(t, i, v)] for tt, i in pairs if tt == t], passed)
        mine = [w for (tt, _), w in outcomes.items() if tt == t and w]
        row["judge"] = [mine.count(w) for w in ("B", "tie", "A")]
        js = [j for j in verdicts if j["task"] == t]
        row["dims"] = {d: {v: mean([j["verdict"]["scores"][v][d] for j in js]) for v in ("A", "B")}
                       for d in dimensions}
        out["tasks"][t] = row

    for name, test in (("completion", lambda r: not failed(r)), ("checks", passed)):
        (k_a, n_a), (k_b, n_b) = (count([paired[(t, i, v)] for t, i in pairs], test)
                                  for v in "AB")
        out[name] = {"A": (k_a, n_a), "B": (k_b, n_b)}
        if n_a and n_b:
            d, lo, hi = newcombe(k_a, n_a, k_b, n_b)
            out["signals"][name] = {"value": d, "lo": lo, "hi": hi, "reading": direction(lo, hi)}

    won = [w for w in outcomes.values() if w]
    wins, ties = won.count("B"), won.count("tie")
    out["judge"] = {"B": wins, "tie": ties, "A": won.count("A"), "n": len(won),
                    "by_rule": sum(1 for (t, i), w in outcomes.items() if w and (
                        failed(paired[(t, i, "A")]) or failed(paired[(t, i, "B")]))),
                    "unread": sum(1 for j in judgments if not j.get("verdict"))}
    if won:
        share = (wins + 0.5 * ties) / len(won)
        lo, hi = wilson(wins + 0.5 * ties, len(won))
        out["signals"]["judge"] = {"value": share, "lo": lo, "hi": hi,
                                   "reading": direction(lo, hi, 0.5)}
    out["dims"] = {d: {v: mean([j["verdict"]["scores"][v][d] for j in verdicts])
                       for v in ("A", "B")} for d in dimensions}

    ok = [r for r in records if not infra(r)]
    trig = {}
    for v in ("A", "B"):
        pos = [r["skill_used"] for r in ok if r["kind"] == "task" and r["version"] == v
               and r.get("skill_used") is not None]
        neg = [r["skill_used"] for r in ok if r["kind"] == "near_miss" and r["version"] == v
               and r.get("skill_used") is not None]
        trig[v] = {"picked": (sum(pos), len(pos)), "near_miss_picked": (sum(neg), len(neg)),
                   "right": (sum(pos) + len(neg) - sum(neg), len(pos) + len(neg))}
    out["trigger"] = trig
    (ka, na), (kb, nb) = trig["A"]["right"], trig["B"]["right"]
    if na and nb:
        d, lo, hi = newcombe(ka, na, kb, nb)
        out["signals"]["trigger"] = {"value": d, "lo": lo, "hi": hi, "reading": direction(lo, hi)}

    planned = len(keys) if planned is None else planned
    complete = sum(1 for t, i in pairs if not failed(paired[(t, i, "A")])
                   and not failed(paired[(t, i, "B")]))
    out["completion"].update(planned=planned, complete_pairs=complete,
                             insufficient=complete < MIN_COMPLETE * planned or not planned,
                             asymmetric=out["completion"]["A"][0] != out["completion"]["B"][0])
    readings = [s["reading"] for s in out["signals"].values()]
    c = out["completion"]
    out["verdict"] = ("worse" if "worse" in readings
                      else "inconclusive" if c["insufficient"] or c["asymmetric"]
                      else "better" if "better" in readings else "no detectable difference")
    return out


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def spend(records, judgments):
    """{part: (sessions, usd, seconds, unknown-cost sessions)}. A session whose cost could not be
    read counts at its cap, so the total never understates the spend."""
    parts = {}
    for name, rows in (("A sessions", [r for r in records if r["kind"] == "task"
                                       and r["version"] == "A"]),
                       ("B sessions", [r for r in records if r["kind"] == "task"
                                       and r["version"] == "B"]),
                       ("Near-miss sessions", [r for r in records if r["kind"] == "near_miss"]),
                       ("Judge sessions", judgments)):
        usd = sum(r["cost_usd"] if r.get("cost_usd") is not None else r.get("budget", 0)
                  for r in rows)
        parts[name] = (len(rows), usd, sum(r.get("seconds", 0) for r in rows),
                       sum(1 for r in rows if r.get("cost_usd") is None))
    return parts


def pct(x):
    return "%d%%" % round(100 * x)


def frac(kn):
    k, n = kn
    return "%s/%d (%s)" % (fmt_num(k), n, pct(k / n)) if n else "n/a"


def fmt_num(x):
    return ("%d" % x) if float(x).is_integer() else ("%.1f" % x)


def clock(seconds):
    m, s = divmod(int(round(seconds)), 60)
    return "%dm %02ds" % (m, s) if m else "%ds" % s


def score(x):
    return "-" if x is None else "%.1f" % x


VERDICT_TEXT = {
    "worse": "**Verdict: worse.** B (the change) did measurably worse than A on at least one signal.",
    "better": "**Verdict: better.** B (the change) did measurably better than A, and worse on none.",
    "no detectable difference": "**Verdict: no detectable difference** between A and B at N=%d "
                                "repeats per version. That is not proof they are equal.",
    "inconclusive": "**Verdict: inconclusive.** Nothing read worse, but too few task pairs "
                    "completed on both sides, or A and B completed different numbers of "
                    "sessions, to call it better or no different. See Completion; fix any "
                    "outage and run again.",
}


def render(meta, records, judgments):
    dims = list(meta["dimensions"])
    t = tally(records, judgments, dims, planned=meta["n_tasks"] * meta["repeats"],
              judged=meta.get("judged"))
    verdict = VERDICT_TEXT[t["verdict"]]
    if t["verdict"] == "no detectable difference":
        verdict %= meta["repeats"]
    lines = ["# skill-eval: %s, A vs B" % meta["skill"], "",
             "- A (current): `%s`, SKILL.md sha256 %s" % (meta["a"]["name"], meta["a"]["sha"]),
             "- B (change): `%s`, SKILL.md sha256 %s" % (meta["b"]["name"], meta["b"]["sha"]),
             "- Task set: `%s` (sha256 %s), %d tasks, %d near-miss prompts" % (
                 meta["tasks_file"], meta["tasks_sha"], meta["n_tasks"], meta["n_near_miss"]),
             "- Runner: profile `%s`, model %s, judge model %s, %d repeats per version, seed %s" % (
                 meta["profile"], meta.get("model") or "CLI default",
                 meta.get("judge_model") or "CLI default", meta["repeats"], meta["seed"]),
             "- Caps: %.2f USD per session, %.2f per judge call, %.2f per near-miss session, "
             "%.2f in all" % (meta["run_budget"], meta["judge_budget"], meta["trigger_budget"],
                              meta["max_cost"]),
             "- Date: %s" % meta["date"], ""]
    if meta.get("stopped"):
        lines += ["**Partial run: %s.** The numbers below cover only what ran." % meta["stopped"],
                  ""]
    lines += [verdict, ""]
    reasons = ["%s %s" % (name, s["reading"]) for name, s in sorted(t["signals"].items())]
    lines += ["Signals: %s." % (", ".join(reasons) or "none had data"), ""]

    lines += ["## Overall", "", "| Measure | A | B | Effect [95% CI] | Reading |",
              "|---|---|---|---|---|"]
    s = t["signals"]
    if "completion" in s:
        c = s["completion"]
        lines.append("| Task sessions completed | %s | %s | B−A %+d pts [%+d, %+d] | %s |" % (
            frac(t["completion"]["A"]), frac(t["completion"]["B"]), round(100 * c["value"]),
            round(100 * c["lo"]), round(100 * c["hi"]), c["reading"]))
    if "checks" in s:
        c = s["checks"]
        lines.append("| Task runs passing every check | %s | %s | B−A %+d pts [%+d, %+d] | %s |" % (
            frac(t["checks"]["A"]), frac(t["checks"]["B"]), round(100 * c["value"]),
            round(100 * c["lo"]), round(100 * c["hi"]), c["reading"]))
    if "judge" in s:
        j, jt = s["judge"], t["judge"]
        lines.append("| Blind judge: B wins / ties / A wins%s | | %d / %d / %d "
                     "| B share %s [%s, %s] | %s |" % (" (%d decided by a failure)" % jt["by_rule"] if jt["by_rule"]
                                  else "", jt["B"], jt["tie"], jt["A"], pct(j["value"]),
                                  pct(j["lo"]), pct(j["hi"]), j["reading"]))
    if "trigger" in s:
        g = s["trigger"]
        lines.append("| Trigger right (picked on tasks, not on near-misses) | %s | %s | B−A %+d pts"
                     " [%+d, %+d] | %s |" % (
                         frac(t["trigger"]["A"]["right"]), frac(t["trigger"]["B"]["right"]),
                         round(100 * g["value"]), round(100 * g["lo"]), round(100 * g["hi"]),
                         g["reading"]))
    for d in dims:
        lines.append("| Judge score: %s (mean, 1-5) | %s | %s | | |" % (
            d, score(t["dims"][d]["A"]), score(t["dims"][d]["B"])))
    c = t["completion"]
    lines += ["", "Completion: %d of %d planned task pairs completed on both sides (a verdict "
              "other than worse needs %s, and the same number of completed sessions for A and B)."
              "%s%s" % (c["complete_pairs"], c["planned"], pct(MIN_COMPLETE),
                        " **Insufficient.**" if c["insufficient"] else "",
                        " **Asymmetric.**" if c["asymmetric"] else "")]
    lines.append("")

    head = "| Task | A checks | B checks | Judge B/tie/A |" + "".join(
        " %s A/B |" % d for d in dims)
    lines += ["## Per task", "", head, "|---" * (4 + len(dims)) + "|"]
    for task, row in sorted(t["tasks"].items()):
        lines.append("| %s | %s | %s | %d/%d/%d |" % ((task, frac(row["A"]), frac(row["B"]))
                                                      + tuple(row["judge"])) + "".join(
            " %s / %s |" % (score(row["dims"][d]["A"]), score(row["dims"][d]["B"]))
            for d in dims))
    lines.append("")

    lines += ["## Trigger", "", "| | A | B |", "|---|---|---|"]
    if all(t["trigger"][v]["right"][1] == 0 for v in ("A", "B")):
        lines += ["| (not measured: the profile cannot see which skill was picked) | | |"]
    else:
        lines += ["| Picked on task prompts | %s | %s |" % (
            frac(t["trigger"]["A"]["picked"]), frac(t["trigger"]["B"]["picked"])),
                  "| Picked on near-miss prompts | %s | %s |" % (
            frac(t["trigger"]["A"]["near_miss_picked"]),
            frac(t["trigger"]["B"]["near_miss_picked"]))]
    lines.append("")

    parts = spend(records, judgments)
    total = sum(p[1] for p in parts.values())
    lines += ["## Cost and time", "", "| Part | Sessions | Spend (USD) | Time |", "|---|---|---|---|"]
    for name, (n, usd, secs, _) in parts.items():
        lines.append("| %s | %d | %.2f | %s |" % (name, n, usd, clock(secs)))
    unknown = sum(p[3] for p in parts.values())
    lines += ["| **Total** | %d | **%.2f** of %.2f cap | %s |" % (
        sum(p[0] for p in parts.values()), total, meta["max_cost"],
        clock(sum(p[2] for p in parts.values()))), ""]
    if unknown:
        lines += ["%d sessions reported no cost; each is counted at its cap." % unknown, ""]

    def item(r, why):
        return "- %s %s repeat %d, %s: %s" % (r["kind"], r["task"], r["repeat"] + 1, r["version"],
                                              why)

    if t["failed"]:
        lines += ["## Failed sessions", "", "Counted above as not completed and failing every "
                  "check; a failed task session loses its judged pair.", ""]
        lines += [item(r, r["error"]) for r in t["failed"]] + [""]
    problems = [item(r, "infrastructure: %s" % r["error"]) for r in t["infra"]]
    problems += [item(r, "its partner did not run or could not start") for r in t["unpaired"]]
    problems += ["- judge %s repeat %d: %s" % (j["task"], j["repeat"] + 1, j.get("error")
                                               or "reply could not be read")
                 for j in judgments if not j.get("verdict")]
    if problems:
        lines += ["## Left out", "", "These are not in the numbers above.", ""]
        lines += problems + [""]

    lines += ["## Reading this", "",
              "A session that failed after the agent started counts against its version; one the "
              "harness could not start is left out with its partner. "
              "Intervals are 95%: Newcombe's hybrid score interval for the differences, Wilson's "
              "for the judge's share. A signal reads worse or better only when its whole interval "
              "is on one side. Runs of the same task are treated as independent, which they are "
              "not quite, so the intervals are a little narrow. No detectable difference means "
              "this N could not see one; more repeats can.", ""]
    return "\n".join(lines), t
