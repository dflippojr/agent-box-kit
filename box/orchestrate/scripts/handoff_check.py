#!/usr/bin/env python3
"""Check whether a worker's PR is ready for the owner, against the host rather than the worker's
report. Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux). The rules
are in ../README.md (Handoff).

Usage:
  handoff_check.py --repo OWNER/NAME --pr N [--owner LOGIN] [--owner-labels A,B]
                   [--accept-label NAME] [--gh CMD] [--format text|json]
  handoff_check.py --local REPO --branch NAME --gate-result FILE --body FILE [--findings FILE]
                   [--owner EMAIL] [--owner-key KEY | --trust-unsigned] [--accept-label NAME]
                   [--format text|json]

  --repo, --pr      Host mode: read the PR from GitHub with `gh api` (REST GETs and one GraphQL
                    query, no mutations).
  --owner           Host mode: the owner's login (default: OWNER from --repo). Local mode: the
                    owner's tagger email; without it no acceptance tag counts.
  --owner-labels    Labels only the owner may apply (default gate-change-approved,
                    findings-accepted). Host mode: one applied by anyone else fails the check.
  --accept-label    The owner-only label that accepts open review findings (default
                    findings-accepted).
  --gh CMD          The command that runs gh, split like a shell would (default: `gh` on PATH).
  --local REPO      No-hosted-VCS mode: a git checkout holding --branch.
  --gate-result     A file the gate run wrote: `commit: <full sha>` and `exit: <code>` lines.
  --body            The handoff note, the PR body's equivalent.
  --findings        Review findings as a task list: `- [ ]` open, `- [x]` resolved. Open findings
                    need the owner's annotated tag `<accept-label>/<branch>`: the tag object
                    names that tag and the head commit, and its message names the issue --body
                    closes (`#7`). The ref name alone does not count.
  --owner-key KEY   Local mode: the owner's signing key, as an OpenPGP fingerprint (40 hex
                    digits) or an SSH key fingerprint (SHA256:...). An acceptance tag counts only
                    when its signature verifies with this key; without it, or --trust-unsigned, no
                    tag counts.
  --trust-unsigned  Count an acceptance tag by the tagger email alone, with no signature check.
                    Only for a repo where workers cannot create tags.
  --format          text (default) or json.

Exit codes: 0 ready; 1 not ready (a verdict: each failed item is named); 2 usage error (bad
option, unreadable --gate-result, --body or --findings file); 3 host or git error (gh missing, the
PR, its checks, threads or label history unreadable; the branch not found). Exit 1 never means an
error.
"""
import sys
# Before any other import: no module may write bytecode, which an inherited PYTHONPYCACHEPREFIX
# could put inside an audited checkout, and box/lib gets none beside the helpers.
sys.dont_write_bytecode = True

import os  # noqa: E402

# select.py sits in this folder and shares its name with the standard library module that
# subprocess imports on POSIX. Drop this folder from the import path before importing subprocess.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != HERE]

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import quote  # noqa: E402

# gh's response handling and git's environment, one implementation each for box-audit and
# orchestrate, loaded by path from box/lib in the checkout this file sits in, now that this
# folder is off the import path.
BOX_LIB = Path(__file__).resolve().parents[2] / "lib"


def load_lib(name):
    spec = importlib.util.spec_from_file_location("box_" + name, str(BOX_LIB / (name + ".py")))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gh_read = load_lib("gh_read")
git_env = load_lib("git_env").git_env

DEFAULT_OWNER_LABELS = "gate-change-approved,findings-accepted"
DEFAULT_ACCEPT = "findings-accepted"
GREEN = {"success", "neutral", "skipped"}
FAILED = {"failure", "timed_out", "action_required", "startup_failure", "stale", "error"}
CLOSING = re.compile(r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?):?[ \t]+((?:[\w.-]+/[\w.-]+)?#\d+)",
                     re.I)
PROOF_COLUMNS = ("criterion", "how", "evidence")
# The signing programs `git verify-tag` runs, whatever the checkout's own config names.
SIGNERS = ["-c", "gpg.program=gpg", "-c", "gpg.openpgp.program=gpg", "-c",
           "gpg.x509.program=gpgsm", "-c", "gpg.ssh.program=ssh-keygen"]
