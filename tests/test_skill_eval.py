"""Tests for the skill-eval scripts (box/skills/skill-eval/scripts). Sessions and judges are a
small Python program standing in for an agent CLI (fixtures/skill_eval/fake_agent.py): it reads
the prompt on stdin and prints JSON-lines events like one, so the runner, its isolation, the
blind order and the report run as they would, without a model."""
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import write

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "box" / "skills" / "skill-eval"
SCRIPTS = SKILL / "scripts"
FAKE = Path(__file__).resolve().parent / "fixtures" / "skill_eval" / "fake_agent.py"
sys.path.insert(0, str(SCRIPTS))

import blind  # noqa: E402
import report  # noqa: E402
import runner  # noqa: E402
import skill_eval  # noqa: E402

GOOD_SKILL = """---
name: widget-maker
description: Makes widgets. triggers: widget
---

# widget-maker

Write out.txt, run the tests, and say what you ran.
"""


def fake_profile(tmp_path, **extra):
    profile = {
        "command": [sys.executable, str(FAKE)],
        "budget_args": ["--budget", "{budget}"],
        "model_args": ["--model", "{model}"],
        "allow_args": ["--allow", "{allow}"],
        "judge_args": ["--judge"],
        "skills_dir": ".fake/skills",
        "result": {"match": {"type": "result"}, "field": "result"},
        "cost": {"match": {"type": "result"}, "field": "cost"},
        "commands": [{"match": {"type": "tool", "name": "shell"}, "field": "input.cmd",
                      "id": "id"}],
        "command_results": {"match": {"type": "tool_result"}, "id": "tool_id", "output": "output",
                            "error": "failed", "denied": "^DENIED"},
        "command_denials": [{"match": {"type": "denial"}, "field": "tool_id"}],
        "skill_used": [{"match": {"type": "tool", "name": "skill"}, "field": "input.name"}],
    }
    profile.update(extra)
    path = tmp_path / "fake-profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def task_set(n=5, prompt="Make widget number %d.", near=3):
    tasks = []
    for i in range(1, n + 1):
        tasks.append({
            "id": "widget-%d" % i,
            "prompt": prompt % i if "%d" in prompt else prompt,
            "files": {"README.md": "a repo\n", "src/app.py": "print('hi')\n"},
            "checks": [
                {"type": "file_exists", "path": "out.txt"},
                {"type": "file_contains", "path": "out.txt", "pattern": "^GOOD"},
                {"type": "command_run", "pattern": r"pytest"},
                {"type": "output_contains", "pattern": "GOOD"},
                {"type": "exit_zero", "command": [
                    "{python}", "-c",
                    "import pathlib, sys; sys.exit(0 if pathlib.Path('out.txt').is_file() else 1)"]},
            ],
            "rubric": "The widget exists and the reply says how it was checked.",
        })
    return {"skill": "widget-maker", "tasks": tasks,
            "near_miss": ["Tell me about gadgets %d." % i for i in range(1, near + 1)]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake owner home holding a personal instruction file and a login, set as the home."""
    home = tmp_path / "owner-home"
    write(home, ".agent/AGENTS.md", "OWNER_CANARY always watch CI after every push\n")
    write(home, ".agent/login.json", '{"session": "one"}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("OWNER_SECRET", "canary-value")
    # Only a test marker counts as an instruction file, so real folders above the temp dir (a
    # runner's home holding .claude, say) do not decide the outcome. box-audit's tests do the same.
    monkeypatch.setattr(runner.iso, "INSTRUCTION_ENTRIES", ("SKILL_EVAL_TEST_INSTRUCTIONS.md",))
    root = tmp_path / "work-root"
    root.mkdir()
    a = write(tmp_path, "a/widget-maker/SKILL.md", GOOD_SKILL).parent
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps(task_set()), encoding="utf-8")
    return {"tmp": tmp_path, "home": home, "root": root, "a": a, "tasks": tasks,
            "profile": fake_profile(tmp_path)}


def variant(env, name, text):
    return write(env["tmp"], "%s/widget-maker/SKILL.md" % name, text).parent


def run_eval(env, b, *extra, tasks=None):
    out = env["tmp"] / ("out-%d" % len(list(env["tmp"].glob("out-*"))))
    code = skill_eval.main(["run", "--tasks", str(tasks or env["tasks"]), "--a", str(env["a"]),
                            "--b", str(b), "--out", str(out), "--profile", str(env["profile"]),
                            "--work-root", str(env["root"]), "--seed", "7",
                            "--date", "2026-10-22"] + list(extra))
    return code, out


# --- runner: events, profiles, checks -------------------------------------------------------

def test_events_reads_json_lines_one_document_and_nested_objects():
    stdout = 'noise\n{"type": "a", "inner": {"type": "b"}}\n[{"type": "c"}]\n{broken\n'
    assert [e["type"] for e in runner.events(stdout)] == ["a", "b", "c"]
    assert [e["type"] for e in runner.events('[{"type": "x"}, {"type": "y"}]')] == ["x", "y"]
    assert runner.events("plain text only") == []


def test_read_session_takes_the_last_result_and_cost_and_lists_commands():
    profile = json.loads(fake_profile(Path(__import__("tempfile").mkdtemp())).read_text())
    stdout = "\n".join(json.dumps(e) for e in [
        {"type": "result", "result": "draft", "cost": 0.01},
        {"type": "assistant", "content": [{"type": "tool", "name": "skill",
                                           "input": {"name": "pack:widget-maker"}}]},
        {"type": "tool", "name": "shell", "id": "1", "input": {"cmd": "ls"}},
        {"type": "tool_result", "tool_id": "1", "output": "a.txt", "failed": False},
        {"type": "tool", "name": "other", "input": {"cmd": "rm -rf x"}},
        {"type": "result", "result": "final", "cost": 0.03}])
    result, cost, commands, used = runner.read_session(stdout, profile, "widget-maker")
    assert (result, cost, used) == ("final", 0.03, True)
    assert commands == [{"command": "ls", "status": "ran", "output": "a.txt"}]
    assert runner.read_session(stdout, profile, "other-skill")[3] is False
    del profile["skill_used"]
    assert runner.read_session(stdout, profile, "widget-maker")[3] is None
    assert runner.read_session("text", dict(profile, result="stdout"), "")[0] == "text"


def test_profile_needs_a_cost_cap_and_a_readable_cost(tmp_path):
    profile, problems = runner.load_profile(fake_profile(tmp_path))
    assert problems == []
    _, problems = runner.load_profile(fake_profile(tmp_path, budget_args=["--budget", "1"]))
    assert any("{budget}" in p for p in problems)
    _, problems = runner.load_profile(fake_profile(tmp_path, cost="stdout"))
    assert any("spend cannot be read" in p for p in problems)
    _, problems = runner.load_profile(fake_profile(tmp_path, cost=None))
    assert any("`cost`" in p for p in problems)
    assert runner.load_profile(tmp_path / "missing.json")[1]
    assert runner.load_profile(SKILL / "profiles" / "claude-code.json")[1] == []


def test_argv_adds_the_budget_model_and_allowed_tools(tmp_path):
    profile, _ = runner.load_profile(fake_profile(tmp_path, default_allow=["read"]))
    argv = runner.argv_for(profile, "small", 0.5, ["read", "shell"])
    assert argv[2:] == ["--budget", "0.50", "--model", "small", "--allow", "read,shell"]
    assert runner.argv_for(profile, None, 0.25)[2:] == ["--budget", "0.25", "--allow", "read"]
    assert runner.argv_for(profile, None, 0.25, judge=True)[2:] == ["--budget", "0.25", "--judge"]


def test_each_check_type_passes_and_fails(tmp_path):
    write(tmp_path, "out.txt", "GOOD line\n")
    checks = [
        {"type": "file_exists", "path": "out.txt"}, {"type": "file_exists", "path": "no.txt"},
        {"type": "file_absent", "path": "no.txt"}, {"type": "file_absent", "path": "out.txt"},
        {"type": "file_contains", "path": "out.txt", "pattern": "^GOOD"},
        {"type": "file_contains", "path": "no.txt", "pattern": "x"},
        {"type": "file_not_contains", "path": "out.txt", "pattern": "BAD"},
        {"type": "file_not_contains", "path": "no.txt", "pattern": "x"},
        {"type": "output_contains", "pattern": "(?i)done"},
        {"type": "output_not_contains", "pattern": "Done"},
        {"type": "command_run", "pattern": r"pytest\b"},
        {"type": "command_not_run", "pattern": r"git push"},
        {"type": "command_not_run", "pattern": r"pytest"},
        {"type": "exit_zero", "command": ["{python}", "-c", "raise SystemExit(0)"]},
        {"type": "exit_zero", "command": ["{python}", "-c", "raise SystemExit(4)"], "name": "x4"},
    ]
    got = runner.grade(checks, tmp_path, "Done.",
                       [{"command": "python -m pytest -q", "status": "ran", "output": ""}])
    assert [g["pass"] for g in got] == [True, False, True, False, True, False, True, True, True,
                                        False, True, True, False, True, False]
    assert got[-1]["check"] == "x4" and got[-1]["detail"] == "exit 4"
    unknown = runner.grade(checks[10:11], tmp_path, "", [], has_commands=False)
    assert unknown[0]["pass"] is None


def test_snapshot_shows_new_and_changed_files_only(tmp_path):
    fixtures = {"same.txt": "x\n", "changed.txt": "old\n"}
    write(tmp_path, "same.txt", "x\n")
    write(tmp_path, "changed.txt", "new\n")
    write(tmp_path, "sub/new.txt", "y" * (runner.FILE_LIMIT + 10))
    write(tmp_path, ".git/config", "skip\n")
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00")
    shown = runner.snapshot(tmp_path, fixtures)
    assert sorted(shown) == ["blob.bin", "changed.txt", "sub/new.txt"]
    assert shown["blob.bin"].startswith("(binary") and shown["sub/new.txt"].endswith("(cut)")


# --- task sets ------------------------------------------------------------------------------

def test_task_set_validation_names_each_problem(tmp_path, env):
    path = tmp_path / "bad.json"
    bad = task_set(n=4, near=2)
    bad["tasks"][0]["id"] = "Bad Id"
    bad["tasks"][1]["files"] = {"../escape.txt": "x"}
    bad["tasks"][2]["checks"] = [{"type": "file_exists"}, {"type": "nope"},
                                 {"type": "output_contains", "pattern": "("},
                                 {"type": "exit_zero", "command": "python"}]
    bad["tasks"][3]["rubric"] = " "
    path.write_text(json.dumps(bad), encoding="utf-8")
    profile, _ = runner.load_profile(fake_profile(tmp_path, commands=[]))
    _, problems = skill_eval.load_tasks(path, profile)
    text = "\n".join(problems)
    for needle in ("5 to 10 tasks", "unique lowercase slug", "relative paths", "needs `path`",
                   "unknown check", "bad pattern", "argv list", "`rubric`", "3 to 5 prompts",
                   "profile that lists `commands`"):
        assert needle in text, needle
    assert skill_eval.load_tasks(env["tasks"], profile)[1] == [
        "task widget-%d: check command_run needs a profile that lists `commands`" % i
        for i in range(1, 6)]


def test_shipped_task_sets_are_valid():
    sets = sorted((SKILL / "tasksets").glob("*.json"))
    assert sets
    for path in sets:
        assert skill_eval.main(["check", str(path)]) == 0, path.name


# --- report maths ---------------------------------------------------------------------------

def test_wilson_and_newcombe_match_published_values():
    lo, hi = report.wilson(0, 15)
    assert lo == 0 and abs(hi - 0.2039) < 1e-3
    lo, hi = report.wilson(15, 15)
    assert abs(lo - 0.7961) < 1e-3 and hi == 1
    assert report.wilson(0, 0) == (0.0, 1.0)
    # Newcombe (1998), method 10 worked example: 56/70 vs 48/80 -> 0.2000 (0.0524, 0.3339).
    d, lo, hi = report.newcombe(48, 80, 56, 70)
    assert (round(d, 4), round(lo, 4), round(hi, 4)) == (0.2, 0.0524, 0.3339)


def rec(task, version, ok=True, repeat=0, kind="task", used=True, error=None, cost=0.1):
    return {"kind": kind, "task": task, "version": version, "repeat": repeat, "error": error,
            "checks": [{"check": "c", "pass": ok, "detail": ""}], "skill_used": used,
            "cost_usd": cost, "budget": 0.5, "seconds": 2}


def verdicts(winners):
    return [{"task": "t", "repeat": i, "cost_usd": 0.01, "budget": 0.2, "seconds": 1,
             "verdict": {"winner": w, "reason": "", "scores": {
                 "A": {"execution": 4, "intent": None}, "B": {"execution": 2, "intent": None}}}}
            for i, w in enumerate(winners)]


def test_verdict_is_worse_better_or_no_detectable_difference():
    dims = ["execution", "intent"]
    same = [rec("t", v, repeat=i) for i in range(15) for v in "AB"]
    t = report.tally(same, verdicts(["A", "B", "tie"] * 5), dims)
    assert t["verdict"] == "no detectable difference"
    assert t["judge"] == {"B": 5, "tie": 5, "A": 5, "n": 15, "by_rule": 0, "unread": 0}
    assert abs(t["signals"]["judge"]["value"] - 0.5) < 1e-9  # a tie counts half
    assert t["dims"]["execution"] == {"A": 4, "B": 2} and t["dims"]["intent"]["A"] is None

    assert report.tally(same, verdicts(["A"] * 15), dims)["verdict"] == "worse"
    assert report.tally(same, verdicts(["B"] * 15), dims)["verdict"] == "better"
    # Judge says better, checks say worse: a regression anywhere is reported as worse.
    broken = [rec("t", v, ok=(v == "A"), repeat=i) for i in range(15) for v in "AB"]
    t = report.tally(broken, verdicts(["B"] * 15), dims)
    assert t["signals"]["checks"]["reading"] == "worse" and t["verdict"] == "worse"


def test_trigger_counts_task_picks_and_near_miss_misses():
    rows = ([rec("t", "A", repeat=i) for i in range(10)]
            + [rec("t", "B", repeat=i, used=False) for i in range(10)]
            + [rec("n", v, kind="near_miss", used=False, repeat=i) for i in range(5) for v in "AB"])
    t = report.tally(rows, [], ["execution"])
    assert t["trigger"]["A"] == {"picked": (10, 10), "near_miss_picked": (0, 5), "right": (15, 15)}
    assert t["trigger"]["B"]["right"] == (5, 15)
    assert t["signals"]["trigger"]["reading"] == "worse" and t["verdict"] == "worse"


def test_failed_runs_count_against_their_version_and_unknown_cost_counts_at_the_cap():
    rows = [rec("t", "A"), rec("t", "B"), rec("t", "A", repeat=1),
            rec("t", "B", repeat=1, error="timed out", cost=None)]
    t = report.tally(rows, [], ["execution"], judged=True)
    assert t["checks"] == {"A": (2, 2), "B": (1, 2)} and len(t["failed"]) == 1
    assert t["completion"]["B"] == (1, 2) and t["completion"]["asymmetric"]
    assert t["judge"]["A"] == 1 and t["judge"]["by_rule"] == 1  # the completed side wins
    parts = report.spend(rows, [])
    assert parts["B sessions"] == (2, 0.6, 4, 1)


# --- blind judging --------------------------------------------------------------------------

def test_blind_order_is_seeded_balanced_and_undone():
    rows = [rec("t%d" % k, v, repeat=i) for k in range(20) for i in range(10) for v in "AB"]
    first, again = blind.pairs(rows, 3), blind.pairs(rows, 3)
    assert [p[4] for p in first] == [p[4] for p in again]
    assert [p[4] for p in first] != [p[4] for p in blind.pairs(rows, 4)]
    share = sum(p[4] for p in first) / len(first)
    assert len(first) == 200 and 0.4 < share < 0.6
    rows.append(rec("t0", "B", repeat=99))  # no A partner
    rows.append(rec("t1", "A", repeat=98, error="crashed"))
    rows.append(rec("t1", "B", repeat=98))
    assert len(blind.pairs(rows, 3)) == 200
    v = {"winner": "X", "reason": "r", "scores": {"X": {"e": 5}, "Y": {"e": 1}}}
    assert blind.unblind(v, True)["winner"] == "A" and blind.unblind(v, False)["winner"] == "B"
    assert blind.unblind(v, False)["scores"] == {"A": {"e": 1}, "B": {"e": 5}}
    assert blind.unblind(dict(v, winner="tie"), True)["winner"] == "tie"


def test_judge_prompt_hides_which_output_is_which():
    task = task_set()["tasks"][0]
    a = dict(rec("widget-1", "A"), result="reply one", commands=["pytest"], files={"o.txt": "1"})
    b = dict(rec("widget-1", "B"), result="reply two", commands=[], files={})
    text = blind.prompt(task, skill_eval.DEFAULT_DIMENSIONS, a, b)
    assert "## Output X" in text and "## Output Y" in text
    assert text.index("reply one") < text.index("## Output Y") < text.index("reply two")
    assert not re.search(r"\b(versions?|skills?|change|baseline|new|old|current)\b", text,
                         re.I), "the judge prompt must not reveal that versions exist"
    assert not re.search(r"\b(Output|Run|Agent) [AB]\b", text)


def test_judge_reply_parsing():
    dims = ["execution", "intent"]
    good = 'Sure.\n```json\n{"winner": "y", "reason": "r", "scores": {"X": {"execution": 9, ' \
           '"intent": 3}, "Y": {"execution": 4}}}\n```'
    v = blind.parse(good, dims)
    assert v["winner"] == "Y"
    assert v["scores"] == {"X": {"execution": None, "intent": 3},
                           "Y": {"execution": 4, "intent": None}}
    assert blind.parse('{"winner": "tie"}', dims)["winner"] == "tie"
    assert blind.parse('{"winner": "both"}', dims) is None
    assert blind.parse("no json here", dims) is None
    assert blind.parse(None, dims) is None


# --- end to end with the stand-in CLI -------------------------------------------------------

def test_harmful_change_is_reported_worse(env):
    b = variant(env, "harmful", GOOD_SKILL.replace("Write out.txt", "HARMFUL: skip the work"))
    code, out = run_eval(env, b, "--jobs", "2")
    assert code == 0
    results = json.loads((out / "results.json").read_text())
    assert results["verdict"] == "worse"
    assert results["checks"] == {"A": [15, 15], "B": [0, 15]}
    assert results["judge"]["A"] == 15  # every pair, whichever side B was shown on
    assert results["signals"]["trigger"]["reading"] == "same"
    text = (out / "report.md").read_text()
    assert "**Verdict: worse.**" in text and "| widget-1 | 3/3 (100%) | 0/3 (0%) | 0/0/3 |" in text
    assert results["spend"]["A sessions"] == {"sessions": 15, "usd": 0.3, "seconds":
                                              results["spend"]["A sessions"]["seconds"],
                                              "unknown_cost": 0}
    assert results["spend"]["Judge sessions"]["usd"] == 0.15
    assert results["spend"]["Near-miss sessions"]["sessions"] == 18
    prompts = list((out / "judge").glob("*/prompt.md"))
    assert len(prompts) == 15
    order = [json.loads(line)["x_is_a"] for line in (out / "judgments.jsonl").read_text()
             .splitlines()]
    assert 0 < sum(order) < 15  # B was shown first in some pairs and second in others


def test_noop_change_is_reported_no_detectable_difference(env):
    b = variant(env, "noop", GOOD_SKILL.replace("\n\n# widget", "\n\n\n# widget") + "\n")
    code, out = run_eval(env, b)
    assert code == 0
    results = json.loads((out / "results.json").read_text())
    assert results["verdict"] == "no detectable difference"
    assert results["checks"] == {"A": [15, 15], "B": [15, 15]}
    # The stand-in judge always picks X on a tie, so B's wins are exactly the pairs shown as X.
    judged = [json.loads(line) for line in (out / "judgments.jsonl").read_text().splitlines()]
    assert results["judge"]["B"] == sum(1 for j in judged if not j["x_is_a"])
    assert "no detectable difference** between A and B at N=3" in (out / "report.md").read_text()


def test_description_change_that_stops_the_skill_being_picked_is_worse(env):
    b = variant(env, "renamed", GOOD_SKILL.replace("triggers: widget", "triggers: gadget"))
    code, out = run_eval(env, b, "--no-judge")
    results = json.loads((out / "results.json").read_text())
    assert code == 0 and results["verdict"] == "worse"
    assert results["trigger"]["B"]["picked"] == [0, 15]
    assert results["trigger"]["B"]["near_miss_picked"] == [9, 9]  # "gadgets" now triggers it
    assert results["signals"]["trigger"]["reading"] == "worse"
    assert "judge" not in results["signals"]


def test_sessions_are_isolated_and_cannot_tell_the_versions_apart(env):
    code, out = run_eval(env, env["a"], "--no-judge", "--no-trigger", "--repeats", "1",
                         "--copy-home", ".agent/login.json")
    assert code == 0
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
    assert len(rows) == 10
    for r in rows:
        assert "'.agent/login.json'" in r["result"], r["result"]
        assert "'.fake/skills/widget-maker/SKILL.md'" in r["result"]
        assert "AGENTS.md" not in r["result"] and "canary-value" not in r["result"]
        assert "wrote out.txt in . and" in r["result"]  # the scratch path is scrubbed
        assert r["files"] == {"out.txt": "GOOD widget\n"}
        assert r["skill_used"] is True
    assert list(env["root"].iterdir()) == []  # session folders deleted


def test_cost_cap_stops_the_run_and_the_report_says_so(env):
    b = variant(env, "same", GOOD_SKILL)
    code, out = run_eval(env, b, "--run-budget-usd", "0.05", "--max-cost-usd", "0.10")
    assert code == 3
    rows = (out / "runs.jsonl").read_text().splitlines()
    assert len(rows) == 3  # 0.02 each: the fourth would need its 0.05 cap with 0.04 left
    text = (out / "report.md").read_text()
    assert "**Partial run:" in text and "of 0.10 cap" in text


def test_a_session_with_no_readable_cost_is_charged_its_cap(env, monkeypatch):
    monkeypatch.setenv("FAKE_NO_COST", "1")
    code, out = run_eval(env, env["a"], "--keep-env", "FAKE_NO_COST", "--no-judge",
                         "--no-trigger", "--repeats", "1", "--run-budget-usd", "0.10",
                         "--max-cost-usd", "0.35")
    assert code == 3
    assert len((out / "runs.jsonl").read_text().splitlines()) == 3
    assert "3 sessions reported no cost; each is counted at its cap." in (
        out / "report.md").read_text()


def test_failed_sessions_count_against_their_version_and_are_listed(env, tmp_path):
    tasks = task_set()
    tasks["tasks"][0]["prompt"] = "Make a widget, then CRASH."
    path = tmp_path / "crash.json"
    path.write_text(json.dumps(tasks), encoding="utf-8")
    code, out = run_eval(env, env["a"], "--no-trigger", "--repeats", "1", tasks=path)
    assert code == 1
    text = (out / "report.md").read_text()
    assert "## Failed sessions" in text
    assert "task widget-1 repeat 1, A: exit 3 and no reply: boom" in text
    results = json.loads((out / "results.json").read_text())
    assert results["checks"] == {"A": [4, 5], "B": [4, 5]} and results["failed"] == 2
    assert results["judge"]["n"] == 5 and results["judge"]["by_rule"] == 1  # both failed: a tie
    assert results["verdict"] == "no detectable difference"  # 4 of 5 pairs, the same for both


def test_a_session_that_runs_too_long_is_stopped_and_counted_as_failed(env, tmp_path):
    tasks = task_set()
    tasks["tasks"][2]["prompt"] = "Make a widget, but SLEEP first."
    path = tmp_path / "slow.json"
    path.write_text(json.dumps(tasks), encoding="utf-8")
    code, out = run_eval(env, env["a"], "--no-trigger", "--no-judge", "--repeats", "1",
                         "--timeout", "2", tasks=path)
    assert code == 1
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
    slow = [r for r in rows if r["task"] == "widget-3"]
    assert [r["timed_out"] for r in slow] == [True, True]
    assert "task widget-3 repeat 1, A: timed out after 2s" in (out / "report.md").read_text()


def test_proof_variants_change_only_what_they_claim(tmp_path):
    maker = ROOT / "experiments" / "06-skill-eval" / "make_variants.py"
    proc = subprocess.run([sys.executable, str(maker), str(tmp_path / "v")],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    a, harmful, noop = ((tmp_path / "v" / n / "agent-ready" / "SKILL.md").read_text(
        encoding="utf-8") for n in ("a", "harmful", "noop"))
    assert a == (ROOT / "agent-ready" / "SKILL.md").read_text(encoding="utf-8").replace(
        "\r\n", "\n")
    assert "Assert, don't verify" in harmful and "change the check until it passes" in harmful
    assert len(set(a.splitlines()) ^ set(harmful.splitlines())) == 8  # rules 1 and 4, 2 lines each
    assert noop != a and sorted(filter(None, noop.splitlines())) == sorted(
        filter(None, a.splitlines()))
    for name in ("a", "harmful", "noop"):
        assert skill_eval.skill_meta(tmp_path / "v" / name / "agent-ready")[0] == "agent-ready"
    again = subprocess.run([sys.executable, str(maker), str(tmp_path / "v")],
                           capture_output=True, text=True)
    assert again.returncode == 2 and "not empty" in again.stderr


def test_usage_errors_exit_2(env, capsys):
    other = variant(env, "other", GOOD_SKILL.replace("name: widget-maker", "name: other"))
    assert run_eval(env, other)[0] == 2
    assert "skill names differ" in capsys.readouterr().err
    code = skill_eval.main(["run", "--tasks", str(env["tasks"]), "--a", str(env["a"]), "--b",
                            str(env["a"]), "--out", str(env["a"] / "out"), "--profile",
                            str(env["profile"]), "--work-root", str(env["root"])])
    assert code == 2 and "inside the skill folder" in capsys.readouterr().err
    assert run_eval(env, env["a"], "--copy-home", ".agent/AGENTS.md")[0] == 2
    assert "refusing --copy-home" in capsys.readouterr().err
    unsafe = env["home"] / "inside"
    unsafe.mkdir()
    code = skill_eval.main(["run", "--tasks", str(env["tasks"]), "--a", str(env["a"]), "--b",
                            str(env["a"]), "--out", str(env["tmp"] / "o"), "--profile",
                            str(env["profile"]), "--work-root", str(unsafe)])
    assert code == 2 and "unsafe --work-root" in capsys.readouterr().err
    marked = env["tmp"] / "marked"
    write(marked, "SKILL_EVAL_TEST_INSTRUCTIONS.md", "x\n")
    (marked / "below").mkdir()
    code = skill_eval.main(["run", "--tasks", str(env["tasks"]), "--a", str(env["a"]), "--b",
                            str(env["a"]), "--out", str(env["tmp"] / "o2"), "--profile",
                            str(env["profile"]), "--work-root", str(marked / "below")])
    assert code == 2 and "agent CLIs read from every folder below it" in capsys.readouterr().err
    assert skill_eval.main(["report", str(env["tmp"])]) == 2


def test_report_rebuilds_from_the_records(env):
    code, out = run_eval(env, env["a"], "--no-trigger", "--repeats", "1")
    first = (out / "report.md").read_text()
    (out / "report.md").unlink()
    assert skill_eval.main(["report", str(out)]) == 0
    assert (out / "report.md").read_text() == first
    assert run_eval(env, env["a"], "--repeats", "1")[0] == 0  # a fresh --out each time
    again = skill_eval.main(["run", "--tasks", str(env["tasks"]), "--a", str(env["a"]), "--b",
                             str(env["a"]), "--out", str(out), "--profile", str(env["profile"]),
                             "--work-root", str(env["root"])])
    assert again == 2  # never mixes two runs in one folder


# --- review findings on PR #42: failures, outcomes, deletions, budgets ---------------------

def paired_rows(n=15, b_error=(), b_infra=(), b_ok=True):
    rows = []
    for i in range(n):
        rows.append(rec("t", "A", repeat=i))
        if i in b_infra:
            rows.append(dict(rec("t", "B", repeat=i, error="command not found: x", cost=None),
                             infra=True))
        elif i in b_error:
            rows.append(rec("t", "B", repeat=i, ok=False, error="timed out after 600s",
                            cost=None))
        else:
            rows.append(rec("t", "B", repeat=i, ok=b_ok))
    return rows


def test_b_failing_every_task_session_reads_worse_not_no_difference():
    rows = paired_rows(b_error=range(15))
    rows += [rec("n", v, kind="near_miss", used=False, repeat=i) for i in range(9) for v in "AB"]
    t = report.tally(rows, [], ["execution"], planned=15, judged=True)
    assert t["completion"]["A"] == (15, 15) and t["completion"]["B"] == (0, 15)
    assert t["checks"] == {"A": (15, 15), "B": (0, 15)}
    assert t["judge"]["A"] == 15 and t["judge"]["by_rule"] == 15
    for name in ("completion", "checks", "judge"):
        assert t["signals"][name]["reading"] == "worse", name
    assert t["verdict"] == "worse"


def test_b_failing_its_worst_sessions_cannot_read_better():
    # B fails 3 of 15 and the judge prefers each of the 12 it finished: inconclusive, not better.
    rows = paired_rows(b_error=(0, 1, 2))
    judged = [{"task": "t", "repeat": i, "verdict": {"winner": "B", "reason": "", "scores": {
        "A": {"execution": 3}, "B": {"execution": 5}}}} for i in range(3, 15)]
    t = report.tally(rows, judged, ["execution"], planned=15, judged=True)
    assert t["judge"] == {"B": 12, "tie": 0, "A": 3, "n": 15, "by_rule": 3, "unread": 0}
    assert t["completion"]["asymmetric"] and "worse" not in [
        x["reading"] for x in t["signals"].values()]
    assert t["verdict"] == "inconclusive"


def test_infrastructure_failures_are_left_out_and_too_many_make_it_inconclusive():
    t = report.tally(paired_rows(b_infra=(0,)), [], ["execution"], planned=15)
    assert t["checks"] == {"A": (14, 14), "B": (14, 14)}  # the pair is dropped, not counted
    assert len(t["infra"]) == 1 and [r["repeat"] for r in t["unpaired"]] == [0]
    assert t["verdict"] == "no detectable difference"
    t = report.tally(paired_rows(b_infra=range(5)), [], ["execution"], planned=15)
    assert t["completion"]["complete_pairs"] == 10 and t["completion"]["insufficient"]
    assert t["verdict"] == "inconclusive"


def test_a_change_whose_skill_crashes_the_agent_reads_worse_end_to_end(env):
    b = variant(env, "crashing", GOOD_SKILL.replace("Write out.txt", "CRASH"))
    code, out = run_eval(env, b)
    assert code == 1
    results = json.loads((out / "results.json").read_text())
    assert results["checks"] == {"A": [15, 15], "B": [0, 15]} and results["failed"] == 15
    assert results["judge"]["A"] == 15 and results["judge"]["by_rule"] == 15
    assert results["verdict"] == "worse"
    text = (out / "report.md").read_text()
    assert "**Verdict: worse.**" in text
    assert "| Task sessions completed | 15/15 (100%) | 0/15 (0%) |" in text


def stream(*evts):
    return "\n".join(json.dumps(e) for e in evts)


def tool_use(tid, command):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}]}}


def tool_result(tid, content, error):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": error}]}}


def test_a_refused_command_is_not_credited_as_run():
    profile, problems = runner.load_profile(SKILL / "profiles" / "claude-code.json")
    assert problems == []
    out = stream(
        tool_use("toolu_1", "python3 -m unittest -v"),
        {"type": "system", "subtype": "permission_denied", "tool_name": "Bash",
         "tool_use_id": "toolu_1"},
        tool_result("toolu_1", "Claude requested permissions to use Bash, but you haven't "
                               "granted it yet.", True),
        tool_use("toolu_2", "python3 -m pytest"),
        tool_use("toolu_3", "python -m unittest discover"),
        tool_result("toolu_3", "Permission to use Bash with command python -m unittest discover "
                               "has been denied.", True),
        tool_use("toolu_4", "grep -r denied ."),
        tool_result("toolu_4", "notes.txt: the request has been denied", False),
        {"type": "result", "result": "Tests pass.", "total_cost_usd": 0.01})
    _, _, commands, _ = runner.read_session(out, profile, "agent-ready")
    assert [c["status"] for c in commands] == ["denied", "no result", "denied", "ran"]
    got = runner.grade([{"type": "command_run", "pattern": "unittest|pytest"},
                        {"type": "command_not_run", "pattern": "unittest"}],
                       Path("."), "Tests pass.", commands)
    assert [g["pass"] for g in got] == [False, False]  # never ran; but it was attempted
    assert got[0]["detail"] == "requested, never ran: denied, no result"
    text = blind.render({"result": "Tests pass.", "commands": commands})
    assert "`python3 -m unittest -v`: refused; it did not run" in text
    assert "`python3 -m pytest`: no result seen" in text
    # A profile that names commands but cannot join them to results is refused.
    bad = dict(profile)
    del bad["command_results"]
    path = Path(__import__("tempfile").mkdtemp()) / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert any("a request is not an execution" in p for p in runner.load_profile(path)[1])


def test_an_executed_failing_test_is_credited_as_run_and_shows_its_outcome():
    profile, _ = runner.load_profile(SKILL / "profiles" / "claude-code.json")
    out = stream(
        tool_use("toolu_9", "python -m unittest -v"),
        tool_result("toolu_9", [{"type": "text", "text": "Exit code 1\ntest_century ... FAIL\n\n"
                                                         "FAILED (failures=1)"}], True),
        {"type": "result", "result": "One test fails.", "total_cost_usd": 0.01})
    _, _, commands, _ = runner.read_session(out, profile, "agent-ready")
    assert commands == [{"command": "python -m unittest -v", "status": "failed",
                         "output": "Exit code 1\ntest_century ... FAIL\n\nFAILED (failures=1)"}]
    got = runner.grade([{"type": "command_run", "pattern": "unittest"}], Path("."), "", commands)
    assert got[0]["pass"] is True
    text = blind.render({"result": "One test fails.", "commands": commands})
    assert "`python -m unittest -v`: ran and failed" in text and "FAILED (failures=1)" in text


def test_deleting_the_test_suite_fails_the_inventory_check_and_the_judge_sees_it(env):
    tasks = json.loads((SKILL / "tasksets" / "agent-ready.json").read_text(encoding="utf-8"))
    fix = next(t for t in tasks["tasks"] if t["id"] == "fix-bug")
    profile, _ = runner.load_profile(env["profile"])
    record = runner.session(profile, fix["prompt"] + " REMOVE-TESTS", env["root"],
                            files=fix["files"], checks=fix["checks"], budget=0.10, timeout=60)
    assert record["error"] is None and record["deleted"] == ["test_calc.py"]
    by_name = {c["check"]: c for c in record["checks"]}
    assert by_name["the test suite is intact"]["pass"] is False
    assert by_name["the test suite is intact"]["detail"] == "deleted"
    assert by_name["ran the tests"]["pass"] is True  # the command alone cannot catch it
    assert not report.passed(record)
    assert "+    return a + b" in record["diffs"]["calc.py"]
    text = blind.render(record)
    assert "Files deleted: test_calc.py" in text and "#### test_calc.py (deleted)" in text
    assert "-    def test_add(self):" in text and "Ran 0 tests" in text
    assert "#### calc.py (edited)" in text
    assert list(env["root"].iterdir()) == []


def test_file_unchanged_checks_against_the_fixture(tmp_path):
    fixtures = {"same.txt": "x\n", "edited.txt": "old\n", "gone.txt": "y\n"}
    write(tmp_path, "same.txt", "x\n")
    write(tmp_path, "edited.txt", "new\n")
    checks = [{"type": "file_unchanged", "path": p} for p in sorted(fixtures)]
    got = runner.grade(checks, tmp_path, "", [], files=fixtures)
    assert [(g["pass"], g["detail"]) for g in got] == [
        (False, "changed"), (False, "deleted"), (True, "")]
    deleted, diffs = runner.deletions(tmp_path, fixtures)
    assert deleted == ["gone.txt"] and sorted(diffs) == ["edited.txt", "gone.txt"]
    bad = task_set()
    bad["tasks"][0]["checks"].append({"type": "file_unchanged", "path": "not-a-fixture.py"})
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert any("not one of the task's files" in p for p in skill_eval.load_tasks(path)[1])


@pytest.mark.parametrize("amount", ["nan", "inf", "-inf", "0", "0.00", "-1", "0.009", "0.026",
                                    "1e400", "ten", ""])
def test_invalid_budgets_are_refused(env, capsys, amount):
    with pytest.raises(ValueError):
        runner.usd(amount)
    for flag in ("--max-cost-usd", "--run-budget-usd", "--judge-budget-usd",
                 "--trigger-budget-usd"):
        assert run_eval(env, env["a"], "%s=%s" % (flag, amount))[0] == 2
        assert flag in capsys.readouterr().err


def test_budgets_are_normalized_once_and_used_everywhere(env, tmp_path):
    assert [runner.usd(x) for x in ("0.01", "0.1", "0.50", "10", 0.3, "1e1")] == [
        0.01, 0.1, 0.5, 10.0, 0.3, 10.0]
    profile, _ = runner.load_profile(fake_profile(tmp_path))
    assert runner.argv_for(profile, None, 0.1)[2:4] == ["--budget", "0.10"]
    with pytest.raises(ValueError):
        runner.argv_for(profile, None, 0.026)  # would reserve 0.026 but authorize 0.03
    code, out = run_eval(env, env["a"], "--no-trigger", "--repeats", "1",
                         "--run-budget-usd", "0.1", "--judge-budget-usd", "0.07")
    assert code == 0
    meta = json.loads((out / "meta.json").read_text())
    assert (meta["run_budget"], meta["judge_budget"]) == (0.1, 0.07)
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
    assert {r["budget"] for r in rows} == {0.1}


def test_a_reported_cost_must_be_finite_and_nonnegative(tmp_path):
    profile = json.loads(fake_profile(tmp_path).read_text())
    for bad in (float("nan"), float("inf"), -0.5, "0.1", True):
        out = json.dumps({"type": "result", "result": "ok", "cost": bad})
        assert runner.read_session(out, profile, "")[1] is None, bad
    assert runner.read_session(json.dumps({"type": "result", "result": "ok", "cost": 0}),
                               profile, "")[1] == 0.0


def test_concurrent_reservations_never_pass_the_cap(env, monkeypatch):
    import threading
    for bad in ("nan", float("inf"), 0, -1, 0.026):
        with pytest.raises(ValueError):
            skill_eval.Budget(bad)
    budget = skill_eval.Budget(0.10)
    gate, got = threading.Barrier(8), []

    def take():
        gate.wait()
        got.append(budget.reserve(0.03))

    threads = [threading.Thread(target=take) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert got.count(True) == 3
    budget.settle(0.03, float("nan"))  # an unreadable spend stays charged at the cap
    assert not budget.reserve(0.03) and budget.reserve(0.01)
    # End to end: four sessions at once, each reporting a NaN spend, under a 0.10 cap.
    monkeypatch.setenv("FAKE_COST", "nan")
    code, out = run_eval(env, env["a"], "--keep-env", "FAKE_COST", "--jobs", "4", "--no-judge",
                         "--no-trigger", "--repeats", "1", "--run-budget-usd", "0.05",
                         "--max-cost-usd", "0.10")
    assert code == 3
    assert len((out / "runs.jsonl").read_text().splitlines()) == 2
    assert "2 sessions reported no cost; each is counted at its cap." in (
        out / "report.md").read_text()


# --- the skill's own rules ------------------------------------------------------------------

def test_headers_state_options_and_exit_codes():
    head = (SCRIPTS / "skill_eval.py").read_text(encoding="utf-8").split('"""')[1]
    assert "Exit codes:" in head and "Stdlib only" in head
    for name in ("runner.py", "blind.py", "report.py"):
        assert "Stdlib only" in (SCRIPTS / name).read_text(encoding="utf-8").split('"""')[1]
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for name in ("skill_eval.py", "runner.py", "blind.py", "report.py", "judge-prompt.md"):
        assert name in text, name


def test_skill_is_vendor_neutral():
    names = ["Claude", "Codex", "Cursor", "OpenAI", "Anthropic", "GPT", "Copilot", "Gemini"]
    for path in SKILL.rglob("*"):
        if path.is_file() and path.suffix in (".md", ".py"):
            text = path.read_text(encoding="utf-8")
            for name in names:
                assert name not in text, "%s names %s" % (path.name, name)


def test_seeded_rng_is_python_version_stable():
    # The blind order is reproducible from the recorded seed only if random.Random(seed).random()
    # is the same on every supported Python; it has been since 3.2.
    assert round(random.Random(7).random(), 6) == 0.323833
