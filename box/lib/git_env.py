"""The environment box scripts run git in. Stdlib only; Python 3.8+. Not a script: box scripts
import it from box/lib (issue #36). Each keeps its own git() runner and error handling.

git_env(keep=()) returns the environment for git, and for gh, which may run git: the caller's,
minus every GIT_* variable (trace files, GIT_CONFIG_* overrides, another GIT_DIR, GIT_COMMON_DIR or
GIT_OBJECT_DIRECTORY), with optional locks and terminal prompts off and trace2 targets from the
owner's git config turned off (these variables override it). It reads os.environ at call time.

`keep` names GIT_* variables a script that writes passes through. IDENTITY is the keep-list for a
script that commits (box-bootstrap): the author and committer name, email and date, since dropping
them would change who a commit is attributed to. A read-only script keeps none.
"""
import os

IDENTITY = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE")


def git_env(keep=()):
    kept = {k.upper() for k in keep}
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("GIT_") or k.upper() in kept}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_TRACE2="0",
               GIT_TRACE2_EVENT="0", GIT_TRACE2_PERF="0")
    return env