# The gpg status keywords that give one signature's result. Only GOODSIG counts.
SIG_RESULTS = {"GOODSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "BADSIG", "ERRSIG"}
THREADS = """query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    reviewThreads(first: 100, after: $after) {
      nodes { isResolved path line comments(first: 1) { nodes { author { login } } } }
      pageInfo { hasNextPage endCursor } } } } }"""


class HostError(Exception):
    """The host or git refused a read the verdict needs: exit 3."""


class UsageError(Exception):
    """Exit 2."""


# ----- PR body: proof table and closing reference --------------------------------------------

def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", (text or "").replace("\r\n", "\n"), flags=re.S)


def section(text, heading, level):
    """The text under a `heading` of `level` hashes, up to the next heading of that level or
    higher, or None when the heading is absent."""
    m = re.search(r"^%s[ \t]+%s[ \t]*$" % ("#" * level, re.escape(heading)), text, re.M | re.I)
    if not m:
        return None
    end = re.search(r"^#{1,%d}[ \t]" % level, text[m.end():], re.M)
    return text[m.end():m.end() + end.start()] if end else text[m.end():]


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def proof_problems(body):
    """The PR body's proof against the rule in the README: a `## Proof` section holding a table
    with Criterion, How verified and Evidence columns and at least one row with no empty cell,
    then non-empty `### Not verified` and `### Gate changes` sections."""
    text = strip_comments(body)
    proof = section(text, "Proof", 2)
    if proof is None:
        return ["no '## Proof' section"]
    out = []
    lines = [l for l in proof.splitlines()]
    start = next((i for i, l in enumerate(lines) if l.strip().startswith("|")), None)
    if start is None:
        out.append("no table under '## Proof'")
    else:
        table = []
        for line in lines[start:]:
            if not line.strip().startswith("|"):
                break
            table.append(cells(line))
        header = [c.lower() for c in table[0]]
        if not all(any(col in h for h in header) for col in PROOF_COLUMNS):
            out.append("proof table header needs Criterion, How verified and Evidence columns")
        if len(table) < 2 or not all(re.match(r"^:?-+:?$", c) for c in table[1]):
            out.append("proof table has no separator row")
        rows = table[2:]
        if not rows:
            out.append("proof table has no rows")
        for n, row in enumerate(rows, 1):
            if len(row) != len(table[0]) or not all(row):
                out.append("proof table row %d has an empty or missing cell" % n)
    for name in ("Not verified", "Gate changes"):
        part = section(proof, name, 3)
        if part is None:
            out.append("no '### %s' section under '## Proof'" % name)
        elif not part.strip():
            out.append("'### %s' is empty (write 'none' if there is nothing)" % name)
    return out


def closing_refs(body):
    return [m.group(0) for m in CLOSING.finditer(strip_comments(body))]


# ----- host mode -----------------------------------------------------------------------------

class Host:
    """Read-only `gh api` calls. Errors are returned, never raised."""

    def __init__(self, gh=None, runner=None):
        self.gh = gh or ([shutil.which("gh")] if shutil.which("gh") else None)
        self.runner = runner or self._gh

    def _gh(self, args):
        if not self.gh:
            return None, "gh CLI not found"
        return gh_read.read(self.gh + args, git_env())

    def get(self, path):
        return self.runner(["api", "-X", "GET", "-H", "Accept: application/vnd.github+json",
                            path])

    def must(self, path, what):
        body, error = self.get(path)
        if error:
            raise HostError("%s: %s" % (what, error))
        return body

    def pages(self, path, what, key=None):
        """Every entry of a per_page=100 list, read to the last page with gh_read.paged."""
        def fetch(page):
            body = self.must("%s&page=%d" % (path, page), what)
            return ((body or {}).get(key) or [] if key else body or []), None
        entries, error = gh_read.paged(fetch)
        if error:
            raise HostError("%s: %s" % (what, error))
        return entries

    def threads(self, slug, number):
        owner, name = slug.split("/")
        nodes, after = [], None
        for _ in range(gh_read.MAX_PAGES):
            args = ["api", "graphql", "-f", "query=" + THREADS, "-f", "owner=" + owner,
                    "-f", "name=" + name, "-F", "number=%d" % number]
            body, error = self.runner(args + (["-f", "after=" + after] if after else []))
            try:
                found = body["data"]["repository"]["pullRequest"]["reviewThreads"]
            except (TypeError, KeyError):
                raise HostError("review threads: %s" % (error or "unexpected response"))
            nodes += found["nodes"]
            if not found["pageInfo"]["hasNextPage"]:
                return nodes
            after = found["pageInfo"]["endCursor"]
        raise HostError("review threads: more than %d pages" % gh_read.MAX_PAGES)


def check_runs(host, slug, sha):
    """(name, state) for every check on the commit: the latest run per check name, then every
    commit status context. State is green, pending, failed or cancelled."""
    runs = host.pages("repos/%s/commits/%s/check-runs?per_page=100" % (slug, sha), "check runs",
                      key="check_runs")
    latest = {}
    for run in runs:
        if run["name"] not in latest or run.get("id", 0) > latest[run["name"]].get("id", 0):
            latest[run["name"]] = run
    out = []
    for name, run in sorted(latest.items()):
        conclusion = run.get("conclusion")
        if run.get("status") != "completed" or conclusion is None:
            state = "pending"
        elif conclusion in GREEN:
            state = "green"
        elif conclusion == "cancelled":
            state = "cancelled"
        else:
            state = "failed"
        out.append((name, state, run.get("status") if state == "pending" else conclusion))
    status = host.must("repos/%s/commits/%s/status?per_page=100" % (slug, sha), "commit status")
    for s in (status or {}).get("statuses") or []:
        state = {"success": "green", "pending": "pending"}.get(s.get("state"), "failed")
        out.append((s["context"], state, s.get("state")))
    return out


def checks_item(found):
    if not found:
        return ["no checks reported on the head commit"]
    return ["%s: %s (%s)" % (state, name, detail)
            for name, state, detail in found if state != "green"]


def head_time(host, pr):
    """When the head commit reached the host: the latest push of it to the head branch, from the
    repository activity list. None when it cannot be read."""
    repo = (pr["head"].get("repo") or {}).get("full_name")
    if not repo:
        return None, "head repository unknown"
    body, error = host.get("repos/%s/activity?ref=%s&per_page=100" % (
        repo, quote("refs/heads/" + pr["head"]["ref"], safe="/")))
    if error:
        return None, "push history: %s" % error
    times = [a["timestamp"] for a in body or [] if a.get("after") == pr["head"]["sha"]]
    return (max(times), None) if times else (None, "no push of the head commit in the history")


def label_history(events, name):
    return [e for e in events if e.get("event") in ("labeled", "unlabeled")
            and (e.get("label") or {}).get("name") == name]


def owner_label_counts(host, pr, events, name, owner):
    """Whether the owner-only label `name` counts: on the PR now, last applied by the owner, and
    after the head commit was pushed. Returns (counts, reason)."""
    if name not in [l["name"] for l in pr.get("labels") or []]:
        return False, "%s is not on the PR" % name
    applied = [e for e in label_history(events, name) if e["event"] == "labeled"]
    if not applied:
        return False, "%s has no label event" % name
    last = applied[-1]
    actor = (last.get("actor") or {}).get("login")
    if (actor or "").lower() != owner.lower():
        return False, "%s was applied by %s, not the owner" % (name, actor)
    pushed, why = head_time(host, pr)
    if pushed is None:
        return False, "%s cannot be tied to the head commit (%s)" % (name, why)
    if last["created_at"] <= pushed:
        return False, "%s was applied at %s, before the head commit was pushed at %s" % (
            name, last["created_at"], pushed)
    return True, "%s applied by the owner after the head commit" % name


def check_pr(slug, number, owner=None, owner_labels=None, accept=DEFAULT_ACCEPT, gh=None,
             runner=None):
    """The verdict on a PR: {"target", "head", "ready", "items": [{name, ok, problems}]}."""
    host = Host(gh, runner)
    owner = owner or slug.split("/")[0]
    owner_labels = owner_labels or DEFAULT_OWNER_LABELS.split(",")
    pr = host.must("repos/%s/pulls/%d" % (slug, number), "pull request")
    sha = pr["head"]["sha"]
    events = host.pages("repos/%s/issues/%d/events?per_page=100" % (slug, number),
                        "label history")
    items = [("checks", checks_item(check_runs(host, slug, sha)))]

    open_threads = [t for t in host.threads(slug, number) if not t["isResolved"]]
    review = []
    if open_threads:
        counts, why = owner_label_counts(host, pr, events, accept, owner)
        if not counts:
            where = ["%s:%s" % (t.get("path"), t.get("line")) for t in open_threads[:5]]
            review = ["%d unresolved review thread%s (%s) and not owner-accepted: %s" % (
                len(open_threads), "" if len(open_threads) == 1 else "s", ", ".join(where), why)]
    items.append(("review", review))

    misuse = ["%s applied by %s, not the owner" % (e["label"]["name"],
                                                   (e.get("actor") or {}).get("login"))
              for name in owner_labels for e in label_history(events, name)
              if e["event"] == "labeled"
              and ((e.get("actor") or {}).get("login") or "").lower() != owner.lower()]
    items.append(("owner-only labels", misuse))
    items.append(("proof", proof_problems(pr.get("body"))))
    items.append(("closing reference", [] if closing_refs(pr.get("body")) else
                  ["no closing reference (Closes #n) in the PR body"]))
    return verdict("%s#%d" % (slug, number), sha, items)


# ----- no-hosted-VCS mode --------------------------------------------------------------------

def git(repo, *args):
    try:
        p = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=git_env())
    except OSError as e:
        raise HostError("git not runnable: %s" % e)
    return p.returncode, p.stdout.strip()


