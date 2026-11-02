"""Run one agent session for skill-eval: isolated, in a scratch workspace, with one version of the
skill installed, under a cost cap; then read what it did and grade the deterministic checks.
Stdlib only. Imported by skill_eval.py; it has no command line of its own.

Isolation is box-audit's (../../box-audit/scripts/judge.py): the session gets a new empty home
holding only the skill under test and any --copy-home login, a new working directory holding only
the task's fixture files, and an environment reduced to judge.py's allowlist plus --keep-env.
Both are deleted afterwards. It isolates startup context; it is not a filesystem sandbox.

A profile (JSON, see ../profiles/) says how to drive one agent CLI:
  command      argv (a list of strings) for a non-interactive session that reads the prompt on
               stdin
  budget_args  argv appended with {budget} filled in: the CLI's own per-session spend cap
               (required)
  model_args   appended with {model} when a model is given
  allow_args   appended with {allow}, the task's allowed tools joined by allow_join (default ",")
  default_allow  tools allowed when a task names none
  judge_args   appended for judge sessions (for example, no tools)
  skills_dir   where the CLI looks for user skills, relative to its home
  result       {"match": {...}, "field": "a.b"}: the event holding the final reply, or "stdout"
  cost         the event holding the session's spend in USD (required); a value that is not a
               finite, nonnegative number counts as unreadable
  commands     list of event specs whose field is a shell command the agent asked to run, each
               with "id": the field holding the request's ID
  command_results  {"match", "id", "output", "error", "denied"}: the event holding a request's
               result, joined to it by ID. A true "error" field means the command ran and failed;
               output matching the "denied" regex means it never ran. Required with commands: a
               request is not an execution.
  command_denials  list of event specs whose field is the ID of a request that was refused
  skill_used   list of event specs that show the skill was picked; "contains" (default "{skill}")
               must appear in the field

load_profile reports a profile that is not a JSON object, lacks a required field, or gives
`command` or `budget_args` as anything but a list of strings; skill_eval.py then exits 2 before
any session starts.

Events are the JSON objects in the CLI's stdout (one document, or one per line), searched at any
depth. When several match, the last one wins for result and cost.

Each command in a record has a status: "ran", "failed" (ran, and its result was an error), "denied"
(refused, never ran) or "no result". command_run counts only commands that ran (or ran and
failed); command_not_run fails on any request, refused or not.

Budgets are whole cents, at least 0.01 USD (usd()): the CLI is given two decimals, so the amount
reserved, passed and recorded is the same number.
"""
import difflib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "box-audit" / "scripts"))
import judge as iso  # noqa: E402  box-audit's isolation: empty home, reduced env, safe work root

PREFIX = "skill-eval-run-"
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", ".venv"}
FILE_LIMIT = 4000   # characters of each changed file shown to the judge
FILES_SHOWN = 20
OUTPUT_LIMIT = 1500  # characters of each command's output kept, from the end
EXECUTED = ("ran", "failed")
CENT = Decimal("0.01")
CHECKS = {
    "file_exists": ("path",), "file_absent": ("path",), "file_unchanged": ("path",),
    "file_contains": ("path", "pattern"), "file_not_contains": ("path", "pattern"),
    "output_contains": ("pattern",), "output_not_contains": ("pattern",),
    "command_run": ("pattern",), "command_not_run": ("pattern",),
    "exit_zero": ("command",),
}


def strings(value):
    return isinstance(value, list) and all(isinstance(a, str) for a in value)


def load_profile(path):
    """Return (profile, problems)."""
    try:
        profile = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, ["profile %s: %s" % (path, e)]
    if not isinstance(profile, dict):
        return None, ["profile %s: must be a JSON object" % path]
    problems = []
    for key in ("command", "budget_args", "skills_dir", "result", "cost"):
        if not profile.get(key):
            problems.append("profile lacks `%s`" % key)
    for key in ("command", "budget_args"):
        if profile.get(key) and not strings(profile[key]):
            problems.append("profile `%s` must be a non-empty list of strings" % key)
    budget_args = profile.get("budget_args") or []
    if strings(budget_args) and "{budget}" not in " ".join(budget_args):
        problems.append("profile budget_args has no {budget}: every session needs a cost cap "
                        "the CLI enforces")
    for key in ("result", "cost"):
        spec = profile.get(key)
        if spec and spec != "stdout" and not (isinstance(spec, dict) and spec.get("field")):
            problems.append("profile `%s` must be \"stdout\" or {\"match\": ..., \"field\": ...}"
                            % key)
    if profile.get("cost") == "stdout":
        problems.append("profile `cost` must name an event field: spend cannot be read from text")
    if profile.get("commands"):
        results = profile.get("command_results")
        if not (isinstance(profile["commands"], list)
                and all(isinstance(c, dict) and c.get("id") for c in profile["commands"])
                and isinstance(results, dict) and results.get("id")):
            problems.append("profile `commands` need an `id` and `command_results` with an `id`: "
                            "a request is not an execution")
        elif results.get("denied"):
            try:
                re.compile(results["denied"])
            except (re.error, TypeError) as e:
                problems.append("profile `command_results.denied` is not a regex: %s" % e)
    return profile, problems


