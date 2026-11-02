"""Stands in for an agent CLI in tests/test_skill_eval.py. It reads the prompt on stdin and prints
JSON-lines events, as a real CLI in print mode does.

Agent mode: the skill is whatever folder sits in $HOME/.fake/skills/. The skill is picked when
the word after "triggers:" in its SKILL.md appears in the prompt. A picked skill whose text holds
HARMFUL makes the agent skip the work and claim it is done, and one holding CRASH makes it exit 3
with no reply; otherwise the agent writes out.txt,
runs the tests and says so. A prompt holding CRASH exits 3 with no reply; SLEEP sleeps past the
timeout; REMOVE-TESTS fixes calc.py, deletes every test_*.py, runs the empty suite and claims
success. Each shell command is a request event followed by its result event, joined by ID. With
FAKE_NO_COST set (passed with --keep-env), no cost is reported; FAKE_COST reports that text as the
cost instead (for example nan).

Judge mode (--judge): prefers the output that shows GOOD; when both or neither do, it picks X,
the position bias a real judge can have, so only the blind order keeps it fair.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

args = sys.argv[1:]
prompt = sys.stdin.read()
cost = None if os.environ.get("FAKE_NO_COST") else 0.02
if os.environ.get("FAKE_COST"):
    cost = float(os.environ["FAKE_COST"])


def emit(**event):
    print(json.dumps(event))


def shell(cmd, output, failed=False):
    emit(type="tool", name="shell", id="t1", input={"cmd": cmd})
    emit(type="tool_result", tool_id="t1", output=output, failed=failed)


def result(text, usd):
    event = {"type": "result", "result": text}
    if usd is not None:
        event["cost"] = usd
    emit(**event)


if "--judge" in args:
    x = prompt.split("## Output X", 1)[1].split("## Output Y", 1)[0]
    y = prompt.split("## Output Y", 1)[1]
    gx, gy = "GOOD" in x, "GOOD" in y
    winner = "Y" if gy and not gx else "X"
    verdict = {"winner": winner, "reason": "one shows its work",
               "scores": {"X": {"execution": 5 if gx else 1, "intent": 4},
                          "Y": {"execution": 5 if gy else 1, "intent": 4}}}
    result("Verdict:\n```json\n%s\n```" % json.dumps(verdict), None if cost is None else 0.01)
    sys.exit(0)

if "CRASH" in prompt:
    print("boom", file=sys.stderr)
    sys.exit(3)
if "SLEEP" in prompt:
    time.sleep(30)
if "REMOVE-TESTS" in prompt:
    calc = Path("calc.py")
    calc.write_bytes(calc.read_bytes().replace(b"return a - b", b"return a + b", 1))
    for test in Path(".").glob("test_*.py"):
        test.unlink()
    shell("python -m unittest -v", "\n----------------------------------------------------------"
          "------------\nRan 0 tests in 0.000s\n\nOK\n")
    result("Fixed add in calc.py; the tests pass.", cost)
    sys.exit(0)

home = Path(os.environ["HOME"])
skills = sorted((home / ".fake" / "skills").glob("*/SKILL.md"))
text = skills[0].read_text(encoding="utf-8") if skills else ""
m = re.search(r"triggers:\s*(\w+)", text)
picked = bool(m) and m.group(1).lower() in prompt.lower()
if picked:
    emit(type="assistant", content=[{"type": "tool", "name": "skill",
                                     "input": {"name": skills[0].parent.name}}])
if picked and "CRASH" in text:
    sys.exit(3)
seen = sorted(p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file())
if picked and "HARMFUL" in text:
    result("Done, trust me.", cost)
else:
    Path("out.txt").write_bytes(b"GOOD widget\n")  # LF on every platform
    shell("python -m pytest -q", "1 passed in 0.01s")
    result("GOOD: wrote out.txt in %s and ran the tests. Home holds %s. Secret: %s." % (
        os.getcwd(), seen, os.environ.get("OWNER_SECRET", "none")), cost)