def read_file(path, what):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise UsageError("%s: %s" % (what, e))


def gate_problems(text, head):
    fields = dict((k.strip().lower(), v.strip()) for k, _, v in
                  (l.partition(":") for l in text.splitlines() if ":" in l))
    if fields.get("commit", "").lower() != head:
        return ["the gate result is for commit %s, not the head %s" % (
            fields.get("commit") or "(none)", head)]
    if fields.get("exit") != "0":
        return ["the gate exited %s" % (fields.get("exit") or "(no exit line)")]
    return []


def gpg_keys(status):
    """The signing and primary key fingerprints in gpg `status` lines, when they report one
    signature, GOODSIG and one VALIDSIG. Any other result (EXPKEYSIG, EXPSIG, REVKEYSIG, BADSIG,
    ERRSIG), a second signature or a missing line counts for nothing: gpg prints VALIDSIG for a
    signature by an expired or revoked key too."""
    lines = re.findall(r"^\[GNUPG:\] (\S+) ?(.*)$", status, re.M)
    words = [k for k, _ in lines]
    valid = [v.split() for k, v in lines if k == "VALIDSIG"]
    results = [k for k in words if k in SIG_RESULTS]
    if results != ["GOODSIG"] or len(valid) != 1 or words.count("NEWSIG") > 1:
        return set()
    return set(f.upper() for f in valid[0][:1] + valid[0][9:10])


