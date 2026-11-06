"""Provenance check: every module and template in agent-ready/ is backed by an EVIDENCE.md row.
Pure stdlib.

A rule row is a data row of an EVIDENCE.md table whose header has an `Evidence` column (the
Finding | Change tables have none and are skipped). For those rows:

- Coverage. Each file under agent-ready/modules/ and agent-ready/templates/ must be named by at
  least one rule row. A module is named by its number in the row's first cell, in a parenthetical
  such as `(02)`, `(01, 03)`, `(02, template)` or `(modules 01, 11)`. Any file, module or template,
  is also named by its full repo-relative path in backticks anywhere in the row. A folder path
  does not cover the files in it, so one row cannot cover everything.
- Paths exist. A backticked token that starts with one of this repo's top-level folders
  (REPO_DIRS) must exist, after dropping a `::name` suffix. Bare names (`CI-CD.md`) and
  paths in other repos (`templates/scripts/check.py`, relative to a box skill) are not checked.
- Module numbers exist. A module number in a first-cell parenthetical must match an
  agent-ready/modules/NN-*.md file.
- Evidence levels. The Evidence cell, with parentheticals removed and split on `;` and `,`, must
  be clauses that each start with observed, asserted or hypothesis. So `observed (stale doc),
  hypothesis (baseline practice)` passes and `verified`, `proven` or an empty cell fails.

Out of scope (issue #16): a new rule added to a module that already has rows; rule IDs; a diff
check. The negative controls copy the real EVIDENCE.md into tmp_path and expect the same checker
to reject each broken tree.
"""
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEVELS = ("observed", "asserted", "hypothesis")
COVERED_DIRS = ("agent-ready/modules", "agent-ready/templates")
REPO_DIRS = ("agent-ready/", "box/", "tests/", "experiments/", "ci/", ".github/")

SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
CODE_RE = re.compile(r"`([^`\n]+)`")
PAREN_RE = re.compile(r"\(([^()]*)\)")
MODULE_GROUP_RE = re.compile(r"^(?:modules? )?\d\d(?:(?:, ?| and |/)\d\d)*(?:, [a-z ]+)?$")
TWO_DIGITS_RE = re.compile(r"\b\d\d\b")
MODULE_FILE_RE = re.compile(r"^(\d\d)-.+\.md$")


def split_row(line):
    """Cells of a Markdown table line, splitting on unescaped pipes."""
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def rule_rows(text):
    """(line number, cells, evidence cell) for each data row of a table with an Evidence column."""
    lines = text.replace("\r\n", "\n").splitlines()
    rows = []
    headers = None
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            headers = None
            continue
        cells = split_row(line)
        if all(SEPARATOR_RE.match(c) for c in cells):
            continue
        if headers is None:
            headers = cells
            continue
        if "Evidence" in headers:
            col = headers.index("Evidence")
            rows.append((i + 1, cells, cells[col] if col < len(cells) else ""))
    return rows


def module_numbers(first_cell):
    """Module numbers a rule's first cell names in a parenthetical such as (02) or (modules 01, 11)."""
    numbers = set()
    for group in PAREN_RE.findall(first_cell):
        if MODULE_GROUP_RE.match(group.strip()):
            numbers.update(TWO_DIGITS_RE.findall(group))
    return numbers


def repo_paths(row_text):
    """Backticked tokens in a row that point into this repo's own top-level folders."""
    paths = []
    for token in CODE_RE.findall(row_text):
        token = token.strip().split("::")[0]
        if token.startswith(REPO_DIRS) and " " not in token:
            paths.append(token)
    return paths


def level_ok(value):
    """True when every clause of an Evidence cell starts with one of LEVELS."""
    stripped = PAREN_RE.sub("", value)
    clauses = [c.strip() for c in re.split(r"[;,]", stripped)]
    if not clauses or not all(clauses):
        return False
    return all(c.split()[0] in LEVELS for c in clauses)


def covered_files(root):
    """Repo-relative POSIX paths of every file that must be backed by a row."""
    files = []
    for folder in COVERED_DIRS:
        base = root / folder
        files.extend(p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file())
    return sorted(files)


def module_files(root):
    """Map module number to its repo-relative path, from agent-ready/modules/NN-*.md."""
    mapping = {}
    for p in (root / "agent-ready" / "modules").glob("*.md"):
        m = MODULE_FILE_RE.match(p.name)
        if m:
            mapping[m.group(1)] = p.relative_to(root).as_posix()
    return mapping


def provenance_problems(root):
    """Every way the tree at root breaks the provenance rule, as readable strings."""
    text = (root / "EVIDENCE.md").read_text(encoding="utf-8")
    modules = module_files(root)
    named = set()
    problems = []
    for lineno, cells, evidence in rule_rows(text):
        where = "EVIDENCE.md:{}".format(lineno)
        if not level_ok(evidence):
            problems.append("{}: evidence {!r} is not {}".format(where, evidence, "/".join(LEVELS)))
        for number in sorted(module_numbers(cells[0])):
            if number in modules:
                named.add(modules[number])
            else:
                problems.append("{}: names module {}, which has no file".format(where, number))
        for path in repo_paths(" | ".join(cells)):
            if not (root / path).exists():
                problems.append("{}: names {}, which does not exist".format(where, path))
            named.add(path)
    for path in covered_files(root):
        if path not in named:
            problems.append("{}: no EVIDENCE.md row names it".format(path))
    return problems


# ----- the real repo -------------------------------------------------------------------------

def test_every_module_and_template_has_a_valid_evidence_row():
    problems = provenance_problems(ROOT)
    assert not problems, "\n".join(problems)


