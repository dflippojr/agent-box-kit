"""Box profiles: which one a repo has chosen, and each profile file checked. Stdlib only; Python
3.8+. Not a script: box/profiles/profile.py (the CLI, whose docstring states the rules) and
box-bootstrap's bootstrap.py import it from box/lib (issue #36). The profile files are the JSON
files in box/profiles.

load(repo) returns the profile as a dict, or None when unset, and raises ProfileError for
anything invalid. load_profile(name) reads one profile by name; chosen(repo) the name in
`.box-profile`; problems(data, name) what is wrong with a parsed profile file.
"""
import json
from pathlib import Path

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
CHOICE = ".box-profile"
# One key per row of box/STANDARD.md's "Host-agnostic mechanisms" table, in table order.
MECHANISMS = ["required_checks", "judge_protection", "worker_identity", "owner_labels",
              "tamper_guard_lint", "scheduled_judges"]
COLUMNS = ["github", "elsewhere", "none"]  # On GitHub, Elsewhere, No hosted VCS
FIELDS = {
    "name": None,  # must equal the file name
    "model_access": {"provider": ["any", "subscription", "api", "bedrock", "other"],
                     "second_family": ["yes", "no", "unknown"]},
    "source_control": ["github", "other", "none", "unknown"],
    "ci_host": ["github", "other", "none", "unknown"],
    "ide": ["any", "none", "other"],
    "mechanisms": dict((key, COLUMNS) for key in MECHANISMS),
}


class ProfileError(Exception):
    """An invalid `.box-profile` or profile file."""


def names():
    """Profile names available, from the JSON files next to this script."""
    return sorted(p.stem for p in PROFILES.glob("*.json"))


def problems(data, name):
    """What is wrong with a parsed profile file called `name`.json, as a list of strings."""
    if not isinstance(data, dict):
        return ["%s.json: not a JSON object" % name]
    out = []

    def walk(value, spec, where):
        if spec is None:
            if value != name:
                out.append("%s: %r does not match the file name %r" % (where, value, name))
        elif isinstance(spec, dict):
            if not isinstance(value, dict):
                out.append("%s: not an object" % where)
                return
            for key in sorted(set(spec) - set(value)):
                out.append("%s.%s: missing" % (where, key))
            for key in sorted(set(value) - set(spec)):
                out.append("%s.%s: not a profile field" % (where, key))
            for key in spec:
                if key in value:
                    walk(value[key], spec[key], "%s.%s" % (where, key))
        elif value not in spec:
            out.append("%s: %r is not one of %s" % (where, value, ", ".join(spec)))

    for key in sorted(set(FIELDS) - set(data)):
        out.append("%s: missing" % key)
    for key in sorted(set(data) - set(FIELDS)):
        out.append("%s: not a profile field" % key)
    for key in FIELDS:
        if key in data:
            walk(data[key], FIELDS[key], key)
    return out


def load_profile(name):
    """The profile called `name`, checked. Raises ProfileError."""
    if name not in names():
        raise ProfileError("unknown profile %r; known: %s" % (name, ", ".join(names())))
    path = PROFILES / (name + ".json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ProfileError("%s: unreadable: %s" % (path.name, exc))
    found = problems(data, name)
    if found:
        raise ProfileError("%s is invalid:\n  %s" % (path.name, "\n  ".join(found)))
    return data


def chosen(repo):
    """The name in REPO/.box-profile, or None if there is no such file. Raises ProfileError."""
    path = Path(repo) / CHOICE
    if path.is_symlink():
        raise ProfileError("%s is a symlink; write the profile name into the file itself" % path)
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProfileError("%s: unreadable: %s" % (path, exc))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ProfileError("%s is not UTF-8 text" % path)
    for ending in ("\r\n", "\n"):
        if text.endswith(ending):
            text = text[:-len(ending)]
            break
    if not text:
        raise ProfileError("%s is empty; write one of: %s" % (path, ", ".join(names())))
    if text != text.strip() or len(text.split()) != 1:
        raise ProfileError("%s must hold exactly one profile name and an optional trailing "
                           "newline; write one of: %s" % (path, ", ".join(names())))
    if text not in names():
        raise ProfileError("%s names unknown profile %r; known: %s"
                           % (path, text[:40], ", ".join(names())))
    return text


def load(repo):
    """REPO's profile as a dict, or None when unset. Raises ProfileError."""
    name = chosen(repo)
    return None if name is None else load_profile(name)
