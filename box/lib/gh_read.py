"""Run one read-only gh command and decode its response. Stdlib only; Python 3.8+. Not a script:
box-audit's collect.py and file_issues.py and orchestrate's select.py and handoff_check.py load this
file by path.
Each keeps its own command, environment, endpoints and error verdicts.

read(argv, env=None) runs the complete argv with a 60-second timeout and returns (body, error):
the JSON on stdout (None when stdout is empty) and None, or None and a one-line reason (`HTTP
<status>` when gh reports one, else gh's first stderr line cut to 160 characters). env None
inherits the caller's environment. Errors are returned, never raised.

paged(fetch, per_page=100, max_pages=MAX_PAGES) reads a list to its last page and returns
(entries, error). fetch(page) returns (entries, error) for pages 1, 2, ...; the first error is
returned as it is. A page shorter than per_page is the last. A full page max_pages is read one page
past, so a list of exactly max_pages full pages is complete; if that page is not empty the error is
`more than <max_pages> pages`. select.py and handoff_check.py page through this.
"""
import json
import re
import subprocess

TIMEOUT = 60
MAX_REASON = 160
MAX_PAGES = 10


def read(argv, env=None):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "gh failed: %s" % e
    if p.returncode != 0:
        m = re.search(r"HTTP (\d{3})", p.stderr)
        first = (p.stderr.strip() or "gh failed").splitlines()[0]
        return None, ("HTTP %s" % m.group(1)) if m else first[:MAX_REASON]
    try:
        return json.loads(p.stdout or "null"), None
    except ValueError:
        return None, "gh returned non-JSON output"


def paged(fetch, per_page=100, max_pages=MAX_PAGES):
    entries = []
    for page in range(1, max_pages + 2):
        batch, error = fetch(page)
        if error:
            return None, error
        if page > max_pages:
            if batch:
                break
            return entries, None
        entries += batch
        if len(batch) < per_page:
            return entries, None
    return None, "more than %d pages" % max_pages
