import json
import os

import pytest

from conftest import git, py, run, write

# Secret-shaped values are assembled at runtime so this file never contains one itself.
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SLACK = "xoxb-" + "1234567890-abcdefghij"
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkw" + "." + "abcdefghijklmnop"
SKKEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
GOOGLE = "AI" + "za" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r"
HF = "hf" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7"
NPM = "npm" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
ASIA = "AS" + "IA" + "ABCDEFGHIJKLMNOP"
LIVE = "sk" + "_live_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
RLIVE = "rk" + "_live_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
PRIVKEY = "-----BEGIN RSA PRIV" + "ATE KEY-----"
ASSIGNED = "pass" + "word = 'hunter2hunter2X9'"

POSITIVE = [
    ("AWS access key id", "key = " + AWS),
    ("GitHub token", "gh = " + GITHUB),
    ("Slack token", "s = " + SLACK),
    ("JWT", "auth: " + JWT),
    ("API key (sk-/pa- prefix)", "k = " + SKKEY),
    ("Private key block", PRIVKEY),
    ("Google API key", "g = " + GOOGLE),
    ("Hugging Face token", "h = " + HF),
    ("npm token", "//registry.npmjs.org/:_authToken=" + NPM),
    ("AWS access key id", "tmp = " + ASIA),
    ("Live payment key", "p = " + LIVE),
    ("Live payment key", "p = " + RLIVE),
    ("Assigned secret", ASSIGNED),
]


def stage(repo, name, text):
    write(repo, name, text)
    git(repo, "add", name)


@pytest.mark.parametrize("label,line", POSITIVE)
def test_detects_each_pattern_in_staged_diff(repo, label, line):
    stage(repo, "a.txt", "one\n" + line + "\n")
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert r.returncode == 1, r.stdout + r.stderr
    assert label in r.stdout
    assert "a.txt:2:" in r.stdout


def test_clean_change_passes(repo):
    stage(repo, "a.txt", "just some ordinary text\nx = 42\n")
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert r.returncode == 0
    assert "clean" in r.stdout


@pytest.mark.parametrize("line", [
    "API_KEY=your-api-key-here",
    "token = os.environ.get('SERVICE_TOKEN_NAME1')",
    "aws = AKIAIOSFODNN7EXAMPLE",
    "password: changeme12345",
    "secret_key = <put-real-value-here-1>",
    "token = some_function_name_here",  # identifier: no digit, so not a plausible secret
])
def test_placeholders_and_identifiers_are_not_flagged(repo, line):
    stage(repo, "a.txt", line + "\n")
    assert py("secret_guard.py", "--staged", "--dir", str(repo)).returncode == 0


def test_placeholder_word_elsewhere_on_line_does_not_hide_a_real_secret(repo):
    # The original line-level allowlist would have skipped this line because of "sample".
    stage(repo, "a.txt", "# sample config\nk = " + SKKEY + "  # sample\n")
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert r.returncode == 1


def test_inline_allow_marker_suppresses_one_line(repo):
    stage(repo, "a.txt", "k = " + SKKEY + "  # secret-guard: allow public test vector\n")
    assert py("secret_guard.py", "--staged", "--dir", str(repo)).returncode == 0


def test_only_added_staged_lines_are_scanned(repo):
    write(repo, "old.txt", "k = " + SKKEY + "\n")
    git(repo, "add", "old.txt")
    git(repo, "commit", "-q", "-m", "old secret already in history")
    write(repo, "unstaged.txt", "k = " + SKKEY + "\n")  # never staged
    stage(repo, "new.txt", "nothing secret\n")
    assert py("secret_guard.py", "--staged", "--dir", str(repo)).returncode == 0


def test_removing_a_secret_is_not_flagged(repo):
    write(repo, "old.txt", "k = " + SKKEY + "\n")
    git(repo, "add", "old.txt")
    git(repo, "commit", "-q", "-m", "add")
    git(repo, "rm", "-q", "old.txt")
    assert py("secret_guard.py", "--staged", "--dir", str(repo)).returncode == 0


