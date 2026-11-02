"""The environment box scripts run git in. Stdlib only; Python 3.8+. Not a script: box-audit's
collect.py and orchestrate's handoff_check.py load this file by path. Each keeps its own git()
runner and error handling.

git_env() returns the environment for git, and for gh, which may run git: the caller's, minus
every GIT_* variable (trace files, GIT_CONFIG_* overrides, another GIT_DIR), with optional locks
and terminal prompts off and trace2 targets from the owner's git config turned off (these
variables override it). It reads os.environ at call time.
"""
import os


def git_env():
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_TRACE2="0",
               GIT_TRACE2_EVENT="0", GIT_TRACE2_PERF="0")
    return env
