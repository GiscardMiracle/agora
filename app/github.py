"""GitHub API: list the repositories of an organisation and name each group after its authors."""
import fnmatch
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config

API = "https://api.github.com"
ORG_RE = re.compile(r"^[\w.-]{1,100}$")


class GitHubError(Exception):
    """Message is safe to show to the user."""


def _get(path: str, params: dict | None = None):
    if not config.GITHUB_TOKEN:
        raise GitHubError("AGORA_GITHUB_TOKEN is not set on the server (read-only GitHub token).")
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agora",
    })
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise GitHubError("GitHub token is invalid or expired.")
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if e.code in (403, 429) and retry_after and retry_after.isdigit() and int(retry_after) <= 20:
                last = e
                time.sleep(int(retry_after))  # secondary rate limit: GitHub says how long to wait
                continue
            if e.code in (403, 429):
                raise GitHubError("GitHub API rate limit reached (or access denied). Try again later.")
            if e.code >= 500:  # GitHub having a bad moment
                last = e
                time.sleep(1 + attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(1 + attempt)
    raise GitHubError(f"GitHub unreachable after several attempts: {last}")


def _paginate(path: str, params: dict, max_pages: int):
    for page in range(1, max_pages + 1):
        items = _get(path, {**params, "per_page": 100, "page": page})
        yield from items
        if len(items) < 100:
            return


def matches(name: str, pattern: str) -> bool:
    """Glob by default (day06-*), or a regex when the pattern starts with 're:'."""
    if pattern.startswith("re:"):
        try:
            return re.search(pattern[3:], name, re.I) is not None
        except re.error as e:
            raise GitHubError(f"Invalid regular expression: {e}")
    return fnmatch.fnmatchcase(name.lower(), pattern.lower())


def list_repos(owner: str, pattern: str) -> list[str]:
    """Names of the repositories of `owner` (organisation or user) matching the pattern.

    Two sources are merged: the organisation's own listing (members see private repos there) and the
    caller's repositories (collaborators only see the repos they were invited to there).
    """
    if not ORG_RE.match(owner):
        raise GitHubError("Invalid organization name.")
    matches("", pattern)  # validates a regex early

    def from_org() -> set[str]:
        try:
            return {r["name"] for r in _paginate(f"/orgs/{owner}/repos", {"type": "all"}, 100)}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise GitHubError(f"GitHub error {e.code}.")
        try:  # not an organisation: a plain user account
            return {r["name"] for r in _paginate(f"/users/{owner}/repos", {"type": "owner"}, 100)}
        except urllib.error.HTTPError:
            return set()

    def from_me() -> set[str]:
        try:
            mine = _paginate("/user/repos", {"affiliation": "owner,collaborator,organization_member"}, 100)
            return {r["name"] for r in mine if (r.get("owner") or {}).get("login", "").lower() == owner.lower()}
        except urllib.error.HTTPError as e:
            raise GitHubError(f"GitHub error {e.code}.")

    with ThreadPoolExecutor(max_workers=2) as pool:  # the two listings are independent: fetch them together
        a, b = pool.submit(from_org), pool.submit(from_me)
        names = a.result() | b.result()
    if not names:
        raise GitHubError(f'No repository of "{owner}" is visible to the GitHub token (wrong organization name, '
                          "or the token cannot access it: use a classic token with the repo scope).")
    return sorted(n for n in names if matches(n, pattern))


def _wanted(email: str) -> bool:
    if "@" not in email or "noreply" in email:
        return False
    return email.endswith(config.EMAIL_DOMAIN) if config.EMAIL_DOMAIN else True


def authors(owner: str, repo: str) -> list[str]:
    """Distinct author emails (restricted to AGORA_EMAIL_DOMAIN when set) that committed to the repository ([] if empty or unreadable)."""
    seen: dict[str, None] = {}
    try:
        for c in _paginate(f"/repos/{owner}/{repo}/commits", {}, 2):
            email = ((c.get("commit") or {}).get("author") or {}).get("email", "").strip().lower()
            if _wanted(email):
                seen[email] = None
    except (urllib.error.HTTPError, GitHubError):
        pass  # 409 = empty repository, 404/403 = no access: fall back to the repo number
    return sorted(seen)


def fallback_name(repo: str) -> str:
    m = re.search(r"(\d+)\D*$", repo)
    return f"#{m[1]}" if m else repo


def group_name(owner: str, repo: str) -> str:
    emails = authors(owner, repo)
    return ", ".join(emails) if emails else fallback_name(repo)


def names_for(owner: str, repos: list[str]) -> dict[str, str]:
    with ThreadPoolExecutor(max_workers=12) as pool:
        return dict(zip(repos, pool.map(lambda r: group_name(owner, r), repos)))
