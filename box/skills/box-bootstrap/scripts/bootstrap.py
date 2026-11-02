#!/usr/bin/env python3
"""Build the repo-level box items a Python repo is missing, on a new branch, until box-audit's
collectors find them all. Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and
3.8 (Linux).

Usage:
  python -B bootstrap.py REPO [--profile NAME] [--stack python] [--base BRANCH]
                         [--branch NAME] [--rounds N]

  REPO          The top of a git checkout with at least one commit and no uncommitted changes
                to tracked files.
  --profile     The box profile (box/profiles/). Default: the one REPO's `.box-profile` names.
                With neither, it stops (exit 2): it never guesses. When given and REPO has no
                `.box-profile`, the file is written on the branch; a different name in it is
                an error.
  --stack       The stack. Only `python` is supported. Default: detected from tracked files;
                any other stack, or none found, stops it (exit 2).
  --base        The default branch (default: guessed locally, as box-audit does). It is never
                written to.
  --branch      The branch the work goes on (default: box-bootstrap). It is created from
                --base if missing, else checked out and added to.
  --rounds N    Build-audit rounds, 1 to 3 (default 3).

Each round runs box-audit's collectors (collect.py, no host), then writes the template files
for each missing item and commits them on the branch. A file that already exists is never
overwritten; only AGENTS.md is added to, with a proof section, when it has none. It never
pushes, merges, changes protection settings or applies labels: those are printed as owner
steps. A mechanism the profile sets to `github` gets the GitHub variant (workflows); `elsewhere`
or `none` gets the host-neutral variant (steps in scripts/ready.py), and `elsewhere` adds the
host-side setting as an owner step.

Before a round writes anything it checks every file it will write: a target behind a link, or
one that resolves outside REPO, refuses the round (exit 3) with nothing written. If writing,
`git add` or `git commit` fails, the round's files are removed again and unstaged. An AGENTS.md
that git does not track (untracked or ignored) is left alone and its item reported missing.

Exit codes: 0 every item bootstrap can create is present; 1 items still missing after the
last round (a verdict; each is printed with the reason); 2 usage error, including no profile or
an unsupported stack; 3 git or I/O error, including a refused target.
"""
import sys
# Before any other import: importing box-audit's collectors must not write bytecode.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TEMPLATES = SKILL / "templates"
BOX = SKILL.parent.parent
sys.path.insert(0, str(BOX / "skills" / "box-audit" / "scripts"))

import collect  # noqa: E402


def load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The stdlib has its own `profile` module, so load box/profiles/profile.py by path.
profiles = load_by_path("box_profile", BOX / "profiles" / "profile.py")

SUPPORTED = ["python"]
STACK_MARKERS = {
    "python": ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "requirements.txt"),
    "javascript": ("package.json",),
    "go": ("go.mod",),
    "rust": ("Cargo.toml",),
    "java": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "ruby": ("Gemfile",),
    "dotnet": (".csproj", ".sln"),
}
MAX_ROUNDS = 3
DOCS = ["docs/README.md", "docs/architecture.md", "docs/data-model.md", "docs/runtime.md",
        "docs/testing.md"]
GATE = "scripts/check.py"
TRACK_RECORD = [
    "D: bug-hunt history. D's 9 needs a dated bug-hunt pass on the default branch and every "
    "escaped defect traced to its PR with a class-level check; a new box has no passes yet.",
    "P: deploy signals. Health and errors an agent can fetch, a silence alarm, vendored-copy "
    "freshness and installer smoke tests come from what the repo deploys or ships, not from "
    "templates (P is n/a for an undeployed library).",
]


class Failure(Exception):
    """An error with its exit code."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code


# ----- git ----------------------------------------------------------------------------------

def git_env():
    """The caller's environment without variables that point git at another repository."""
    return {k: v for k, v in os.environ.items()
            if k.upper() not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}


