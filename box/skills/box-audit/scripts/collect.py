#!/usr/bin/env python3
"""Gather box-audit evidence from a repository, read-only. Stdlib only. CI runs it on Python 3.10
(Linux, macOS, Windows) and 3.8 (Linux).

Usage:
  collect.py REPO [--remote OWNER/NAME | --no-remote] [--runs N] [--prs N]
                  [--gh CMD] [--format json|md] [--out FILE]

  REPO          A local git checkout, or a folder in one: the whole checkout (from `git rev-parse
                --show-toplevel`) is collected and guarded. Only tracked files at the working
                tree are read; a file that is a symlink or junction, or sits under one, is
                listed but never read.
  --remote      The GitHub repository to read host evidence from. Default: parsed from the
                `origin` remote when it points at GitHub.
  --no-remote   Skip host evidence even if a remote exists.
  --runs N      CI runs to read from the host (default 100, max 200).
  --prs N       Recently merged PRs judged by their head's checks as of the merge (default
                20, max 50).
  --gh CMD      The command that runs gh, split like a shell would (default: `gh` on PATH).
                Use it when gh is a wrapper script the OS cannot execute directly.
  --format      json (default) or md, a compact rendering for the judge.
  --out FILE    Write there instead of stdout. FILE must be outside the checkout, and not an
                existing file with other hard links. It is replaced, never written through.

Exit codes: 0 evidence written; 2 usage error (REPO is not in a git checkout, --out inside it,
a PYTHONPYCACHEPREFIX inside it without -B, bad option). A missing host, `gh` or permission is not an error: each host collector records
`unavailable` with the reason, so a repo with no remote still gets a full report.

Read-only by design: the script runs only read-only git commands with optional locks off, never
fetches, never executes code from REPO, and writes nothing inside it. Git and gh run without any
GIT_* variable from the caller (no trace file, config override or other repository) and with
trace2 targets from git config turned off. Run it as `python -B`: interpreter startup, before the
first line, can write bytecode under a PYTHONPYCACHEPREFIX, so without -B a prefix inside the
checkout is refused (exit 2). Host evidence comes from the `gh` CLI's `gh api` (GET requests
only).

Every evidence item carries a basis. `verified` means it was observed in a system's actual state:
the host API, CI run results or git history. `read` means a file in the repo says so. The standard
counts read-only evidence as partial at best, so the judge needs the difference.

The test inventory, oracle and production collectors match file names and contents against
keyword lists. They find candidates; they do not prove a test is real or an oracle independent.
"""
import sys
# Before any other import: no module may write bytecode, which an inherited PYTHONPYCACHEPREFIX
# would put inside the audited checkout. Startup, before this line, is startup_bytecode()'s job.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import quote  # noqa: E402

# gh's response handling and git's environment, one implementation each for box-audit and
# orchestrate, loaded by path from box/lib in the checkout this file sits in. Bytecode is off by
# now, and the import path is untouched.
BOX_LIB = Path(__file__).resolve().parents[3] / "lib"


def load_lib(name):
    spec = importlib.util.spec_from_file_location("box_" + name, str(BOX_LIB / (name + ".py")))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gh_read = load_lib("gh_read")
git_env = load_lib("git_env").git_env

MAX_READ = 200000
MAX_TEST_FILES = 3000
MAX_PAGES = 10  # pages of 100 read from one host list; past that the list is incomplete

CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rb", ".java", ".kt",
            ".cs", ".rs", ".php", ".swift", ".sh", ".ps1", ".ex", ".exs"}
TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|specs?|e2e|integration[-_]?tests?|src/test)/"
    r"|(^|/)test_[^/]+\.py$|_test\.(py|go|rb|exs?)$|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|(Test|Tests|IT)\.(java|kt|cs)$|_spec\.rb$")

MOCK = re.compile(
    r"unittest\.mock|from mock import|MagicMock|mock\.patch|@patch\b|jest\.mock|"
    r"jest\.fn|vi\.mock|vi\.fn|sinon\.|\bnock\(|\bmsw\b|Mockito|@MockBean|mockk|gomock|"
    r"testify/mock|httpretty|requests_mock|\brespx\b|fakeredis|\bmoto\b|\bFake[A-Z]\w*|"
    r"\bStub[A-Z]\w*|\bInMemory[A-Z]\w*")
REAL = re.compile(
    r"testcontainers|docker|psycopg|asyncpg|postgres(ql)?://|mysql://|redis://|DATABASE_URL|"
    r"subprocess|child_process|execa|TestClient|supertest|httptest\.NewServer|sqlite3|"
    r"better-sqlite3")
E2E = re.compile(r"playwright|cypress|selenium|puppeteer|webdriver|\bdetox\b|appium")

ORACLES = {
    "property-based tests": r"\bhypothesis\b|fast-check|\bfc\.assert|proptest|quickcheck|jqwik|"
                            r"gopter|\brapid\.",
    "golden or recorded data": r"\bgolden\b|cassette|\bvcr\b|\brecorded\b|captured (on|from)",
    "snapshot tests (written by the code under test)": r"toMatchSnapshot|toMatchInlineSnapshot|"
                                                       r"snapshot\.assert|syrupy",
    "reference, oracle or differential": r"reference implementation|\boracle\b|differential|"
                                         r"\bparity\b",
    "validator or conformance suite": r"\bvalidator\b|conformance|official (test|schema|suite)",
    "contract tests": r"\bpact\b|contract test|consumer-driven",
    "reconciliation against real data": r"reconcil",
    "eval or model judge": r"\bevals?\b|\bjudge\b|llm-as|\bgrader\b",
    "mutation testing": r"mutmut|stryker|pitest|cosmic-ray",
}

HEALTH = re.compile(r"[\"'`/](healthz?|readyz|livez|_health|heartbeat|version)[\"'`/]")
TELEMETRY = re.compile(r"sentry|opentelemetry|rollbar|bugsnag|honeybadger|datadog|prometheus|"
                       r"newrelic|statsd|healthchecks\.io|uptime[-_ ]?kuma|ntfy|pagerduty",
                       re.I)
INSTALLER = re.compile(r"electron-builder|pyinstaller|\bnsis\b|\bwix\b|inno ?setup|\.msi\b|"
                       r"\.dmg\b|cargo-dist|goreleaser|msix|\.AppImage|flatpak|snapcraft", re.I)
VENDOR_DIR = re.compile(r"(^|/)(vendor|vendored|third[_-]party|external)/")
VENDOR_OUT = re.compile(r"vendor[-_](into|out|to)|(copy|sync|publish)[-_](to|into)[-_]", re.I)
VENDOR_OUT_TEXT = re.compile(r"(?i)vendor(ed)? (it |them |this )?into|copied into (the|a|another) "
                             r"(site|repo)")

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md",
                     "CONTRIBUTING.md")
PROOF_HEADING = re.compile(r"proof|prov(e|ing)|verif|evidence|done|test|ready|pull request|\bPR\b|"
                           r"merge|gate", re.I)
GATE_TARGET = re.compile(r"^(check|verify|ci|gate|ready|test|validate|preflight|precommit|"
                         r"pre-commit|lint|all)$")
BUGGY_LABEL = re.compile(r"bug|defect|regression|escaped|hunt", re.I)
# A change reference: #123, a pull URL, or a commit id (hex with at least one digit, so a word
# like "defaced" is not one).
CHANGE_REF = r"(#\d+|https?://\S+/pull/\d+|\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b)"
# "Introduced by #12", or an "Introducing PR" field followed by a reference. A field left at
# "unknown", "N/A" or a form's "_No response_" does not count.
INTRODUCED = re.compile(r"(introduc|caus|regress)\w*\s+(by|in)\s+(PR\s*)?" + CHANGE_REF +
                        r"|introducing (PR|change|commit)\b[\s:*_>-]{0,12}(PR\s*)?" + CHANGE_REF,
                        re.I)
FIX_SUBJECT = re.compile(r"^(fix|hotfix|bugfix|revert)\b|\bfix(es|ed)?\b|^Revert \"", re.I)


def item(claim, source, basis="read"):
    return {"claim": claim, "source": source, "basis": basis}


# ----- local access (read-only) -------------------------------------------------------------

