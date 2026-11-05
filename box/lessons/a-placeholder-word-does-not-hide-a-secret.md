# A placeholder word does not hide a secret

**Rule:** Apply a secret scanner's placeholder allowlist to the matched value, never to the whole line. Evidence row: [Secrets guard: staged diff, placeholder allowlist, whole-tree scan (04)](../../EVIDENCE.md)

**Why:** A line-wide allowlist lets a real key through whenever a word like "sample" sits anywhere on its line.

**Incident:** The scanner the guard was ported from skipped any line containing "sample", real key included.

**Enforced by:** `tests/test_secret_guard.py::test_placeholder_word_elsewhere_on_line_does_not_hide_a_real_secret`

**Evidence:** observed

**Status:** enforced