def test_the_checker_reads_rule_rows_from_every_rule_table():
    rows = rule_rows((ROOT / "EVIDENCE.md").read_text(encoding="utf-8"))
    assert len(rows) > 100
    assert {"02", "11"} <= set().union(*(module_numbers(cells[0]) for _, cells, _ in rows))


# ----- negative controls ---------------------------------------------------------------------

def copy_tree(tmp_path):
    """A throwaway copy of the files the checker reads."""
    for name in ("agent-ready", "box", "tests", "experiments", "ci"):
        shutil.copytree(str(ROOT / name), str(tmp_path / name),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy(str(ROOT / "EVIDENCE.md"), str(tmp_path / "EVIDENCE.md"))
    return tmp_path


def append_row(root, row):
    """Add a rule row to the end of the first rule table in a copied EVIDENCE.md."""
    path = root / "EVIDENCE.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("| Rule (module) |"))
    end = next(i for i in range(start, len(lines)) if not lines[i].startswith("|"))
    lines.insert(end, row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_new_module_with_no_row_fails(tmp_path):
    root = copy_tree(tmp_path)
    assert provenance_problems(root) == []
    (root / "agent-ready" / "modules" / "12-new-module.md").write_text("# 12\n", encoding="utf-8")
    assert provenance_problems(root) == [
        "agent-ready/modules/12-new-module.md: no EVIDENCE.md row names it"]


def test_a_new_module_passes_once_a_row_names_its_number(tmp_path):
    root = copy_tree(tmp_path)
    (root / "agent-ready" / "modules" / "12-new-module.md").write_text("# 12\n", encoding="utf-8")
    append_row(root, "| A new rule (12) | none | hypothesis | |")
    assert provenance_problems(root) == []


def test_a_new_template_with_no_row_fails(tmp_path):
    root = copy_tree(tmp_path)
    (root / "agent-ready" / "templates" / "NEW.md").write_text("# New\n", encoding="utf-8")
    assert provenance_problems(root) == ["agent-ready/templates/NEW.md: no EVIDENCE.md row names it"]


def test_a_folder_path_does_not_cover_its_files(tmp_path):
    root = copy_tree(tmp_path)
    (root / "agent-ready" / "templates" / "NEW.md").write_text("# New\n", encoding="utf-8")
    append_row(root, "| Everything (`agent-ready/templates/`) | none | hypothesis | |")
    assert provenance_problems(root) == ["agent-ready/templates/NEW.md: no EVIDENCE.md row names it"]


def test_a_date_in_a_rule_does_not_name_a_module(tmp_path):
    root = copy_tree(tmp_path)
    (root / "agent-ready" / "modules" / "12-new-module.md").write_text("# 12\n", encoding="utf-8")
    append_row(root, "| A rule (owner decision, 2026-10-12) | none | hypothesis | |")
    assert provenance_problems(root) == [
        "agent-ready/modules/12-new-module.md: no EVIDENCE.md row names it"]


def test_a_row_naming_a_missing_path_fails(tmp_path):
    root = copy_tree(tmp_path)
    append_row(root, "| Gone (`agent-ready/templates/GONE.md`) | none | hypothesis | |")
    problems = provenance_problems(root)
    assert len(problems) == 1
    assert problems[0].endswith(": names agent-ready/templates/GONE.md, which does not exist")


def test_a_row_naming_a_missing_module_number_fails(tmp_path):
    root = copy_tree(tmp_path)
    append_row(root, "| A rule (99) | none | hypothesis | |")
    problems = provenance_problems(root)
    assert len(problems) == 1
    assert problems[0].endswith(": names module 99, which has no file")


def test_a_row_with_an_unknown_evidence_level_fails(tmp_path):
    root = copy_tree(tmp_path)
    for bad in ("verified", "", "observed; proven", "Observed"):
        append_row(root, "| A rule (02) | none | {} | |".format(bad))
    problems = provenance_problems(root)
    assert len(problems) == 4
    assert all(" is not observed/asserted/hypothesis" in p for p in problems)


def test_compound_evidence_values_pass():
    for good in ("observed", "observed (structure)", "asserted (problem); observed (fix)",
                 "observed (stale doc), hypothesis (baseline practice)",
                 "observed (synthetic) for the files; hypothesis for the answer convention"):
        assert level_ok(good), good


def test_a_row_without_a_leading_pipe_is_still_checked(tmp_path):
    root = copy_tree(tmp_path)
    append_row(root, "Bad rule (02) | none | verified |")
    problems = provenance_problems(root)
    assert len(problems) == 1
    assert problems[0].endswith(": evidence 'verified' is not observed/asserted/hypothesis")


def test_a_slash_date_in_a_rule_does_not_name_a_module(tmp_path):
    root = copy_tree(tmp_path)
    (root / "agent-ready" / "modules" / "12-new-module.md").write_text("# 12\n", encoding="utf-8")
    append_row(root, "| Policy reviewed (11/12) | owner notes | asserted | |")
    assert provenance_problems(root) == [
        "agent-ready/modules/12-new-module.md: no EVIDENCE.md row names it"]


def test_a_missing_path_with_a_space_fails(tmp_path):
    root = copy_tree(tmp_path)
    append_row(root, "| Gone (02) | none | hypothesis | `agent-ready/templates/GONE FILE.md` |")
    problems = provenance_problems(root)
    assert len(problems) == 1
    assert problems[0].endswith(": names agent-ready/templates/GONE FILE.md, which does not exist")


def test_a_template_with_a_space_is_covered_by_its_path(tmp_path):
    root = copy_tree(tmp_path)
    (root / "agent-ready" / "templates" / "NEW FILE.md").write_text("# New\n", encoding="utf-8")
    append_row(root, "| New (`agent-ready/templates/NEW FILE.md`) | none | hypothesis | |")
    assert provenance_problems(root) == []
