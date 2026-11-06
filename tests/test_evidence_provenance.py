"""Provenance check: every module and template in agent-ready/ is backed by an EVIDENCE.md row.
Pure stdlib.

A rule row is a data row of an EVIDENCE.md table whose header has an `Evidence` column (the
Finding | Change tables have none and are skipped). Only rows of plain tables count, read in the
format EVIDENCE.md uses (see scan): a header at column 0 after a blank line or heading, a
delimiter row of the same width, then lines that each start with a pipe at column 0, until a
blank line. Anything that could hide a table from the rendered page or show it differently
fails instead of being guessed at: a fence, an indented line or an HTML block (reading stops
there), a pipe line outside a table (also in a blockquote or list item), a non-pipe line inside
a table, a row with more cells than its header, and raw HTML outside a code span in a rule row.
Lines end only at LF, CR or CRLF, as in GFM; a line holding any other control character or a
Unicode line separator (U+0085, U+2028, U+2029) fails, and reading stops there. Write a literal
pipe inside a cell, even in a code span, as `\\|`. For those rows:

- Coverage. Each file under agent-ready/modules/ and agent-ready/templates/ must be named by at
  least one rule row. A module is named by its number in the row's first cell, in a parenthetical
  such as `(02)`, `(01, 03)`, `(02, template)` or `(modules 01, 11)`. A slash is not a
  separator, so a date such as `(11/12)` names no module. Any file, module or template,
  is also named by its full repo-relative path in backticks in the row's first cell or its
  Notes cell; a path in the Source cell is checked but names nothing. A folder path does not
  cover the files in it, so one row cannot cover everything.
- Paths exist. A backticked token that starts with one of this repo's top-level folders
  (REPO_DIRS) must exist, after dropping a `::name` suffix; spaces are part of the path. Bare
  names (`CI-CD.md`) and paths in other repos (`templates/scripts/check.py`, relative to a box
  skill) are not checked.
- Module numbers exist. A module number in a first-cell parenthetical must match an
  agent-ready/modules/NN-*.md file, and no two module files may share a number.
- Evidence levels. The Evidence cell, with parentheticals removed and split on `;` and `,`, must
  be clauses that each start with observed, asserted or hypothesis. So `observed (stale doc),
  hypothesis (baseline practice)` passes and `verified`, `proven` or an empty cell fails.

Out of scope (issue #16): a new rule added to a module that already has rows; rule IDs; a diff
check. The negative controls copy the real EVIDENCE.md into tmp_path and expect the same checker
to reject each broken tree; the copy holds every folder in REPO_DIRS. A control that adds a module picks a number the copied tree does not
use, so adding the next real module does not break it.
"""
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEVELS = ("observed", "asserted", "hypothesis")
COVERED_DIRS = ("agent-ready/modules", "agent-ready/templates")
REPO_DIRS = ("agent-ready/", "box/", "tests/", "experiments/", "ci/", ".github/")

SEPARATOR_RE = re.compile(r"^:?-+:?$")
CODE_RE = re.compile(r"`([^`\n]+)`")
PAREN_RE = re.compile(r"\(([^()]*)\)")
MODULE_GROUP_RE = re.compile(r"^(?:modules? )?\d\d(?:(?:, ?| and )\d\d)*(?:, [a-z ]+)?$")
TWO_DIGITS_RE = re.compile(r"\b\d\d\b")
MODULE_FILE_RE = re.compile(r"^(\d\d)-.+\.md$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HTML_START_RE = re.compile(r"^ {0,3}<")
CONTAINER_RE = re.compile(r"^(?:\s*(?:>|[-*+](?=\s)|\d{1,9}[.)](?=\s)))*\s*")
INLINE_HTML_RE = re.compile(r"<[A-Za-z/!?]")
LINE_END_RE = re.compile(r"\r\n|\r|\n")
BAD_CHAR_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f\x85\u2028\u2029]")


def split_row(line):
    """Cells of a Markdown table line, splitting on unescaped pipes."""
    body = line.strip(" \t")
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [cell.strip(" \t") for cell in re.split(r"(?<!\\)\|", body)]


def is_delimiter(line, width):
    """True when line is a table delimiter row (| --- | :-: |) at column 0 with width cells."""
    cells = split_row(line)
    return (line.startswith("|") and len(cells) == width
            and all(SEPARATOR_RE.match(c) for c in cells))