def usd(value):
    """A budget as a float of whole cents, or raise ValueError. One normalized value is used for
    the reservation, the CLI's argument, the record and the charge when spend is unreadable."""
    try:
        d = Decimal(str(value).strip())
        if not d.is_finite() or d < CENT or not math.isfinite(float(d)):
            raise ValueError("%r: must be a finite amount of at least 0.01 USD" % (value,))
        if d != d.quantize(CENT):
            raise ValueError("%r: use whole cents; the agent CLI is given two decimals" % (value,))
    except InvalidOperation:
        raise ValueError("%r is not an amount in USD" % (value,))
    return float(d.quantize(CENT))


def cost_ok(value):
    """True for a spend a session may report: a finite, nonnegative number."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def rel_ok(path):
    p = Path(path)
    return bool(path) and not p.is_absolute() and ".." not in p.parts and not p.drive


def argv_for(profile, model=None, budget=None, allow=None, judge=False):
    def fill(args, **values):
        out = []
        for a in args:
            for k, v in values.items():
                a = a.replace("{%s}" % k, v)
            out.append(a)
        return out
    argv = list(profile["command"])
    argv += fill(profile["budget_args"], budget="%.2f" % usd(budget))
    if model:
        argv += fill(profile.get("model_args", []), model=model)
    if judge:
        argv += list(profile.get("judge_args", []))
    else:
        tools = allow if allow else profile.get("default_allow")
        if tools and profile.get("allow_args"):
            argv += fill(profile["allow_args"], allow=profile.get("allow_join", ",").join(tools))
    return argv


def events(stdout):
    """Every JSON object in stdout, at any depth, in document order."""
    docs = []
    try:
        docs = [json.loads(stdout)]
    except ValueError:
        for line in stdout.splitlines():
            line = line.strip()
            if line[:1] in ("{", "["):
                try:
                    docs.append(json.loads(line))
                except ValueError:
                    pass
    found, stack = [], list(reversed(docs))
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            found.append(x)
            stack.extend(reversed(list(x.values())))
        elif isinstance(x, list):
            stack.extend(reversed(x))
    return found


def field(obj, dotted):
    for part in dotted.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def matching(evts, spec):
    """The events matching every spec["match"] item."""
    match = spec.get("match", {})
    return [e for e in evts if all(field(e, k) == v for k, v in match.items())]


def picked(evts, spec):
    """Values of spec["field"] in the events matching every spec["match"] item."""
    return [v for v in (field(e, spec["field"]) for e in matching(evts, spec)) if v is not None]


def text_of(value):
    """A tool result's content as text: a string, or the text parts of a list of blocks."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text_of(v.get("text") if isinstance(v, dict) else v) for v in value)
    return json.dumps(value)


def read_commands(evts, profile):
    """[{"command", "status", "output"}]: each shell command requested, joined to its result."""
    spec = profile.get("command_results") or {}
    results = {}
    if spec.get("id"):
        for e in matching(evts, spec):
            results[str(field(e, spec["id"]))] = e
    denied = {str(v) for s in profile.get("command_denials", []) for v in picked(evts, s)}
    out = []
    for s in profile.get("commands", []):
        for e in matching(evts, s):
            command = field(e, s["field"])
            if command is None:
                continue
            rid = str(field(e, s["id"])) if s.get("id") else None
            res = results.get(rid)
            output = text_of(field(res, spec["output"])) if res and spec.get("output") else ""
            if rid in denied or (res and spec.get("denied")
                                 and re.search(spec["denied"], output)):
                status = "denied"
            elif res is None:
                status = "no result"
            elif spec.get("error") and field(res, spec["error"]):
                status = "failed"
            else:
                status = "ran"
            out.append({"command": str(command), "status": status,
                        "output": output[-OUTPUT_LIMIT:]})
    return out


