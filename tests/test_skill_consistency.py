"""Checks the repo's own rules for the skill (AGENTS.md): the router, README layout, neutrality,
self-containment and script headers must agree with the files on disk. Pure stdlib."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "agent-ready"
SKILL_MD = SKILL_DIR / "SKILL.md"
README = ROOT / "README.md"

# Vendor, model and harness names that must not appear in agent-ready/.
VENDOR_NAMES = ["Claude", "Codex", "Cursor", "OpenAI", "Anthropic", "GPT", "Copilot", "Gemini"]
# (relative path, lowercase name) pairs that are allowed to match. Keep this small.
ALLOWLIST = set()

MODULE_RE = re.compile(r"\b\d\d-[a-z0-9-]+\.md\b")


def rel(path):
    return path.relative_to(ROOT).as_posix()


def skill_files(suffixes=(".md", ".py", ".json")):
    return sorted(p for p in SKILL_DIR.rglob("*") if p.is_file() and p.suffix in suffixes)


def disk_modules():
    return sorted(p.name for p in (SKILL_DIR / "modules").glob("*.md"))


def read(path):
    return path.read_text(encoding="utf-8")


def test_skill_md_front_matter():
    text = read(SKILL_MD)
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    assert m, "%s: missing YAML front matter" % rel(SKILL_MD)
    keys = dict(
        line.split(":", 1) for line in m.group(1).splitlines() if re.match(r"^\w+\s*:", line)
    )
    for key in ("name", "description"):
        assert keys.get(key, "").strip(), "%s: front matter lacks a non-empty `%s`" % (
            rel(SKILL_MD), key)


def test_modules_are_routed_and_listed():
    on_disk = set(disk_modules())
    for doc in (SKILL_MD, README):
        named = set(MODULE_RE.findall(read(doc)))
        for name in sorted(on_disk - named):
            raise AssertionError("%s: module %s exists but is not named here" % (rel(doc), name))
        for name in sorted(named - on_disk):
            raise AssertionError("%s: names module %s but no such file in agent-ready/modules/"
                                 % (rel(doc), name))


def test_module_table_is_in_numeric_order():
    rows = re.findall(r"^\|.*`modules/(\d\d)-[a-z0-9-]+\.md`", read(SKILL_MD), re.M)
    assert rows == sorted(rows), "%s: module table rows out of numeric order: %s" % (
        rel(SKILL_MD), " ".join(rows))


def test_description_says_what_the_skill_is_not_for():
    m = re.search(r"^description:(.*)$", read(SKILL_MD), re.M)
    assert m and "Not for " in m.group(1), "%s: description lacks a \"Not for\" clause" % (
        rel(SKILL_MD))


def readme_layout_block():
    m = re.search(r"## Layout\s+```\n(.*?)```", read(README), re.S)
    assert m, "%s: no Layout code block found" % rel(README)
    return m.group(1)


def test_scripts_named_exist():
    on_disk = {p.name for p in (SKILL_DIR / "scripts").glob("*.py")}
    for doc, text in ((SKILL_MD, read(SKILL_MD)), (README, readme_layout_block())):
        named = set(re.findall(r"\b[a-z_]+\.py\b", text))
        for name in sorted(named - on_disk):
            raise AssertionError("%s: names script %s but it is not in agent-ready/scripts/"
                                 % (rel(doc), name))
        for name in sorted(on_disk - named):
            raise AssertionError("%s: script %s exists but is not named here" % (rel(doc), name))


def test_templates_named_exist():
    templates = SKILL_DIR / "templates"
    for path in re.findall(r"`templates/([^`]+)`", read(SKILL_MD) + read(README)):
        if path.endswith("/") or not path.strip():
            assert (templates / path).is_dir(), "templates/%s does not exist" % path
        else:
            assert (templates / path).exists(), "templates/%s is named but missing" % path
    # README layout lists templates by bare name, e.g. "AGENTS, REQUIREMENTS, ... docs/ (...)".
    block = readme_layout_block()
    m = re.search(r"templates/(.*?)\n\s*scripts/", block, re.S)
    assert m, "%s: layout block has no templates/ entry before scripts/" % rel(README)
    body = m.group(1)
    docs_part = re.search(r"docs/\s*\((.*?)\)", body, re.S)
    top = body[: docs_part.start()] if docs_part else body
    names = re.findall(r"\b[A-Z][A-Z-]+\b", top)
    on_disk = {p.stem for p in templates.iterdir() if p.is_file()}
    for name in names:
        assert name in on_disk, "%s: layout names template %s but no such file in agent-ready/templates/" % (
            rel(README), name)
    for name in sorted(on_disk - set(names)):
        raise AssertionError("%s: template %s exists but is not in the layout block"
                             % (rel(README), name))
    if docs_part:
        listed = set(re.findall(r"[a-z-]+", docs_part.group(1)))
        have = {p.stem for p in (templates / "docs").glob("*.md")}
        for stem in sorted(have):
            key = "index" if stem == "README" else stem
            assert key in listed, "%s: docs template %s is not in the layout block" % (
                rel(README), stem)


def test_no_vendor_names_in_skill():
    pattern = re.compile(r"\b(%s)\b" % "|".join(VENDOR_NAMES), re.I)
    problems = []
    for path in skill_files(suffixes=(".md", ".py", ".json", ".txt")):
        for n, line in enumerate(read(path).splitlines(), 1):
            for m in pattern.finditer(line):
                if (rel(path), m.group(1).lower()) not in ALLOWLIST:
                    problems.append("%s:%d: vendor/model name %r (AGENTS.md: agent-agnostic)"
                                    % (rel(path), n, m.group(1)))
    assert not problems, "\n".join(problems)


def test_no_links_leave_skill():
    link_re = re.compile(r"\]\(([^)\s#]+)[^)]*\)")
    problems = []
    files = [SKILL_MD] + sorted((SKILL_DIR / "modules").glob("*.md"))  # templates exempt
    for path in files:
        for target in link_re.findall(read(path)):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue  # URL or mailto
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(SKILL_DIR.resolve())
            except ValueError:
                problems.append("%s: link %r leaves agent-ready/ (AGENTS.md: skill self-contained)"
                                % (rel(path), target))
    assert not problems, "\n".join(problems)


def test_script_headers_state_exit_codes():
    for path in sorted((SKILL_DIR / "scripts").glob("*.py")):
        doc = ast.get_docstring(ast.parse(read(path)))
        assert doc, "%s: no header docstring (AGENTS.md: scripts state options and exit codes)" % rel(path)
        assert re.search(r"exit codes", doc, re.I), (
            "%s: header docstring does not mention 'Exit codes'" % rel(path))