def git(repo, *args):
    """Run a read-only git command. Returns stdout, or None if git failed."""
    env = git_env()
    try:
        p = subprocess.run(["git", "-C", str(repo), "-c", "core.fsmonitor=false"] + list(args),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env)
    except OSError:
        return None
    return p.stdout if p.returncode == 0 else None


def tracked_files(repo):
    out = git(repo, "ls-files", "-z")
    return sorted(f for f in (out or "").split("\0") if f)


def is_link(path):
    """A symlink, or on Windows a junction: either can point outside the checkout."""
    if os.path.islink(str(path)):
        return True
    if os.name != "nt":
        return False
    try:
        os.readlink(str(path))  # succeeds for junctions too (Python 3.8+)
        return True
    except (OSError, ValueError):
        return False


def linked(repo, rel):
    """True if rel, or a folder on the way to it, is a link. Such a path is never read: a tracked
    link can point at the owner's own instruction files, which must not reach the judge."""
    p = Path(repo)
    for part in Path(rel).parts:
        p = p / part
        if is_link(p):
            return True
    return False


def linked_files(repo, files):
    """The tracked files that are links or sit under one, checking each folder once."""
    memo = {}

    def check(rel):
        if rel not in memo:
            parent = rel.rpartition("/")[0]
            memo[rel] = bool(parent) and check(parent) or is_link(Path(repo) / rel)
        return memo[rel]
    return [f for f in files if check(f)]


def read(repo, rel, limit=MAX_READ):
    """Text of a tracked file, or None if missing, binary, unreadable or behind a link."""
    if linked(repo, rel):
        return None
    try:
        with open(Path(repo) / rel, "rb") as f:
            data = f.read(limit)
    except OSError:
        return None
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def find_line(text, pattern):
    """1-based line number of the first match, or 0."""
    m = re.search(pattern, text, re.M)
    return text.count("\n", 0, m.start()) + 1 if m else 0


# ----- host access (GitHub, GET only) -------------------------------------------------------

class Host:
    """`gh api` GETs against one repository. Errors are returned, never raised."""

    def __init__(self, slug, runner=None, gh=None):
        self.slug = slug
        self.gh = gh or ([shutil.which("gh")] if shutil.which("gh") else None)
        self.runner = runner or self._gh

    def _gh(self, path):
        if not self.gh:
            return None, "gh CLI not found"
        return gh_read.read(self.gh + ["api", "-X", "GET", "-H",
                                       "Accept: application/vnd.github+json", path], git_env())

    def get(self, path):
        return self.runner(path.replace("{repo}", "repos/" + self.slug))

    def get_all(self, path, key=None, enough=None):
        """Every entry across the pages of a per_page=100 list (the response itself, or the
        list under `key`), the first page's body, and an error if any page was refused or the
        page bound cut the list short. Reading stops early once `enough(entries)` is true."""
        entries, first, total = [], None, None
        for page in range(1, MAX_PAGES + 1):
            body, error = self.get(path if page == 1 else "%s&page=%d" % (path, page))
            if error:
                return entries, first, error if page == 1 else "page %d %s" % (page, error)
            if key:
                body = body or {}
                first = body if first is None else first
                batch = body.get(key) or []
                total = first.get("total_count")
            else:
                batch = body or []
                first = batch if first is None else first
            entries += batch
            # Without a total, a short page is the last one.
            done = len(entries) >= total if total is not None else len(batch) < 100
            if done or (enough and enough(entries)):
                return entries, first, None
            if not batch:
                return entries, first, "page %d empty at %d of %s" % (page, len(entries), total)
        if total is None:
            # MAX_PAGES full pages may be the whole list: an empty page after them says so.
            page = MAX_PAGES + 1
            body, error = self.get("%s&page=%d" % (path, page))
            if error:
                return entries, first, "page %d %s" % (page, error)
            if not ((body or {}).get(key) if key else body):
                return entries, first, None
        return entries, first, "stopped after %d page%s at %d of %s" % (
            MAX_PAGES, "" if MAX_PAGES == 1 else "s", len(entries), total)


