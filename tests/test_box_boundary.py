"""The import boundary of box/ (issue #36): box/lib is the only code box scripts share. Pure
stdlib; it parses every `box/**/*.py` outside `templates/` with `ast` and imports none of them.

It fails on:
- a `sys.path` edit that points outside the script's own folder or box/lib. Where an edit points
  is worked out from `__file__` through Path, os.path, `.parent`, `.parents[N]`, `/` and names
  bound at module level; an edit it cannot work out fails too. Removing the script's own folder
  (a list comprehension over sys.path that only filters) is allowed: select.py and
  handoff_check.py share a folder with a file named like the stdlib's `select`;
- a by-path load (importlib's spec_from_file_location or a loader, runpy, `__import__`,
  import_module) anywhere: box/lib is imported by name;
- an import of a module that is a script in another box folder, and on Python 3.10+ any import
  that is not the standard library, the script's own folder or box/lib;
- a top-level def or class in a script that redefines a box/lib helper the issue names (one
  implementation each of git's environment, link detection, inside, startup_bytecode,
  unsafe_output and write_outside, and Markdown sections);
- a box/lib module that edits sys.path, imports anything but the standard library and box/lib,
  or is named like a standard library module or a box script;
- a script that puts box/lib on sys.path without turning bytecode off first.

`python tests/test_box_boundary.py [BOX]` prints the census of sys.path edits and by-path loads
for a box/ folder (default: this checkout's), the before and after counts the issue asks for.
"""
import ast
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BOX = ROOT / "box"
LOADERS = {"spec_from_file_location", "spec_from_loader", "SourceFileLoader",
           "SourcelessFileLoader", "load_source", "load_module", "run_path", "run_module",
           "import_module", "__import__"}
# The helpers issue #36 gives one implementation each, in box/lib/paths.py, git_env.py and md.py.
GUARDED = {"git_env", "is_link", "is_link_stat", "linked", "inside", "startup_bytecode",
           "unsafe_output", "write_outside", "handle_path", "headings", "section"}


class Unknown(Exception):
    """An expression this test cannot evaluate to a path."""


def box_files(box=BOX):
    return sorted(p for p in Path(box).rglob("*.py")
                  if "templates" not in p.relative_to(box).parts
                  and "__pycache__" not in p.parts)


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = dotted(node.value)
        return inner + "." + node.attr if inner else None
    return None


def evaluate(node, env, path):
    """The path `node` names when the script at `path` runs, or raise Unknown."""
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return Path(os.path.realpath(str(path)))
        if node.id in env:
            return env[node.id]
        raise Unknown(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        return Path(evaluate(node.value, env, path)).parent
    if isinstance(node, ast.Attribute) and node.attr == "pardir":
        return os.pardir
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
            and node.value.attr == "parents":
        index = node.slice.value if isinstance(node.slice, ast.Index) else node.slice  # 3.8
        if isinstance(index, ast.Constant) and isinstance(index.value, int):
            return Path(evaluate(node.value.value, env, path)).parents[index.value]
        raise Unknown(ast.dump(node))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return Path(evaluate(node.left, env, path)) / evaluate(node.right, env, path)
    if isinstance(node, ast.Call):
        name = dotted(node.func)
        args = [evaluate(a, env, path) for a in node.args]
        if name in ("Path", "pathlib.Path", "str", "os.fspath") and len(args) == 1:
            return Path(args[0])
        if name in ("os.path.dirname",) and len(args) == 1:
            return Path(args[0]).parent
        if name in ("os.path.abspath", "os.path.realpath", "os.path.normpath") and len(args) == 1:
            return Path(os.path.normpath(str(args[0])))
        if name == "os.path.join" and args:
            return Path(os.path.normpath(os.path.join(*[str(a) for a in args])))
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("resolve", "absolute") \
                and not node.args:
            return Path(os.path.normpath(str(evaluate(node.func.value, env, path))))
    raise Unknown(ast.dump(node))


def module_env(tree, path):
    """Names bound at module level to an expression evaluate() can follow."""
    env = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name):
            try:
                env[stmt.targets[0].id] = evaluate(stmt.value, env, path)
            except Unknown:
                pass
    return env


def is_sys_path(node):
    return dotted(node) == "sys.path"


def only_filters_sys_path(value):
    """`[p for p in sys.path if ...]`: removes entries, adds none."""
    return (isinstance(value, ast.ListComp) and len(value.generators) == 1
            and is_sys_path(value.generators[0].iter) and value.generators[0].ifs
            and isinstance(value.elt, ast.Name) and isinstance(value.generators[0].target, ast.Name)
            and value.elt.id == value.generators[0].target.id)