def git(repo, *args, check=True):
    try:
        p = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=git_env())
    except OSError as exc:
        raise Failure(3, "cannot run git: %s" % exc)
    if check and p.returncode != 0:
        raise Failure(3, "git %s failed: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout.strip() if p.returncode == 0 else None


def tracked_changes(repo):
    return [l for l in (git(repo, "status", "--porcelain", "--untracked-files=no") or "")
            .splitlines() if l.strip()]


# ----- inputs -------------------------------------------------------------------------------

def detect_stacks(files):
    found = set()
    for f in files:
        base = f.rsplit("/", 1)[-1]
        for stack, markers in STACK_MARKERS.items():
            if base in markers or any(m.startswith(".") and base.endswith(m) for m in markers):
                found.add(stack)
        if base.endswith(".py"):
            found.add("python")
    return found


def resolve_stack(arg, files):
    if arg:
        if arg.lower() not in SUPPORTED:
            raise Failure(2, "stack %r is not supported; supported stacks: %s"
                          % (arg, ", ".join(SUPPORTED)))
        return arg.lower()
    found = detect_stacks(files)
    if not found:
        raise Failure(2, "cannot tell the stack from the tracked files; pass --stack (supported "
                         "stacks: %s)" % ", ".join(SUPPORTED))
    if found != {"python"}:
        raise Failure(2, "detected stack(s) %s; supported stacks: %s. A mixed repo whose gate "
                         "is Python can pass --stack python" % (", ".join(sorted(found)),
                                                                 ", ".join(SUPPORTED)))
    return "python"


def resolve_profile(repo, arg):
    """(profile dict, whether .box-profile must be written)."""
    try:
        chosen = profiles.chosen(repo)
        if arg:
            if chosen and chosen != arg:
                raise Failure(2, ".box-profile names %r but --profile is %r; settle on one"
                              % (chosen, arg))
            return profiles.load_profile(arg), chosen is None
    except profiles.ProfileError as exc:
        raise Failure(2, str(exc))
    if chosen is None:
        raise Failure(2, "no profile: REPO has no .box-profile and no --profile was given "
                         "(known: %s). Bootstrap never guesses" % ", ".join(profiles.names()))
    return profiles.load_profile(chosen), False


# ----- what to build ------------------------------------------------------------------------

def variant(profile, mechanism):
    return "github" if profile["mechanisms"][mechanism] == "github" else "neutral"


def plan(profile):
    """Each item: (key, dimension, description, files it needs). Files map a repo path to a
    template path under templates/. Which files depends on the profile's variants."""
    gate, checks = variant(profile, "required_checks"), variant(profile, "tamper_guard_lint")
    scripts = {GATE: "scripts/check.py", "scripts/tamper_guard.py": "scripts/tamper_guard.py",
               "scripts/pr_body_lint.py": "scripts/pr_body_lint.py"}
    ready = dict(scripts, **{"scripts/ready.py": "neutral/ready.py"})
    pr_template = (".github/pull_request_template.md" if checks == "github" else
                   "docs/pull_request_template.md")
    items = [
        ("gate", "G", "CI gate: the one-command gate runs on every change" +
         (", default-branch runs never cancelled" if gate == "github" else
          " through scripts/ready.py"),
         dict({GATE: "scripts/check.py"}, **{".github/workflows/gate.yml": "github/gate.yml"})
         if gate == "github" else ready),
        ("tamper_guard", "G", "Tamper guard on every change" +
         (" (pr-checks workflow)" if checks == "github" else " (step in scripts/ready.py)"),
         dict(scripts, **{".github/workflows/pr-checks.yml": "github/pr-checks.yml"})
         if checks == "github" else ready),
        ("local_gate", "W", "One command runs the whole gate locally (%s)" % GATE,
         {GATE: "scripts/check.py"}),
        ("agents_proof", "W", "AGENTS.md says how to prove a change and names the gate",
         {"AGENTS.md": "AGENTS.md"}),
        ("docs", "W", "Docs layer: index, architecture, data model, runtime, testing",
         dict((d, d) for d in DOCS)),
        ("verify", "W", "Verify skill (stub to fill in)",
         {".agents/skills/verify/SKILL.md": "verify-skill.md"}),
        ("instance", "W", "Disposable-instance contract (stub to fill in)",
         {"docs/disposable-instance.md": "docs/disposable-instance.md"}),
        ("pr_template", "W", "PR template with Proof, Not verified, Gate changes, Closes",
         {pr_template: "pull_request_template.md"}),
        ("pr_body_lint", "W", "PR-body lint on every change" +
         (" (pr-checks workflow)" if checks == "github" else " (step in scripts/ready.py)"),
         dict(scripts, **{".github/workflows/pr-checks.yml": "github/pr-checks.yml"})
         if checks == "github" else ready),
    ]
    return items, pr_template


def render(template, values):
    text = (TEMPLATES / template).read_text(encoding="utf-8").replace("\r\n", "\n")
    for key, value in values.items():
        text = text.replace("@@%s@@" % key, value)
    left = re.search(r"@@[A-Z_]+@@", text)
    if left:
        raise Failure(3, "template %s has an unfilled value %s" % (template, left.group(0)))
    return text


def values(profile, base, project, pr_template):
    gate, checks = variant(profile, "required_checks"), variant(profile, "tamper_guard_lint")
    out = {"DEFAULT_BRANCH": base, "PROJECT": project, "PR_TEMPLATE": pr_template}
    out["MERGE_GATE"] = render("%s/merge-gate.md" % gate, out).strip()
    out["PR_CHECKS"] = render("%s/pr-checks.md" % checks, out).strip()
    out["PROVING"] = render("proving.md", out)
    return out


# ----- what the collectors find -------------------------------------------------------------

def present(repo, profile, evidence):
    """Map item key to (present?, reason), from box-audit's collector evidence."""
    by_name = dict((c["name"], c) for c in evidence["collectors"])
    ci, proof = by_name["ci_config"]["data"], by_name["proof_rules"]["data"]
    workflows = ci["workflows"]
    ready_text = "\n".join(collect.read(repo, f) or ""
                           for f in by_name["protection"]["data"]["ready_scripts"])

    def running(script):
        return [wf for wf, facts in sorted(workflows.items())
                if any(script in cmd for _, _, cmd in facts["runs"])]

    def gate_workflow(wf):
        facts = workflows[wf]
        return ("pull_request" in facts["triggers"] and "push" in facts["triggers"] and
                not any(v.strip().lower() == "true" for _, v in facts["cancel_in_progress"]))

    gh_gate = variant(profile, "required_checks") == "github"
    gh_checks = variant(profile, "tamper_guard_lint") == "github"
    agents = collect.read(repo, "AGENTS.md") or ""
    docs = set(proof.get("docs", []))
    out = {}
    if gh_gate:
        ok = [wf for wf in running(GATE) if gate_workflow(wf)]
        out["gate"] = (bool(ok), "no workflow runs %s on pull_request and push without "
                                 "cancelling default-branch runs" % GATE)
    else:
        out["gate"] = (GATE in ready_text, "no ready script runs %s" % GATE)
    for key, script in (("tamper_guard", "scripts/tamper_guard.py"),
                        ("pr_body_lint", "scripts/pr_body_lint.py")):
        if gh_checks:
            out[key] = (bool(running(script)), "no workflow runs %s" % script)
        else:
            out[key] = (script in ready_text, "no ready script runs %s" % script)
    out["local_gate"] = (any(target == GATE for _, target in ci["local_gate"]),
                         "box-audit finds no local gate at %s" % GATE)
    out["agents_proof"] = (bool(proof.get("proof_excerpt")) and GATE in agents,
                           "AGENTS.md has no proof section naming %s" % GATE)
    out["docs"] = (all(d in docs for d in DOCS), "docs layer lacks %s" % ", ".join(
        d for d in DOCS if d not in docs))
    out["verify"] = (bool(proof.get("verify")), "no verify skill or UI-testing contract")
    out["instance"] = (bool(proof.get("instance_contract")),
                       "no disposable-instance contract")
    full = ["Proof", "Not verified", "Gate changes", "Closes"]
    out["pr_template"] = (any(m == full for m in proof.get("pr_templates", {}).values()),
                          "no PR template mentions %s" % ", ".join(full))
    return out


# ----- building -----------------------------------------------------------------------------

def build(repo, items, found, vals):
    """Plan the files of each missing item that do not exist yet, writing nothing. Returns
    ({repo path: text to write}, {item key: why it could not be built})."""
    writes, stuck = {}, {}
    for key, _, _, files in items:
        if found[key][0]:
            continue
        wrote = False
        for rel, template in sorted(files.items()):
            path = repo / rel
            if rel in writes:
                wrote = True
                continue
            if rel == "AGENTS.md" and path.is_file() and not collect.linked(repo, rel):
                if git(repo, "ls-files", "--error-unmatch", "--", rel, check=False) is None:
                    stuck[key] = ("AGENTS.md is untracked or ignored; bootstrap does not commit "
                                  "it")
                    continue
                text = path.read_text(encoding="utf-8")
                if GATE not in text:
                    sep = "" if text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
                    writes[rel] = text + sep + vals["PROVING"]
                    wrote = True
                continue
            if os.path.lexists(str(path)):
                continue
            if git(repo, "check-ignore", "-q", "--", rel, check=False) is not None:
                stuck[key] = "%s is ignored by git; bootstrap does not force-add it" % rel
                continue
            writes[rel] = render(template, vals)
            wrote = True
        if not wrote and key not in stuck:
            stuck[key] = ("its files exist (%s) but box-audit does not find it: %s; fix by hand"
                          % (", ".join(sorted(files)), found[key][1]))
    return writes, stuck


def check_targets(repo, rels):
    """Refuse the round, before anything is written, if a target sits behind a link or resolves
    outside REPO: writing there would land outside the repo or where git cannot add it."""
    refused = []
    for rel in sorted(rels):
        path = repo / rel
        if collect.linked(repo, rel):
            refused.append("%s (a folder on the way to it is a link)" % rel)
            continue
        try:
            path.resolve().relative_to(repo)
        except ValueError:
            refused.append("%s (it resolves outside the repo)" % rel)
    if refused:
        raise Failure(3, "refusing to write outside the repo or through a link: %s. Nothing was "
                         "written; remove the link or create the files by hand"
                      % "; ".join(refused))


def commit_round(repo, writes, message):
    """Write, add and commit the round's files. If any step fails, put every file and folder
    back as it was and unstage them, so a failed round leaves nothing behind."""
    before, made = [], []
    try:
        for rel, text in sorted(writes.items()):
            path = repo / rel
            before.append((path, path.read_bytes() if path.is_file() else None))
            missing, parent = [], path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            path.parent.mkdir(parents=True, exist_ok=True)
            made += missing
            path.write_bytes(text.encode("utf-8"))
        git(repo, "add", "--", *sorted(writes))
        git(repo, "commit", "-q", "-m", message)
    except (Failure, OSError) as exc:
        git(repo, "reset", "-q", "--", *sorted(writes), check=False)
        for path, old in reversed(before):
            try:
                if old is None:
                    path.unlink()
                else:
                    path.write_bytes(old)
            except OSError:
                pass
        for folder in sorted(made, key=lambda f: len(f.parts), reverse=True):
            try:
                folder.rmdir()
            except OSError:
                pass
        raise Failure(3, "%s; the round's files were removed again" % exc)


def switch_branch(repo, base, branch):
    current = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    if current == branch:
        return "on %s" % branch
    if git(repo, "rev-parse", "--verify", "-q", "refs/heads/%s" % branch, check=False):
        git(repo, "checkout", "-q", branch)
        return "checked out existing %s" % branch
    git(repo, "checkout", "-q", "-b", branch, base)
    return "created %s from %s" % (branch, base)


def owner_steps(profile, base):
    m = profile["mechanisms"]
    steps = ["Review the branch and merge it into %s yourself; bootstrap never merges or pushes."
             % base]
    if m["required_checks"] == "github":
        steps.append("Require the checks `gate`%s on %s (a ruleset or branch protection), "
                     "with the branch up to date, so the head commit is what is judged."
                     % (", `tamper-guard` and `pr-body`" if m["tamper_guard_lint"] == "github"
                        else "", base))
    else:
        if m["required_checks"] == "elsewhere":
            steps.append("In the host, run `python scripts/check.py` in a pipeline on every "
                         "change and require it before merging into %s (protected branch with "
                         "passing pipelines, merge checks or a build-validation policy)." % base)
        steps.append("Until the host enforces it, merge into %s only on `python scripts/ready.py "
                     "--body FILE` exit 0, and write down that merges go through it." % base)
    if m["tamper_guard_lint"] == "github":
        steps.append("Create the label `gate-change-approved` and apply it yourself, only after "
                     "reading a flagged gate change; workers never apply it.")
    else:
        if m["tamper_guard_lint"] == "elsewhere":
            steps.append("In the host, add required pipeline jobs that run "
                         "`python scripts/tamper_guard.py --base <target>` and "
                         "`python scripts/pr_body_lint.py <description file>`.")
        steps.append("Approve a flagged gate change by tagging its head commit yourself: "
                     "`git tag gate-change-approved/<full commit id> <commit>` (sign it with "
                     "`-s` where you can). Workers never create that tag.")
    if m["judge_protection"] == "github":
        steps.append("For G's 10: run pr-checks from the base branch (pull_request_target or a "
                     "required workflow) so a PR cannot rewrite its own judge.")
    elif m["judge_protection"] == "none":
        steps.append("For G's 10: keep a copy of scripts/ready.py, check.py, tamper_guard.py "
                     "and pr_body_lint.py together in one folder outside the repo, and run that "
                     "ready.py from the checkout, so a change cannot rewrite its own judge. "
                     "check.py's test steps still run the checkout's tests.")
    else:
        steps.append("For G's 10: keep the gate's pipeline definition in a protected project "
                     "or path the change cannot edit.")
    steps.append("Workers act under their own identity (%s), never yours."
                 % {"github": "a GitHub App", "elsewhere": "a bot user or service principal",
                    "none": "a separate OS user and git identity"}[m["worker_identity"]])
    return steps


# ----- main ---------------------------------------------------------------------------------

def run(args):
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        raise Failure(2, "%s is not a directory" % args.repo)
    if collect.checkout_root(repo) != repo:
        raise Failure(2, "%s is not the top of a git checkout" % args.repo)
    if not 1 <= args.rounds <= MAX_ROUNDS:
        raise Failure(2, "--rounds must be 1 to %d" % MAX_ROUNDS)
    profile = resolve_profile(repo, args.profile)[0]
    resolve_stack(args.stack, collect.tracked_files(repo))
    if not git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False):
        raise Failure(3, "%s has no commits; commit the project first" % repo)
    base = args.base or collect.default_branch(repo, None)[0]
    base_commit = git(repo, "rev-parse", "--verify", "-q", "%s^{commit}" % base, check=False)
    if not base_commit:
        raise Failure(2, "default branch %r not found; pass --base" % base)
    if args.branch == base:
        raise Failure(2, "--branch must differ from the default branch %s" % base)
    if tracked_changes(repo):
        raise Failure(3, "uncommitted changes to tracked files; commit or stash them first:\n%s"
                      % "\n".join(tracked_changes(repo)))

    print("box-bootstrap: %s, profile %s (%s), stack python" % (
        repo.name, profile["name"], ", ".join("%s %s" % kv
                                              for kv in profile["mechanisms"].items())))
    print("Branch: %s; %s stays at %s" % (switch_branch(repo, base, args.branch), base,
                                          base_commit[:12]))
    resolve_profile(repo, profile["name"])  # an existing branch may record another profile
    write_choice = profiles.chosen(repo) is None
    items, pr_template = plan(profile)
    vals = values(profile, base, repo.name, pr_template)
    stuck = {}
    for n in range(1, args.rounds + 1):
        found = present(repo, profile, collect.collect(repo, no_remote=True))
        missing = [i for i in items if not found[i[0]][0]]
        if not missing and (not write_choice or profiles.chosen(repo)):
            print("Round %d: box-audit finds every item" % n)
            break
        writes, stuck = build(repo, items, found, vals)
        if write_choice and not profiles.chosen(repo):
            writes[profiles.CHOICE] = profile["name"] + "\n"
        written = sorted(writes)
        if not written:
            print("Round %d: nothing left that bootstrap can write" % n)
            break
        check_targets(repo, written)
        commit_round(repo, writes, "box-bootstrap round %d: %s\n\n%s" % (
            n, ", ".join(i[0] for i in missing) or "record the profile",
            "\n".join("- %s" % w for w in written)))
        print("Round %d: missing %s; wrote %s; committed %s" % (
            n, ", ".join(i[0] for i in missing) or "nothing", ", ".join(written),
            git(repo, "rev-parse", "--short=12", "HEAD")))
    found = present(repo, profile, collect.collect(repo, no_remote=True))
    if git(repo, "rev-parse", "%s^{commit}" % base) != base_commit:
        raise Failure(3, "the default branch %s moved during the run" % base)

    print("\nItems, as box-audit's collectors find them:")
    for key, dim, text, _ in items:
        ok, why = found[key]
        print("  [%s] %s  %s%s" % ("x" if ok else " ", dim, text,
                                   "" if ok else "  -- MISSING: %s" % stuck.get(key, why)))
    print("\nFill in before relying on them: AGENTS.md, docs/, .agents/skills/verify/SKILL.md "
          "and docs/disposable-instance.md hold `<...>` placeholders where bootstrap created "
          "them.")
    print("\nTrack record bootstrap cannot create:")
    for line in TRACK_RECORD:
        print("  - %s" % line)
    print("\nOwner steps (bootstrap does none of these):")
    for line in owner_steps(profile, base):
        print("  - %s" % line)
    missing = [key for key, _, _, _ in items if not found[key][0]]
    if missing:
        print("\nBOOTSTRAP_INCOMPLETE: %s" % ", ".join(missing))
        return 1
    print("\nBOOTSTRAP_DONE: every repo-level item bootstrap can create is present on %s"
          % args.branch)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a Python repo's missing box items on a "
                                             "branch.")
    ap.add_argument("repo")
    ap.add_argument("--profile")
    ap.add_argument("--stack")
    ap.add_argument("--base")
    ap.add_argument("--branch", default="box-bootstrap")
    ap.add_argument("--rounds", type=int, default=MAX_ROUNDS)
    args = ap.parse_args(argv)
    try:
        return run(args)
    except Failure as exc:
        print("bootstrap.py: %s" % exc, file=sys.stderr)
        return exc.code
    except OSError as exc:
        print("bootstrap.py: %s" % exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
