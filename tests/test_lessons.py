"""Checks the lessons registry in box/lessons/: one Markdown file per lesson, each tied to the
check or rubric line that enforces it. Pure stdlib.

A lesson has six bold-label fields (FIELDS), each once. **Rule** links one EVIDENCE.md row by the
exact text of the row's first cell (rows have no anchors). **Evidence** and **Status** take a value
from their set, and **Evidence** must be a level the linked row's Evidence cell names, when its
table has that column. **Enforced by** is `none`, or names checks: a backticked repo-relative path
to a .py file or a workflow, optionally `path.py::name` (or `::Class::name`) that must exist as a
function or class, or a Markdown link, relative to the lesson, to a heading of box/STANDARD.md.
An `enforced` lesson names at least one check; an `open` lesson says `none`.

box/lessons/README.md lists exactly the lesson files, each with its status and its check, and
lists the open ones again under `## Open`. The negative controls build lessons in a throwaway repo
under tmp_path and expect the same checker to reject each broken one.
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LESSONS = ROOT / "box" / "lessons"
NOT_LESSONS = {"README.md", "TEMPLATE.md"}

FIELDS = ["Rule", "Why", "Incident", "Enforced by", "Evidence", "Status"]
LEVELS = ("observed", "asserted", "hypothesis")
STATUSES = ("enforced", "open")
MIN_SEEDS = 10

FIELD_RE = re.compile(r"^\*\*([A-Z][A-Za-z ]*):\*\*[ \t]*", re.M)
LINK_RE = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\(([^()\s]+)\)")
CODE_RE = re.compile(r"`([^`]+)`")
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def lesson_files(folder=LESSONS):
    return sorted(p for p in folder.glob("*.md") if p.name not in NOT_LESSONS)


# ----- EVIDENCE.md rows ----------------------------------------------------------------------

def split_row(line):
    """Cells of a Markdown table line, splitting on unescaped pipes."""
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def evidence_rows(path):
    """Map each data row's first cell to its Evidence cell, or None when its table has none."""
    rows = {}
    lines = read(path).splitlines()
    headers = None
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            headers = None
            continue
        cells = split_row(line)
        if all(re.match(r"^:?-{3,}:?$", c) for c in cells):
            continue
        following = lines[i + 1] if i + 1 < len(lines) else ""
        if headers is None and re.match(r"^\s*\|?\s*:?-{3,}", following):
            headers = cells
            continue
        col = headers.index("Evidence") if headers and "Evidence" in headers else None
        rows[cells[0]] = cells[col] if col is not None and col < len(cells) else None
    return rows


# ----- headings and references ---------------------------------------------------------------

def slug(heading):
    """The anchor GitHub gives a heading: link text kept, lowercased, punctuation dropped."""
    text = LINK_RE.sub(lambda m: m.group(1), heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(path):
    found, counts, fenced = set(), {}, False
    for line in read(path).splitlines():
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else HEADING_RE.match(line)
        if m:
            base = slug(m.group(2))
            n = counts.get(base, 0)
            counts[base] = n + 1
            found.add(base if n == 0 else "%s-%d" % (base, n))
    return found


def defines(source, names):
    """Whether `names` (a function, or Class then method) is defined in the Python source."""
    scope = ast.parse(source).body
    for name in names:
        node = next((n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                        ast.ClassDef)) and n.name == name), None)
        if node is None:
            return False
        scope = getattr(node, "body", [])
    return True


def is_check(rel):
    """A check is a Python test or script, a workflow, or a line of the box standard."""
    return rel.endswith(".py") or rel.startswith(".github/workflows/") or rel == "box/STANDARD.md"