def github_slug(url):
    m = re.search(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(\.git)?/?$", url or "")
    return "%s/%s" % (m.group(1), m.group(2)) if m else None


def unavailable(name, reason):
    return {"name": name, "status": "unavailable", "reason": reason, "items": [], "data": {}}


# ----- collectors ---------------------------------------------------------------------------

def repo_facts(ctx):
    repo = ctx["repo"]
    head = (git(repo, "rev-parse", "HEAD") or "").strip()
    branch = (git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    count = (git(repo, "rev-list", "--count", "HEAD") or "").strip()
    last = (git(repo, "log", "-1", "--format=%cs") or "").strip()
    exts = Counter(Path(f).suffix.lower() for f in ctx["files"] if Path(f).suffix)
    items = [item("HEAD is %s on %s, %s commits, last commit %s" % (head[:12], branch, count, last),
                  "git rev-parse / rev-list", "verified"),
             item("%d tracked files; top extensions %s" % (
                 len(ctx["files"]), ", ".join("%s %d" % e for e in exts.most_common(6))),
                  "git ls-files", "verified")]
    if ctx["links"]:
        items.append(item("%d tracked paths are links or sit under one, so they were not read and "
                          "what they hold is unavailable: %s" % (
                              len(ctx["links"]), ", ".join(ctx["links"][:12])),
                          "git ls-files + lstat", "verified"))
    host = ctx.get("host_reason")
    items.append(item("Remote: %s" % (ctx["slug"] or "none") +
                      ("" if not host else " (host evidence unavailable: %s)" % host),
                      "git remote / --remote", "verified"))
    return {"name": "repo", "status": "ok", "items": items,
            "data": {"head": head, "branch": branch, "commits": count, "last_commit": last,
                     "default_branch": ctx["default_branch"], "remote": ctx["slug"]}}


SOFT_FAIL = re.compile(r"\|\|\s*(true|exit 0)|; *exit 0$")
# A YAML block scalar header: | or >, then optional chomping and indentation indicators in either
# order, then an optional comment.
BLOCK_SCALAR = re.compile(r"^[|>](?:[+-]?[1-9]?|[1-9][+-])\s*(#.*)?$")


def strip_comment(value):
    """A single-line YAML value without its comment, and without its quotes if it is quoted.
    A comment is a # at the start or after whitespace, outside a quoted scalar."""
    m = re.match(r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^']|'')*)'", value)
    rest = value[m.end():] if m else value
    c = re.search(r"(?:^|\s)#", rest)
    if m:
        if m.group(1) is not None:
            return re.sub(r"\\([\"\\])", r"\1", m.group(1))
        return m.group(2).replace("''", "'")
    return rest[:c.start()].rstrip() if c else rest


def strip_shell_comment(command):
    """A shell command line without its comment: a # that starts a word, outside shell quotes and
    not escaped."""
    quote, escaped, word_start = None, False, True
    for i, ch in enumerate(command):
        if escaped:
            escaped, word_start = False, False
        elif quote == "'":
            quote = None if ch == "'" else quote
        elif ch == "\\":
            escaped = True
        elif quote == '"':
            quote = None if ch == '"' else quote
        elif ch in "'\"":
            quote, word_start = ch, False
        elif ch == "#" and word_start:
            return command[:i].rstrip()
        else:
            word_start = ch in " \t;&|()<>"
    return command


def parse_workflow(text):
    """Line-based facts from a GitHub Actions workflow. Not a YAML parser; enough for evidence."""
    lines = text.splitlines()
    facts = {"triggers": [], "jobs": [], "runs": [], "uses": [], "cancel_in_progress": [],
             "continue_on_error": 0, "soft_fail": [], "secret_conditions": [], "images": [],
             "schedules": [], "runners": [],
             "opens_issues": bool(re.search(r"gh issue create|issues\.create|create-issue", text))}
    section, job, block_indent = None, None, None
    for n, raw in enumerate(lines, 1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            if indent > block_indent:
                facts["runs"].append((n, job, stripped[:200]))
                if SOFT_FAIL.search(stripped):
                    facts["soft_fail"].append((n, stripped[:120]))
                continue
            block_indent = None
        if indent == 0:
            m = re.match(r"^[\"']?(on|true)[\"']?:\s*(.*)$", line)
            section = "on" if m else line.split(":")[0]
            if m and m.group(2):
                facts["triggers"] += re.findall(r"[\w-]+", m.group(2))
            continue
        if section == "on" and indent == 2 and stripped.endswith(":"):
            facts["triggers"].append(stripped[:-1].strip("'\""))
        elif section == "on" and indent == 2 and ":" in stripped:
            facts["triggers"].append(stripped.split(":")[0].strip("'\""))
        if section == "jobs" and indent == 2 and re.match(r"^[\w-]+:\s*$", stripped):
            job = stripped[:-1]
            facts["jobs"].append(job)
        m = re.match(r"^(-\s*)?run:\s*(.*)$", stripped)
        if m:
            if BLOCK_SCALAR.match(m.group(2)):
                # The body ends at the run key's own column, so sibling step keys after a
                # "- run:" line are parsed, not read as commands.
                block_indent = indent + len(m.group(1) or "")
            else:
                facts["runs"].append((n, job, m.group(2)[:200]))
                if SOFT_FAIL.search(strip_shell_comment(strip_comment(m.group(2)))):
                    facts["soft_fail"].append((n, m.group(2)[:120]))
        m = re.match(r"^-?\s*uses:\s*(\S+)", stripped)
        if m:
            facts["uses"].append((n, m.group(1)))
        m = re.match(r"^cancel-in-progress:\s*(.+)$", stripped)
        if m:
            facts["cancel_in_progress"].append((n, m.group(1)))
        if re.match(r"^continue-on-error:\s*true", stripped):
            facts["continue_on_error"] += 1
        m = re.match(r"^-?\s*if:\s*(.+)$", stripped)
        if m and re.search(r"secrets\.|env\.\w*(TOKEN|KEY)", m.group(1)):
            facts["secret_conditions"].append((n, m.group(1)[:120]))
        m = re.match(r"^-?\s*(image|container):\s*([\w./:@${}-]+)$", stripped)
        if m:
            facts["images"].append((n, m.group(2)))
        m = re.match(r"^-?\s*runs-on:\s*(.+)$", stripped)
        if m:
            facts["runners"].append((n, m.group(1)[:120]))
        elif re.match(r"^-\s*\{.*\b(os|runner|platform)\b.*\}$", stripped) or \
                re.match(r"^(os|platform|python(-version)?|node(-version)?):\s*\[", stripped):
            facts["runners"].append((n, stripped[:160]))
        m = re.match(r"^-\s*cron:\s*(.+)$", stripped)
        if m:
            facts["schedules"].append(m.group(1).strip("'\""))
    facts["triggers"] = sorted(set(facts["triggers"]))
    return facts


OTHER_CI = (".gitlab-ci.yml", "azure-pipelines.yml", "bitbucket-pipelines.yml", "Jenkinsfile",
            ".circleci/config.yml", ".drone.yml", ".woodpecker.yml", ".buildkite/pipeline.yml")


def ci_config(ctx):
    repo, items, data = ctx["repo"], [], {"workflows": {}, "other_ci": [], "local_gate": []}
    workflows = [f for f in ctx["files"]
                 if re.match(r"^\.github/workflows/[^/]+\.ya?ml$", f)]
    for wf in workflows:
        text = read(repo, wf) or ""
        facts = parse_workflow(text)
        data["workflows"][wf] = facts
        items.append(item("%s: triggers %s; jobs %s" % (
            wf, ", ".join(facts["triggers"]) or "none", ", ".join(facts["jobs"]) or "none"), wf))
        for n, job, cmd in facts["runs"][:25]:
            items.append(item("runs `%s` (job %s)" % (cmd, job), "%s:%d" % (wf, n)))
        for n, runner in facts["runners"][:8]:
            items.append(item("runs on / matrix: %s" % runner, "%s:%d" % (wf, n)))
        for n, ref in facts["uses"]:
            if not re.search(r"^actions/(checkout|setup-|cache|upload-artifact|download-artifact)",
                             ref):
                items.append(item("uses %s" % ref, "%s:%d" % (wf, n)))
        for n, value in facts["cancel_in_progress"]:
            items.append(item("cancel-in-progress: %s" % value, "%s:%d" % (wf, n)))
        for n, cond in facts["secret_conditions"]:
            items.append(item("step or job runs only if `%s`: it may pass green while skipping"
                              % cond, "%s:%d" % (wf, n)))
        for n, cmd in facts["soft_fail"]:
            items.append(item("soft-fail command `%s`" % cmd, "%s:%d" % (wf, n)))
        if facts["continue_on_error"]:
            items.append(item("%d continue-on-error: true" % facts["continue_on_error"], wf))
        if "pull_request_target" in facts["triggers"]:
            items.append(item("pull_request_target: the workflow definition comes from the base "
                              "branch", wf))
        if facts["schedules"]:
            items.append(item("scheduled: %s%s" % (", ".join(facts["schedules"]),
                                                   "; opens issues" if facts["opens_issues"]
                                                   else ""), wf))
    for name in OTHER_CI:
        if name in ctx["files"]:
            text = read(repo, name) or ""
            scripts = re.findall(r"^[ \t]*-\s+(.+)$", text, re.M)[:15]
            data["other_ci"].append(name)
            items.append(item("%s present; script lines: %s" % (name, "; ".join(scripts)[:600]),
                              name))
    if not workflows and not data["other_ci"]:
        items.append(item("no CI configuration found", "git ls-files", "verified"))
    data["local_gate"] = local_gate(ctx)
    for src, target in data["local_gate"]:
        items.append(item("local gate candidate `%s`" % target, src))
    if not data["local_gate"]:
        items.append(item("no one-command local gate found (Makefile, package.json, justfile, "
                          "scripts/ready*, scripts/ci*, tox.ini, noxfile.py)", "git ls-files",
                          "verified"))
    return {"name": "ci_config", "status": "ok", "items": items, "data": data}


def local_gate(ctx):
    repo, found = ctx["repo"], []
    for f in ctx["files"]:
        base = f.rsplit("/", 1)[-1]
        if f.count("/") <= 1 and re.match(r"^(ready|check|verify|ci|gate|preflight)"
                                          r"([-_.][\w.-]*)?$", base) and \
                (f.startswith(("scripts/", "bin/", "tools/")) or "/" not in f):
            found.append((f, f))
    if "Makefile" in ctx["files"]:
        for m in re.finditer(r"^([\w-]+):", read(repo, "Makefile") or "", re.M):
            if GATE_TARGET.match(m.group(1)):
                found.append(("Makefile", "make " + m.group(1)))
    for pkg in [f for f in ctx["files"] if f.endswith("package.json") and f.count("/") <= 1]:
        try:
            data = json.loads(read(repo, pkg) or "{}")
        except ValueError:
            continue
        scripts = data.get("scripts") if isinstance(data, dict) else None
        if not isinstance(scripts, dict):
            continue
        for name in scripts:
            if GATE_TARGET.match(name.split(":")[0]):
                found.append((pkg, "npm run %s" % name))
    for name, pattern in (("justfile", r"^([\w-]+):"), ("Taskfile.yml", r"^  ([\w-]+):")):
        if name in ctx["files"]:
            for m in re.finditer(pattern, read(repo, name) or "", re.M):
                if GATE_TARGET.match(m.group(1)):
                    found.append((name, "%s %s" % ("just" if name == "justfile" else "task",
                                                   m.group(1))))
    for name in ("tox.ini", "noxfile.py"):
        if name in ctx["files"]:
            found.append((name, name.split(".")[0]))
    return found[:20]


def ci_runs(ctx):
    host = ctx["host"]
    if not host:
        return unavailable("ci_runs", ctx["host_reason"])
    runs, error = [], None
    for page in (1, 2):
        if len(runs) >= ctx["runs"]:
            break
        body, error = host.get("{repo}/actions/runs?per_page=%d&page=%d"
                               % (min(100, ctx["runs"]), page))
        if error:
            break
        batch = (body or {}).get("workflow_runs", [])
        runs += batch
        if len(batch) < 100:
            break
    if error and not runs:
        return unavailable("ci_runs", "actions/runs: %s" % error)
    out = summarize_runs(runs[:ctx["runs"]], ctx["default_branch"])
    if error:
        # The unread runs can hold cancellations or flakes: a short sample is not a clean one.
        out["data"]["incomplete"] = "page %d %s" % (page, error)
        out["items"].insert(0, item(
            "read %d of the %d runs asked for (%s): cancellations, re-attempts and flakes in the "
            "older runs are unknown" % (len(runs), ctx["runs"], out["data"]["incomplete"]),
            "api actions/runs", "verified"))
    return out


def summarize_runs(runs, default_branch):
    items, data = [], {"total": len(runs)}
    if not runs:
        return {"name": "ci_runs", "status": "ok", "data": data,
                "items": [item("no CI runs on the host", "api actions/runs", "verified")]}
    span = "%s to %s" % (runs[-1].get("created_at", "")[:10], runs[0].get("created_at", "")[:10])
    concl = Counter(r.get("conclusion") or r.get("status") for r in runs)
    items.append(item("last %d runs (%s): %s" % (len(runs), span, ", ".join(
        "%s %d" % kv for kv in concl.most_common())), "api actions/runs", "verified"))
    default = [r for r in runs if r.get("head_branch") == default_branch and
               r.get("event") in ("push", "merge_group", "schedule", "workflow_dispatch")]
    dconcl = Counter(r.get("conclusion") or r.get("status") for r in default)
    items.append(item("default-branch runs (%s): %d: %s" % (default_branch, len(default), ", ".join(
        "%s %d" % kv for kv in dconcl.most_common()) or "none"), "api actions/runs", "verified"))
    cancelled = [r for r in default if r.get("conclusion") == "cancelled"]
    if cancelled:
        items.append(item("%d default-branch runs were cancelled, e.g. %s at %s" % (
            len(cancelled), cancelled[0].get("name"), cancelled[0].get("head_sha", "")[:12]),
            "api actions/runs", "verified"))
    by_sha = defaultdict(set)
    for r in runs:
        by_sha[(r.get("name"), r.get("head_sha"))].add(r.get("conclusion"))
    flaky = sorted({k[0] for k, v in by_sha.items() if "failure" in v and "success" in v})
    reruns = [r for r in runs if (r.get("run_attempt") or 1) > 1]
    items.append(item("%d runs were re-attempts; workflows with both failure and success on one "
                      "commit (flake suspects): %s" % (len(reruns), ", ".join(flaky) or "none"),
                      "api actions/runs", "verified"))
    per_wf = defaultdict(Counter)
    for r in runs:
        # Host-generated workflows (dependency updates, pages) get one row per run otherwise.
        name = r.get("path") if str(r.get("path", "")).startswith("dynamic/") else r.get("name")
        per_wf[str(name).split("/")[1] if str(name).startswith("dynamic/") else name][
            r.get("conclusion") or r.get("status")] += 1
    for name, c in sorted(per_wf.items(), key=lambda kv: str(kv[0])):
        items.append(item("workflow %s: %s" % (name, ", ".join("%s %d" % kv for kv in
                                                               c.most_common())),
                          "api actions/runs", "verified"))
    data.update({"conclusions": dict(concl), "default_branch_runs": len(default),
                 "default_branch_cancelled": len(cancelled), "reruns": len(reruns),
                 "flake_suspects": flaky})
    return {"name": "ci_runs", "status": "ok", "items": items, "data": data}


def protection(ctx):
    # `_` is both a separator and a word character, so only `-` and `.` may start a later part.
    ready = r"(^|/)ready(?:[-_.]\w+(?:[-.]\w+)*)?$|(^|/)ready\.\w+$"
    items, data = [], {"ready_scripts": [f for f in ctx["files"] if re.search(ready, f)]}
    for f in data["ready_scripts"]:
        items.append(item("ready script present: %s" % f, f))
    for f in ctx["files"]:
        if f in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
            text = read(ctx["repo"], f) or ""
            gate = [l for l in text.splitlines() if re.search(r"workflows|\.github|sonar|coverage",
                                                              l)]
            items.append(item("CODEOWNERS present; gate-path lines: %s" % ("; ".join(gate)[:300]
                                                                           or "none"), f))
    host = ctx["host"]
    if not host:
        out = unavailable("protection", ctx["host_reason"])
        out["items"], out["data"] = items, data
        return out
    branch = ctx["default_branch"]
    rules, _, error = host.get_all("{repo}/rules/branches/%s?per_page=100" % branch)
    if error and not rules:
        items.append(item("effective rules on %s unavailable: %s" % (branch, error),
                          "api rules/branches", "verified"))
    else:
        data["rules"] = rules
        items += describe_rules(rules, branch)
        if error:
            # An unread page can hold a required check, so what is required stays unknown.
            data["rules_incomplete"] = error
            items.append(item("effective rules on %s read only in part: %s; rules on the unread "
                              "pages are unknown" % (branch, error), "api rules/branches",
                              "verified"))
    sets, _, error = host.get_all("{repo}/rulesets?includes_parents=true&per_page=100")
    for rs in sets:
        items.append(item("ruleset %r: target %s, enforcement %s" % (
            rs.get("name"), rs.get("target"), rs.get("enforcement")), "api rulesets", "verified"))
    if error:
        items.append(item("ruleset list %s: %s" % ("read only in part" if sets else "unavailable",
                                                    error), "api rulesets", "verified"))
    br, error = host.get("{repo}/branches/%s" % branch)
    if error or not br:
        items.append(item("classic branch protection on %s unavailable: %s" % (
            branch, error or "empty response"), "api branches", "verified"))
    else:
        prot = br.get("protection") or {}
        checks = (prot.get("required_status_checks") or {})
        items.append(item("classic branch protection on %s: %s; required checks %s" % (
            branch, "enabled" if br.get("protected") else "not enabled",
            ", ".join(checks.get("contexts") or []) or "none"), "api branches", "verified"))
        data["classic"] = {"protected": br.get("protected"), "contexts": checks.get("contexts")}
    # The rules endpoint reports rulesets only, so "nothing required" needs classic too.
    if "rules" in data and not data["rules"]:
        if "classic" not in data:
            items.append(item("no ruleset rules and classic protection unknown: whether anything "
                              "is required to merge %s is unknown" % branch,
                              "api rules/branches + branches", "verified"))
        elif not data["classic"]["protected"]:
            items.append(item("no ruleset rules and no classic branch protection: nothing is "
                              "required to merge %s" % branch, "api rules/branches + branches",
                              "verified"))
    status = "ok" if "rules" in data or "classic" in data else "unavailable"
    return {"name": "protection", "status": status, "items": items, "data": data,
            "reason": None if status == "ok" else "host refused every protection lookup"}


def describe_rules(rules, branch):
    items = []
    if not rules:
        return [item("no active ruleset rules apply to %s" % branch, "api rules/branches",
                     "verified")]
    for rule in rules:
        kind, p = rule.get("type"), rule.get("parameters") or {}
        if kind == "required_status_checks":
            checks = [c.get("context") for c in p.get("required_status_checks", [])]
            claim = "required checks on %s: %s (must be up to date with base: %s)" % (
                branch, ", ".join(checks) or "none",
                "yes" if p.get("strict_required_status_checks_policy") else "no")
        elif kind == "pull_request":
            claim = "PR required on %s: %d approvals, dismiss stale reviews on push: %s, " \
                    "last-push approval: %s" % (
                        branch, p.get("required_approving_review_count", 0),
                        p.get("dismiss_stale_reviews_on_push"), p.get("require_last_push_approval"))
        elif kind == "workflows":
            claim = "required workflows: %s" % ", ".join(
                "%s@%s" % (w.get("path"), (w.get("sha") or w.get("ref") or "")[:12])
                for w in p.get("workflows", []))
        else:
            claim = "rule %s on %s" % (kind, branch)
        items.append(item(claim, "api rules/branches", "verified"))
    return items


def actions_run(check):
    return (check.get("app") or {}).get("slug") == "github-actions"


def suite_id(check):
    return (check.get("check_suite") or {}).get("id")


RED_CHECK = ("failure", "timed_out", "cancelled", "action_required")
RED_STATUS = ("failure", "error")


def when(stamp):
    """A GitHub timestamp (2026-10-01T10:05:00Z) as a UTC datetime, or None."""
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def checks_at(runs, merged, workflows=None):
    """Check names red as of `merged`, red now, and without the times to tell, from every run
    at one commit. A check can run several times on one commit: a re-run attempt stays in its
    check suite, but a workflow triggered again on the same head (labeled, reopened,
    cancel-in-progress) runs in a new suite. So a check is its app and name, plus for GitHub
    Actions its workflow, from `workflows` (check suite to workflow id). An equal name from
    another app or workflow is a separate check with its own verdict. With `workflows` None,
    an Actions name is one check across workflows: a failure there is red under any lineage,
    but a pass proves nothing about the other workflows.

    A check's verdict at the merge is its newest run (highest id) started by then, if that run
    had finished: one still running was pending, and a check first run later was not part of
    the merge. Overlapping runs can start out of creation order, so start time does not pick
    the newest run. Its verdict now is its latest run, reruns after the merge included, and needs
    neither `merged` nor run times. Without `merged` there is no merge verdict to give."""
    by_check = defaultdict(list)
    for c in runs:
        wf = workflows.get(suite_id(c)) if workflows is not None and actions_run(c) else None
        by_check[((c.get("app") or {}).get("id"), wf, c.get("name"))].append(c)
    red, now, unknown = set(), set(), set()
    for (_, _, name), rs in by_check.items():
        if max(rs, key=lambda c: c.get("id", 0)).get("conclusion") in RED_CHECK:
            now.add(name)
        if merged is None:
            continue
        if any(when(c.get("started_at")) is None for c in rs):
            unknown.add(name)
            continue
        before = [c for c in rs if when(c["started_at"]) <= merged]
        if not before:
            continue
        run = max(before, key=lambda c: c.get("id", 0))
        done = when(run.get("completed_at"))
        if run.get("status") == "completed" and done is None:
            unknown.add(name)
        elif done and done <= merged and run.get("conclusion") in RED_CHECK:
            red.add(name)
    return sorted(red), sorted(now), sorted(unknown)


def statuses_at(statuses, merged):
    """Contexts red as of `merged`, red now, and without the times to tell, from the statuses
    at one commit. A status is never changed, only followed by a newer one, so a context's
    verdict at the merge is its latest status created by then. Its verdict now does not need
    `merged`, and without `merged` there is no merge verdict to give."""
    by_context = defaultdict(list)
    for s in statuses:
        by_context[s.get("context")].append(s)
    red, now, unknown = [], [], []
    for context, ss in by_context.items():
        if any(when(s.get("created_at")) is None for s in ss):
            unknown.append(context)
            continue
        ss.sort(key=lambda s: (when(s["created_at"]), s.get("id", 0)))
        if ss[-1].get("state") in RED_STATUS:
            now.append(context)
        if merged is None:
            continue
        before = [s for s in ss if when(s["created_at"]) <= merged]
        if before and before[-1].get("state") in RED_STATUS:
            red.append(context)
    return red, now, unknown


def merged_prs(ctx):
    host = ctx["host"]
    if not host:
        return unavailable("merged_prs", ctx["host_reason"])
    # Closed PRs include unmerged ones, so read pages until the merged sample is full.
    pulls, _, pulls_error = host.get_all(
        "{repo}/pulls?state=closed&base=%s&sort=updated&direction=desc&per_page=100"
        % ctx["default_branch"],
        enough=lambda ps: sum(1 for p in ps if p.get("merged_at")) >= ctx["prs"])
    merged = [p for p in pulls if p.get("merged_at")][:ctx["prs"]]
    if pulls_error and not merged:
        return unavailable("merged_prs", "pulls: %s" % pulls_error)
    # The merge verdict comes from the head's run and status history as of `merged_at`. The
    # head's latest results are a separate snapshot: a rerun after the merge changes them, not
    # the merge.
    items, red, refused, red_now = [], [], [], []
    for pr in merged:
        sha = (pr.get("head") or {}).get("sha", "")
        at = when(pr.get("merged_at"))
        bad, now, errors = [], [], []
        if at is None:
            errors.append("merge time %r unreadable" % pr.get("merged_at"))
        # Without filter=all the list holds only each check's latest run.
        runs, _, error = host.get_all(
            "{repo}/commits/%s/check-runs?per_page=100&filter=all" % sha, "check_runs")
        if error:
            # An unread page can hold a later run of a failed check, so a partial read proves
            # nothing either way.
            errors.append("check-runs %s" % error)
        else:
            workflows, error = {}, None
            if any(actions_run(c) for c in runs):
                wruns, _, error = host.get_all("{repo}/actions/runs?head_sha=%s&per_page=100"
                                               % sha, "workflow_runs")
                workflows = {r.get("check_suite_id"): r.get("workflow_id") for r in wruns}
                unknown = sorted({suite_id(c) for c in runs if actions_run(c)} - set(workflows))
                if error:
                    error = "actions/runs %s" % error
                elif unknown:
                    error = "workflow of check suite %s unknown" % ", ".join(map(str, unknown))
            if error:
                errors.append(error)
            # The snapshot is taken whether or not the merge can be placed in the history.
            bad, now, untimed = checks_at(runs, at, None if error else workflows)
            if untimed:
                errors.append("check-runs without run times: %s" % ", ".join(sorted(untimed)))
        # Status-based CI posts commit statuses, not check runs. This list is every status,
        # newest first, so the pages read hold each context's latest ones: a status red there
        # is red even on a partial read.
        statuses, _, error = host.get_all("{repo}/commits/%s/statuses?per_page=100" % sha)
        if error:
            errors.append("statuses %s" % error)
        failed, failing_now, untimed = statuses_at(statuses, at)
        bad, now = bad + failed, now + failing_now
        if untimed:
            errors.append("statuses without times: %s" % ", ".join(sorted(untimed)))
        if now:
            red_now.append((pr.get("number"), now))
        if bad:
            red.append(pr.get("number"))
            items.append(item("PR #%s merged with non-green checks at its head %s: %s (as of "
                              "the merge at %s)" % (pr.get("number"), sha[:12],
                                                    ", ".join(sorted(bad)), pr.get("merged_at")),
                              "api check-runs + commit statuses", "verified"))
        elif errors:
            refused.append((pr.get("number"), "; ".join(errors)))
    # A PR whose history could not all be read is unknown unless one read showed it red. With
    # every merge verdict unknown the collector is unavailable, but the snapshot still stands.
    none_read = merged and len(refused) == len(merged)
    read_ok = len(merged) - len(refused)
    if not none_read:
        items.insert(0, item("%d of %d merged PRs whose merge verdict could be read (of the last "
                             "%d) had, as of the merge, a check whose latest finished run "
                             "failed, was cancelled or timed out, or a commit status in failure "
                             "or error" % (len(red), read_ok, len(merged)),
                             "api pulls + check-runs + commit statuses", "verified"))
    if refused:
        items.insert(0 if none_read else 1, item("merge verdict unknown for %d merged PRs, not counted: %s" % (
            len(refused), ", ".join("#%s: %s" % r for r in refused[:10])),
            "api check-runs + commit statuses", "verified"))
    if red_now:
        items.append(item("snapshot, not the merge verdict: %d merged PRs have a check or status "
                          "failing at their head now, reruns after the merge included: %s" % (
                              len(red_now), ", ".join("#%s (%s)" % (n, ", ".join(sorted(c)))
                                                      for n, c in red_now[:10])),
                          "api check-runs + commit statuses", "verified"))
    if pulls_error:
        items.insert(0, item("closed PRs read only in part: %s; %d merged PRs found of the %d "
                             "asked for, and older ones are unknown" % (
                                 pulls_error, len(merged), ctx["prs"]), "api pulls", "verified"))
    labels = Counter(l.get("name") for p in merged for l in p.get("labels") or [])
    if labels:
        items.append(item("labels on those PRs: %s" % ", ".join("%s %d" % kv for kv in
                                                                labels.most_common(12)),
                          "api pulls", "verified"))
    data = {"merged": len(merged), "merged_red": red,
            "checks_unavailable": [n for n, _ in refused], "red_now": [n for n, _ in red_now]}
    if pulls_error:
        data["pulls_incomplete"] = pulls_error
    if none_read:
        return {"name": "merged_prs", "status": "unavailable", "items": items, "data": data,
                "reason": "merge verdict: %s for all %d merged PRs" % (refused[0][1], len(merged))}
    return {"name": "merged_prs", "status": "ok", "items": items, "data": data}


def test_inventory(ctx):
    repo = ctx["repo"]
    tests = [f for f in ctx["files"] if TEST_PATH.search(f) and Path(f).suffix in CODE_EXT]
    kinds, examples, markers = Counter(), defaultdict(list), Counter()
    for f in tests[:MAX_TEST_FILES]:
        text = read(repo, f) or ""
        mock = MOCK.findall(text)
        real = [m.group(0) for m in REAL.finditer(text)]
        e2e = [m.group(0) for m in E2E.finditer(text)]
        markers.update(m.group(0).split("(")[0] for m in MOCK.finditer(text))
        markers.update(real + e2e)
        kind = ("end-to-end" if e2e else "real dependency" if real and not mock else
                "mixed (real and mocks)" if real else "mocked" if mock else "plain unit")
        kinds[kind] += 1
        if len(examples[kind]) < 6:
            examples[kind].append(f)
    items = [item("%d test files: %s" % (len(tests), ", ".join(
        "%s %d" % kv for kv in kinds.most_common()) or "none"), "git ls-files + keyword scan")]
    for kind, files in sorted(examples.items()):
        items.append(item("%s examples: %s" % (kind, ", ".join(files)), "keyword scan"))
    if markers:
        items.append(item("most frequent markers: %s" % ", ".join(
            "%s %d" % kv for kv in markers.most_common(15)), "keyword scan"))
    images = []
    for f in ctx["files"]:
        base = f.rsplit("/", 1)[-1].lower()
        if re.match(r"(docker-)?compose[\w.-]*\.ya?ml$", base) or base.startswith("dockerfile"):
            text = read(repo, f) or ""
            for m in re.finditer(r"^\s*(?:image:|FROM)\s+([\w./:@${}-]+)", text, re.M | re.I):
                images.append((f, m.group(1)))
    for wf, facts in ctx.get("workflows", {}).items():
        images += [(wf, img) for _, img in facts["images"]]
    if images:
        items.append(item("images (compare CI test versions with production): %s" % "; ".join(
            "%s in %s" % (img, f) for f, img in images[:20]), "compose, Dockerfile, workflows"))
    return {"name": "tests", "status": "ok", "items": items,
            "data": {"files": len(tests), "kinds": dict(kinds), "images": images[:40]}}


def oracles(ctx):
    repo = ctx["repo"]
    scan = [f for f in ctx["files"] if (TEST_PATH.search(f) or f.startswith(
        (".github/workflows/", "scripts/", "eval", "tools/", "docs/"))) and
        Path(f).suffix in CODE_EXT | {".yml", ".yaml", ".md", ".toml", ".json", ".cfg", ".ini"}]
    scan += [f for f in ("pyproject.toml", "package.json", "requirements-dev.txt",
                         "requirements.txt", "go.mod", "Cargo.toml") if f in ctx["files"]]
    hits = defaultdict(list)
    for f in scan[:MAX_TEST_FILES]:
        text = read(repo, f) or ""
        for label, pattern in ORACLES.items():
            line = find_line(text, "(?i)" + pattern)
            if line and len(hits[label]) < 6:
                hits[label].append("%s:%d" % (f, line))
    # File names find oracles that live in product code, such as a reconciliation command.
    named = defaultdict(list)
    for f in ctx["files"]:
        words = f.replace("_", " ").replace("-", " ")
        for label, pattern in ORACLES.items():
            if len(named[label]) < 6 and re.search(pattern, words, re.I):
                named[label].append(f)
        if re.search(r"(^|/)(golden|recorded|cassettes)(/|$)", f, re.I):
            label = "golden or recorded data"
            if len(named[label]) < 6 and f not in named[label]:
                named[label].append(f)
    items = [item("%s: %s" % (label, ", ".join(paths)), "keyword scan")
             for label, paths in sorted(hits.items())]
    items += [item("file names matching %s: %s" % (label, ", ".join(paths)), "git ls-files",
                   "verified") for label, paths in sorted(named.items()) if paths]
    review = [wf for wf in ctx.get("workflows", {}) if re.search(r"review|judge|verif", wf, re.I)]
    for wf in review:
        items.append(item("workflow that may run an outside reviewer or judge: %s" % wf, wf))
    if not items:
        items.append(item("no candidate outside oracle found by name or keyword",
                          "keyword scan"))
    return {"name": "oracles", "status": "ok", "items": items,
            "data": {"content": dict(hits), "names": {k: v for k, v in named.items() if v}}}


def proof_rules(ctx):
    repo, items, data = ctx["repo"], [], {}
    present = [f for f in ctx["files"] if f in INSTRUCTION_FILES or
               re.search(r"(^|/)AGENTS\.md$", f)]
    data["instruction_files"] = present
    items.append(item("instruction files: %s" % (", ".join(present) or "none"), "git ls-files",
                      "verified"))
    agents = "AGENTS.md" if "AGENTS.md" in ctx["files"] else None
    if agents in ctx["links"]:
        items.append(item("AGENTS.md is a link or sits under one: not read, so its proof rules "
                          "are unavailable", "git ls-files + lstat", "verified"))
    elif agents:
        text = read(repo, agents) or ""
        heads = re.findall(r"^#{1,4} .+$", text, re.M)
        data["agents_headings"] = heads
        items.append(item("AGENTS.md: %d lines; headings: %s" % (
            text.count("\n"), " | ".join(h.lstrip("# ") for h in heads)[:600]), agents))
        excerpts = proof_sections(text)
        data["proof_excerpt"] = excerpts
        if excerpts:
            items.append(item("AGENTS.md proof-related sections (excerpt):\n" + excerpts, agents))
        else:
            items.append(item("AGENTS.md has no section on proof, verification or evidence",
                              agents))
    skills = [f for f in ctx["files"] if re.search(
        # The lookahead finds the folder's closing `/` once, so `verif` is not retried to the end.
        r"(^|/)skills/(?=[\w-]*/)[\w-]*verif"
        r"|docs/ui-testing\.md$|(^|/)verify[\w-]*\.(md|sh|py|ps1)$", f, re.I)]
    data["verify"] = skills
    items.append(item("verify skill or UI-testing contract: %s" % (", ".join(skills[:8]) or
                                                                   "none found"), "git ls-files",
                      "verified"))
    contracts = [f for f in ctx["files"]
                 if re.search(r"(^|/)disposable[-_]instance\.md$", f, re.I)]
    data["instance_contract"] = contracts
    items.append(item("disposable-instance contract: %s" % (", ".join(contracts[:4]) or
                                                            "none found"), "git ls-files",
                      "verified"))
    templates = [f for f in ctx["files"] if re.search(r"pull_request_template\.md$", f, re.I)]
    data["pr_templates"] = {}
    for t in templates:
        text = read(repo, t) or ""
        mentions = [w for w in ("Proof", "Not verified", "Gate changes", "Closes") if w in text]
        data["pr_templates"][t] = mentions
        items.append(item("PR template %s; mentions: %s" % (
            t, ", ".join(mentions) or "none of Proof, Not verified, Gate changes, Closes"), t))
    lint = [wf for wf, facts in ctx.get("workflows", {}).items()
            if re.search(r"Proof|Not verified|pr[-_ ]body", read(repo, wf) or "")]
    data["pr_body_lint"] = lint
    items.append(item("workflows that read the PR body for proof: %s" % (", ".join(lint) or
                                                                         "none"), "keyword scan"))
    docs = [f for f in ctx["files"] if re.match(r"docs/(architecture|data-model|runtime|testing|"
                                                r"README|index)\.md$", f, re.I)]
    data["docs"] = docs
    items.append(item("docs layer: %s" % (", ".join(docs) or "none of docs/architecture, "
                                                             "data-model, runtime, testing"),
                      "git ls-files", "verified"))
    return {"name": "proof_rules", "status": "ok", "items": items, "data": data}


def proof_sections(text, limit=60):
    out, keep = [], False
    for line in text.splitlines():
        if re.match(r"^#{1,4} ", line):
            keep = bool(PROOF_HEADING.search(line))
        if keep:
            out.append(line)
        if len(out) >= limit:
            out.append("[... truncated]")
            break
    return "\n".join(out)


def production(ctx):
    repo, items = ctx["repo"], []
    src = [f for f in ctx["files"] if Path(f).suffix in CODE_EXT and not TEST_PATH.search(f)]
    health, telemetry = [], Counter()
    for f in src[:MAX_TEST_FILES]:
        text = read(repo, f) or ""
        if len(health) < 6 and HEALTH.search(text):
            health.append("%s:%d" % (f, find_line(text, HEALTH.pattern)))
        for m in TELEMETRY.finditer(text):
            telemetry[m.group(0).lower()] += 1
    for dep in ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml"):
        for m in TELEMETRY.finditer((read(repo, dep) or "") if dep in ctx["files"] else ""):
            telemetry[m.group(0).lower()] += 1
    items.append(item("health or version endpoints in source: %s" % (", ".join(health) or
                                                                    "none found"), "keyword scan"))
    items.append(item("telemetry, error-reporting or alerting terms: %s" % (", ".join(
        "%s %d" % kv for kv in telemetry.most_common(8)) or "none"), "keyword scan"))
    deploy = [wf for wf in ctx.get("workflows", {}) if re.search(
        r"deploy|release|publish|pages|cd\b|ship", wf, re.I)]
    sched = ["%s (%s%s)" % (wf, ", ".join(f["schedules"]), "; opens issues" if f["opens_issues"]
                            else "") for wf, f in ctx.get("workflows", {}).items() if f["schedules"]]
    items.append(item("deploy or release workflows: %s" % (", ".join(deploy) or "none"),
                      ".github/workflows"))
    items.append(item("scheduled workflows: %s" % ("; ".join(sched) or "none"), ".github/workflows"))
    container = [f for f in ctx["files"] if re.search(r"(^|/)(Dockerfile[\w.-]*|"
                                                      r"(docker-)?compose[\w.-]*\.ya?ml)$", f)]
    items.append(item("container files: %s" % (", ".join(container[:8]) or "none"),
                      "git ls-files", "verified"))
    installers = sorted({m.group(0) for f in [x for x in ctx["files"] if x.endswith(
        ("package.json", ".yml", ".yaml", ".toml", ".spec", ".iss", ".wxs", ".nsi"))][:400]
        for m in INSTALLER.finditer(read(repo, f) or "")})
    items.append(item("installer tooling: %s" % (", ".join(installers) or "none"), "keyword scan"))
    vendored = sorted({VENDOR_DIR.search(f).group(0) for f in ctx["files"]
                       if VENDOR_DIR.search(f)} | {f for f in ctx["files"]
                                                   if f.endswith((".min.js", ".bundle.js"))})
    items.append(item("vendored copies: %s" % (", ".join(vendored[:10]) or "none"),
                      "git ls-files", "verified"))
    # A build copied into another repo makes that repo's deployment this one's real use.
    out = [f for f in ctx["files"] if VENDOR_OUT.search(f)][:6]
    for f in [x for x in ctx["files"] if x.endswith(".md")][:400]:
        line = find_line(read(repo, f) or "", VENDOR_OUT_TEXT.pattern)
        if line and len(out) < 10:
            out.append("%s:%d" % (f, line))
    items.append(item("copies of this repo's build into another repo or site: %s" % (
        ", ".join(out) or "none found"), "git ls-files + keyword scan"))
    kind = "unknown"
    if deploy or container or health:
        kind = "deployed service or app"
    elif installers:
        kind = "shipped installer"
    elif any(f in ctx["files"] for f in ("setup.py", "pyproject.toml", "Cargo.toml", "go.mod",
                                         "package.json")):
        kind = "library or tool (no deploy, container or health endpoint found)"
    items.append(item("product shape guess: %s" % kind, "derived from the items above"))
    return {"name": "production", "status": "ok", "items": items,
            "data": {"health": health, "deploy": deploy, "kind": kind, "vendored": vendored}}


def _local_defects(ctx):
    """Defect evidence from local history and bug forms alone: (items, data)."""
    repo, items, data = ctx["repo"], [], {}
    # The remote-tracking ref is fresher than a local branch; neither is fetched.
    ref = next((r for r in ("origin/" + ctx["default_branch"], ctx["default_branch"])
                if git(repo, "rev-parse", "--verify", "-q", r)), "HEAD")
    log = git(repo, "log", ref, "-n", "300", "--no-merges", "--format=%H%x09%cs%x09%s",
              "--name-only") or ""
    commits, current = [], None
    for line in log.splitlines():
        if re.match(r"^[0-9a-f]{40}\t", line):
            sha, date, subject = line.split("\t", 2)
            current = {"sha": sha, "date": date, "subject": subject, "files": []}
            commits.append(current)
        elif line.strip() and current:
            current["files"].append(line.strip())
    fixes = [c for c in commits if FIX_SUBJECT.search(c["subject"])]
    with_tests = [c for c in fixes if any(TEST_PATH.search(f) for f in c["files"])]
    reverts = [c for c in commits if c["subject"].startswith(("Revert", "revert"))]
    items.append(item("last %d non-merge commits on %s: %d look like fixes, %d of those touched a "
                      "test file, %d reverts" % (len(commits), ref, len(fixes), len(with_tests),
                                                 len(reverts)), "git log", "verified"))
    for c in (reverts + [f for f in fixes if f not in with_tests and f not in reverts])[:8]:
        items.append(item("%s %s %s%s" % (c["sha"][:10], c["date"], c["subject"][:100],
                                          "" if c in reverts else " (no test file changed)"),
                          "git log", "verified"))
    data.update({"commits": len(commits), "fixes": len(fixes), "fixes_with_tests": len(with_tests),
                 "reverts": len(reverts)})
    forms = [f for f in ctx["files"] if re.match(r"\.github/ISSUE_TEMPLATE/.*bug", f, re.I)]
    for f in forms:
        asks = bool(re.search(r"introduc|which (PR|change|commit)|regress", read(repo, f) or "",
                              re.I))
        items.append(item("bug form %s %s which change introduced the defect" % (
            f, "asks" if asks else "does not ask"), f))
    return items, data


def defects(ctx):
    items, data = _local_defects(ctx)
    host = ctx["host"]
    if not host:
        out = unavailable("defects", ctx["host_reason"])
        out["items"], out["data"] = items, data
        return out
    labels, _, labels_error = host.get_all("{repo}/labels?per_page=100")
    if labels_error and not labels:
        items.append(item("labels unavailable: %s" % labels_error, "api labels", "verified"))
        return {"name": "defects", "status": "ok", "items": items, "data": data}
    buggy = [l.get("name") for l in labels if BUGGY_LABEL.search(l.get("name", ""))]
    seen, refused, partial = {}, [], []
    for name in buggy:
        issues, _, error = host.get_all("{repo}/issues?state=all&per_page=100&labels=%s"
                                        % quote(name, safe=""))
        if error and not issues:
            refused.append((name, error))
            continue
        if error:
            partial.append((name, error))
        for i in issues:
            if "pull_request" not in i:
                seen[i["number"]] = i
        n = sum(1 for i in issues if "pull_request" not in i)
        items.append(item("label %r: %s%d issues%s" % (
            name, "at least " if error else "", n, " (%s)" % error if error else ""),
            "api issues", "verified"))
    # A label whose issues could not be read is unknown, never zero: it leaves the count.
    refusals = ", ".join("%r: %s" % r for r in refused[:10])
    if buggy and len(refused) == len(buggy):
        out = unavailable("defects", "issues: refused for all %d defect labels (%s)" % (
            len(buggy), refusals))
        out["items"], out["data"] = items, dict(data, issues_unavailable=buggy)
        return out
    if refused:
        items.append(item("issues unavailable for %d defect labels, not counted: %s" % (
            len(refused), refusals), "api issues", "verified"))
    traced = [i for i in seen.values() if INTRODUCED.search(i.get("body") or "")]
    hunts = Counter((i.get("created_at") or "")[:10] for i in seen.values()
                    if re.search(r"hunt", " ".join([i.get("title") or ""] + [
                        l.get("name", "") for l in i.get("labels") or []]), re.I))
    scope = (" under %d of %d defect labels" % (len(buggy) - len(refused), len(buggy))
             if refused else "")
    # Lists read only in part make every count below a lower bound.
    gaps = (["labels %s" % labels_error] if labels_error else []) + [
        "%r issues %s" % p for p in partial]
    lower = "; lower bounds, read in part: %s" % "; ".join(gaps) if gaps else ""
    items.append(item("%s%d defect-labelled issues%s; %d name the change that introduced them; "
                      "open %d%s" % ("at least " if gaps else "", len(seen), scope, len(traced),
                                     sum(1 for i in seen.values() if i.get("state") == "open"),
                                     lower), "api issues", "verified"))
    if hunts:
        items.append(item("bug-hunt issues by day: %s%s" % (", ".join(
            "%s %d" % kv for kv in sorted(hunts.items())[-6:]), lower), "api issues",
            "verified"))
    for i in sorted(seen.values(), key=lambda i: i.get("created_at") or "", reverse=True)[:8]:
        items.append(item("#%s %s %s: %s" % (i["number"], (i.get("created_at") or "")[:10],
                                             i.get("state"), (i.get("title") or "")[:100]),
                          "api issues", "verified"))
    data.update({"defect_issues": len(seen), "traced": len(traced), "bug_hunt_days": dict(hunts),
                 "issues_unavailable": [n for n, _ in refused],
                 "issues_incomplete": [n for n, _ in partial], "labels_incomplete": labels_error})
    return {"name": "defects", "status": "ok", "items": items, "data": data}


COLLECTORS = (repo_facts, ci_config, ci_runs, protection, merged_prs, test_inventory, oracles,
              proof_rules, production, defects)


def default_branch(repo, meta):
    """The default branch and where it came from: `meta`, the host's repository metadata, when
    it names one, else a local guess. Pass meta=None when the host was not read."""
    if meta and meta.get("default_branch"):
        return meta["default_branch"], "host"
    ref = git(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if ref and ref.strip():
        name, source = ref.strip().split("/", 1)[-1], "local origin/HEAD"
    else:
        name = next((n for n in ("main", "master", "trunk")
                     if git(repo, "rev-parse", "--verify", "-q", n)), None)
        source = "local branch name"
        if not name:
            name = (git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD").strip()
            source = "local HEAD"
    return name, source + ("; not confirmed by the host" if meta is not None else "")


def collect(repo, slug=None, no_remote=False, runs=100, prs=20, runner=None, gh=None):
    repo = checkout_root(repo) or Path(repo).resolve()
    reason = None
    if no_remote:
        slug, reason = None, "skipped with --no-remote"
    elif not slug:
        slug = github_slug((git(repo, "remote", "get-url", "origin") or "").strip())
        if not slug:
            url = (git(repo, "remote", "get-url", "origin") or "").strip()
            reason = ("no remote" if not url else
                      "remote is not on GitHub; no host collector for it yet")
    host = Host(slug, runner, gh) if slug else None
    meta = None
    if host:
        # Read once: a second read that is refused must not swap in a local guess.
        meta, error = host.get("{repo}")
        if error:
            reason, host, meta = "%s: %s" % (slug, error), None, None
        else:
            meta = meta or {}
    files = tracked_files(repo)
    ctx = {"repo": repo, "files": files, "links": linked_files(repo, files), "slug": slug,
           "host": host, "host_reason": reason, "runs": runs, "prs": prs}
    ctx["default_branch"], branch_source = default_branch(repo, meta)
    results = []
    for fn in COLLECTORS:
        result = fn(ctx)
        if fn is ci_config:
            ctx["workflows"] = result["data"]["workflows"]
        results.append(result)
    return {"repo": slug.split("/")[1] if slug else repo.name, "remote": slug, "host_evidence": "available" if host else
            "unavailable (%s)" % reason, "default_branch": ctx["default_branch"],
            "default_branch_source": branch_source, "collectors": results}


def render_md(evidence):
    out = ["# Evidence for %s" % evidence["repo"], "",
           "- Remote: %s" % (evidence["remote"] or "none"),
           "- Host evidence: %s" % evidence["host_evidence"],
           "- Default branch: %s (from %s)" % (evidence["default_branch"],
                                                evidence["default_branch_source"]), "",
           "Basis: `verified` = observed in a system's actual state (host API, CI results, git "
           "history); `read` = a file in the repo says so.", ""]
    for c in evidence["collectors"]:
        out.append("## %s%s" % (c["name"], "" if c["status"] == "ok" else
                                " (unavailable: %s)" % c.get("reason")))
        for i in c["items"]:
            claim = i["claim"].replace("\n", "\n    ")
            out.append("- [%s] %s  (%s)" % (i["basis"], claim, i["source"]))
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repo")
    ap.add_argument("--remote")
    ap.add_argument("--no-remote", action="store_true")
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--prs", type=int, default=20)
    ap.add_argument("--gh")
    ap.add_argument("--format", choices=("json", "md"), default="json")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    repo = checkout_root(args.repo)
    if repo is None:
        print("collect: %s is not in a git checkout" % args.repo, file=sys.stderr)
        return 2
    if startup_bytecode(repo):
        print("collect: %s" % startup_bytecode(repo), file=sys.stderr)
        return 2
    if args.out and unsafe_output(args.out, repo):
        print("collect: --out must be outside the audited repo (report mode is read-only): %s"
              % unsafe_output(args.out, repo), file=sys.stderr)
        return 2
    if args.remote and not re.match(r"^[\w.-]+/[\w.-]+$", args.remote):
        print("collect: --remote must be OWNER/NAME", file=sys.stderr)
        return 2
    try:
        gh = shlex.split(args.gh) if args.gh else None
    except ValueError as e:
        print("collect: --gh: %s" % e, file=sys.stderr)
        return 2
    evidence = collect(repo, args.remote, args.no_remote, max(1, min(args.runs, 200)),
                       max(0, min(args.prs, 50)), gh=gh)
    text = json.dumps(evidence, indent=1, default=list) if args.format == "json" else \
        render_md(evidence)
    if args.out:
        write_outside(Path(args.out), text + "\n", repo)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


def checkout_root(path):
    """The top of the checkout holding path, resolved, or None outside one. A subdirectory
    stands for its whole checkout, so every collector and boundary check sees the same tree."""
    top = git(Path(path).resolve(), "rev-parse", "--show-toplevel")
    return Path(top.strip()).resolve() if top and top.strip() else None


def inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def startup_bytecode(root):
    """Why interpreter startup may have written bytecode inside root, or None. Startup runs
    before a script's first line, so only `python -B` (or PYTHONDONTWRITEBYTECODE) stops it."""
    prefix = getattr(sys, "pycache_prefix", None)
    if sys.flags.dont_write_bytecode or not prefix or not inside(Path(prefix), root):
        return None
    return ("PYTHONPYCACHEPREFIX (%s) is inside the audited repo, so interpreter startup may "
            "already have written bytecode there. Run with `python -B`, or unset it" % prefix)


def unsafe_output(path, root):
    """Why writing path could change something inside root, or None. A file with other hard
    links is refused: the other link may be inside root, and replacing this one would still
    change that file's link count."""
    path = Path(path)
    if inside(path, root) or inside(path.parent, root):
        return "%s resolves inside the audited repo" % path
    try:
        if os.lstat(str(path)).st_nlink > 1:
            return "%s has other hard links, which may be inside the audited repo" % path
    except OSError:
        pass
    return None


def write_outside(path, text, root):
    """Write text to path, which unsafe_output must pass. The text goes to a new file created
    beside path, which then replaces path's directory entry: an existing file is never written
    through or truncated."""
    path = Path(path)
    problem = unsafe_output(path, root)
    if problem:
        raise ValueError(problem)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)  # mkstemp makes it owner-only; give it a new file's mode
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


if __name__ == "__main__":
    sys.exit(main())