def read_session(stdout, profile, skill):
    """(result text or None, cost or None, commands, skill_used or None) from a session's stdout."""
    evts = events(stdout)
    if profile["result"] == "stdout":
        result = stdout if stdout.strip() else None
    else:
        values = [v for v in picked(evts, profile["result"]) if isinstance(v, str)]
        result = values[-1] if values else None
    costs = picked(evts, profile["cost"])
    cost = float(costs[-1]) if costs and cost_ok(costs[-1]) else None
    commands = read_commands(evts, profile)
    used = None
    if profile.get("skill_used"):
        used = False
        for spec in profile["skill_used"]:
            needle = spec.get("contains", "{skill}").replace("{skill}", skill)
            if any(needle in str(v).replace("\\", "/") for v in picked(evts, spec)):
                used = True
    return result, cost, commands, used


def grade(checks, work, result, commands, env=None, has_commands=True, files=None):
    """One {"check", "pass", "detail"} per check. pass is None when it cannot be decided.
    `commands` are read_commands() entries; `files` are the task's fixtures."""
    out = []
    for c in checks:
        kind, ok, detail = c["type"], None, ""
        if kind == "file_unchanged":
            target, before = work / c["path"], (files or {}).get(c["path"])
            if not target.is_file():
                ok, detail = False, "deleted"
            else:
                ok = before is not None and target.read_bytes() == before.encode("utf-8")
                detail = "" if ok else "changed"
        elif kind in ("file_exists", "file_absent"):
            exists = (work / c["path"]).is_file()
            ok = exists if kind == "file_exists" else not (work / c["path"]).exists()
        elif kind in ("file_contains", "file_not_contains"):
            target = work / c["path"]
            text = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
            if text is None:
                ok, detail = kind == "file_not_contains", "no such file"
            else:
                found = re.search(c["pattern"], text, re.M) is not None
                ok = found if kind == "file_contains" else not found
        elif kind in ("output_contains", "output_not_contains"):
            found = re.search(c["pattern"], result or "", re.M) is not None
            ok = found if kind == "output_contains" else not found
        elif kind in ("command_run", "command_not_run"):
            if has_commands:
                hits = [cmd for cmd in commands if re.search(c["pattern"], cmd["command"])]
                if kind == "command_run":
                    ok = any(cmd["status"] in EXECUTED for cmd in hits)
                    detail = "" if ok or not hits else "requested, never ran: %s" % ", ".join(
                        sorted({cmd["status"] for cmd in hits}))
                else:
                    ok = not hits
            else:
                detail = "the profile cannot see commands"
        elif kind == "exit_zero":
            argv = [sys.executable if a == "{python}" else a for a in c["command"]]
            try:
                p = subprocess.run(argv, cwd=str(work), env=env, capture_output=True,
                                   timeout=int(c.get("timeout", 120)))
                ok, detail = p.returncode == 0, "exit %d" % p.returncode
            except (OSError, subprocess.TimeoutExpired) as e:
                ok, detail = False, type(e).__name__
        out.append({"check": c.get("name") or "%s %s" % (kind, c.get("path") or c.get("pattern")
                                                          or " ".join(c.get("command", []))),
                    "pass": ok, "detail": detail})
    return out


def snapshot(work, fixtures):
    """Files the session created or changed, as {path: text}, for the judge."""
    shown = {}
    for top, dirs, files in os.walk(str(work)):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            path = Path(top, name)
            rel = path.relative_to(work).as_posix()
            data = path.read_bytes()
            if fixtures.get(rel, None) is not None and fixtures[rel].encode("utf-8") == data:
                continue
            if len(shown) >= FILES_SHOWN:
                shown["..."] = "(more files not shown)"
                return shown
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = "(binary, %d bytes)" % len(data)
            shown[rel] = text if len(text) <= FILE_LIMIT else text[:FILE_LIMIT] + "\n(cut)"
    return shown