def unsupported(line):
    """Why a line is outside the plain format this check reads, or None.

    Fences, indented code and HTML blocks can each hide a table from the rendered page, so
    EVIDENCE.md may not use them at all; the check then never has to decide where one ends.
    """
    if FENCE_RE.match(line):
        return "code fence"
    if line.startswith("\t") or line.startswith("    "):
        return "indented line"
    if HTML_START_RE.match(line):
        return "HTML block"
    return None


def scan(text):
    """(rows, problems) for EVIDENCE.md, read in the plain format it uses.

    A table is a header line at column 0 that starts with a pipe, right after a blank line, a
    heading or the start of the file, then a delimiter row with as many cells. Its rows are the
    following lines, each at column 0 and starting with a pipe, until a blank line. As in GFM,
    lines end only at LF, CR or CRLF, a blank line holds only spaces and tabs, and cells are
    trimmed of spaces and tabs only; a line with any other control character or U+0085, U+2028
    or U+2029 stops reading, because those split lines in Python but not on the page. rows holds
    (line number, headers, cells) with cells cut to the header width. Every line that breaks
    this format is a problem and never a row: a non-pipe line inside a table (it also ends the
    table), a row with more cells than its header (GFM drops the extra cells), a pipe line
    outside any table (also inside a blockquote or list item), a fence, an indented line or an
    HTML block. Where such a block ends depends on GFM rules this check does not model, so
    reading stops at the first one: nothing after it is a row.
    """
    lines = LINE_END_RE.split(text)
    rows, problems = [], []

    def problem(n, why):
        problems.append("EVIDENCE.md:{}: {}; the check reads plain tables only".format(n, why))

    headers = None
    can_start = True
    i = 0
    while i < len(lines):
        n, line = i + 1, lines[i]
        i += 1
        bad = BAD_CHAR_RE.search(line)
        if bad:
            problem(n, "holds U+{:04X}, a control or line-separator character, so nothing after"
                       " it is read".format(ord(bad.group())))
            break
        if not line.strip(" \t"):
            headers, can_start = None, True
            continue
        why = unsupported(line)
        if why:
            problem(n, why + ", so nothing after it is read")
            break
        if headers is not None:
            if not line.startswith("|"):
                problem(n, "line inside a table that does not start with a pipe")
                headers, can_start = None, False
                continue
            cells = split_row(line)
            if len(cells) > len(headers):
                problems.append("EVIDENCE.md:{}: row has {} cells, its table has {}".format(
                    n, len(cells), len(headers)))
            rows.append((n, headers, cells[:len(headers)]))
            continue
        cells = split_row(line)
        if (can_start and line.startswith("|") and i < len(lines)
                and is_delimiter(lines[i], len(cells))):
            headers = cells
            i += 1
            continue
        if CONTAINER_RE.sub("", line).startswith("|"):
            problem(n, "table line outside a table")
        can_start = line.startswith("#")
    return rows, problems


def rule_rows(text):
    """(line number, headers, cells) for each row of a table with an Evidence column."""
    return [(n, headers, cells) for n, headers, cells in scan(text)[0] if "Evidence" in headers]


def cell(headers, cells, name):
    """The row's cell under the header name ('' when the row is short)."""
    col = headers.index(name)
    return cells[col] if col < len(cells) else ""


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
    """Map module number to the sorted repo-relative paths of agent-ready/modules/NN-*.md."""
    mapping = {}
    for p in sorted((root / "agent-ready" / "modules").glob("*.md")):
        m = MODULE_FILE_RE.match(p.name)
        if m:
            mapping.setdefault(m.group(1), []).append(p.relative_to(root).as_posix())
    return mapping