def signing_keys(repo, oid):
    """The fingerprints of the keys that made a good signature on the tag object `oid`: OpenPGP
    signing and primary key fingerprints from `git verify-tag --raw` (see gpg_keys), or the SSH
    key fingerprint. The signing programs are pinned, so a checkout's own config cannot swap in
    one that reports any key. Git for Windows 2.56 exits 0 for an EXPKEYSIG signature, so the
    status lines decide; a non-zero exit still counts for nothing."""
    try:
        p = subprocess.run(["git", "-C", str(repo)] + SIGNERS + ["verify-tag", "--raw", oid],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=git_env())
    except OSError as e:
        raise HostError("git not runnable: %s" % e)
    if p.returncode != 0:
        return set()
    out = p.stdout + p.stderr
    if re.search(r"^\[GNUPG:\] ", out, re.M):
        return gpg_keys(out)
    return set(re.findall(r'^Good "git" signature (?:for .* )?with \S+ key (SHA256:\S+)$', out,
                          re.M))


def key_id(key):
    """An OpenPGP fingerprint in upper case without spaces; an SSH fingerprint as given."""
    return key if key.startswith("SHA256:") else re.sub(r"\s", "", key).upper()


def tag_fields(repo, oid):
    """The header fields of the tag object `oid` ({name: [values]}) and its message, the part a
    signature covers: everything before the first `-----BEGIN ` line after the header."""
    code, raw = git(repo, "cat-file", "tag", oid)
    if code != 0:
        return None, None
    header, _, message = raw.partition("\n\n")
    fields = {}
    for line in header.splitlines():
        name, _, value = line.partition(" ")
        fields.setdefault(name, []).append(value)
    return fields, re.split(r"^-----BEGIN ", message, maxsplit=1, flags=re.M)[0]


