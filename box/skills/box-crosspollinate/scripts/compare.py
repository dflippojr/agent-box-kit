#!/usr/bin/env python3
"""Compare box-audit score cards across repos and propose porting each dimension's strongest
practice to the weaker repos. Reads cards only: it never re-scores a card or reads a repo.
Stdlib only. CI runs it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux).

Usage:
  compare.py CARD CARD [CARD...] [--max-age DAYS] [--out DIR]

  CARD        A box-audit score card that passes `card.py check`, one per repo. Two cards for
              the same repo are refused: pass the newest.
  --max-age   Warn when the oldest and newest card dates are more than DAYS apart (default 30).
              The comparison still runs: a stale card may score a box that has since changed.
  --out       Write each weaker repo's proposals to DIR/crosspollinate-<repo>-<date>.md, <date>
              being the newest card's. An existing file is never overwritten. Without --out the
              proposals are printed after the report. `file_issues.py` in box-audit files a
              proposal file the way it files a card's proposals: dry run first.

The report is a matrix of repo against the G R J W P D marks, with each card's date, overall score
and Proven value; then, for each dimension, the strongest repo or repos (the highest mark, ties all
listed) with the Evidence items behind that mark and their sources. Marks rank ✗ < ~ < ✓ < ★. n/a
(–) is never strongest, and a repo marked n/a on a dimension gets no proposal for it. A repo whose
mark on a dimension is below the strongest gets one proposal for that dimension, titled
"Port the <dimension> from <repo>", in card-format.md's proposal shape and labels, naming the
source paths the strongest card's evidence cites.

Exit codes: 0 report printed (and any proposal files written), stale warning or not; 1 a card
fails `card.py check`, nothing compared; 2 usage error (fewer than two cards, an unreadable card,
two cards for one repo, a bad --max-age, an --out that is not a folder or a proposal file that
already exists).
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "box-audit" / "scripts"))

import card  # noqa: E402

RANK = {"✗": 0, "~": 1, "✓": 2, "★": 3}  # "–" (n/a) has no rank: never strongest
TITLE = re.compile(r"^# Box audit: (.+) \((\d{4}-\d{2}-\d{2})\)\s*$")
SOURCE = re.compile(r"\(([^()]*)\)\s*$")
# A path is one run of path characters with a name character before a `/` or `.`; each test
# is a single linear scan (one pattern with overlapping runs backtracked on long input).
PATH_CHARS = re.compile(r"[\w./-]+")
NAME_THEN_SEP = re.compile(r"[\w-][/.]")
LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")
PROPOSAL_FILE = "crosspollinate-%s-%s.md"


class UsageError(Exception):
    pass


def items(evidence, label):
    """Evidence items under `**label**`, each joined with its wrapped continuation lines, as
    card.listed finds them; [] for `none` or a missing label."""
    if not card.listed(evidence, label):
        return []
    m = re.search(r"^\*\*%s\*\*\s*$(.*?)(?=^\*\*|^#|\Z)" % re.escape(label), evidence,
                  re.M | re.S)
    out = []
    for line in m.group(1).strip().splitlines():
        if line.strip().startswith("- "):
            out.append(line.strip()[2:].strip())
        elif out and line.strip():
            out[-1] += " " + line.strip()
    return out


def source_paths(item):
    """Repo paths an evidence item cites, without line numbers: those in its trailing
    `(source)`, then those in its code spans that name a folder (`scripts/verify.py`)."""
    m = SOURCE.search(item)
    parts = re.split(r"[,;]\s*", m.group(1)) if m else []
    spans = [s for s in re.findall(r"`([^`]+)`", item) if "/" in s]
    paths = []
    for part in parts + spans:
        part = part.strip().strip("`")
        path = LINE_SUFFIX.sub("", part)
        if PATH_CHARS.fullmatch(path) and NAME_THEN_SEP.search(path) and \
                not path[0].isdigit() and path not in paths:
            paths.append(path)
    return paths


def read_card(path):
    """A parsed card dict, or raise UsageError (unreadable) or ValueError (invalid)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise UsageError("cannot read %s: %s" % (path, e))
    problems = card.check(text)
    if problems:
        raise ValueError("%s: CARD_INVALID\n%s" % (path, "\n".join("- " + p for p in problems)))
    repo, date = TITLE.match(text.splitlines()[0]).groups()
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        raise ValueError("%s: CARD_INVALID\n- date %s in the first line is not a calendar date"
                         % (path, date))
    row = card.ROW.search(re.search(r"^- Score: (.*)$", text, re.M).group(1))
    marks = card.parse_row(row.group(1))
    dims = {}
    for dim, _, body in card.sections(text):
        evidence = card.part(body, "Evidence") or ""
        dims[dim] = {"verified": items(evidence, "Verified"),
                     "read": items(evidence, "Read only"),
                     "gap": card.part(body, "Gap") or ""}
    return {"path": str(path), "repo": repo, "date": date, "marks": dict(zip(card.DIMENSIONS,
                                                                           marks)),
            "score": int(row.group(2)), "proven": card.proven(marks), "dims": dims}