def check_reference(kind, ref, lesson, root):
    """Problems with one **Enforced by** reference (empty when it points at a live check)."""
    root = root.resolve()
    if kind == "code":
        path_part, _, rest = ref.partition("::")
        target = (root / path_part).resolve()
    else:
        path_part, _, rest = ref.partition("#")
        if re.match(r"^[a-z][a-z0-9+.-]*:", path_part, re.I):
            return ["link %s leaves the repo; name a check in it" % ref]
        target = (lesson.parent / path_part).resolve()
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        return ["%s points outside the repo" % ref]
    if not target.is_file():
        return ["%s: no such file %s" % (ref, rel)]
    if not is_check(rel):
        return ["%s is not a check (a .py test or script, a workflow, or a box/STANDARD.md "
                "line)" % ref]
    if kind == "code" and rest:
        if not rel.endswith(".py"):
            return ["%s: only a .py file has ::names" % ref]
        if not defines(read(target), rest.split("::")):
            return ["%s: %s is not defined in %s" % (ref, rest, rel)]
    if kind == "link":
        if rel.endswith(".md") and not rest:
            return ["%s: link a heading of %s, not the whole file" % (ref, rel)]
        if rest and rest not in anchors(target):
            return ["%s: no heading in %s has the anchor #%s" % (ref, rel, rest)]
    return []


def references(value):
    links = [("link", m.group(2)) for m in LINK_RE.finditer(value)]
    code = [("code", m.group(1).strip()) for m in CODE_RE.finditer(LINK_RE.sub("", value))]
    return links + code


# ----- one lesson ----------------------------------------------------------------------------

def parse_fields(text):
    marks = list(FIELD_RE.finditer(text))
    fields, dupes = {}, []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        name = m.group(1)
        if name in fields:
            dupes.append(name)
        fields[name] = " ".join(text[m.end():end].split())
    return fields, dupes


def check_lesson(path, root, rows):
    """Problems with one lesson file; empty means it passes."""
    fields, dupes = parse_fields(read(path))
    problems = ["field **%s** appears more than once" % d for d in dupes]
    for name in FIELDS:
        if not fields.get(name):
            problems.append("missing field **%s**" % name)
    evidence = fields.get("Evidence", "")
    if evidence and evidence not in LEVELS:
        problems.append("**Evidence** is %r; want one of %s" % (evidence, ", ".join(LEVELS)))
    status = fields.get("Status", "")
    if status and status not in STATUSES:
        problems.append("**Status** is %r; want one of %s" % (status, ", ".join(STATUSES)))

    rule = fields.get("Rule", "")
    evidence_file = (root / "EVIDENCE.md").resolve()
    row_links = [m.group(1) for m in LINK_RE.finditer(rule)
                 if (path.parent / m.group(2).partition("#")[0]).resolve() == evidence_file]
    if rule and len(row_links) != 1:
        problems.append("**Rule** must link one EVIDENCE.md row, found %d" % len(row_links))
    for cell in row_links:
        if cell not in rows:
            problems.append("**Rule** links %r, which is not the first cell of any EVIDENCE.md "
                            "row" % cell)
        elif rows[cell] is not None and evidence in LEVELS and evidence not in rows[cell]:
            problems.append("**Evidence** is %s but the row says %r" % (evidence, rows[cell]))

    enforced_by = fields.get("Enforced by", "")
    refs = [] if enforced_by == "none" else references(enforced_by)
    if enforced_by and enforced_by != "none" and not refs:
        problems.append("**Enforced by** names no check; write `none` if nothing enforces it")
    for kind, ref in refs:
        problems.extend(check_reference(kind, ref, path, root))
    if status == "enforced" and enforced_by == "none":
        problems.append("an `enforced` lesson must name its check, not `none`")
    if status == "open" and refs:
        problems.append("an `open` lesson names a check; mark it `enforced` or say `none`")
    return problems


# ----- the README ----------------------------------------------------------------------------

def check_readme(folder):
    """Problems with box/lessons/README.md against the lesson files in `folder`."""
    readme = folder / "README.md"
    if not readme.is_file():
        return ["%s is missing" % readme.name]
    text = read(readme)
    present = {p.name: parse_fields(read(p))[0] for p in lesson_files(folder)}
    listed = {}
    for line in text.splitlines():
        cells = split_row(line) if line.lstrip().startswith("|") else []
        m = LINK_RE.match(cells[0]) if cells else None
        if m and "/" not in m.group(2) and m.group(2).endswith(".md"):
            listed[m.group(2)] = cells
    problems = ["README lists %s, which is not a lesson file" % n for n in sorted(set(listed)
                                                                                 - set(present))]
    problems += ["README does not list lesson %s" % n for n in sorted(set(present) - set(listed))]
    for name in sorted(set(listed) & set(present)):
        cells, fields = listed[name], present[name]
        want = [fields.get("Status", ""), fields.get("Enforced by", "")]
        if cells[1:3] != want:
            problems.append("README row for %s says %s; the lesson says %s" % (name, cells[1:3],
                                                                                want))
    m = re.search(r"^## Open\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    open_listed = set(re.findall(r"\]\(([^()/\s]+\.md)\)", m.group(1))) if m else set()
    open_present = {n for n, f in present.items() if f.get("Status") == "open"}
    if not m:
        problems.append("README has no `## Open` section")
    elif open_listed != open_present:
        problems.append("README `## Open` lists %s; the open lessons are %s"
                        % (sorted(open_listed), sorted(open_present)))
    return problems