def names_issue(message, refs):
    """Whether `message` names one of the issue references `refs` (`#7`, `owner/app#7`) as
    written, and not as part of a longer reference."""
    return any(re.search(r"(?<![\w/#.-])%s(?!\d)" % re.escape(r), message, re.I) for r in refs)


def accept_tag(repo, branch, head, accept, owner, owner_key, trust_unsigned, issues):
    """Whether the owner's acceptance tag `<accept>/<branch>` names the head commit and, unless
    `trust_unsigned`, is signed with `owner_key`. Everything is read from the one tag object the
    ref points to, since a worker can point the ref at any tag: the object's own name must be the
    acceptance tag's and its message must name one of `issues`, the issues the handoff note
    closes. The tagger is whoever made the tag says it is, and `git verify-tag` passes for any key
    the verifier holds, so only the key binds the tag to the owner."""
    tag = "%s/%s" % (accept, branch)
    code, oid = git(repo, "rev-parse", "--verify", "--quiet", "refs/tags/" + tag)
    if code != 0 or not oid:
        return False, "no tag %s" % tag
    _, kind = git(repo, "cat-file", "-t", oid)
    if kind != "tag":
        return False, "tag %s is not annotated" % tag
    fields, message = tag_fields(repo, oid)
    if not fields or any(len(fields.get(f, [])) != 1 for f in ("object", "type", "tag", "tagger")):
        return False, "tag %s is not a well-formed tag object" % tag
    target = fields["object"][0] if fields["type"][0] == "commit" else "a %s" % fields["type"][0]
    if target != head:
        return False, "tag %s names %s, not the head %s" % (tag, target[:12], head[:12])
    if fields["tag"][0] != tag:
        return False, "tag %s is named %s inside the signed object" % (tag, fields["tag"][0])
    tagger = re.search(r"<[^<>]*>", fields["tagger"][0])
    tagger = tagger.group(0) if tagger else ""
    if not owner or tagger.strip("<>").lower() != owner.lower():
        return False, "tag %s was made by %s, not the owner%s" % (
            tag, tagger or "(unknown)", "" if owner else " (no --owner given)")
    if not names_issue(message, issues):
        return False, "tag %s message does not name %s, the issue the handoff note closes" % (
            tag, " or ".join(issues) or "(none)")
    if trust_unsigned:
        return True, "tag %s (signature not checked)" % tag
    if not owner_key:
        return False, "no --owner-key given, so tag %s cannot be tied to the owner" % tag
    keys = signing_keys(repo, oid)
    if not keys:
        return False, "tag %s has no good signature git can verify" % tag
    if key_id(owner_key) not in keys:
        return False, "tag %s is signed with %s, not the owner's key" % (
            tag, ", ".join(sorted(keys)))
    return True, "tag %s signed with the owner's key" % tag