def provenance_problems(root):
    """Every way the tree at root breaks the provenance rule, as readable strings."""
    text = (root / "EVIDENCE.md").read_text(encoding="utf-8")
    modules = module_files(root)
    named = set()
    rows, problems = scan(text)
    for number, paths in sorted(modules.items()):
        if len(paths) > 1:
            problems.append("agent-ready/modules: {} share module number {}".format(
                " and ".join(Path(p).name for p in paths), number))
    for lineno, headers, cells in rows:
        if "Evidence" not in headers:
            continue
        where = "EVIDENCE.md:{}".format(lineno)
        evidence = cell(headers, cells, "Evidence")
        if not level_ok(evidence):
            problems.append("{}: evidence {!r} is not {}".format(where, evidence, "/".join(LEVELS)))
        if any(INLINE_HTML_RE.search(CODE_RE.sub("", c)) for c in cells):
            problems.append("{}: raw HTML outside a code span can hide text".format(where))
            continue
        for number in sorted(module_numbers(cells[0])):
            if number in modules:
                named.update(modules[number])
            else:
                problems.append("{}: names module {}, which has no file".format(where, number))
        naming = {0, headers.index("Notes")} if "Notes" in headers else {0}
        for col, value in enumerate(cells):
            for path in repo_paths(value):
                if not (root / path).exists():
                    problems.append("{}: names {}, which does not exist".format(where, path))
                elif col in naming:
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
    assert {"02", "11"} <= set().union(*(module_numbers(cells[0]) for _, _, cells in rows))


# ----- negative controls ---------------------------------------------------------------------

def copy_tree(tmp_path):
    """A throwaway copy of the files the checker reads."""
    for name in (d.rstrip("/") for d in REPO_DIRS):
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


def unused_number(root):
    """The lowest two-digit module number no file in root's agent-ready/modules/ uses."""
    used = module_files(root)
    return next("{:02d}".format(n) for n in range(1, 100) if "{:02d}".format(n) not in used)


def add_module(root):
    """Add a module file under an unused number; return (number, its missing-row problem)."""
    number = unused_number(root)
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


def test_the_new_module_controls_survive_the_next_real_module(tmp_path):
    """The next real module, with its row, must not break the controls that add a module."""
    root = copy_tree(tmp_path)
    taken = unused_number(root)
    (root / "agent-ready" / "modules" / "{}-new-module.md".format(taken)).write_text(
        "# {}\n".format(taken), encoding="utf-8")
    append_row(root, "| A real rule ({}) | none | hypothesis | |".format(taken))
    assert provenance_problems(root) == []
    number, missing = add_module(root)
    assert number != taken
    assert provenance_problems(root) == [missing]


def test_two_modules_sharing_a_number_fail(tmp_path):
    root = copy_tree(tmp_path)
    n = unused_number(root)
    for name in ("{}-one.md", "{}-two.md"):
        (root / "agent-ready" / "modules" / name.format(n)).write_text("# x\n", encoding="utf-8")
    append_row(root, "| A rule ({}) | none | hypothesis | |".format(n))
    assert provenance_problems(root) == [
        "agent-ready/modules: {0}-one.md and {0}-two.md share module number {0}".format(n)]


def test_a_table_in_a_code_fence_is_not_evidence(tmp_path):
    """A fenced example row is a code sample, not a rule row, so it covers no module."""
    root = copy_tree(tmp_path)
    number, missing = add_module(root)
    for fence in ("```", "~~~~"):
        with (root / "EVIDENCE.md").open("a", encoding="utf-8") as f:
            f.write("\n{0}markdown\n| Rule (module) | Source | Evidence | Notes |\n|---|---|---|---|\n"
                    "| Proposed example ({1}) | none | hypothesis | |\n{0}\n".format(fence, number))
        problems = provenance_problems(root)
        assert len(problems) == 2 and problems[1] == missing, fence
        assert problems[0].endswith(": code fence, so nothing after it is read;"
                                    " the check reads plain tables only"), fence


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


def test_a_row_without_a_leading_pipe_fails(tmp_path):
    root = copy_tree(tmp_path)
    append_row(root, "Bad rule (02) | none | verified |")
    problems = provenance_problems(root)
    assert len(problems) == 1
    assert problems[0].endswith(": line inside a table that does not start with a pipe;"
                                " the check reads plain tables only")


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


def test_a_line_with_no_pipe_inside_a_table_fails(tmp_path):
    root = copy_tree(tmp_path)
    append_row(root, "Stray text that GFM reads as one more row")
    problems = provenance_problems(root)
    assert len(problems) == 1
    assert problems[0].endswith(": line inside a table that does not start with a pipe;"
                                " the check reads plain tables only")


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


# ----- only real rule-table rows give coverage (review round 3) ------------------------------

