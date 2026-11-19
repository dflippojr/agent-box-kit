"""box/lib: the one home of the helpers box scripts share (issue #36). Pure stdlib; real files,
with a stat result faked only where a platform cannot make the file kind under test."""
import os
import stat
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "box" / "skills" / "box-audit" / "scripts"
sys.path.insert(0, str(AUDIT))

import collect  # noqa: E402

REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


def fake_reparse(monkeypatch, target):
    """os.lstat reports `target` as a plain file that is a Windows reparse point, as Windows does
    for a reparse point that is not a symlink or junction (os.readlink cannot read it)."""
    real = os.lstat

    def lstat(path, *args, **kw):
        if os.path.abspath(str(path)) == os.path.abspath(str(target)):
            return types.SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_nlink=1,
                                         st_file_attributes=REPARSE)
        return real(path, *args, **kw)
    monkeypatch.setattr(os, "lstat", lstat)


def test_collect_counts_any_reparse_point_as_a_link(tmp_path, monkeypatch):
    """Any reparse point is a link, the more conservative refusal judge.py and select.py made;
    collect.py once asked only whether os.readlink succeeds."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("x\n", encoding="utf-8")
    fake_reparse(monkeypatch, tmp_path / "docs")
    assert collect.linked(tmp_path, "docs/a.md")
    assert collect.read(tmp_path, "docs/a.md") is None


# box/lib, which collect.py put on sys.path.
import git_env  # noqa: E402
import isolation  # noqa: E402
import issue_folder  # noqa: E402
import paths  # noqa: E402


def test_any_reparse_point_is_a_link_to_every_caller(tmp_path, monkeypatch):
    """One link test for box/: paths.is_link. collect.py, judge.py's sweep (isolation), the issue
    folder reader and bootstrap all read it, so a reparse point is refused alike everywhere."""
    folder = tmp_path / "docs"
    folder.mkdir()
    assert not paths.is_link(folder) and not paths.linked(tmp_path, "docs/a.md")
    fake_reparse(monkeypatch, folder)
    assert paths.is_link(folder)
    assert paths.is_link_stat(os.lstat(str(folder)))
    assert paths.linked(tmp_path, "docs/a.md")
    assert collect.linked_files(tmp_path, ["docs/a.md", "b.md"]) == ["docs/a.md"]
    assert isolation.is_link is paths.is_link and collect.is_link is paths.is_link


def test_a_missing_path_is_not_a_link_and_an_unreadable_one_is_refused(tmp_path, monkeypatch):
    assert not paths.is_link(tmp_path / "missing")
    assert not paths.linked(tmp_path, "missing/a.md")
    real = os.lstat

    def lstat(path, *args, **kw):
        if os.path.basename(str(path)) == "locked":
            raise PermissionError(13, "Permission denied")
        return real(path, *args, **kw)
    monkeypatch.setattr(os, "lstat", lstat)
    with pytest.raises(PermissionError):
        paths.is_link(tmp_path / "locked")
    assert paths.linked(tmp_path, "locked/a.md")
    assert collect.linked_files(tmp_path, ["locked/a.md"]) == ["locked/a.md"]


@pytest.mark.skipif(os.name != "nt", reason="a junction is a Windows reparse point")
def test_a_junction_is_a_link_to_every_caller(tmp_path):
    import _winapi
    target = tmp_path / "target"
    target.mkdir()
    (target / "1.md").write_text("---\nnumber: 1\ntitle: t\nstate: open\n---\nbody\n",
                                 encoding="utf-8")
    junction = tmp_path / "j"
    _winapi.CreateJunction(str(target), str(junction))
    assert paths.is_link(junction) and paths.linked(tmp_path, "j/1.md")
    assert collect.linked(tmp_path, "j/1.md") and collect.read(tmp_path, "j/1.md") is None
    with pytest.raises(issue_folder.InputError, match="link"):
        issue_folder.read_folder(junction)
    (target / ".git").mkdir()
    outer = tmp_path / "outer"
    outer.mkdir()
    _winapi.CreateJunction(str(target), str(outer / "inner"))
    assert not isolation.holds_checkout(outer)  # the sweep never walks through a junction


def test_inside_and_startup_bytecode_are_one_check(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "sub").mkdir(parents=True)
    assert paths.inside(root / "sub", root) and paths.inside(root, root)
    assert not paths.inside(tmp_path, root)
    monkeypatch.setattr(sys, "pycache_prefix", str(root / "sub"), raising=False)
    if sys.flags.dont_write_bytecode:
        assert paths.startup_bytecode(root) is None
    else:
        assert "is inside the audited repo" in paths.startup_bytecode(root)
        assert "is inside %s," % root in paths.startup_bytecode(root, root)
    assert collect.startup_bytecode is paths.startup_bytecode


def test_unsafe_output_refuses_inside_and_hard_links(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    assert paths.unsafe_output(root / "x", root)
    outside = tmp_path / "out.txt"
    assert paths.unsafe_output(outside, root) is None
    paths.write_outside(outside, "hi\n", root)
    assert outside.read_text(encoding="utf-8") == "hi\n"
    if hasattr(os, "link"):
        os.link(str(outside), str(tmp_path / "other.txt"))
        assert "hard links" in paths.unsafe_output(outside, root)
        with pytest.raises(ValueError):
            paths.write_outside(outside, "x", root)


def test_git_env_drops_every_git_variable_but_the_keep_list(monkeypatch):
    for name in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_CONFIG_COUNT",
                 "GIT_AUTHOR_NAME", "GIT_COMMITTER_EMAIL", "git_index_file"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("OTHER", "kept")
    read = git_env.git_env()
    assert not [k for k in read if k.upper().startswith("GIT_") and k not in (
        "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT", "GIT_TRACE2", "GIT_TRACE2_EVENT",
        "GIT_TRACE2_PERF")], read
    assert read["OTHER"] == "kept" and read["GIT_OPTIONAL_LOCKS"] == "0"
    write = git_env.git_env(keep=git_env.IDENTITY)
    assert write["GIT_AUTHOR_NAME"] == "x" and write["GIT_COMMITTER_EMAIL"] == "x"
    assert "GIT_COMMON_DIR" not in write and "GIT_DIR" not in write
    assert set(git_env.IDENTITY) == {"GIT_%s_%s" % (who, what) for who in ("AUTHOR", "COMMITTER")
                                     for what in ("NAME", "EMAIL", "DATE")}


import md  # noqa: E402
import scorecard  # noqa: E402

FENCED_EXAMPLE = """\
An example of the shape, not a section:

```markdown
### Proposed issues

#### Fake issue from an example
Labels: tier:mechanical
```

"""


def test_md_section_skips_headings_in_fenced_code():
    text = "```\n## Proof\nfenced\n```\n\n## Proof\n\nreal\n\n## Next\n"
    assert md.section(text, "Proof", 2) == "real"
    assert md.section(text, "proof", 2) == "real"
    assert md.section("~~~\n## Proof\n~~~\n", "Proof", 2) is None
    assert md.section("    ```\n## Proof\nx\n", "Proof", 2) == "x"  # not a fence md reads
    assert [h[:2] for h in md.headings("# A\n```\n# B\n```\n## C\n")] == [(1, "A"), (2, "C")]


def test_the_card_rules_skip_a_fenced_example_of_a_part():
    """A card's sections and parts are read with md.py, so a fenced example of `### Proposed
    issues` in a Gap is content, not a proposal the card must vouch for (issue #36)."""
    from test_box_audit import make_card
    card = make_card(["✓", "~", "✗", "~", "–", "~"])
    assert scorecard.check(card) == []
    before = [t for _, t, _ in scorecard.proposals(card)]
    gap = card.index("### Gap", card.index("## R: "))
    fenced = card[:gap] + FENCED_EXAMPLE + card[gap:]
    assert [t for _, t, _ in scorecard.proposals(fenced)] == before
    assert scorecard.check(fenced) == []
    assert [d for d, _, _ in scorecard.sections(
        "```\n## G: Enforced gate\n```\n" + card)] == scorecard.DIMENSIONS