@pytest.mark.parametrize("decoy", ["++ /dev/null", "++ b/other.txt"])
def test_added_line_that_looks_like_a_file_header_is_content(repo, decoy):
    stage(repo, "a.txt", "notes\n%s\nk = %s\n" % (decoy, SKKEY))
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert r.returncode == 1
    assert "a.txt:3:" in r.stdout


@pytest.mark.parametrize("sep", ["\u2028", "\r"])
def test_line_separator_inside_added_text_cannot_forge_a_header(repo, sep):
    """git ends diff lines with LF only; a CR or U+2028 inside one added line is still content."""
    stage(repo, "a.txt", "note%sdiff --git a/a.txt b/a.txt\nk = %s\n" % (sep, SKKEY))
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "a.txt:2:" in r.stdout


def test_line_numbers_are_correct_in_a_later_hunk(repo):
    write(repo, "big.txt", "".join("line %d\n" % i for i in range(1, 31)))
    git(repo, "add", "big.txt")
    git(repo, "commit", "-q", "-m", "big")
    lines = ["line %d\n" % i for i in range(1, 31)]
    lines[19] = "k = " + SKKEY + "\n"  # line 20
    stage(repo, "big.txt", "".join(lines))
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert "big.txt:20:" in r.stdout


def test_output_never_contains_the_full_secret(repo):
    stage(repo, "a.txt", "k = " + SKKEY + "\n")
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert SKKEY not in r.stdout + r.stderr
    assert SKKEY[4:] not in r.stdout + r.stderr


def test_tree_scan_covers_tracked_text_files_only(repo):
    write(repo, "tracked.txt", "k = " + SKKEY + "\n")
    git(repo, "add", "tracked.txt")
    write(repo, "untracked.txt", "k = " + SKKEY + "\n")
    (repo / "bin.dat").write_bytes(b"\0\0" + ("k = " + SKKEY).encode())
    git(repo, "add", "bin.dat")
    r = py("secret_guard.py", "--tree", "--dir", str(repo))
    assert r.returncode == 1
    assert "tracked.txt:1:" in r.stdout
    assert "untracked.txt" not in r.stdout
    assert "bin.dat" not in r.stdout


def test_tree_scan_clean_repo(repo):
    assert py("secret_guard.py", "--tree", "--dir", str(repo)).returncode == 0


def test_config_extra_patterns_allowlist_and_ignore_paths(repo):
    ssn = "123-" + "45-6788"
    write(repo, ".secret-guard.json", json.dumps({
        "extra_patterns": [{"label": "SSN-shaped", "regex": r"\b\d{3}-\d{2}-\d{4}\b"}],
        "allow_substrings": ["000-00-0000"],
        "ignore_paths": ["fixtures/*"],
    }))
    stage(repo, "a.txt", "ssn " + ssn + "\n")
    stage(repo, "b.txt", "ssn 000-00-0000\n")
    stage(repo, "fixtures/c.txt", "ssn " + ssn + "\n")
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert r.returncode == 1
    assert "a.txt:1: SSN-shaped" in r.stdout
    assert "b.txt" not in r.stdout
    assert "fixtures" not in r.stdout


@pytest.mark.parametrize("ending", ["\r\n", "\rnote\n", "\rnote\r", "\r\r\n"])
@pytest.mark.parametrize("mode", ["--staged", "--tree"])
def test_end_anchored_extra_pattern_matches_before_any_cr(repo, mode, ending):
    """CRLF, an embedded bare CR, bare-CR endings: the value ends a line in all of them."""
    ssn = "123-" + "45-6788"
    write(repo, ".secret-guard.json", json.dumps({
        "extra_patterns": [{"label": "SSN-shaped", "regex": r"\b\d{3}-\d{2}-\d{4}$"}]}))
    (repo / "a.txt").write_bytes(("ssn " + ssn + ending).encode("utf-8"))
    git(repo, "add", "a.txt")
    r = py("secret_guard.py", mode, "--dir", str(repo))
    assert r.returncode == 1 and "a.txt:1: SSN-shaped" in r.stdout, r.stdout + r.stderr