RULE_TABLE = "| Rule (module) | Source | Evidence | Notes |\n|---|---|---|---|\n"


def indent(block, prefix):
    return "".join(prefix + line + "\n" for line in block.splitlines())


def wrapped(kind, n):
    """A block appended to EVIDENCE.md, or a row inserted into its first rule table, that
    names module n somewhere GFM would not render it as a cell of a rule-table row."""
    row = "| Example ({}) | none | hypothesis | |".format(n)
    table = RULE_TABLE + row + "\n"
    path = "`agent-ready/modules/{}-new-module.md`".format(n)
    blocks = {
        "fence with a blank line": "```\nexample\n\n" + table + "```\n",
        "tilde fence": "~~~\n" + table + "~~~\n",
        "four-space indent": indent(table, "    "),
        "tab indent": indent(table, "\t"),
        "HTML comment with a blank line": "<!--\nexample\n\n" + table + "-->\n",
        "pre block": "<pre>\n" + table + "</pre>\n",
        "blockquote": indent(table, "> "),
        "list item": "- example\n\n" + indent(table, "  "),
        "header after a paragraph": "Some text.\n" + table,
        "header indented two spaces": indent(table, "  "),
    }
    rows = {
        "excess cell": "| Example | none | hypothesis | | {} |".format(path),
        "list line after a row": "- note\n" + row,
        "inline HTML comment": "| Example <!-- ({}) --> | none | hypothesis | |".format(n),
        "Source column": "| Example | {} | hypothesis | |".format(path),
    }
    return ("append", blocks[kind]) if kind in blocks else ("row", rows[kind])


SWEEP = ["fence with a blank line", "tilde fence", "four-space indent", "tab indent",
         "HTML comment with a blank line", "pre block", "blockquote", "list item",
         "header after a paragraph", "header indented two spaces", "excess cell",
         "list line after a row", "inline HTML comment", "Source column"]


def add_text(root, how, text):
    if how == "row":
        append_row(root, text)
    else:
        with (root / "EVIDENCE.md").open("a", encoding="utf-8") as f:
            f.write("\n" + text)


def test_only_rendered_rule_rows_cover_a_module(tmp_path):
    """Sweep: each way of writing a module's number outside a rule-table cell covers nothing."""
    covered = []
    for i, kind in enumerate(SWEEP):
        root = copy_tree(tmp_path / str(i))
        number, missing = add_module(root)
        add_text(root, *wrapped(kind, number))
        if missing not in provenance_problems(root):
            covered.append(kind)
    assert covered == []


def test_an_indented_code_sample_is_rejected_and_covers_nothing(tmp_path):
    root = copy_tree(tmp_path)
    number, missing = add_module(root)
    add_text(root, *wrapped("four-space indent", number))
    problems = provenance_problems(root)
    assert missing in problems
    assert len(problems) == 2 and problems[1] == missing
    assert problems[0].endswith(": indented line, so nothing after it is read;"
                                " the check reads plain tables only")


def test_a_path_in_a_discarded_cell_covers_nothing(tmp_path):
    root = copy_tree(tmp_path)
    number, missing = add_module(root)
    add_text(root, *wrapped("excess cell", number))
    problems = provenance_problems(root)
    assert len(problems) == 2 and problems[1] == missing
    assert problems[0].endswith(": row has 5 cells, its table has 4")


def test_a_missing_path_in_a_discarded_cell_is_not_checked(tmp_path):
    root = copy_tree(tmp_path)
    append_row(root, "| A rule (02) | none | hypothesis | | `agent-ready/templates/GONE.md` |")
    problems = provenance_problems(root)
    assert len(problems) == 1
    assert problems[0].endswith(": row has 5 cells, its table has 4")


def test_a_valid_workflow_reference_survives_the_fixture_copy(tmp_path):
    root = copy_tree(tmp_path)
    append_row(root, "| CI runs the suite (02) | none | observed | `.github/workflows/tests.yml` |")
    assert provenance_problems(root) == []


# ----- line endings and whitespace as GFM reads them (review round 4) ------------------------

SEPARATORS = [" ", " ", "\x85", "\v", "\f", "\x1c", "\x1d", "\x1e"]