# ----- the registry in this repo -------------------------------------------------------------

def test_template_has_every_field():
    fields, _ = parse_fields(read(LESSONS / "TEMPLATE.md"))
    assert [f for f in FIELDS if f not in fields] == []


def test_enough_seed_lessons():
    assert len(lesson_files()) >= MIN_SEEDS


@pytest.mark.parametrize("path", lesson_files(), ids=lambda p: p.stem)
def test_lesson(path):
    problems = check_lesson(path, ROOT, evidence_rows(ROOT / "EVIDENCE.md"))
    assert not problems, "%s:\n%s" % (path.name, "\n".join(problems))


def test_readme_lists_exactly_the_lessons():
    problems = check_readme(LESSONS)
    assert not problems, "\n".join(problems)


def test_box_readme_points_at_the_lessons():
    assert "](lessons/" in read(ROOT / "box" / "README.md")


def test_agent_ready_never_points_at_the_lessons():
    """agent-ready/ must work when copied alone, so it may be pointed at but never points out."""
    hits = [p.relative_to(ROOT).as_posix() for p in (ROOT / "agent-ready").rglob("*")
            if p.is_file() and p.suffix in (".md", ".py", ".json") and "lessons/" in read(p)]
    assert hits == []


# ----- negative controls ---------------------------------------------------------------------

GOOD = """\
# Keep the gate honest

**Rule:** Fail a gate that runs nothing. Evidence row: [Gate fails empty (05)](../../EVIDENCE.md)

**Why:** A green gate that ran nothing proves nothing.

**Incident:** A gate ran zero tests and reported green.

**Enforced by:** `tests/test_gate.py::test_empty_fails`; [Per dimension](../STANDARD.md#per-dimension)

**Evidence:** observed

**Status:** enforced
"""


@pytest.fixture
def fake_repo(tmp_path):
    """A throwaway repo with one EVIDENCE.md row, a standard with a heading and one test."""
    (tmp_path / "box" / "lessons").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "EVIDENCE.md").write_text(
        "| Rule (module) | Source | Evidence | Notes |\n|---|---|---|---|\n"
        "| Gate fails empty (05) | a run | observed | |\n", encoding="utf-8")
    (tmp_path / "box" / "STANDARD.md").write_text("# Standard\n\n### Per dimension\n\nText.\n",
                                                  encoding="utf-8")
    (tmp_path / "tests" / "test_gate.py").write_text("def test_empty_fails():\n    pass\n",
                                                     encoding="utf-8")
    (tmp_path / "box" / "notes.md").write_text("# Notes\n", encoding="utf-8")
    return tmp_path


def lesson_problems(repo, text, name="lesson.md"):
    path = repo / "box" / "lessons" / name
    path.write_text(text, encoding="utf-8")
    return check_lesson(path, repo, evidence_rows(repo / "EVIDENCE.md"))


def test_control_a_good_lesson_passes(fake_repo):
    assert lesson_problems(fake_repo, GOOD) == []


def open_lesson(text):
    return text.replace("**Status:** enforced", "**Status:** open")


