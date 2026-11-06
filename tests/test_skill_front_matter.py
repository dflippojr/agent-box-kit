"""Every SKILL.md in the repo must have YAML front matter that a strict YAML parser accepts, with a
non-empty string `name` and `description`. A plain scalar holding ": " (for example "will review:
changing") is not valid YAML. Some loaders quietly retry with the value quoted; others reject the
file or drop its metadata. So the file must parse as written. Uses PyYAML (ci/requirements-test.txt)
because the stdlib has no YAML parser, and a hand-rolled check would miss what a real one rejects."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FRONT_MATTER = re.compile(r"---\r?\n(.*?)\r?\n---\r?\n", re.S)
SKILL_FILES = sorted(p for p in ROOT.rglob("SKILL.md")
                     if not any(part.startswith(".") for part in p.relative_to(ROOT).parts))


def test_the_skills_are_found():
    names = {p.parent.name for p in SKILL_FILES}
    assert {"agent-ready", "skill-eval", "box-audit"} <= names, sorted(names)


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_front_matter_parses_as_yaml_with_name_and_description(path):
    rel = path.relative_to(ROOT).as_posix()
    m = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    assert m, "%s: no front matter between --- lines at the top of the file" % rel
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        raise AssertionError("%s: front matter is not valid YAML (quote a value that holds "
                             "': ' or starts with a YAML indicator): %s" % (rel, e))
    assert isinstance(meta, dict), "%s: front matter is not a key: value mapping" % rel
    for key in ("name", "description"):
        value = meta.get(key)
        assert isinstance(value, str) and value.strip(), (
            "%s: front matter lacks a non-empty string `%s`" % (rel, key))
