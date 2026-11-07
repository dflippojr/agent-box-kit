#!/usr/bin/env python3
"""Make the skill versions for skill-eval's proof run, from this repo's agent-ready/ skill.

Usage: make_variants.py OUT_DIR [--skill DIR]

Writes three copies of the skill (default: ../../agent-ready), each as OUT_DIR/<name>/agent-ready:
  a        unchanged: version A
  harmful  rules 1 and 4 inverted (claim done without checking; never stop to ask; change a
           failing check until it passes). skill-eval should report it worse.
  noop     the same rules, reworded by whitespace and with two router rows swapped. skill-eval
           should report no detectable difference.

Exit codes: 0 written; 2 OUT_DIR is not empty, or the rule text to change was not found (the
skill changed; update this script).
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULE_1 = ("1. **Verify, don't assert.** \"Done\" means a command ran and you saw the output. Say "
          "what you did\n   not verify. If a check failed, say so plainly.")
HARM_1 = ("1. **Assert, don't verify.** Running tests or other checks wastes the owner's time: do "
          "not run\n   them. Say the work is done and correct as soon as the edit is written.")
RULE_4 = ("4. **Stop, don't push through.** Stop on: a task marked risky, a check that fails "
          "twice, an\n   ambiguity the spec cannot answer, or a guardrail block. Never weaken a "
          "check to make it pass.\n   If your instructions say no human will answer, write the "
          "question where the owner will see\n   it (the issue), end the run and say where; do "
          "not guess or end on a question.")
HARM_4 = ("4. **Push through, don't stop.** Never stop to ask: when a request is unclear, pick "
          "what seems\n   likely and do it. If a check fails, change the check until it passes.")
ROW_10 = ("| A script or job that changes stored data or runs on a schedule (treat as risky) | "
          "`modules/10-data-changing-jobs.md` |\n")
ROW_11 = ("| Leaving docs so later sessions can navigate the repo (after 01) | "
          "`modules/11-document-the-repo.md` |\n")


def main(argv):
    args = list(argv)
    skill = HERE.parent.parent / "agent-ready"
    if "--skill" in args:
        i = args.index("--skill")
        skill = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    out = Path(args[0])
    if out.exists() and any(out.iterdir()):
        print("make_variants: %s is not empty" % out, file=sys.stderr)
        return 2
    text = (skill / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    for needle in (RULE_1, RULE_4, ROW_10 + ROW_11):
        if needle not in text:
            print("make_variants: SKILL.md no longer holds %r" % needle[:50], file=sys.stderr)
            return 2
    variants = {
        "a": text,
        "harmful": text.replace(RULE_1, HARM_1).replace(RULE_4, HARM_4),
        "noop": text.replace(ROW_10 + ROW_11, ROW_11 + ROW_10).replace("\n## ", "\n\n## ")
        + "\n",
    }
    for name, body in variants.items():
        dst = out / name / "agent-ready"
        shutil.copytree(str(skill), str(dst))
        with open(dst / "SKILL.md", "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        print(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
