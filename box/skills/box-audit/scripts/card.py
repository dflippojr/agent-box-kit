#!/usr/bin/env python3
"""Check a box-audit score card against card-format.md, or score a mark row. Stdlib only. CI runs
it on Python 3.10 (Linux, macOS, Windows) and 3.8 (Linux).

Usage:
  card.py check CARD      Print CARD_OK, or CARD_INVALID and one problem per line.
  card.py score "ROW"     Print the overall score for a row such as
                          "G ✓ · R ~ · J ✗ · W ~ · P – · D ~".
  card.py proven "ROW"    Print the row's Proven value, such as 5.0.
  card.py standard        Print this kit's Standard value, such as 0123456789ab.
  card.py --help          Print this usage.

Exit codes: 0 card valid, row scored, Proven, Standard or usage printed; 1 card invalid; 2 usage
error (unreadable card, malformed row, an unreadable rubric file).

The overall rule is the one in box/STANDARD.md:
  10 every applicable dimension is ★;
   9 every applicable dimension is ✓ or ★, or exactly one ~ with a written external blocker;
  otherwise 3 + the dimensions marked ~, ✓, ★ or –, at most 8.
Proven, also from the standard: ✓ and ★ count 1, ~ 0.5, ✗ 0, averaged over the dimensions that
apply, times 10, to one decimal with halves rounded up. A card's `- Proven:` line is optional
(audit.py writes it from the score row); when present, `check` requires it to match.

Standard: the first 12 hex digits of a SHA-256 over the four files that decide a card's marks,
STANDARD.md, judge-prompt.md, card-format.md and collect.py, each framed by its path in the kit
and its length, with CRLF read as LF so a Windows checkout gives the same value. A card's
`- Standard:` line is optional (audit.py writes it); when present, `check` requires 12 lowercase
hex digits, and `check` notes `standard: unknown` on stderr when it is absent. It is a content
hash, so it works from a copied kit as well as a checkout.
"""
import sys
# Before any other import: box/lib sits in the kit, which may be the audited checkout.
sys.dont_write_bytecode = True

from pathlib import Path  # noqa: E402

# box/lib, in the checkout this file sits in, holds the helpers box scripts share (issue #36).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from scorecard import card_standard, check, overall, parse_row, proven, standard_hash  # noqa: E402


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    sys.stdout.reconfigure(encoding="utf-8")
    if argv in (["--help"], ["-h"]):
        print(__doc__.split("\n\n")[1])
        return 0
    if argv == ["standard"]:
        try:
            print(standard_hash())
        except OSError as e:
            print("card: cannot read the rubric: %s" % e, file=sys.stderr)
            return 2
        return 0
    if len(argv) != 2 or argv[0] not in ("check", "score", "proven"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    if argv[0] in ("score", "proven"):
        marks = parse_row(argv[1].split("→")[0].strip().strip("`"))
        if not marks:
            print("card: malformed row %r" % argv[1], file=sys.stderr)
            return 2
        print(overall(marks) if argv[0] == "score" else proven(marks))
        return 0
    try:
        text = Path(argv[1]).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print("card: cannot read %s: %s" % (argv[1], e), file=sys.stderr)
        return 2
    problems = check(text)
    if problems:
        print("CARD_INVALID")
        for p in problems:
            print("- " + p)
        return 1
    print("CARD_OK")
    if card_standard(text) is None:
        print("card: standard: unknown (no `- Standard:` line, so the rubric that scored this "
              "card is not recorded)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
