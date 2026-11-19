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
