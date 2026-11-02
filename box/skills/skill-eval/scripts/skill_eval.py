#!/usr/bin/env python3
"""Compare two versions of a skill, A (current) and B (the change), on a task set: isolated agent
sessions under a cost cap, deterministic checks, a blind pairwise judge and a trigger check, then
a report with a verdict. Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and 3.8.

Usage:
  skill_eval.py check TASKS [--profile FILE]
  skill_eval.py run --tasks TASKS --a DIR --b DIR --out DIR [--profile FILE]
                    [--model NAME] [--judge-model NAME] [--repeats N] [--seed N]
                    [--run-budget-usd X] [--judge-budget-usd X] [--trigger-budget-usd X]
                    [--max-cost-usd X] [--timeout SECONDS] [--jobs N]
                    [--keep-env NAME]... [--copy-home RELPATH]... [--work-root DIR]
                    [--no-judge] [--no-trigger] [--date YYYY-MM-DD]
  skill_eval.py report DIR

  check       Validate a task set (and that the profile can grade it) without running anything.
  run         For every task and repeat, run one session with A installed and one with B, in
              alternating order; judge each A/B pair blind; run each near-miss prompt N times per
              version; write DIR/report.md, DIR/results.json and the raw records.
  report      Rebuild DIR/report.md and DIR/results.json from DIR's records.
  --a, --b    Skill folders holding SKILL.md. Their front-matter names must match the task set's
              `skill`; both are installed under that name, so a session cannot tell which it has.
  --profile   How to drive the agent CLI (default: ../profiles/claude-code.json).
  --model     Model for the agent sessions; --judge-model for the judge (default: CLI's own).
  --repeats   Sessions per task per version (default 3).
  --seed      Seed for the blind order (default: random, recorded in the report).
  --run-budget-usd      Cap per task session, passed to the CLI (default 0.50).
  --judge-budget-usd    Cap per judge call (default 0.25).
  --trigger-budget-usd  Cap per near-miss session (default 0.15).
  --max-cost-usd        Cap on the whole run (default 10). A session starts only if its own cap
              still fits under what is left; a session whose spend cannot be read (missing, not
              finite, or negative) counts at its cap. When the next session does not fit, the
              run stops and reports what it has. Every amount must be finite whole cents, at
              least 0.01; the value reserved is the value the CLI is given and the record shows.
  --timeout   Seconds before one session is stopped (default 600).
  --jobs      Sessions at once, 1 to 4 (default 1).
  --keep-env, --copy-home, --work-root   As for box-audit's judge.py: pass one environment
              variable through, copy one login file into each session's empty home, and choose
              where session folders are made (outside the home, no instruction files above).
  --no-judge, --no-trigger   Skip the judge, or the near-miss sessions.

Exit codes: 0 report written and every session and judge call worked (check: the task set is
valid); 1 report written but some sessions or judge calls failed (the report lists them: a
session that failed after the agent started counts against its version; one the harness could
not start, and an unreadable judge reply, are left out); 2 usage error (bad task set, profile,
skill folder, budget, unsafe --work-root or --copy-home, --out inside a skill folder); 3 the cost
cap stopped the run early (partial report written). The verdict is in the report, not the exit
code.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blind  # noqa: E402
import report  # noqa: E402
import runner  # noqa: E402

iso = runner.iso
DEFAULT_PROFILE = HERE.parent / "profiles" / "claude-code.json"
DEFAULT_DIMENSIONS = {
    "execution": "the work is done, correct, and checked by something the output shows",
    "intent": "it does what the user asked, no more and no less, and says what it did not do",
}
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def load_tasks(path, profile=None):
    """Return (task set, problems)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, ["%s: %s" % (path, e)]
    problems = []
    if not isinstance(data, dict):
        return None, ["%s: must be a JSON object" % path]
    if not isinstance(data.get("skill"), str) or not data["skill"]:
        problems.append("`skill` must name the skill")
    dims = data.setdefault("dimensions", dict(DEFAULT_DIMENSIONS))
    if not isinstance(dims, dict) or not dims or not all(
            isinstance(k, str) and isinstance(v, str) and v for k, v in dims.items()):
        problems.append("`dimensions` must map each name to what it means")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not 5 <= len(tasks) <= 10:
        problems.append("`tasks` must hold 5 to 10 tasks")
        tasks = tasks if isinstance(tasks, list) else []
    seen = set()
    for n, t in enumerate(tasks, 1):
        where = "task %s" % (t.get("id") if isinstance(t, dict) and t.get("id") else n)
        if not isinstance(t, dict):
            problems.append("%s: must be an object" % where)
            continue
        if not isinstance(t.get("id"), str) or not ID.match(t["id"]) or t["id"] in seen:
            problems.append("%s: `id` must be a unique lowercase slug" % where)
        seen.add(t.get("id"))
        for key in ("prompt", "rubric"):
            if not isinstance(t.get(key), str) or not t[key].strip():
                problems.append("%s: `%s` must be non-empty text" % (where, key))
        files = t.setdefault("files", {})
        if not isinstance(files, dict) or not all(
                isinstance(v, str) and runner.rel_ok(k) for k, v in files.items()):
            problems.append("%s: `files` must map relative paths (no ..) to text" % where)
        allow = t.get("allow")
        if allow is not None and not (isinstance(allow, list) and all(
                isinstance(a, str) for a in allow)):
            problems.append("%s: `allow` must be a list of tool names" % where)
        checks = t.get("checks")
        if not isinstance(checks, list) or not checks:
            problems.append("%s: needs at least one check" % where)
            checks = []
        for c in checks:
            problems += ["%s: %s" % (where, p) for p in check_problems(c, profile, files)]
    near = data.get("near_miss")
    if not isinstance(near, list) or not 3 <= len(near) <= 5 or not all(
            isinstance(p, str) and p.strip() for p in near):
        problems.append("`near_miss` must hold 3 to 5 prompts")
    return data, problems


