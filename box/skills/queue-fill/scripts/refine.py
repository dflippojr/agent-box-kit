#!/usr/bin/env python3
"""Refine `needs-refinement` issues the owner has answered: list them, then rewrite one around
the answer and relabel it. Dry run unless --apply. Stdlib only. CI runs it on Python 3.10 and
3.8.

Usage:
  refine.py list (--repo OWNER/NAME | --folder DIR) [--owner LOGIN] [--gh CMD]
  refine.py apply NUMBER BODY (--repo OWNER/NAME | --folder DIR) [--owner LOGIN] [--apply]
            [--gh CMD] [--allow-label NAME]...

  list           The open `needs-refinement` issues: those with an owner answer first, each
                 answer quoted with its date, then those still waiting.
  apply          Check BODY, the rewritten issue body for issue NUMBER (`-` reads stdin), and
                 print the new labels and body. Nothing changes without --apply.
  --repo         A GitHub repository, read with `gh api` (GET) and edited with `gh issue edit`.
  --folder       An issue folder in box/orchestrate's format, for a project with no hosted VCS.
  --owner        Whose comments are answers on the host (default: OWNER from --repo).
  --apply        Write the new body and labels.
  --gh CMD       The command that runs gh, split like a shell would (default: `gh` on PATH).
  --allow-label  Another label BODY may carry, as for issue_lint.py. The issue's own labels are
                 always allowed.

An answer is a comment by --owner on the host. In a folder, which has no comments, it is a
section of the issue file under a heading that starts with `Owner answer`.

apply refines only an open issue labelled `needs-refinement` that has an answer. If BODY has no
`Open question` section, the new labels are the issue's labels without `needs-refinement` and
with `ready`; otherwise they stay as they are. BODY must pass issue_lint.py with the new labels,
or nothing changes and the question stays in the body the issue already has. Refinement only
ever removes `needs-refinement` and adds `ready`: every other label, owner-only ones included,
stays as it is. It keeps the title, so it never makes a duplicate. On the host, `ready` must
already exist on the repo.

Exit codes: 0 listed, dry run printed or the issue rewritten; 1 not refined: the issue is not an
open `needs-refinement` issue, has no answer, BODY fails the lint, `ready` is missing on the
repo, or the edit failed; 2 usage, input or host error (bad options, unreadable BODY or issue
file, an issue file that is a link or has other hard links, gh missing, a refused read).

In a folder, the issue file is replaced by a new file, never written through: a file the folder
links to elsewhere is refused and left as it is, and so is a folder reached through a link. Reads
and the write are relative to the folder as first opened, so a folder swapped for a link later
is not followed. Where the platform cannot do that (Windows), apply --folder --apply refuses to
write (exit 1).
"""
import argparse
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "box-audit" / "scripts"))

import file_issues  # noqa: E402
import issue_lint  # noqa: E402

select = issue_lint.select
REFINE, READY = "needs-refinement", "ready"


class HostError(Exception):
    """A read the host refused, or no gh: exit 2."""


SAFE_WRITES = (select.DIR_FDS and os.rename in os.supports_dir_fd
               and os.unlink in os.supports_dir_fd and hasattr(os, "fchmod"))


def replace_entry(folder, name, data, mode):
    """Write data to a new file in folder (a descriptor) and move it over entry name, relative to
    folder throughout: neither a link nor a folder swapped in after the checks is followed. The
    mode is set on the open file, and the entry moved in is checked to be that file. Returns an
    error message, or None."""
    tmp = ".%s.%s.tmp" % (name, secrets.token_hex(8))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fchmod(fd, mode)
            os.replace(tmp, name, src_dir_fd=folder, dst_dir_fd=folder)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=folder)
            except OSError:
                pass
            raise
        if not os.path.samestat(os.fstat(fd), os.stat(name, dir_fd=folder,
                                                      follow_symlinks=False)):
            return "%s was swapped while it was written; check it by hand" % name
    finally:
        os.close(fd)
    return None