def strongest(cards, dim):
    """(mark, repos) holding the highest applicable mark on `dim`, or (None, []) when every card
    marks it n/a."""
    ranked = [c for c in cards if c["marks"][dim] in RANK]
    if not ranked:
        return None, []
    top = max(RANK[c["marks"][dim]] for c in ranked)
    best = [c for c in ranked if RANK[c["marks"][dim]] == top]
    return best[0]["marks"][dim], best


def age_warning(cards, max_age):
    dated = sorted(cards, key=lambda c: c["date"])
    days = (datetime.date.fromisoformat(dated[-1]["date"]) -
            datetime.date.fromisoformat(dated[0]["date"])).days
    if days > max_age:
        return ("WARNING: the cards are %d days apart (%s %s, %s %s), more than %d: a stale card "
                "may not score the box as it is now; re-audit before acting." % (
                    days, dated[0]["repo"], dated[0]["date"], dated[-1]["repo"],
                    dated[-1]["date"], max_age))
    return None


def matrix(cards):
    width = max(len("Repo"), max(len(c["repo"]) for c in cards))
    lines = ["%-*s  %-10s  %s  Score  Proven" % (width, "Repo", "Date",
                                                 "  ".join(card.DIMENSIONS))]
    for c in cards:
        lines.append("%-*s  %s  %s  → %-3d  %s" % (
            width, c["repo"], c["date"], "  ".join(c["marks"][d] for d in card.DIMENSIONS),
            c["score"], c["proven"]))
    return lines


def quoted(c, dim, indent=""):
    """The evidence behind `c`'s mark on `dim`, Verified apart from Read only."""
    lines = []
    for label, key in (("Verified", "verified"), ("Read only", "read")):
        found = c["dims"][dim][key]
        lines.append("%s%s:%s" % (indent, label, "" if found else " none"))
        lines += ["%s- %s" % (indent, i) for i in found]
    return lines


def practice(dim):
    return "the " + card.NAMES[dim].lower()


def proposal(weak, dim, mark, best):
    """One proposal in card-format.md's shape: `#### title` through **Out of scope**."""
    names = " and ".join(c["repo"] for c in best)
    paths = []
    for c in best:
        for i in c["dims"][dim]["verified"] + c["dims"][dim]["read"]:
            paths += ["`%s` (%s)" % (p, c["repo"]) for p in source_paths(i)
                      if "`%s` (%s)" % (p, c["repo"]) not in paths]
    gap = [l for l in weak["dims"][dim]["gap"].splitlines() if l.strip()]
    lines = ["#### Port %s from %s" % (practice(dim), names), "",
             "Labels: tier:standard, ready", "Open decisions: none", "", "**Problem**",
             "%s marks %s (%s) %s in its box audit of %s; %s %s it %s. %s's gap there:" % (
                 weak["repo"], dim, card.NAMES[dim], weak["marks"][dim], weak["date"], names,
                 "marks" if len(best) == 1 else "mark", mark, weak["repo"])]
    lines += gap or ["- none written"]
    for c in best:
        lines += ["", "Evidence behind %s's %s on %s (card of %s):" % (c["repo"], mark, dim,
                                                                      c["date"])]
        lines += quoted(c, dim)
    lines += ["", "**Want**",
              "- %s has the practice behind %s's %s mark, adapted to its own code and CI." % (
                  weak["repo"], names, dim),
              "- A fresh box audit of %s marks %s at %s%s, with verified evidence." % (
                  weak["repo"], dim, mark, "" if mark == "★" else " or better"), "",
              "**Constraints**",
              "- Read the practice in %s first. Source paths %s: %s." % (
                  names, "its card cites" if len(best) == 1 else "their cards cite",
                  ", ".join(paths) if paths else "none, so start from the evidence quoted above"),
              "- Change only %s; the source repo is read, not edited." % weak["repo"],
              "- Proof: the new check's output in the PR, and the re-audit card's %s section."
              % dim, "",
              "**Dependencies**", "none", "",
              "**Out of scope**",
              "Porting code automatically, other dimensions, and changing box-audit's scoring."]
    return lines