def check_problems(c, profile, files=None):
    if not isinstance(c, dict) or c.get("type") not in runner.CHECKS:
        return ["unknown check %r; known: %s" % (c.get("type") if isinstance(c, dict) else c,
                                                  ", ".join(sorted(runner.CHECKS)))]
    out = []
    for key in runner.CHECKS[c["type"]]:
        if key not in c:
            out.append("check %s needs `%s`" % (c["type"], key))
    if "path" in c and not runner.rel_ok(c["path"]):
        out.append("check %s: path must be relative, without .." % c["type"])
    if c["type"] == "file_unchanged" and c.get("path") not in (files or {}):
        out.append("check file_unchanged: %s is not one of the task's files" % c.get("path"))
    if "pattern" in c:
        try:
            re.compile(c["pattern"])
        except (re.error, TypeError) as e:
            out.append("check %s: bad pattern: %s" % (c["type"], e))
    if c["type"] == "exit_zero" and not (isinstance(c.get("command"), list) and c["command"]
                                         and all(isinstance(a, str) for a in c["command"])):
        out.append("check exit_zero: `command` must be a non-empty argv list")
    if (profile is not None and c["type"].startswith("command_")
            and not profile.get("commands")):
        out.append("check %s needs a profile that lists `commands`" % c["type"])
    return out


def skill_meta(folder):
    """(front-matter name, sha256 of SKILL.md) or raise ValueError."""
    path = Path(folder) / "SKILL.md"
    if not path.is_file():
        raise ValueError("%s has no SKILL.md" % folder)
    data = path.read_bytes()
    m = re.match(r"---\r?\n(.*?)\r?\n---", data.decode("utf-8", errors="replace"), re.S)
    name = None
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip("'\"")
    if not name:
        raise ValueError("%s: SKILL.md front matter has no name" % folder)
    return name, hashlib.sha256(data).hexdigest()[:12]


class Budget:
    """A session reserves its cap before it starts and settles to its real spend after."""

    def __init__(self, cap):
        self.cap, self.spent, self.lock = runner.usd(cap), 0.0, threading.Lock()

    def reserve(self, amount):
        amount = runner.usd(amount)
        with self.lock:
            if self.spent + amount > self.cap + 1e-9:
                return False
            self.spent += amount
            return True

    def settle(self, reserved, actual):
        """Replace the reservation with the real spend; an unreadable spend stays at the cap."""
        with self.lock:
            self.spent += (actual if runner.cost_ok(actual) else reserved) - reserved


class Log:
    """Append-only JSON lines, safe from several threads; a killed run keeps what finished."""

    def __init__(self, path):
        self.path, self.lock = Path(path), threading.Lock()

    def add(self, row):
        with self.lock, open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def read_rows(path):
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def inside(path, root):
    return iso.inside(path, root)


