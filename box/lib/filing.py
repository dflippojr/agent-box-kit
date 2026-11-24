"""Filing issues: on a GitHub repository with gh, or into an issue folder in box/orchestrate's
format. Stdlib only; Python 3.8+. Not a script: box-audit's file_issues.py (the CLI, whose
docstring states the filing rules) and queue-fill's hunt.py and refine.py import it from box/lib
(issue #36).

file_all(issues, repo, folder, apply, gh_spec, offline, name) prints what would be filed and,
with `apply`, files it, returning the exit code. target_error checks a filing target before the
issues are read. issue_file renders one issue file. gh_json and read_all are the read-only host
calls, through gh_read, whose timeout and error text apply to every read.
"""
import itertools
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import gh_read
import issue_folder


def gh_json(gh, args):
    """One read-only gh call: (body, error), as gh_read.read returns them."""
    return gh_read.read(gh + args)


def read_all(gh, what, path):
    """Every item of a paged host list, to the last page: a label or title missed on a later page
    would be reported missing or filed twice. Raises RuntimeError."""
    items = []
    for page in itertools.count(1):
        body, error = gh_json(gh, ["api", "%s&page=%d" % (path, page)])
        if error:
            raise RuntimeError("%s: %s" % (what, error))
        items += body or []
        if len(body or []) < 100:
            return items


def host_state(gh, repo):
    """(label names, open issue titles) or raise RuntimeError."""
    labels = read_all(gh, "labels", "repos/%s/labels?per_page=100" % repo)
    issues = read_all(gh, "issues", "repos/%s/issues?state=open&per_page=100" % repo)
    return ({l["name"] for l in labels},
            {i["title"] for i in issues if "pull_request" not in i})


def target_error(repo, folder, apply, offline):
    """The usage error in a filing target, or None. Checked before the issues are read."""
    if repo is not None and not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        return "--repo must be OWNER/NAME"
    if offline and folder is not None:
        return "--offline is for --repo dry runs; a folder is read anyway"
    if offline and apply:
        return "--offline is for dry runs only"
    return None


def issue_file(number, title, labels, body, created, state="open"):
    """An issue file in box/orchestrate's issue-folder format."""
    if "\n" in title or "\n" in created:
        raise ValueError("a header value spans lines")
    return "---\nnumber: %d\ntitle: %s\nstate: %s\nlabels: %s\ncreatedAt: %s\n---\n%s" % (
        number, title, state, ", ".join(labels), created, body)


def file_all(issues, repo, folder, apply, gh_spec, offline, name="file_issues"):
    """Print what would be filed and, with `apply`, file it: on the GitHub repository `repo`, or
    into the issue folder `folder`. Each issue is a dict with dimension, title, labels and body.
    Returns the exit code."""
    labels, titles, existing = None, set(), []
    if folder is not None:
        try:
            existing = issue_folder.read_folder(folder)
        except issue_folder.InputError as e:
            print("%s: cannot read %s: %s" % (name, folder, e), file=sys.stderr)
            return 2
        titles = {i["title"] for i in existing if i["state"] == "OPEN"}
    try:
        gh = shlex.split(gh_spec) if gh_spec else ([shutil.which("gh")] if shutil.which("gh")
                                                   else None)
    except ValueError as e:
        print("%s: --gh: %s" % (name, e), file=sys.stderr)
        return 2
    if folder is None and not offline:
        if not gh:
            print("%s: gh CLI not found" % name, file=sys.stderr)
            return 2
        try:
            labels, titles = host_state(gh, repo)
        except RuntimeError as e:
            print("%s: cannot read %s: %s" % (name, repo, e), file=sys.stderr)
            return 2
    missing = sorted({l for i in issues for l in i["labels"]} - labels) if labels is not None \
        else []
    mode = "APPLY" if apply else "DRY RUN"
    note = " (offline: labels and duplicates not checked)" if offline else \
        " (a folder has no label list: labels not checked)" if folder is not None else ""
    print("%s: %d proposed issues for %s%s" % (mode, len(issues), repo or folder, note))
    for i in issues:
        dup = i["title"] in titles
        print("\n=== [%s] %s%s\nLabels: %s\n\n%s" % (
            i["dimension"], i["title"], "  (SKIP: an open issue has this title)" if dup else "",
            ", ".join(i["labels"]), i["body"]))
    if missing:
        print("MISSING LABELS on %s: %s. Nothing was created; ask the owner to add them."
              % (repo, ", ".join(missing)))
        return 1
    if not apply:
        return 0
    failed = 0
    number = max([i["number"] for i in existing] or [0])
    for i in issues:
        if i["title"] in titles:
            continue
        if folder is not None:
            number += 1
            path = Path(folder) / ("%d.md" % number)
            try:
                with open(str(path), "x", encoding="utf-8", newline="\n") as f:
                    f.write(issue_file(number, i["title"], i["labels"], i["body"],
                                       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
            except (OSError, ValueError) as e:
                failed += 1
                print("FAILED %r: %s" % (i["title"], e))
                continue
            titles.add(i["title"])
            print("CREATED %s" % path)
            continue
        cmd = ["issue", "create", "-R", repo, "--title", i["title"], "--body", i["body"]]
        for label in i["labels"]:
            cmd += ["--label", label]
        p = subprocess.run(gh + cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if p.returncode == 0:
            titles.add(i["title"])
            print("CREATED %s" % p.stdout.strip())
        else:
            failed += 1
            print("FAILED %r: %s" % (i["title"], p.stderr.strip()[:200]))
    return 1 if failed else 0