def write_raw(root, text):
    """Append text to the copied EVIDENCE.md byte for byte, with no newline translation."""
    with (root / "EVIDENCE.md").open("a", encoding="utf-8", newline="") as f:
        f.write(text)


def test_a_non_markdown_line_separator_fails_closed(tmp_path):
    """GFM ends lines only at LF, CR and CRLF, so one physical row must not become two."""
    uncaught = []
    for i, ch in enumerate(SEPARATORS):
        root = copy_tree(tmp_path / str(i))
        number, missing = add_module(root)
        append_row(root, "| Innocent | none | hypothesis | |" + ch
                   + "| Hidden ({}) | none | hypothesis | |".format(number))
        problems = provenance_problems(root)
        flagged = any("U+{:04X}".format(ord(ch)) in p for p in problems)
        if missing not in problems or not flagged:
            uncaught.append("U+{:04X}".format(ord(ch)))
    assert uncaught == []


def test_a_line_of_non_ascii_space_is_not_blank(tmp_path):
    """A no-break space line does not end a table in GFM, so no new rule table starts after it."""
    root = copy_tree(tmp_path)
    number, missing = add_module(root)
    write_raw(root, "\n| Finding | Change |\n|---|---|\n| a | b |\n \n" + RULE_TABLE
              + "| Example ({}) | none | hypothesis | |\n".format(number))
    assert missing in provenance_problems(root)


def test_a_delimiter_padded_with_non_ascii_space_starts_no_table(tmp_path):
    root = copy_tree(tmp_path)
    number, missing = add_module(root)
    write_raw(root, "\n| Rule (module) | Source | Evidence | Notes |\n| --- |---|---|---|\n"
              "| Example ({}) | none | hypothesis | |\n".format(number))
    assert missing in provenance_problems(root)


def test_a_crlf_evidence_file_reads_the_same(tmp_path):
    root = copy_tree(tmp_path)
    text = (root / "EVIDENCE.md").read_text(encoding="utf-8")
    (root / "EVIDENCE.md").write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert provenance_problems(root) == []


# ----- cells are read only when their code spans parse exactly (review round 5) --------------

def cell_tricks(n):
    """Rule rows that name module n, or its file, only through escapes or markup around code
    spans. Each hides the reference from the page or makes the spans ambiguous."""
    path = "agent-ready/modules/{}-new-module.md".format(n)
    first = [
        "Rule \\`<!-- ({}) -->\\`".format(n),          # escaped backticks around a comment
        "Rule \\\\`x` ({})".format(n),                  # escaped backslash before a span
        "Rule ``x`` ({})".format(n),                    # double-backtick span
        "Rule ` ({})".format(n),                        # unmatched backtick
        "Rule &#96;<!-- ({}) -->&#96;".format(n),       # entity backticks around a comment
        "Rule \\`{}\\`".format(path),                   # escaped backticks around a path
        "Rule [see](https://example.com \"({})\")".format(n),  # link title
        "Rule ![({})](x.png)".format(n),                # image alt
        "Rule [x][({})]".format(n),                     # reference label
    ]
    notes = [
        "[x](`{}`)".format(path),                       # path as a link destination
        "[^`{}`]".format(path),                         # path as a footnote label
    ]
    return (["| {} | none | hypothesis | |".format(c) for c in first]
            + ["| Rule | none | hypothesis | {} |".format(c) for c in notes])


def test_escaped_backticks_around_a_comment_hide_nothing(tmp_path):
    """Codex r5: the escaped backticks are literal, so the comment hides (12) on the page."""
    root = copy_tree(tmp_path)
    number, missing = add_module(root)
    append_row(root, "| Rule \\`<!-- ({}) -->\\` | none | hypothesis | |".format(number))
    problems = provenance_problems(root)
    assert len(problems) == 2 and problems[1] == missing
    assert "cannot read exactly" in problems[0]


def test_escapes_and_markup_around_code_spans_fail_closed(tmp_path):
    uncaught = []
    for i, row in enumerate(cell_tricks("NN")):
        root = copy_tree(tmp_path / str(i))
        number, missing = add_module(root)
        row = row.replace("NN", number)
        append_row(root, row)
        problems = provenance_problems(root)
        if missing not in problems or not any("cannot read exactly" in p for p in problems):
            uncaught.append(row)
    assert uncaught == []