def run(args):
    profile, problems = runner.load_profile(args.profile)
    tasks, more = load_tasks(args.tasks, profile)
    problems += more
    try:
        a_name, a_sha = skill_meta(args.a)
        b_name, b_sha = skill_meta(args.b)
    except ValueError as e:
        problems.append(str(e))
    else:
        if tasks and not {a_name, b_name} == {tasks.get("skill")}:
            problems.append("skill names differ: A %r, B %r, task set %r; they must match" % (
                a_name, b_name, tasks.get("skill")))
    if not 1 <= args.jobs <= 4:
        problems.append("--jobs must be 1 to 4")
    if args.repeats < 1:
        problems.append("--repeats must be at least 1")
    for name in ("run_budget_usd", "judge_budget_usd", "trigger_budget_usd", "max_cost_usd"):
        try:
            setattr(args, name, runner.usd(getattr(args, name)))
        except ValueError as e:
            problems.append("--%s %s" % (name.replace("_", "-"), e))
    work_root = args.work_root or tempfile.gettempdir()
    unsafe = iso.unsafe_root(work_root)
    if unsafe:
        problems.append("unsafe --work-root: %s. Pass a folder outside the home and free of "
                        "instruction files." % unsafe)
    for rel in args.copy_home:
        p = iso.check_copy(rel, Path.home())
        if p:
            problems.append("refusing --copy-home %s: %s" % (rel, p))
    out = Path(args.out)
    for folder in (args.a, args.b):
        if inside(out, folder):
            problems.append("--out %s is inside the skill folder %s" % (out, folder))
    if problems:
        for p in problems:
            print("skill-eval: %s" % p, file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    for name in ("runs.jsonl", "judgments.jsonl"):
        if (out / name).exists():
            print("skill-eval: %s already holds a run; pass a new --out" % out, file=sys.stderr)
            return 2
    seed = args.seed if args.seed is not None else int.from_bytes(os.urandom(4), "big")
    meta = {"skill": tasks["skill"], "a": {"name": Path(args.a).resolve().name, "sha": a_sha},
            "b": {"name": Path(args.b).resolve().name, "sha": b_sha},
            "tasks_file": Path(args.tasks).name,
            "tasks_sha": hashlib.sha256(Path(args.tasks).read_bytes()).hexdigest()[:12],
            "n_tasks": len(tasks["tasks"]), "n_near_miss": len(tasks["near_miss"]),
            "dimensions": tasks["dimensions"], "profile": Path(args.profile).stem,
            "model": args.model, "judge_model": args.judge_model, "repeats": args.repeats,
            "seed": seed, "run_budget": args.run_budget_usd, "judge_budget": args.judge_budget_usd,
            "trigger_budget": args.trigger_budget_usd, "max_cost": args.max_cost_usd,
            "judged": False,
            "date": args.date or datetime.date.today().isoformat(), "stopped": None}
    sessions = len(tasks["tasks"]) * args.repeats * 2
    near = 0 if args.no_trigger else len(tasks["near_miss"]) * args.repeats * 2
    judged = 0 if args.no_judge else len(tasks["tasks"]) * args.repeats
    worst = (sessions * args.run_budget_usd + near * args.trigger_budget_usd
             + judged * args.judge_budget_usd)
    print("skill-eval: %d sessions, %d judge calls, %d near-miss sessions; worst case %.2f USD, "
          "cap %.2f" % (sessions, judged, near, worst, args.max_cost_usd), file=sys.stderr)

    budget, runs, judgments = Budget(args.max_cost_usd), Log(out / "runs.jsonl"), Log(
        out / "judgments.jsonl")
    folders = {"A": Path(args.a), "B": Path(args.b)}
    stopped = threading.Event()
    common = dict(keep=args.keep_env, copy=args.copy_home, timeout=args.timeout)

    def session(kind, task_id, repeat, version, prompt, files, checks, allow, cap):
        if stopped.is_set() or not budget.reserve(cap):
            stopped.set()
            return
        row = {"kind": kind, "task": task_id, "repeat": repeat, "version": version, "budget": cap}
        try:
            row.update(runner.session(profile, prompt, work_root, tasks["skill"],
                                      folders[version], files, checks, allow, args.model, cap,
                                      **common))
        except (OSError, ValueError) as e:
            row.update(error="%s: %s" % (type(e).__name__, e), cost_usd=None, seconds=0)
        budget.settle(cap, row.get("cost_usd"))
        runs.add(row)

    jobs = []
    for t in tasks["tasks"]:
        for i in range(args.repeats):
            for v in (("A", "B") if i % 2 == 0 else ("B", "A")):
                jobs.append(("task", t["id"], i, v, t["prompt"], t["files"], t["checks"],
                             t.get("allow"), args.run_budget_usd))
    with ThreadPoolExecutor(args.jobs) as pool:
        list(pool.map(lambda j: session(*j), jobs))

    if not args.no_judge and not stopped.is_set():
        by_id = {t["id"]: t for t in tasks["tasks"]}

        def judge(pair):
            task_id, repeat, a, b, x_is_a = pair
            cap = args.judge_budget_usd
            if stopped.is_set() or not budget.reserve(cap):
                stopped.set()
                return
            x, y = (a, b) if x_is_a else (b, a)
            bundle = out / "judge" / ("%s-%d" % (task_id, repeat + 1))
            bundle.mkdir(parents=True, exist_ok=True)
            (bundle / "prompt.md").write_text(blind.prompt(by_id[task_id], tasks["dimensions"],
                                                           x, y), encoding="utf-8")
            reply = bundle / "reply.txt"
            argv = runner.argv_for(profile, args.judge_model, cap, judge=True)
            start = time.monotonic()
            code = iso.run(bundle, argv, args.keep_env, args.copy_home, args.timeout, str(reply),
                           work_root)
            text = reply.read_text(encoding="utf-8") if reply.is_file() else ""
            result, cost, _, _ = runner.read_session(text, profile, "")
            verdict = blind.parse(result, tasks["dimensions"]) if result else None
            row = {"task": task_id, "repeat": repeat, "x_is_a": x_is_a, "budget": cap,
                   "cost_usd": cost, "seconds": round(time.monotonic() - start, 1),
                   "verdict": blind.unblind(verdict, x_is_a) if verdict else None,
                   "error": None if verdict else "judge exit %d; reply not readable" % code}
            budget.settle(cap, cost)
            judgments.add(row)

        with ThreadPoolExecutor(args.jobs) as pool:
            list(pool.map(judge, blind.pairs(read_rows(out / "runs.jsonl"), seed)))
        # Pairs with a failed session are scored by rule only when every pair was judged.
        meta["judged"] = not stopped.is_set()

    if not args.no_trigger and not stopped.is_set():
        jobs = []
        for n, prompt in enumerate(tasks["near_miss"], 1):
            for i in range(args.repeats):
                for v in (("A", "B") if i % 2 == 0 else ("B", "A")):
                    jobs.append(("near_miss", "near-miss-%d" % n, i, v, prompt, {}, [], None,
                                 args.trigger_budget_usd))
        with ThreadPoolExecutor(args.jobs) as pool:
            list(pool.map(lambda j: session(*j), jobs))

    if stopped.is_set():
        meta["stopped"] = "the %.2f USD cap left too little for the next session" % (
            args.max_cost_usd)
    (out / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
    return write_report(out, 3 if stopped.is_set() else None)


def write_report(out, code=None):
    out = Path(out)
    if not (out / "meta.json").is_file():
        print("skill-eval: %s has no meta.json; not a skill-eval run" % out, file=sys.stderr)
        return 2
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    records, judgments = read_rows(out / "runs.jsonl"), read_rows(out / "judgments.jsonl")
    text, t = report.render(meta, records, judgments)
    with open(out / "report.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    results = {k: t[k] for k in ("verdict", "signals", "completion", "checks", "judge",
                                 "trigger", "dims")}
    results["tasks"] = t["tasks"]
    results["failed"] = len(t["failed"])
    results["left_out"] = len(t["infra"]) + len(t["unpaired"]) + t["judge"]["unread"]
    results["spend"] = {k: {"sessions": v[0], "usd": round(v[1], 4), "seconds": v[2],
                            "unknown_cost": v[3]}
                        for k, v in report.spend(records, judgments).items()}
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
    print("verdict: %s (%s)" % (t["verdict"], out / "report.md"))
    if code is not None:
        return code
    return 1 if results["failed"] or results["left_out"] else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("tasks")
    c.add_argument("--profile", default=str(DEFAULT_PROFILE))
    r = sub.add_parser("run")
    r.add_argument("--tasks", required=True)
    r.add_argument("--a", required=True)
    r.add_argument("--b", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--profile", default=str(DEFAULT_PROFILE))
    r.add_argument("--model")
    r.add_argument("--judge-model")
    r.add_argument("--repeats", type=int, default=3)
    r.add_argument("--seed", type=int)
    r.add_argument("--run-budget-usd", default="0.50")
    r.add_argument("--judge-budget-usd", default="0.25")
    r.add_argument("--trigger-budget-usd", default="0.15")
    r.add_argument("--max-cost-usd", default="10.00")
    r.add_argument("--timeout", type=int, default=600)
    r.add_argument("--jobs", type=int, default=1)
    r.add_argument("--keep-env", action="append", default=[])
    r.add_argument("--copy-home", action="append", default=[])
    r.add_argument("--work-root")
    r.add_argument("--no-judge", action="store_true")
    r.add_argument("--no-trigger", action="store_true")
    r.add_argument("--date")
    p = sub.add_parser("report")
    p.add_argument("dir")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        profile, problems = runner.load_profile(args.profile)
        data, more = load_tasks(args.tasks, profile)
        problems += more
        for p in problems:
            print("skill-eval: %s" % p, file=sys.stderr)
        if not problems:
            print("ok: %d tasks, %d near-miss prompts" % (len(data["tasks"]),
                                                          len(data["near_miss"])))
        return 2 if problems else 0
    if args.cmd == "report":
        return write_report(args.dir)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
