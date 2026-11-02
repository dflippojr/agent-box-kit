"""Checks the Scripts rule (AGENTS.md): everything in agent-ready/scripts/ imports only the
standard library. It parses the scripts with `ast` and imports none of them. Pure stdlib.

It checks import statements and calls to `__import__`, `builtins.__import__` or
`importlib.import_module`, under any alias the script binds with `import ... as` or
`from ... import ... as`, whose module name (first argument or `name=`) is a string literal. A
computed module name, or a call through a variable assigned the function, is not checked.
`__main__` is the running script itself, so it counts as local.

Needs sys.stdlib_module_names, so it skips below Python 3.10."""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "agent-ready" / "scripts"

needs_310 = pytest.mark.skipif(sys.version_info < (3, 10),
                               reason="sys.stdlib_module_names needs Python 3.10")


# Where each import function lives: (module, attribute).
IMPORT_FUNCS = {("importlib", "import_module"), ("builtins", "__import__")}
LOCAL_MODULES = {"__main__"}


def import_call_names(tree):
    """Return the call names that mean an import function, with the aliases the script binds."""
    names = {"__import__", "import_module"} | {"%s.%s" % f for f in IMPORT_FUNCS}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for module, attr in IMPORT_FUNCS:
                    if alias.name == module and alias.asname:
                        names.add("%s.%s" % (alias.asname, attr))
        elif isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                if (node.module, alias.name) in IMPORT_FUNCS:
                    names.add(alias.asname or alias.name)
    return names


def call_name(func):
    """Return `f` for `f(...)` and `m.f` for `m.f(...)`, else None."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return "%s.%s" % (func.value.id, func.attr)
    return None


def imported_names(node, call_names):
    """Return the absolute module names one node imports. Relative imports are local."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [] if node.level else [node.module]
    if isinstance(node, ast.Call) and call_name(node.func) in call_names:
        args = node.args[:1] + [k.value for k in node.keywords if k.arg == "name"]
        return [arg.value for arg in args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                and not arg.value.startswith(".")]
    return []


def non_stdlib_imports(path, label=None):
    """Return a `path:line` message for each absolute import of a non-stdlib top-level module."""
    label = label or path.name
    problems = []
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    call_names = import_call_names(tree)
    for node in ast.walk(tree):
        for name in imported_names(node, call_names):
            top = name.split(".")[0]
            if top not in sys.stdlib_module_names and top not in LOCAL_MODULES:
                problems.append("%s:%d: imports non-stdlib module %r (AGENTS.md: stdlib-only)"
                                % (label, node.lineno, top))
    return problems


@needs_310
def test_scripts_import_only_stdlib():
    scripts = sorted(SCRIPTS_DIR.glob("*.py"))
    assert scripts, "no scripts found in %s" % SCRIPTS_DIR
    problems = []
    for path in scripts:
        problems += non_stdlib_imports(path, path.relative_to(ROOT).as_posix())
    assert not problems, "\n".join(problems)


@needs_310
def test_checker_flags_third_party_import(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import json\nfrom requests.adapters import HTTPAdapter\n", encoding="utf-8")
    assert non_stdlib_imports(bad) == [
        "bad.py:2: imports non-stdlib module 'requests' (AGENTS.md: stdlib-only)"]
    good = tmp_path / "good.py"
    good.write_text("import json\nfrom pathlib import Path\nfrom . import sibling\n",
                    encoding="utf-8")
    assert non_stdlib_imports(good) == []


@needs_310
def test_checker_flags_dynamic_import_of_third_party_module(tmp_path):
    bad = tmp_path / "dynamic.py"
    bad.write_text("import importlib\n"
                   "from importlib import import_module\n"
                   "a = importlib.import_module('yaml')\n"
                   "b = __import__('requests.adapters')\n"
                   "c = import_module('toml')\n"
                   "d = importlib.import_module('json')\n"
                   "e = importlib.import_module('.sibling', __package__)\n", encoding="utf-8")
    assert non_stdlib_imports(bad) == [
        "dynamic.py:3: imports non-stdlib module 'yaml' (AGENTS.md: stdlib-only)",
        "dynamic.py:4: imports non-stdlib module 'requests' (AGENTS.md: stdlib-only)",
        "dynamic.py:5: imports non-stdlib module 'toml' (AGENTS.md: stdlib-only)"]


@needs_310
def test_checker_resolves_aliased_and_keyword_dynamic_imports(tmp_path):
    bad = tmp_path / "aliased.py"
    bad.write_text("import importlib as il\n"
                   "from importlib import import_module as im\n"
                   "import builtins\n"
                   "a = il.import_module('yaml')\n"
                   "b = im('toml')\n"
                   "c = importlib.import_module(name='requests')\n"
                   "d = builtins.__import__('attr')\n"
                   "e = il.import_module('json')\n"
                   "f = im(name='.sibling', package=__package__)\n"
                   "import __main__\n"
                   "g = __import__('__main__')\n", encoding="utf-8")
    assert non_stdlib_imports(bad) == [
        "aliased.py:4: imports non-stdlib module 'yaml' (AGENTS.md: stdlib-only)",
        "aliased.py:5: imports non-stdlib module 'toml' (AGENTS.md: stdlib-only)",
        "aliased.py:6: imports non-stdlib module 'requests' (AGENTS.md: stdlib-only)",
        "aliased.py:7: imports non-stdlib module 'attr' (AGENTS.md: stdlib-only)"]