class Folder:
    """An issue folder. Answers are `Owner answer` sections in the issue file. The folder is
    opened once (select.IssueDir); every read and the write are relative to it."""

    def __init__(self, path):
        self.path = Path(path)
        self.dir = None
        self.seen = {}  # number -> the issue file's stat when it was read

    def folder(self):
        if self.dir is None:
            self.dir = select.IssueDir(self.path)
        return self.dir

    def issues(self):
        d = self.folder()
        return [i for i in (d.read(name)[0] for name in d.names())
                if i["state"] == "OPEN" and REFINE in i["labels"]]

    def issue(self, number):
        issue, st = self.folder().read("%d.md" % number)
        self.seen[number] = st
        return issue

    def answers(self, issue):
        return [("(in the file)", text) for _, title, _, text in issue_lint.headings(issue["body"])
                if title.lower().startswith("owner answer") and text]

    def labels(self):
        return None  # a folder has no label list

    def edit(self, issue, body, labels):
        """Replace the issue file with a new one, so a link swapped in after the read is
        replaced, not followed. The entry must still be the file read."""
        name = "%d.md" % issue["number"]
        if not SAFE_WRITES or self.dir is None or self.dir.fd is None:
            return ("this platform cannot write into a folder without following links; "
                    "nothing written")
        text = file_issues.issue_file(issue["number"], issue["title"], labels, body,
                                      issue["createdAt"], issue["state"].lower())
        try:
            st = os.stat(name, dir_fd=self.dir.fd, follow_symlinks=False)
            seen = self.seen.get(issue["number"])
            if seen is None or not os.path.samestat(st, seen) or select.linked(st) \
                    or st.st_nlink > 1:
                return "%s changed after it was read; nothing written" % name
            return replace_entry(self.dir.fd, name, text.encode("utf-8"),
                                 stat.S_IMODE(st.st_mode))
        except OSError as e:
            return str(e)