def test_bad_config_is_an_error_not_a_silent_pass(repo):
    write(repo, ".secret-guard.json", "{not json")
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert r.returncode not in (0, 1)


@pytest.mark.parametrize("config", [
    {"extra_patterns": [{"label": "x", "regex": "("}]},
    {"extra_patterns": [{"label": "x", "regex": "a{4294967296}"}]},
    {"extra_patterns": [{"label": "x", "regex": "(" * 1000}]},
    {"extra_patterns": [{"label": "x"}]},
    {"extra_patterns": ["not an object"]},
    ["not", "an", "object"],
])
def test_invalid_config_values_exit_2_not_1(repo, config):
    write(repo, ".secret-guard.json", json.dumps(config))
    r = py("secret_guard.py", "--tree", "--dir", str(repo))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Traceback" not in r.stderr


# The repository is untrusted input to the guard. With a one-character extra pattern, a file
# read through a link would print in full, one character per finding. None of these characters
# may reach the output: none of them is in "secret_guard: clean".
CANARY = "QZJ-9047-WVX"


def symlink_or_skip(target, link):
    try:
        os.symlink(str(target), str(link))
    except (OSError, NotImplementedError) as e:
        pytest.skip("cannot make a symlink here: %s" % e)


def assert_canary_absent(out):
    leaked = sorted(set(CANARY) & set(out))
    assert not leaked, "outside bytes reached the output: %s\n%s" % (leaked, out)


@pytest.mark.parametrize("layout", ["tracked link", "folder replaced by a link"])
def test_tree_scan_never_reads_through_a_link_out_of_the_repo(repo, tmp_path, layout):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_bytes((CANARY + "\n").encode())
    write(repo, ".secret-guard.json", json.dumps({
        "extra_patterns": [{"label": "char", "regex": "."}],
        "ignore_paths": ["README.md", ".secret-guard.json"]}))
    if layout == "tracked link":
        symlink_or_skip(outside / "notes.txt", repo / "notes.txt")
        git(repo, "add", "notes.txt")
    else:
        write(repo, "d/notes.txt", "")
        git(repo, "add", "d/notes.txt")
        (repo / "d" / "notes.txt").unlink()
        (repo / "d").rmdir()
        symlink_or_skip(outside, repo / "d")  # the index still lists d/notes.txt
    git(repo, "add", ".secret-guard.json")
    r = py("secret_guard.py", "--tree", "--dir", str(repo))
    assert_canary_absent(r.stdout + r.stderr)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("mode", ["--staged", "--tree"])
def test_a_linked_config_is_refused_not_read(repo, tmp_path, mode):
    outside = tmp_path / "outside.json"
    outside.write_bytes(json.dumps({"extra_patterns": [{"label": CANARY, "regex": "("}]}).encode())
    symlink_or_skip(outside, repo / ".secret-guard.json")
    r = py("secret_guard.py", mode, "--dir", str(repo))
    assert r.returncode == 2 and "link" in r.stderr, r.stdout + r.stderr
    assert CANARY not in r.stdout + r.stderr


def test_not_a_git_repo_is_an_error(tmp_path):
    r = py("secret_guard.py", "--staged", "--dir", str(tmp_path))
    assert r.returncode not in (0, 1)


# ---- the installed pre-commit hook, exercised with real `git commit` ----

def test_hook_blocks_a_secret_commit_and_allows_a_clean_one(repo):
    assert py("secret_guard.py", "--install-hook", "--dir", str(repo)).returncode == 0
    before = git(repo, "rev-parse", "HEAD").strip()

    stage(repo, "a.txt", "k = " + SKKEY + "\n")
    blocked = run(["git", "-C", str(repo), "commit", "-m", "add secret"])
    assert blocked.returncode != 0
    assert git(repo, "rev-parse", "HEAD").strip() == before

    git(repo, "reset", "-q")
    stage(repo, "b.txt", "harmless\n")
    ok = run(["git", "-C", str(repo), "commit", "-m", "harmless"])
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert git(repo, "rev-parse", "HEAD").strip() != before


