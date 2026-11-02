#!/usr/bin/env python3
"""Run a box audit in report mode: collect evidence, score it with an isolated judge, check the
card, write it. Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux).

Usage:
  python -B audit.py REPO [--remote OWNER/NAME | --no-remote] [--gh CMD] [--runs N] [--prs N]
           [--name NAME] [--date YYYY-MM-DD] [--out DIR] [--judge-line TEXT]
           [--keep-env NAME]... [--copy-home RELPATH]... [--work-root DIR] [--timeout SECONDS]
           (-- JUDGE_COMMAND [ARG...] | --bundle-only DIR)

  REPO            The checkout to audit, or a folder in it: the whole checkout (from `git
                  rev-parse --show-toplevel`) is audited and guarded. Nothing inside the
                  checkout is written, bytecode included.
  --remote ... --prs   Passed to collect.py.
  --name          Repo name for the card (default: the remote's name, else the checkout's
                  folder name).
  --date          Card date (default: today).
  --out DIR       Where the card goes (default: the current directory). The card is
                  DIR/box-audit-<name>-<date>.md. DIR, and the card after links are resolved,
                  must be outside the checkout, so run from outside it or pass --out. An
                  existing card with other hard links is refused; any other is replaced, never
                  written through. Evidence and the judge's input live in a temporary
                  directory, deleted afterwards. It, and --work-root, must be outside the
                  checkout too: TMPDIR, TEMP and TMP, if set, must all be outside it (the judge
                  inherits them), and the temp dir is picked without writing a test file in it.
  --judge-line    Text for the card's `- Judge:` line, describing how the judge was isolated.
  --keep-env, --copy-home, --work-root, --timeout   Passed to `judge.py run`. Prove the
                  isolation once per judge command with `judge.py probe` first.
  -- JUDGE_COMMAND  The judge: any agent CLI in non-interactive mode reading the prompt on stdin.
  --bundle-only DIR  Write the evidence and the judge's prompt to DIR and stop, for a harness
                  that starts its own isolated judge. Then check its card with `card.py check`.

If the card fails `card.py check`, the judge gets one more attempt with the problems listed.

Run it with `python -B`. Interpreter startup runs before the first line and can write bytecode
under a PYTHONPYCACHEPREFIX; without -B, a prefix inside the checkout is refused (exit 2), since
startup may already have written there. The script turns bytecode off at its first statement.
The judge's sweep of folders left by a killed run never deletes one overlapping the checkout,
and a --copy-home file whose refreshed copy would be written back into it is refused.

Exit codes: 0 card written and valid (or bundle written); 1 judge failed, or the card is still
invalid after the retry (it is written anyway, with the problems printed); 2 usage error.
"""
import sys
# Before any other import: a self-audit runs these scripts from inside the audited checkout, and
# an inherited PYTHONPYCACHEPREFIX can point inside it. No import may write bytecode there.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import datetime  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import card  # noqa: E402
import collect  # noqa: E402
import judge  # noqa: E402


def clean(text):
    """The card from the judge's output: drop any preamble and a wrapping code fence."""
    m = re.search(r"^# Box audit:", text, re.M)
    if not m:
        return text.strip() + "\n"
    text = text[m.start():].rstrip()
    if text.endswith("```"):
        text = text[:-3].rstrip()
    return text + "\n"


