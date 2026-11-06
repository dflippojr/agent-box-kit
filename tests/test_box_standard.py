"""Checks box/STANDARD.md keeps the shape the box audit relies on: six dimensions, each with a
9 bar, a 10 bar, evidence and 3-5 failure stories; worked score examples that follow the overall
rule; and box/README.md and the README layout pointing at it. Pure stdlib."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STANDARD = ROOT / "box" / "STANDARD.md"
BOX_README = ROOT / "box" / "README.md"
README = ROOT / "README.md"

DIMENSIONS = ["G", "R", "J", "W", "P", "D"]
PARTS = ["**9 needs:**", "**10 needs:**", "**Evidence:**", "**Failure stories:**"]


def read(path):
    return path.read_text(encoding="utf-8")


def sections():
    """Map each dimension letter to the text of its `## X: Name` section."""
    text = read(STANDARD)
    found = {}
    for m in re.finditer(r"^## ([A-Z]): .*?$(.*?)(?=^## |\Z)", text, re.M | re.S):
        found[m.group(1)] = m.group(2)
    return found


def test_six_dimensions_in_order():
    assert list(sections()) == DIMENSIONS


def test_each_dimension_has_every_part():
    problems = []
    for dim, body in sections().items():
        positions = [body.find(part) for part in PARTS]
        for part, pos in zip(PARTS, positions):
            if pos < 0:
                problems.append("%s: missing %s" % (dim, part))
        if all(p >= 0 for p in positions) and positions != sorted(positions):
            problems.append("%s: parts out of order %s" % (dim, PARTS))
    assert not problems, "\n".join(problems)


def test_three_to_five_failure_stories():
    for dim, body in sections().items():
        stories = body.split("**Failure stories:**", 1)[1]
        count = len(re.findall(r"^\d+\. ", stories, re.M))
        assert 3 <= count <= 5, "%s has %d failure stories, want 3-5" % (dim, count)


def overall(marks):
    """The overall rule as STANDARD.md states it."""
    applicable = [m for m in marks if m != "–"]
    if all(m == "★" for m in applicable):
        return 10
    if all(m in "✓★" for m in applicable):
        return 9
    return min(8, 3 + sum(m in "~✓★–" for m in marks))


def test_overall_rule_examples():
    examples = re.findall(r"`((?:[A-Z] \S · ){5}[A-Z] \S) → (\d+)`", read(STANDARD))
    assert examples, "no worked score example found in STANDARD.md"
    for row, score in examples:
        marks = [cell.split()[1] for cell in row.split(" · ")]
        assert [cell.split()[0] for cell in row.split(" · ")] == DIMENSIONS, row
        assert overall(marks) == int(score), "%s should score %d" % (row, overall(marks))


def test_rule_floor_and_ceiling():
    assert overall(["✗"] * 6) == 3
    assert overall(["~"] * 6) == 8
    assert overall(["✓"] * 5 + ["~"]) == 8  # the written-blocker exception is a judgment call
    assert overall(["✓"] * 5 + ["–"]) == 9
    assert overall(["★"] * 5 + ["–"]) == 10


def test_readmes_point_at_the_standard():
    assert "](STANDARD.md)" in read(BOX_README)
    m = re.search(r"## Layout\s+```\n(.*?)```", read(README), re.S)
    assert m, "README has no Layout code block"
    for name in ("box/", "STANDARD.md"):
        assert name in m.group(1), "README layout block does not list %s" % name


def test_rule_three_counts_every_mark_above_absent():
    """Upgrading a dimension must never lower the score, so rule 3 counts ★ with ~ and ✓."""
    m = re.search(r"^3\. \*\*Otherwise\*\*: (.*?)$", read(STANDARD), re.M)
    assert m, "overall rule 3 not found"
    for mark in ("~", "✓", "★", "n/a"):
        assert mark in m.group(1), "rule 3 does not count %s: %s" % (mark, m.group(1))


def test_upgrading_a_mark_never_lowers_the_score():
    ladder = ["✗", "~", "✓", "★"]
    base = ["✓", "~", "✗", "✗", "–", "✗"]
    for i, mark in enumerate(base):
        for better in ladder[ladder.index(mark) + 1:] if mark in ladder else []:
            upgraded = base[:i] + [better] + base[i + 1:]
            assert overall(upgraded) >= overall(base), "%s -> %s lowers the score" % (base, upgraded)


def test_reusable_workflow_row_protects_the_caller():
    """A SHA pin protects the callee only; the caller's conditions and inputs need protection too."""
    row = next(l for l in read(STANDARD).splitlines() if l.startswith("| A PR cannot rewrite its own judge"))
    assert "caller" in row and "base branch" in row, row


RULE_THREE = ("3. **Otherwise**: 3 + the number of dimensions marked ~, ✓, ★ or n/a. "
              "The maximum is 8.")


def proven(marks):
    """Proven as STANDARD.md states it: ✓ and ★ count 1, ~ 0.5, ✗ 0, averaged over the
    dimensions that apply, times 10, to one decimal with halves rounded up."""
    from decimal import Decimal, ROUND_HALF_UP
    worth = {"★": 1, "✓": 1, "~": Decimal("0.5"), "✗": 0}
    applicable = [m for m in marks if m != "–"]
    value = Decimal(10) * sum(worth[m] for m in applicable) / len(applicable)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def test_rule_three_text_is_unchanged():
    """Proven was added beside rule 3, so earlier scores stay comparable (issue #19)."""
    assert RULE_THREE in read(STANDARD).splitlines()


def test_proven_is_defined_with_its_weights_and_rounding():
    m = re.search(r"^### Proven\s*$(.*?)(?=^### |^## )", read(STANDARD), re.M | re.S)
    assert m, "STANDARD.md has no ### Proven section"
    text = " ".join(m.group(1).split())
    for needle in ("✓ = 1", "★ = 1", "~ = 0.5", "✗ = 0", "apply", "× 10", "one decimal",
                   "rounded up", "n/a"):
        assert needle in text, "Proven section does not say %r" % needle


def test_containment_is_named_as_a_known_limit():
    m = re.search(r"^## Known limits\s*$(.*?)(?=^## |\Z)", read(STANDARD), re.M | re.S)
    assert m, "STANDARD.md has no ## Known limits section"
    assert "containment" in m.group(1).lower()


def test_proven_examples_follow_the_definition():
    examples = re.findall(r"`((?:[A-Z] \S · ){5}[A-Z] \S)` has Proven (\d+\.\d)",
                          read(STANDARD))
    assert examples, "no worked Proven example found in STANDARD.md"
    for row, value in examples:
        marks = [cell.split()[1] for cell in row.split(" · ")]
        assert proven(marks) == float(value), "%s should have Proven %.1f" % (row, proven(marks))


def test_proven_separates_rows_that_rule_three_scores_alike():
    """The saturation issue #19 reports: all ~ and nearly all ✓ both score 8."""
    assert overall(["~"] * 6) == overall(["✓"] * 5 + ["~"]) == 8
    assert proven(["~"] * 6) == 5.0
    assert proven(["✓"] * 5 + ["~"]) == 9.2
    assert proven(["✓", "–", "~", "✗", "–", "★"]) == 6.3  # 2.5 / 4, a half rounded up
