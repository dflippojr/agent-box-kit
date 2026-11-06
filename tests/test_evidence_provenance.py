"""Provenance check: every module and template in agent-ready/ is backed by an EVIDENCE.md row.
Pure stdlib.

A rule row is a data row of an EVIDENCE.md table whose header has an `Evidence` column (the
Finding | Change tables have none and are skipped). Tables are read as GFM reads them: every
line after the delimiter row is a data row, with or without leading and trailing pipes, until a
blank line or another block. A line that starts with a pipe outside any such table (say, under
a header whose delimiter row has a different cell count) fails. For those rows:

- Coverage. Each file under agent-ready/modules/ and agent-ready/templates/ must be named by at
  least one rule row. A module is named by its number in the row's first cell, in a parenthetical
  such as `(02)`, `(01, 03)`, `(02, template)` or `(modules 01, 11)`. A slash is not a
  separator, so a date such as `(11/12)` names no module. Any file, module or template,
  is also named by its full repo-relative path in backticks anywhere in the row. A folder path
  does not cover the files in it, so one row cannot cover everything.
- Paths exist. A backticked token that starts with one of this repo's top-level folders
  (REPO_DIRS) must exist, after dropping a `::name` suffix; spaces are part of the path. Bare
  names (`CI-CD.md`) and paths in other repos (`templates/scripts/check.py`, relative to a box
  skill) are not checked.
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

SEPARATOR_RE = re.compile(r"^:?-+:?$")
PIPE_RE = re.compile(r"(?<!\\)\|")
CODE_RE = re.compile(r"`([^`\n]+)`")
PAREN_RE = re.compile(r"\(([^()]*)\)")
MODULE_GROUP_RE = re.compile(r"^(?:modules? )?\d\d(?:(?:, ?| and )\d\d)*(?:, [a-z ]+)?$")
TWO_DIGITS_RE = re.compile(r"\b\d\d\b")
MODULE_FILE_RE = re.compile(r"^(\d\d)-.+\.md$")


def split_row(line):
    """Cells of a Markdown table line, splitting on unescaped pipes."""
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def is_delimiter(line, width):
    """True when line is a table delimiter row (| --- | :-: |) with width cells."""
    cells = split_row(line)
    return "-" in line and len(cells) == width and all(SEPARATOR_RE.match(c) for c in cells)


def ends_table(line):
    """True when line ends a table: a blank line or the start of another block (GFM)."""
    stripped = line.strip()
    return not stripped or stripped.startswith(("#", ">", "```", "~~~"))


def parse_tables(text):
    """(rows, table line numbers): every table's data rows as (line number, headers, cells).

    Tables follow GFM: a header line with a pipe, then a delimiter row with as many cells. Every
    later line is a data row, leading and trailing pipes optional, until a blank line or another
    block starts. A row line with no pipe at all is still a row, so it fails the Evidence check
    instead of being skipped. The line numbers cover headers, delimiters and rows.
    """
    lines = text.replace("\r\n", "\n").splitlines()
    rows = []
    in_table = set()
    headers = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if headers is not None and ends_table(line):
            headers = None
        if headers is None:
            cells = split_row(line)
            if (PIPE_RE.search(line) and i + 1 < len(lines)
                    and is_delimiter(lines[i + 1], len(cells))):
                headers = cells
                in_table.update((i + 1, i + 2))
                i += 2
                continue
            i += 1
            continue
        rows.append((i + 1, headers, split_row(line)))
        in_table.add(i + 1)
        i += 1
    return rows, in_table


def rule_rows(text):
    """(line number, cells, evidence cell) for each data row of a table with an Evidence column."""
    rows = []
    for lineno, headers, cells in parse_tables(text)[0]:
        if "Evidence" in headers:
            col = headers.index("Evidence")
            rows.append((lineno, cells, cells[col] if col < len(cells) else ""))
    return rows


def stray_table_lines(text):
    """Line numbers of lines that start with a pipe but belong to no table GFM would render.

    A header whose delimiter row has a different cell count is not a table, so its rows would
    otherwise be skipped without a word.
    """
    in_table = parse_tables(text)[1]
    lines = text.replace("\r\n", "\n").splitlines()
    return [n for n, line in enumerate(lines, 1)
            if line.lstrip().startswith("|") and n not in in_table]


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
        if token.startswith(REPO_DIRS):
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
    problems = ["EVIDENCE.md:{}: table line outside a table (no matching delimiter row)".format(n)
                for n in stray_table_lines(text)]
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


def add_module(root):
    """Add a module file under a number no module in root uses; return (number, missing-row problem)."""
    number = "12"
    path = "agent-ready/modules/{}-new-module.md".format(number)
    (root / path).write_text("# {}\n".format(number), encoding="utf-8")
    return number, "{}: no EVIDENCE.md row names it".format(path)


def test_a_new_module_with_no_row_fails(tmp_path):
    root = copy_tree(tmp_path)
    assert provenance_problems(root) == []
    _, missing = add_module(root)
    assert provenance_problems(root) == [missing]


def test_a_new_module_passes_once_a_row_names_its_number(tmp_path):
    root = copy_tree(tmp_path)
    number, _ = add_module(root)
    append_row(root, "| A new rule ({}) | none | hypothesis | |".format(number))
    assert provenance_problems(root) == []


def test_the_new_module_controls_survive_a_real_module_12(tmp_path):
    """A valid module 12 with its row, added later, must not break the controls that add a module."""
    root = copy_tree(tmp_path)
    (root / "agent-ready" / "modules" / "12-new-module.md").write_text("# 12\n", encoding="utf-8")
    append_row(root, "| A real rule (12) | none | hypothesis | |")
    assert provenance_problems(root) == []
    number, missing = add_module(root)
    assert number != "12"
    assert provenance_problems(root) == [missing]


def test_two_modules_sharing_a_number_fail(tmp_path):
    root = copy_tree(tmp_path)
    for name in ("12-one.md", "12-two.md"):
        (root / "agent-ready" / "modules" / name).write_text("# 12\n", encoding="utf-8")
    append_row(root, "| A rule (12) | none | hypothesis | |")
    assert provenance_problems(root) == [
        "agent-ready/modules: 12-one.md and 12-two.md share module number 12"]


def test_a_table_in_a_code_fence_is_not_evidence(tmp_path):
    """A fenced example row is a code sample, not a rule row, so it covers no module."""
    root = copy_tree(tmp_path)
    number, missing = add_module(root)
    for fence in ("```", "~~~~"):
        with (root / "EVIDENCE.md").open("a", encoding="utf-8") as f:
            f.write("\n{0}markdown\n| Rule (module) | Source | Evidence | Notes |\n|---|---|---|---|\n"
                    "| Proposed example ({1}) | none | hypothesis | |\n{0}\n".format(fence, number))
        assert provenance_problems(root) == [missing], fence


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
    number, missing = add_module(root)
    append_row(root, "| A rule (owner decision, 2026-10-{}) | none | hypothesis | |".format(number))
    assert provenance_problems(root) == [missing]


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
    number, missing = add_module(root)
    append_row(root, "| Policy reviewed (11/{}) | owner notes | asserted | |".format(number))
    assert provenance_problems(root) == [missing]


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


def test_a_line_with_no_pipe_inside_a_table_is_a_row_and_fails(tmp_path):
    root = copy_tree(tmp_path)
    append_row(root, "Stray text that GFM reads as one more row")
    problems = provenance_problems(root)
    assert len(problems) == 1
    assert problems[0].endswith(" is not observed/asserted/hypothesis")


def test_a_table_whose_delimiter_does_not_match_its_header_fails(tmp_path):
    root = copy_tree(tmp_path)
    with (root / "EVIDENCE.md").open("a", encoding="utf-8") as f:
        f.write("\n| Rule (module) | Source | Evidence | Notes |\n|---|---|---|\n"
                "| X (02) | none | verified | |\n")
    problems = provenance_problems(root)
    assert len(problems) == 3
    assert all("table line outside a table" in p for p in problems)


def test_a_one_hyphen_delimiter_starts_a_table(tmp_path):
    root = copy_tree(tmp_path)
    with (root / "EVIDENCE.md").open("a", encoding="utf-8") as f:
        f.write("\n| Rule (module) | Source | Evidence | Notes |\n|-|:-|-:|-|\n"
                "| X (02) | none | verified | |\n")
    problems = provenance_problems(root)
    assert len(problems) == 1
    assert problems[0].endswith(": evidence 'verified' is not observed/asserted/hypothesis")
