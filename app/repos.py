"""Parsing of repository lists (uploaded .txt/.csv or pasted text)."""

import re

# https://github.com/org/repo(.git) | github.com/org/repo | git@github.com:org/repo(.git)
_HTTPS = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", re.I)
_SSH = re.compile(r"^git@github\.com:([\w.-]+)/([\w.-]+?)(?:\.git)?$", re.I)
_SPLIT = re.compile(r"[,;\t ]+")


def normalize(token: str) -> tuple[str, str] | None:
    """Return (canonical_url, repo_name) or None if token is not a GitHub repo."""
    token = token.strip().strip("\"'")
    if m := _SSH.match(token):
        return f"git@github.com:{m[1]}/{m[2]}.git", m[2]
    if m := _HTTPS.match(token):
        return f"https://github.com/{m[1]}/{m[2]}.git", m[2]
    return None


def parse_list(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Parse one repo per line. Any extra tokens on the line become the display name.

    Accepted lines:
        https://github.com/my-org/day01-john.doe
        john.doe, git@github.com:my-org/day01-john.doe.git
        # comments and empty lines are ignored
    Returns (entries, rejected_lines).
    """
    entries: list[tuple[str, str]] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = [t for t in _SPLIT.split(line) if t]
        found = None
        rest = []
        for t in tokens:
            n = normalize(t) if found is None else None
            if n:
                found = n
            else:
                rest.append(t.strip("\"'"))
        if not found:
            rejected.append(line)
            continue
        url, repo_name = found
        if url in seen:
            continue
        seen.add(url)
        entries.append((url, " ".join(rest) or repo_name))
    return entries, rejected