def deletions(work, fixtures):
    """(fixture paths the session deleted, {path: unified diff}) for the deleted and changed
    fixtures, so the judge sees what went as well as what came."""
    deleted, diffs = [], {}
    for rel in sorted(fixtures):
        path = work / rel
        if not path.is_file():
            deleted.append(rel)
            after = ""
        else:
            data = path.read_bytes()
            if data == fixtures[rel].encode("utf-8"):
                continue
            try:
                after = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
        if len(diffs) < FILES_SHOWN:
            diff = "".join(difflib.unified_diff(
                fixtures[rel].splitlines(True), after.splitlines(True), "before/" + rel,
                "after/" + rel))
            diffs[rel] = diff if len(diff) <= FILE_LIMIT else diff[:FILE_LIMIT] + "\n(cut)"
    return deleted, diffs


def scrub(text, root):
    """Replace the run's temporary paths, which differ per run, with stable names."""
    if not text:
        return text
    for raw, name in ((root / "work", "."), (root / "home", "~"), (root, "<run>")):
        for form in {str(raw), str(raw.resolve()), raw.as_posix(), raw.resolve().as_posix()}:
            text = text.replace(form, name)
    return text


def session(profile, prompt, work_root, skill=None, skill_dir=None, files=None, checks=(),
            allow=None, model=None, budget=0.5, timeout=600, keep=(), copy=()):
    """Run one session and return its record. `copy` must already be checked."""
    files = files or {}
    record = {"exit": None, "timed_out": False, "seconds": 0.0, "cost_usd": None, "result": None,
              "commands": [], "skill_used": None, "files": {}, "deleted": [], "diffs": {},
              "checks": [], "error": None, "infra": False}
    try:
        iso.sweep(work_root, max(iso.STALE_SECONDS, 2 * timeout), prefix=PREFIX)
        root = Path(tempfile.mkdtemp(prefix=PREFIX, dir=str(work_root)))
    except OSError as e:
        record.update(error="could not start: %s: %s" % (type(e).__name__, e), infra=True)
        return record
    try:
        # Until the agent starts, a failure is the harness's (infra): it says nothing about the
        # skill, and the report leaves it out instead of counting it against a version.
        try:
            (root / iso.OWN_MARK).write_text("made by skill-eval runner.py; deleted when stale\n")
            home, work = root / "home", root / "work"
            home.mkdir()
            work.mkdir()
            for rel, text in files.items():
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                (work / rel).write_bytes(text.encode("utf-8"))
            if skill_dir:
                shutil.copytree(str(skill_dir), str(home / profile["skills_dir"] / skill))
            env, copied = iso.copy_home(home, copy, keep, Path.home())
            argv = argv_for(profile, model, budget, allow)
            exe = shutil.which(argv[0], path=env.get("PATH"))
            if not exe:
                record["error"], record["infra"] = "command not found: %s" % argv[0], True
                return record
        except (OSError, ValueError) as e:
            record.update(error="could not start: %s: %s" % (type(e).__name__, e), infra=True)
            return record
        start = time.monotonic()
        try:
            p = subprocess.run([exe] + argv[1:], input=prompt.encode("utf-8"), cwd=str(work),
                               env=env, capture_output=True, timeout=timeout)
            stdout, record["exit"] = p.stdout, p.returncode
            stderr = p.stderr
        except subprocess.TimeoutExpired as e:
            stdout, stderr, record["timed_out"] = e.stdout or b"", e.stderr or b"", True
        except OSError as e:
            record.update(error="could not start: %s: %s" % (type(e).__name__, e), infra=True)
            return record
        finally:
            record["seconds"] = round(time.monotonic() - start, 1)
            for original, dst, before in copied:
                iso.write_back(original, dst, before)
        text = stdout.decode("utf-8", errors="replace")
        result, cost, commands, used = read_session(text, profile, skill or "")
        record.update(result=scrub(result, root), cost_usd=cost, skill_used=used,
                      commands=[dict(c, command=scrub(c["command"], root),
                                     output=scrub(c["output"], root)) for c in commands])
        if record["timed_out"]:
            record["error"] = "timed out after %ss" % timeout
        elif result is None:
            record["error"] = "exit %s and no reply: %s" % (
                record["exit"], stderr.decode("utf-8", errors="replace")[-500:].strip())
        record["checks"] = grade(checks, work, result, commands, env,
                                 has_commands=bool(profile.get("commands")), files=files)
        record["files"] = {k: scrub(v, root) for k, v in snapshot(work, files).items()}
        deleted, diffs = deletions(work, files)
        record["deleted"] = deleted
        record["diffs"] = {k: scrub(v, root) for k, v in diffs.items()}
        return record
    finally:
        shutil.rmtree(str(root), ignore_errors=True)
