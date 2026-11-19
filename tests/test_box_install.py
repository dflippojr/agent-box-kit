"""The box skills' install contract (issue #38, option A). Pure stdlib.

Every box skill is installed by symlinking its folder into a skills folder, never by copying it,
because its SKILL.md and scripts reach other folders of the checkout (`../../STANDARD.md`,
`../box-audit/scripts/`, box/lib). On Windows the folder is not installed: the agent reads the
SKILL.md in the checkout and runs its scripts by path. Each SKILL.md must say both, and every
relative path it names must resolve the same through a symlinked install as in the checkout.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted(p.parent for p in (ROOT / "box" / "skills").glob("*/SKILL.md"))


def paragraphs(text):
    return [" ".join(p.split()) for p in re.split(r"\n[ \t]*\n", text)]


def test_every_box_skill_is_listed():
    assert {p.name for p in SKILLS} == {"box-audit", "box-bootstrap", "box-crosspollinate",
                                        "queue-fill", "skill-eval"}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skill_md_has_an_install_line(skill):
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    lines = [p for p in paragraphs(text) if p.startswith("Install")]
    assert lines, "%s/SKILL.md has no paragraph starting with Install" % skill.name
    line = lines[0]
    for needed in ("symlink", "not by copying", "Windows", "by path"):
        assert needed in line, "%s install line lacks %r: %s" % (skill.name, needed, line)


def named_paths(text):
    """Relative paths a SKILL.md names: link targets, `../` paths and `scripts/*.py`."""
    paths = {m.split("#")[0] for m in re.findall(r"\]\(([^)\s]+)\)", text)
             if not m.startswith(("#", "http://", "https://"))}
    paths |= set(re.findall(r"(?<![\w./<>-])((?:\.\./)+[\w./-]*\w|scripts/\w+\.py)", text))
    paths.discard("")
    return paths


@pytest.mark.skipif(sys.platform == "win32", reason="Windows resolves .. before the symlink")
@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_paths_resolve_from_a_symlinked_install(skill, tmp_path):
    skills = tmp_path / "home" / "skills"
    skills.mkdir(parents=True)
    linked = skills / skill.name
    os.symlink(str(skill), str(linked), target_is_directory=True)
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    checked = 0
    for rel in sorted(named_paths(text)):
        in_checkout = os.path.join(str(skill), rel)
        if not os.path.exists(in_checkout):
            # `scripts/check.py` in box-bootstrap is a file in the user's repo, not the kit's.
            assert not rel.startswith("..") and "](" + rel not in text, (skill.name, rel)
            continue
        through_link = os.path.join(str(linked), rel)
        assert os.path.exists(through_link), (skill.name, rel)
        assert os.path.samefile(through_link, in_checkout), (skill.name, rel)
        checked += 1
    assert checked, skill.name


@pytest.mark.skipif(sys.platform == "win32", reason="Windows resolves .. before the symlink")
@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_scripts_run_through_a_symlinked_install(skill, tmp_path):
    """A script started by its path through the link finds the other folders it loads."""
    linked = tmp_path / skill.name
    os.symlink(str(skill), str(linked), target_is_directory=True)
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    run = set(re.findall(r"python3? (?:-B )?scripts/(\w+\.py)", text))
    run = [name for name in run if (skill / "scripts" / name).exists()]
    assert run, skill.name
    # Every script that loads box/lib, named in SKILL.md or not (issue #36).
    run = sorted(set(run) | {p.name for p in (skill / "scripts").glob("*.py")
                             if '/ "lib"))' in p.read_text(encoding="utf-8")})
    for name in run:
        proc = subprocess.run([sys.executable, "-B", str(linked / "scripts" / name), "--help"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60, cwd=str(tmp_path))
        assert proc.returncode == 0, (skill.name, name, proc.stdout + proc.stderr)