def census(path):
    """(edits, strips, loads, problems) for one file: each sys.path edit as (line, the folder it
    adds or None), each own-folder strip's line, each by-path load's line, and what breaks the
    boundary."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), str(path))
    env = module_env(tree, path)
    own, lib = Path(os.path.realpath(str(path))).parent, Path(os.path.realpath(str(BOX))) / "lib"
    edits, strips, loads, problems = [], [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and is_sys_path(node.func.value):
            arg = {"insert": 1, "append": 0}.get(node.func.attr)
            try:
                added = Path(os.path.normpath(str(evaluate(node.args[arg], env, path))))
            except (Unknown, IndexError, TypeError):
                added = None
            edits.append((node.lineno, added))
            if node.func.attr not in ("insert", "append"):
                problems.append("line %d: sys.path.%s" % (node.lineno, node.func.attr))
            elif added is None:
                problems.append("line %d: a sys.path edit this test cannot follow" % node.lineno)
            elif added not in (own, lib):
                problems.append("line %d: sys.path gets %s, outside the script's folder and "
                                "box/lib" % (node.lineno, added))
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                base = target.value if isinstance(target, ast.Subscript) else target
                if is_sys_path(base):
                    if isinstance(node, ast.Assign) and only_filters_sys_path(node.value):
                        strips.append(node.lineno)
                    else:
                        edits.append((node.lineno, None))
                        problems.append("line %d: sys.path is assigned" % node.lineno)
        elif isinstance(node, ast.Call):
            name = dotted(node.func) or ""
            if name.split(".")[-1] in LOADERS:
                loads.append(node.lineno)
                problems.append("line %d: a by-path load (%s); import box/lib by name"
                                % (node.lineno, name))
    return edits, strips, loads, problems


def imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.lineno, node.module.split(".")[0]


def lib_modules(box=BOX):
    return {p.stem for p in (Path(box) / "lib").glob("*.py")}


def scripts_by_folder(box=BOX):
    out = {}
    for p in box_files(box):
        if p.parent != Path(box) / "lib":
            out.setdefault(p.stem, set()).add(p.parent)
    return out


def boundary_problems(path, box=BOX):
    """Everything wrong with one file's imports, as messages."""
    path = Path(path)
    rel = path.relative_to(box).as_posix()
    in_lib = path.parent == Path(box) / "lib"
    _, _, _, problems = census(path)
    out = ["%s: %s" % (rel, p) for p in problems]
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    lib, scripts = lib_modules(box), scripts_by_folder(box)
    own = {p.stem for p in path.parent.glob("*.py")}
    stdlib = getattr(sys, "stdlib_module_names", None)
    for line, name in imported_modules(tree):
        if name in lib or name == "__main__":
            continue
        if not in_lib and name in own:
            continue
        if name in scripts:
            out.append("%s:%d: imports %s from %s, another box folder" % (
                rel, line, name, ", ".join(sorted(p.relative_to(box).as_posix()
                                                  for p in scripts[name]))))
        elif stdlib is not None and name not in stdlib:
            out.append("%s:%d: imports %r, which is neither the standard library, its own folder "
                       "nor box/lib" % (rel, line, name))
    top = {id(stmt) for stmt in tree.body}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in top and any(
                name in lib for _, name in imported_modules(ast.Module(body=[node],
                                                                       type_ignores=[]))):
            out.append("%s:%d: imports box/lib inside a block; import it at the top, so `--help` "
                       "and a symlinked install load it too" % (rel, node.lineno))
    if in_lib:
        if any(census(path)[0]):
            out.append("%s: a box/lib module edits sys.path" % rel)
        return out
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.ClassDef)) and stmt.name in GUARDED:
            out.append("%s:%d: redefines box/lib's %s; import it" % (rel, stmt.lineno, stmt.name))
    return out


def lib_insert_line(path):
    edits = census(path)[0]
    lib = Path(os.path.realpath(str(BOX))) / "lib"
    return next((line for line, added in edits if added == lib), None)


def bytecode_off_line(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), str(path))
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and dotted(stmt.targets[0]) == "sys.dont_write_bytecode" \
                and isinstance(stmt.value, ast.Constant) and stmt.value.value is True:
            return stmt.lineno
    return None


FILES = box_files()
SCRIPTS = [p for p in FILES if p.parent != BOX / "lib"]
LIB = [p for p in FILES if p.parent == BOX / "lib"]


def test_the_census_finds_the_files():
    assert len(SCRIPTS) >= 18 and len(LIB) >= 10
    assert {p.stem for p in LIB} >= {"paths", "git_env", "md", "gh_read", "issue_folder",
                                    "scorecard", "issue_shape", "filing", "isolation",
                                    "profiles"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(BOX).as_posix())
def test_imports_stay_inside_the_folder_and_box_lib(path):
    assert boundary_problems(path) == []