@pytest.mark.parametrize("mutate, problem", [
    (lambda t: re.sub(r"\*\*Why:\*\*.*\n", "", t), "missing field **Why**"),
    (lambda t: t.replace("**Incident:** A gate ran zero tests and reported green.",
                         "**Incident:**"), "missing field **Incident**"),
    (lambda t: t + "\n**Why:** again\n", "**Why** appears more than once"),
    (lambda t: t.replace("**Evidence:** observed", "**Evidence:** proven"), "**Evidence** is"),
    (lambda t: t.replace("**Evidence:** observed", "**Evidence:** asserted"), "the row says"),
    (lambda t: t.replace("**Status:** enforced", "**Status:** done"), "**Status** is"),
    (lambda t: t.replace("Gate fails empty (05)", "Gate fails empty"), "not the first cell"),
    (lambda t: t.replace("[Gate fails empty (05)](../../EVIDENCE.md)", "Gate fails empty (05)"),
     "must link one EVIDENCE.md row, found 0"),
    (lambda t: t.replace("tests/test_gate.py::", "tests/test_gone.py::"), "no such file"),
    (lambda t: t.replace("::test_empty_fails", "::test_renamed"), "is not defined in"),
    (lambda t: t.replace("#per-dimension", "#per-dimensions"), "no heading in"),
    (lambda t: t.replace("../STANDARD.md#per-dimension", "../notes.md#notes"), "is not a check"),
    (lambda t: t.replace("../STANDARD.md#per-dimension", "../STANDARD.md"), "not the whole file"),
    (lambda t: t.replace("../STANDARD.md#per-dimension", "https://example.com/x"),
     "leaves the repo"),
    (lambda t: re.sub(r"\*\*Enforced by:\*\*.*", "**Enforced by:** none", t),
     "`enforced` lesson must name its check"),
    (lambda t: re.sub(r"\*\*Enforced by:\*\*.*", "**Enforced by:** the reviewer", t),
     "names no check"),
    (open_lesson, "`open` lesson names a check"),
], ids=["missing-field", "empty-field", "duplicate-field", "bad-evidence", "evidence-vs-row",
        "bad-status", "rule-not-a-row", "rule-unlinked", "dead-path", "dead-test-name",
        "dead-anchor", "not-a-check", "whole-file", "external-link", "enforced-without-check",
        "prose-check", "open-with-check"])
def test_control_a_broken_lesson_is_rejected(fake_repo, mutate, problem):
    broken = mutate(GOOD)
    assert broken != GOOD
    problems = lesson_problems(fake_repo, broken)
    assert any(problem in p for p in problems), problems


def test_control_an_open_lesson_with_none_passes(fake_repo):
    text = open_lesson(re.sub(r"\*\*Enforced by:\*\*.*", "**Enforced by:** none", GOOD))
    assert lesson_problems(fake_repo, text) == []


README_GOOD = """\
# Lessons

| Lesson | Status | Enforced by |
|---|---|---|
| [Keep the gate honest](lesson.md) | enforced | `tests/test_gate.py::test_empty_fails`; [Per dimension](../STANDARD.md#per-dimension) |

## Open

None.
"""


def write_readme(repo, text):
    (repo / "box" / "lessons" / "README.md").write_text(text, encoding="utf-8")
    return check_readme(repo / "box" / "lessons")


def test_control_a_good_readme_passes(fake_repo):
    lesson_problems(fake_repo, GOOD)
    assert write_readme(fake_repo, README_GOOD) == []


@pytest.mark.parametrize("change, problem", [
    (lambda repo: lesson_problems(repo, GOOD, "second.md"), "does not list lesson second.md"),
    (lambda repo: (repo / "box" / "lessons" / "lesson.md").unlink(),
     "lists lesson.md, which is not a lesson file"),
    (lambda repo: lesson_problems(repo, open_lesson(re.sub(
        r"\*\*Enforced by:\*\*.*", "**Enforced by:** none", GOOD))), "README row for lesson.md"),
], ids=["one-missing", "one-extra", "stale-status"])
def test_control_a_stale_readme_is_rejected(fake_repo, change, problem):
    lesson_problems(fake_repo, GOOD)
    change(fake_repo)
    problems = write_readme(fake_repo, README_GOOD)
    assert any(problem in p for p in problems), problems


def test_control_an_open_lesson_missing_from_the_open_section_is_rejected(fake_repo):
    lesson_problems(fake_repo, open_lesson(re.sub(r"\*\*Enforced by:\*\*.*",
                                                  "**Enforced by:** none", GOOD)))
    text = README_GOOD.replace("| enforced | `tests/test_gate.py::test_empty_fails`; "
                               "[Per dimension](../STANDARD.md#per-dimension) |", "| open | none |")
    problems = write_readme(fake_repo, text)
    assert any("`## Open` lists" in p for p in problems), problems