class Host:
    """A GitHub repository through gh. Reads are GETs; the one write is `gh issue edit`."""

    def __init__(self, repo, owner, gh):
        self.repo, self.owner, self.gh = repo, owner, gh

    def get(self, what, path, all_pages=False):
        try:
            if all_pages:
                return file_issues.read_all(self.gh, what, path)
        except RuntimeError as e:
            raise HostError(str(e))
        body, error = file_issues.gh_json(self.gh, ["api", path])
        if error:
            raise HostError("%s: %s" % (what, error))
        return body

    def issues(self):
        raw = self.get("issues", "repos/%s/issues?state=open&labels=%s&per_page=100"
                       % (self.repo, REFINE), True)
        return [self.normal(i) for i in raw if "pull_request" not in i]

    def normal(self, raw):
        return select.normalize(dict(raw, createdAt=raw.get("created_at")),
                                "#%s" % raw.get("number"))

    def issue(self, number):
        raw = self.get("issue #%d" % number, "repos/%s/issues/%d" % (self.repo, number))
        if not isinstance(raw, dict) or "pull_request" in raw:
            raise select.InputError("#%d is not an issue" % number)
        return self.normal(raw)

    def answers(self, issue):
        comments = self.get("comments", "repos/%s/issues/%d/comments?per_page=100"
                            % (self.repo, issue["number"]), True)
        return [((c.get("created_at") or "")[:10], (c.get("body") or "").strip())
                for c in comments
                if ((c.get("user") or {}).get("login") or "").lower() == self.owner.lower()]

    def labels(self):
        return {l["name"] for l in self.get("labels", "repos/%s/labels?per_page=100"
                                            % self.repo, True)}

    def edit(self, issue, body, labels):
        cmd = ["issue", "edit", str(issue["number"]), "-R", self.repo, "--body", body]
        if READY in labels and READY not in issue["labels"]:
            cmd += ["--add-label", READY]
        if REFINE in issue["labels"] and REFINE not in labels:
            cmd += ["--remove-label", REFINE]
        p = subprocess.run(self.gh + cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        return None if p.returncode == 0 else (p.stderr.strip() or "gh failed")[:200]


def new_labels(labels, body):
    """The labels after refinement: `ready` for `needs-refinement` once no question is open and
    the body has only Markdown the lint models."""
    if issue_lint.open_questions(body) or issue_lint.unmodelled(body):
        return list(labels)
    return [l for l in labels if l != REFINE] + ([] if READY in labels else [READY])


def list_issues(source):
    issues = source.issues()
    answered = [(i, source.answers(i)) for i in issues]
    ready = [(i, a) for i, a in answered if a]
    print("Answered by the owner, ready to refine (%d):" % len(ready))
    for issue, answers in ready:
        print("  #%-5d %s" % (issue["number"], issue["title"]))
        for date, text in answers:
            first = text.splitlines()[0] if text else ""
            print("         - %s: %s" % (date, first[:100]))
    waiting = [i for i, a in answered if not a]
    print("Waiting for the owner (%d):" % len(waiting))
    for issue in waiting:
        print("  #%-5d %s" % (issue["number"], issue["title"]))
    return 0


def apply_body(source, number, body, apply, known):
    issue = source.issue(number)
    where = "#%d" % number
    if issue["state"] != "OPEN" or REFINE not in issue["labels"]:
        print("NOT REFINED: %s is not an open %s issue" % (where, REFINE))
        return 1
    if not source.answers(issue):
        print("NOT REFINED: %s has no answer from the owner yet" % where)
        return 1
    labels = new_labels(issue["labels"], body)
    problems = issue_lint.lint(body, labels, known | set(issue["labels"]), where)
    if problems:
        print("NOT REFINED: the new body fails the lint with labels %s; nothing changed"
              % ", ".join(labels))
        for p in problems:
            print("- " + p)
        return 1
    have = source.labels()
    if have is not None and READY in labels and READY not in have:
        print("MISSING LABELS: %s. Nothing changed; ask the owner to add it." % READY)
        return 1
    print("%s: refine %s %s\nLabels: %s -> %s\n\n%s" % (
        "APPLY" if apply else "DRY RUN", where, issue["title"], ", ".join(issue["labels"]),
        ", ".join(labels), body))
    if not apply:
        return 0
    error = source.edit(issue, body, labels)
    if error:
        print("FAILED %s: %s" % (where, error))
        return 1
    print("REFINED %s%s" % (where, " (now ready)" if READY in labels else ""))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["list", "apply"])
    ap.add_argument("number", nargs="?", type=int)
    ap.add_argument("body", nargs="?")
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo")
    target.add_argument("--folder")
    ap.add_argument("--owner")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--gh")
    ap.add_argument("--allow-label", action="append", default=[])
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if (args.command == "list") != (args.number is None and args.body is None) or \
            (args.command == "apply" and args.body is None):
        print("refine: list takes no NUMBER or BODY; apply takes both", file=sys.stderr)
        return 2
    if args.command == "list" and args.apply:
        print("refine: --apply is for apply", file=sys.stderr)
        return 2
    error = file_issues.target_error(args.repo, args.folder, args.apply, False)
    if error:
        print("refine: %s" % error, file=sys.stderr)
        return 2
    if args.folder is not None:
        source = Folder(args.folder)
    else:
        try:
            gh = shlex.split(args.gh) if args.gh else (
                [shutil.which("gh")] if shutil.which("gh") else None)
        except ValueError as e:
            print("refine: --gh: %s" % e, file=sys.stderr)
            return 2
        if not gh:
            print("refine: gh CLI not found", file=sys.stderr)
            return 2
        source = Host(args.repo, args.owner or args.repo.split("/")[0], gh)
    try:
        if args.command == "list":
            return list_issues(source)
        body = sys.stdin.read() if args.body == "-" else \
            Path(args.body).read_text(encoding="utf-8")
        body = body.replace("\r\n", "\n")
        return apply_body(source, args.number, body, args.apply,
                          issue_lint.KNOWN | set(args.allow_label))
    except (OSError, UnicodeDecodeError, select.InputError, HostError) as e:
        print("refine: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