def check_local(repo, branch, gate_result, body_file, findings_file=None, owner=None,
                accept=DEFAULT_ACCEPT, trust_unsigned=False, owner_key=None):
    code, head = git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/%s^{commit}" % branch)
    if code != 0 or not head:
        raise HostError("branch %s not found in %s" % (branch, repo))
    body = read_file(body_file, "--body")
    items = [("checks", gate_problems(read_file(gate_result, "--gate-result"), head))]
    review = []
    if findings_file:
        open_findings = re.findall(r"^[ \t]*[-*][ \t]+\[ \][ \t]+(.+)$",
                                   read_file(findings_file, "--findings"), re.M)
        if open_findings:
            issues = [re.search(r"\S+$", r).group(0) for r in closing_refs(body)]
            counts, why = accept_tag(repo, branch, head, accept, owner, owner_key,
                                     trust_unsigned, issues)
            if not counts:
                review = ["%d open review finding%s and not owner-accepted: %s" % (
                    len(open_findings), "" if len(open_findings) == 1 else "s", why)]
    items.append(("review", review))
    items.append(("proof", proof_problems(body)))
    items.append(("closing reference", [] if closing_refs(body) else
                  ["no closing reference (Closes #n) in the handoff note"]))
    return verdict(branch, head, items)


# ----- output --------------------------------------------------------------------------------

def verdict(target, head, items):
    items = [{"name": n, "ok": not p, "problems": p} for n, p in items]
    return {"target": target, "head": head, "ready": all(i["ok"] for i in items),
            "items": items}


def render(result):
    out = ["%s: %s at %s" % ("READY" if result["ready"] else "NOT READY", result["target"],
                             result["head"])]
    for item in result["items"]:
        out.append("  %-18s %s" % (item["name"] + ":", "ok" if item["ok"] else "FAIL"))
        out += ["    - %s" % p for p in item["problems"]]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--owner")
    ap.add_argument("--owner-labels", default=DEFAULT_OWNER_LABELS)
    ap.add_argument("--accept-label", default=DEFAULT_ACCEPT)
    ap.add_argument("--gh")
    ap.add_argument("--local")
    ap.add_argument("--branch")
    ap.add_argument("--gate-result")
    ap.add_argument("--body")
    ap.add_argument("--findings")
    ap.add_argument("--owner-key")
    ap.add_argument("--trust-unsigned", action="store_true")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args(argv)
    host_mode = args.repo is not None or args.pr is not None
    local_mode = args.trust_unsigned or any(v is not None for v in (
        args.local, args.branch, args.gate_result, args.body, args.findings, args.owner_key))
    if host_mode == local_mode:
        ap.print_usage(sys.stderr)
        print("handoff_check: give --repo and --pr, or --local, --branch, --gate-result and "
              "--body", file=sys.stderr)
        return 2
    try:
        if host_mode:
            if not args.pr or not re.match(r"^[\w.-]+/[\w.-]+$", args.repo or ""):
                raise UsageError("--repo must be OWNER/NAME and --pr a PR number")
            labels = [l.strip() for l in args.owner_labels.split(",") if l.strip()]
            try:
                gh = shlex.split(args.gh) if args.gh else None
            except ValueError as e:
                raise UsageError("--gh: %s" % e)
            try:
                result = check_pr(args.repo, args.pr, args.owner, labels, args.accept_label,
                                  gh=gh)
            except (KeyError, TypeError, AttributeError) as e:
                raise HostError("unexpected response shape (%s: %s)" % (type(e).__name__, e))
        else:
            if not (args.local and args.branch and args.gate_result and args.body):
                raise UsageError("local mode needs --local, --branch, --gate-result and --body")
            if args.owner_key and args.trust_unsigned:
                raise UsageError("give --owner-key or --trust-unsigned, not both")
            if args.owner_key and not re.match(r"^(SHA256:[A-Za-z0-9+/=]+|[0-9A-Fa-f ]{40,})$",
                                               args.owner_key.strip()):
                raise UsageError("--owner-key must be an OpenPGP fingerprint or SHA256:...")
            result = check_local(args.local, args.branch, args.gate_result, args.body,
                                 args.findings, args.owner, args.accept_label,
                                 args.trust_unsigned, args.owner_key)
    except UsageError as e:
        print("handoff_check: %s" % e, file=sys.stderr)
        return 2
    except HostError as e:
        print("handoff_check: host error: %s" % e, file=sys.stderr)
        return 3
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, indent=1) if args.format == "json" else render(result))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
