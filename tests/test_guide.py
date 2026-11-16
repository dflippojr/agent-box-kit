"""GUIDE.md names only things that exist and runs scripts only with flags they accept. Pure stdlib.

Paths: every relative link target, and every backticked path that starts with `<kit>/` or with
one of the kit's top-level folders, must exist in the repo; a link's `#anchor` must match a
heading in the target. Paths in the user's repo (`scripts/check.py`, `docs/`) are not kit paths
and are not checked here.

Scripts: every `<kit>/....py` the guide runs, inside a code block or a backticked span, must exit
0 on `--help` (after its subcommand, such as `judge.py probe`, where the script accepts it
there), and every `--flag` shown with it must appear in that help. A flag the prose mentions
on its own (add `--no-remote`) must appear in the help of a script the same section runs.
The scripts bootstrap writes into the user's repo are checked from their templates when the
guide shows them with a flag.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "GUIDE.md"
KIT_TOP = ("agent-ready/", "box/", "tests/", "ci/", "experiments/")
# Scripts box-bootstrap writes into the user's repo, and the template each is written from.
GENERATED = {
    "scripts/ready.py": "box/skills/box-bootstrap/templates/neutral/ready.py",
    "scripts/check.py": "box/skills/box-bootstrap/templates/scripts/check.py",
    "scripts/pr_body_lint.py": "box/skills/box-bootstrap/templates/scripts/pr_body_lint.py",
    "scripts/tamper_guard.py": "box/skills/box-bootstrap/templates/scripts/tamper_guard.py",
}
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z-]*")


def guide_text():
    return GUIDE.read_text(encoding="utf-8")


def sections(text):
    """(heading, body) for each `## ` section; the part before the first one is ''."""
    parts = re.split(r"^## (.*)$", text, flags=re.M)
    out = [("", parts[0])]
    out += list(zip(parts[1::2], parts[2::2]))
    return out


def code_spans(body):
    """Each code block (continuation lines joined) and each backticked span, as one string."""
    spans = []
    fence = r"^ *```[^\n]*\n(.*?)^ *```"
    blocks = re.findall(fence, body, flags=re.M | re.S)
    for block in blocks:
        spans.extend(line for line in block.replace("\\\n", " ").splitlines() if line.strip())
    rest = re.sub(fence, "", body, flags=re.M | re.S)
    # An inline span may wrap across lines in the source; join it into one.
    spans.extend(" ".join(s.split()) for s in re.findall(r"`([^`]+)`", rest))
    return spans


def invocations(span):
    """(script repo path, subcommand or None, flags) for each python script the span runs."""
    found = []
    for m in re.finditer(r"python3?(?: -B)? (<kit>/)?(\S+\.py)((?: (?!python)\S+)*)", span):
        kit, rel, tail = m.group(1), m.group(2), m.group(3).split()
        if kit:
            path = rel
        elif rel in GENERATED:
            path = GENERATED[rel]
        else:
            continue
        sub = tail[0] if tail and re.fullmatch(r"[a-z]+", tail[0]) else None
        found.append((path, sub, sorted(set(FLAG.findall(" ".join(tail)))), bool(kit)))
    return found


def help_text(path, sub):
    """Run the script's --help (after the subcommand if it takes it there); return (rc, text)."""
    for args in ([sub, "--help"] if sub else None, ["--help"]):
        if args is None:
            continue
        proc = subprocess.run([sys.executable, "-B", str(ROOT / path)] + args,
                              capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return 0, proc.stdout + proc.stderr
    return proc.returncode, proc.stdout + proc.stderr


def headings(path):
    slugs = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"#{1,6} (.*)", line)
        if m:
            slug = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-")
            slugs.add(slug)
    return slugs


def test_guide_is_linked_from_readme():
    assert "GUIDE.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_every_link_target_exists():
    problems = []
    for target in re.findall(r"\]\(([^)\s]+)\)", guide_text()):
        if re.match(r"[a-z]+:", target):
            continue
        rel, _, anchor = target.partition("#")
        path = ROOT / rel
        if not path.exists():
            problems.append("missing: %s" % target)
        elif anchor and path.is_file() and anchor not in headings(path):
            problems.append("no heading for anchor: %s" % target)
    assert not problems, problems


def test_every_kit_path_exists():
    problems = []
    for span in code_spans(guide_text()):
        for token in re.findall(r"[^\s`'\"]+", span):
            token = token.rstrip(".,;:)")
            if token.startswith("<kit>/"):
                rel = token[len("<kit>/"):]
            elif token.startswith(KIT_TOP):
                rel = token
            else:
                continue
            if not (ROOT / rel).exists():
                problems.append(token)
    assert not problems, problems


def test_guide_runs_kit_scripts():
    runs = [inv for span in code_spans(guide_text()) for inv in invocations(span)]
    kit_scripts = {path for path, _, _, kit in runs if kit}
    # The guide's own steps: profile, judge probe, audit, card check, bootstrap, filing, hunt.
    for name in ("profile.py", "judge.py", "audit.py", "card.py", "bootstrap.py",
                 "file_issues.py"):
        assert any(p.endswith("/" + name) for p in kit_scripts), name


def test_every_script_accepts_the_flags_shown():
    problems = []
    for heading, body in sections(guide_text()):
        helps = []
        prose_flags = set()
        for span in code_spans(body):
            runs = invocations(span)
            if not runs and span.startswith("--"):
                prose_flags.update(FLAG.findall(span))
            for path, sub, flags, kit in runs:
                if not kit and not flags:
                    continue  # a generated script run bare: nothing to check
                rc, text = help_text(path, sub)
                if rc != 0:
                    problems.append("%s: %s --help exits %d" % (heading, path, rc))
                    continue
                helps.append(text)
                problems.extend("%s: %s does not accept %s" % (heading, path, f)
                                for f in flags if f not in text)
        for flag in sorted(prose_flags - {"--help"}):
            if not any(flag in text for text in helps):
                problems.append("%s: %s is shown, but no script this section runs accepts it"
                                % (heading or "(intro)", flag))
    assert not problems, problems