def proposals_for(weak, cards):
    """The proposal file text for `weak`, or None when no dimension is below the strongest."""
    sections = []
    for dim in card.DIMENSIONS:
        mark, best = strongest(cards, dim)
        if weak["marks"][dim] not in RANK or mark is None or \
                RANK[weak["marks"][dim]] >= RANK[mark]:
            continue
        sections += ["## %s: %s" % (dim, card.NAMES[dim]), "", "### Proposed issues", ""]
        sections += proposal(weak, dim, mark, best) + [""]
    if not sections:
        return None
    newest = max(c["date"] for c in cards)
    others = ", ".join("%s (%s)" % (c["repo"], c["date"]) for c in cards if c is not weak)
    head = ["# Box crosspollinate: %s (%s)" % (weak["repo"], newest), "",
            "- Card: %s (%s), score %d" % (weak["repo"], weak["date"], weak["score"]),
            "- Compared with: %s" % others, ""]
    return "\n".join(head + sections).rstrip() + "\n"


def report(cards, max_age):
    lines = ["CARDS: %d" % len(cards)]
    warning = age_warning(cards, max_age)
    if warning:
        lines.append(warning)
    lines += [""] + matrix(cards) + ["", "Strongest per dimension:"]
    for dim in card.DIMENSIONS:
        mark, best = strongest(cards, dim)
        if mark is None:
            lines += ["", "%s %s: none (n/a on every card)" % (dim, card.NAMES[dim])]
            continue
        lines += ["", "%s %s: %s %s" % (dim, card.NAMES[dim], mark,
                                        ", ".join(c["repo"] for c in best))]
        for c in best:
            lines += ["  %s (%s):" % (c["repo"], c["date"])] + quoted(c, dim, "    ")
    return lines


def safe_name(repo):
    return re.sub(r"[^\w.-]+", "-", repo).strip(".-") or "repo"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cards", nargs="+")
    ap.add_argument("--max-age", type=int, default=30)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        if len(args.cards) < 2:
            raise UsageError("give two or more cards")
        if args.max_age < 0:
            raise UsageError("--max-age must be 0 or more")
        if args.out is not None and not Path(args.out).is_dir():
            raise UsageError("--out %s is not a folder" % args.out)
        cards = [read_card(p) for p in args.cards]
        seen = {}
        for c in cards:
            if c["repo"] in seen:
                raise UsageError("two cards for %s (%s, %s): pass the newest" % (
                    c["repo"], seen[c["repo"]], c["path"]))
            seen[c["repo"]] = c["path"]
        files = [(c, proposals_for(c, cards)) for c in cards]
        targets = {}
        if args.out is not None:
            for c, text in files:
                if text:
                    target = Path(args.out) / (PROPOSAL_FILE % (safe_name(c["repo"]),
                                                                max(x["date"] for x in cards)))
                    if target.exists() or target in targets.values():
                        raise UsageError("%s already exists; move it or pick another --out"
                                         % target)
                    targets[c["repo"]] = target
    except UsageError as e:
        print("compare: %s" % e, file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e))
        return 1
    lines = report(cards, args.max_age) + ["", "Proposals:"]
    for c, text in files:
        if not text:
            lines.append("- %s: none (no dimension below the strongest)" % c["repo"])
        elif args.out is not None:
            with open(str(targets[c["repo"]]), "x", encoding="utf-8", newline="\n") as f:
                f.write(text)
            lines.append("- %s: %s" % (c["repo"], targets[c["repo"]]))
        else:
            lines.append("- %s:" % c["repo"])
    print("\n".join(lines))
    if args.out is None:
        for c, text in files:
            if text:
                print("\n" + text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