@pytest.mark.parametrize("path", [p for p in SCRIPTS if lib_insert_line(p)],
                         ids=lambda p: p.relative_to(BOX).as_posix())
def test_bytecode_is_off_before_box_lib_is_loaded(path):
    off = bytecode_off_line(path)
    assert off is not None and off < lib_insert_line(path), path


def test_every_script_that_imports_box_lib_puts_it_on_the_path():
    lib = lib_modules()
    for path in SCRIPTS:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        if any(name in lib for _, name in imported_modules(tree)):
            assert lib_insert_line(path), path


def test_box_lib_names_shadow_no_stdlib_module_and_no_script():
    lib, scripts = lib_modules(), scripts_by_folder()
    assert not lib & set(scripts), lib & set(scripts)
    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is not None:
        assert not lib & set(stdlib), lib & set(stdlib)
    assert not (BOX / "lib" / "__init__.py").exists()  # modules on the path, not a package


def write_script(tmp_path, folder, text):
    path = tmp_path / "box" / folder / "x.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "box" / "lib").mkdir(exist_ok=True)
    (tmp_path / "box" / "lib" / "paths.py").write_text("", encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("text, problem", [
    ("import sys\nfrom pathlib import Path\n"
     "sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'box-audit' / 'scripts'))\n",
     "outside the script's folder"),
    ("import sys\nsys.path.insert(0, compute())\n", "cannot follow"),
    ("import sys\nsys.path = ['x']\n", "sys.path is assigned"),
    ("import sys\nsys.path.extend(['x'])\n", "sys.path.extend"),
    ("import importlib.util\nspec = importlib.util.spec_from_file_location('m', 'p.py')\n",
     "by-path load"),
    ("import runpy\nrunpy.run_path('p.py')\n", "by-path load"),
    ("def inside(path, root):\n    return True\n", "redefines box/lib's inside"),
    ("def section(text, heading, level):\n    return None\n", "redefines box/lib's section"),
    ("def main():\n    import paths\n", "inside a block"),
], ids=["other-skill", "unknown", "assigned", "extend", "spec", "runpy", "inside", "section",
        "lazy"])
def test_the_boundary_check_catches(tmp_path, monkeypatch, text, problem):
    path = write_script(tmp_path, "skills/a/scripts", text)
    monkeypatch.setattr(sys.modules[__name__], "BOX", tmp_path / "box")
    found = boundary_problems(path, tmp_path / "box")
    assert any(problem in p for p in found), found


def test_the_boundary_check_allows_its_own_folder_box_lib_and_a_strip(tmp_path, monkeypatch):
    text = ("import os\nimport sys\nHERE = os.path.dirname(os.path.abspath(__file__))\n"
            "sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != HERE]\n"
            "sys.dont_write_bytecode = True\nfrom pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'lib'))\n")
    path = write_script(tmp_path, "skills/a/scripts", text)
    monkeypatch.setattr(sys.modules[__name__], "BOX", tmp_path / "box")
    assert boundary_problems(path, tmp_path / "box") == []
    edits, strips, loads, _ = census(path)
    assert len(edits) == 2 and len(strips) == 1 and loads == []


def test_an_import_of_another_folders_script_is_caught(tmp_path, monkeypatch):
    box = tmp_path / "box"
    other = box / "skills" / "b" / "scripts" / "helper.py"
    other.parent.mkdir(parents=True)
    other.write_text("X = 1\n", encoding="utf-8")
    path = write_script(tmp_path, "skills/a/scripts", "import helper\n")
    monkeypatch.setattr(sys.modules[__name__], "BOX", box)
    found = boundary_problems(path, box)
    assert any("another box folder" in p for p in found), found


def report(box=BOX):
    box = Path(box)
    files = box_files(box)
    totals = {"sys.path inserts": 0, "own-folder strips": 0, "by-path loads": 0}
    with_edits, with_loads = set(), set()
    for path in files:
        edits, strips, loads, _ = census(path)
        inserts = list(edits)
        totals["sys.path inserts"] += len(inserts)
        totals["own-folder strips"] += len(strips)
        totals["by-path loads"] += len(loads)
        if inserts:
            with_edits.add(path)
        if loads:
            with_loads.add(path)
    print("%s: %d .py files outside templates/" % (box, len(files)))
    print("sys.path edits: %d in %d files" % (totals["sys.path inserts"], len(with_edits)))
    print("own-folder strips: %d" % totals["own-folder strips"])
    print("by-path loads: %d in %d files" % (totals["by-path loads"], len(with_loads)))
    problems = [p for path in files for p in boundary_problems(path, box)]
    print("boundary problems: %d" % len(problems))
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(report(sys.argv[1] if len(sys.argv) > 1 else BOX))