def temp_dir(repo):
    """(folder, None) for the temp dir to use, or (None, why there is none). It is picked without
    tempfile.gettempdir(), which tests its pick by writing a file in it. Every temp variable that
    is set must be outside the checkout, since the judge inherits them; then the first of them,
    or of the usual system temp dirs, that exists, is writable and is outside the checkout."""
    variables = ("TMPDIR", "TEMP", "TMP")
    for name in variables:
        if os.environ.get(name) and collect.inside(Path(os.environ[name]), repo):
            return None, "%s (%s) is inside the audited repo" % (name, os.environ[name])
    names = [os.environ[n] for n in variables if os.environ.get(n)]
    names += ([os.path.expandvars(p) for p in (r"%LOCALAPPDATA%\Temp", r"%SYSTEMROOT%\Temp")]
              if os.name == "nt" else ["/tmp", "/var/tmp", "/usr/tmp"])
    for folder in names:
        usable = os.path.isdir(folder) and os.access(folder, os.W_OK)
        if usable and not collect.inside(Path(folder), repo):
            return os.path.abspath(folder), None
    return None, "no writable temp dir outside the audited repo; set TMPDIR to one"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    command = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repo")
    ap.add_argument("--remote")
    ap.add_argument("--no-remote", action="store_true")
    ap.add_argument("--gh")
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--prs", type=int, default=20)
    ap.add_argument("--name")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--out", default=".")
    ap.add_argument("--judge-line")
    ap.add_argument("--keep-env", action="append", default=[])
    ap.add_argument("--copy-home", action="append", default=[])
    ap.add_argument("--work-root")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--bundle-only")
    args = ap.parse_args(argv)
    repo = collect.checkout_root(args.repo)
    if repo is None:
        print("audit: %s is not in a git checkout" % args.repo, file=sys.stderr)
        return 2
    if collect.startup_bytecode(repo):
        print("audit: %s" % collect.startup_bytecode(repo), file=sys.stderr)
        return 2
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        print("audit: --date must be YYYY-MM-DD", file=sys.stderr)
        return 2
    if bool(command) == bool(args.bundle_only):
        print("audit: give either `-- JUDGE_COMMAND` or --bundle-only DIR", file=sys.stderr)
        return 2
    if args.bundle_only and collect.inside(Path(args.bundle_only), repo):
        print("audit: --bundle-only must be outside the audited repo", file=sys.stderr)
        return 2
    if not args.bundle_only and collect.inside(Path(args.out), repo):
        print("audit: --out (default: the current directory) must be outside the audited repo",
              file=sys.stderr)
        return 2
    if args.work_root and collect.inside(Path(args.work_root), repo):
        print("audit: --work-root is inside the audited repo; it must be outside", file=sys.stderr)
        return 2
    tmp_root, problem = temp_dir(repo)
    if problem:
        print("audit: the temp dir: %s; it must be outside" % problem, file=sys.stderr)
        return 2
    collect_args = [str(repo), "--runs", str(args.runs), "--prs", str(args.prs), "--format", "md"]
    collect_args += ["--remote", args.remote] if args.remote else []
    collect_args += ["--no-remote"] if args.no_remote else []
    collect_args += ["--gh", args.gh] if args.gh else []

    tmp = Path(tempfile.mkdtemp(prefix="box-audit-", dir=tmp_root))
    try:
        evidence = tmp / "evidence.md"
        code = collect.main(collect_args + ["--out", str(evidence)])
        if code:
            return code
        remote = re.search(r"^- Remote: (\S+)", evidence.read_text(encoding="utf-8"), re.M)
        name = args.name or (remote.group(1).split("/")[-1] if remote and "/" in remote.group(1)
                             else repo.name)
        if args.bundle_only:
            out = Path(args.bundle_only)
            files = [evidence, judge.prepare(evidence, tmp / "bundle", args.date, args.judge_line)]
            problems = [p for p in (collect.unsafe_output(out / f.name, repo) for f in files) if p]
            if problems:
                print("audit: %s; it must be outside" % problems[0], file=sys.stderr)
                return 2
            for f in files:
                collect.write_outside(out / f.name, f.read_text(encoding="utf-8"), repo)
            print(out / "prompt.md")
            return 0
        out_dir = Path(args.out)
        target = out_dir / ("box-audit-%s-%s.md" % (re.sub(r"[^\w.-]", "-", name), args.date))
        problem = collect.unsafe_output(target, repo)  # the card is a link into the repo
        if problem:
            print("audit: %s; it must be outside" % problem, file=sys.stderr)
            return 2
        out_dir.mkdir(parents=True, exist_ok=True)
        feedback, problems, text = None, None, ""
        for attempt in (1, 2):
            bundle = tmp / ("bundle%d" % attempt)
            judge.prepare(evidence, bundle, args.date, args.judge_line, feedback)
            raw = tmp / ("raw%d.md" % attempt)
            code = judge.run(bundle, command, args.keep_env, args.copy_home, args.timeout,
                             str(raw), args.work_root or tmp_root, protect=repo)
            if code:
                return code
            text = clean(raw.read_text(encoding="utf-8"))
            problems = card.check(text)
            if not problems:
                break
            feedback = tmp / "feedback.md"
            feedback.write_text("Problems found by card.py check:\n\n%s\n\nYour previous card:\n\n"
                                "%s" % ("\n".join("- " + p for p in problems), text),
                                encoding="utf-8")
        collect.write_outside(target, text, repo)
        sys.stdout.reconfigure(encoding="utf-8")
        print(target)
        if problems:
            print("CARD_INVALID after %d attempts:" % 2)
            for p in problems:
                print("- " + p)
            return 1
        print("CARD_OK")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