def test_no_verify_bypasses_the_hook_which_is_why_ci_is_needed(repo):
    py("secret_guard.py", "--install-hook", "--dir", str(repo))
    stage(repo, "a.txt", "k = " + SKKEY + "\n")
    r = run(["git", "-C", str(repo), "commit", "--no-verify", "-m", "bypass"])
    assert r.returncode == 0
    # The whole-tree scan is what catches it afterwards.
    assert py("secret_guard.py", "--tree", "--dir", str(repo)).returncode == 1


def test_install_refuses_to_overwrite_a_foreign_hook_unless_forced(repo):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\necho mine\n")
    assert py("secret_guard.py", "--install-hook", "--dir", str(repo)).returncode == 2
    assert "echo mine" in hook.read_text()
    assert py("secret_guard.py", "--install-hook", "--force", "--dir", str(repo)).returncode == 0
    assert "secret_guard.py" in hook.read_text()


def test_reinstall_replaces_our_own_hook(repo):
    assert py("secret_guard.py", "--install-hook", "--dir", str(repo)).returncode == 0
    assert py("secret_guard.py", "--install-hook", "--dir", str(repo)).returncode == 0


def test_hook_works_from_a_linked_worktree(repo, tmp_path):
    py("secret_guard.py", "--install-hook", "--dir", str(repo))
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "-b", "feature")
    write(wt, "a.txt", "k = " + SKKEY + "\n")
    git(wt, "add", "a.txt")
    r = run(["git", "-C", str(wt), "commit", "-m", "secret in worktree"])
    assert r.returncode != 0


# ---- bare vendor formats: tree mode, negatives, placeholders, output ----

NEW_FORMATS = [GOOGLE, HF, NPM, ASIA, LIVE, RLIVE]


@pytest.mark.parametrize("value", NEW_FORMATS)
def test_new_formats_are_flagged_in_tree_mode(repo, value):
    write(repo, "a.txt", "one\nv " + value + "\n")
    git(repo, "add", "a.txt")
    r = py("secret_guard.py", "--tree", "--dir", str(repo))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "a.txt:2:" in r.stdout


@pytest.mark.parametrize("value", NEW_FORMATS)
def test_new_formats_print_only_label_and_first_four_chars(repo, value):
    stage(repo, "a.txt", "v " + value + "\n")
    out =py("secret_guard.py", "--staged", "--dir", str(repo))
    text = out.stdout + out.stderr
    assert value[:4] + "... (%d chars)" % len(value) in text
    assert value[4:] not in text


@pytest.mark.parametrize("line", [
    "g = " + GOOGLE[:-1],               # Google: one character short
    "g = AIzb" + GOOGLE[4:],            # Google: wrong prefix
    "h = " + HF[:-1],                   # Hugging Face: too short
    "h = hg_" + HF[3:],                 # Hugging Face: wrong prefix
    "n = " + NPM[:-1],                  # npm: too short
    "n = nvm_" + NPM[4:],               # npm: wrong prefix
    "a = " + ASIA[:-1],                 # ASIA: too short
    "a = ASIB" + ASIA[4:],              # ASIA: wrong prefix
    "p = " + LIVE[:-8],                 # live key: too short
    "p = sk_test_" + LIVE[8:],          # test-mode key is not a live key
    "p = pk_live_" + LIVE[8:],          # publishable key is not secret
])
def test_new_formats_negative_cases_are_not_flagged(repo, line):
    stage(repo, "a.txt", line + "\n")
    r = py("secret_guard.py", "--staged", "--dir", str(repo))
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("value", [
    "AIza" + "example" + "A" * 28,
    "hf_" + "example" + "A" * 27,
    "npm_" + "example" + "A" * 29,
    "ASIA" + "EXAMPLE" + "A" * 9,
    "sk_live_" + "example" + "A" * 17,
])
def test_new_formats_documented_placeholders_are_not_flagged(repo, value):
    stage(repo, "a.txt", "v " + value + "\n")
    assert py("secret_guard.py", "--staged", "--dir", str(repo)).returncode == 0
