"""Coding-style violations found in a build log.

Understood (anything else is ignored):
  epiclang   file.c:38:14: warning: [Banana] [Major] nested if statement at depth 3 (C-C1)
  banana     ./file.c:12: MAJOR:C-F3 # message
  other      file.c:4:1: warning: message [C-F4]     (a rule id on a clang diagnostic)

A violation is identified by (file, line, column, rule): a Makefile that rebuilds several times prints
the same warning each time and it is still counted once.
A build whose log shows the checker running (even with nothing to report) has a style result of 0/0/0,
so a clean repository shows a clean score instead of a blank.
"""
import re

SEVERITIES = ("major", "minor", "info")
MAX_ITEMS = 300      # stored per build
MAX_TRACKED = 5000   # distinct violations counted per build

EPICLANG = re.compile(
    r"^\s*(?P<file>[^\s:][^:]*):(?P<line>\d+):(?P<col>\d+):\s*(?:warning|error):\s*"
    r"\[Banana\]\s*\[(?P<sev>Major|Minor|Info)\]\s*(?P<msg>.*?)\s*\((?P<rule>C-[A-Z]\d+)\)\s*$")
BANANA = re.compile(
    r"^\s*(?P<file>[^\s:][^:]*):(?P<line>\d+):\s*(?P<sev>MAJOR|MINOR|INFO)\s*:\s*(?P<rule>C-[A-Z]\d+)\s*(?:#\s*(?P<msg>.*?))?\s*$")
GENERIC = re.compile(
    r"^\s*(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<kind>warning|error):\s*(?P<msg>.*?)\s*"
    r"\[?\(?(?P<rule>C-[A-Z]\d+)\)?\]?\s*$")
# "epiclang -o prog a.c b.c" in the echoed make command, or banana-check-repo anywhere
CHECKER_RUN = re.compile(r"(?:^|[\s;&|/])(?:epiclang|banana-check-repo)(?:\s|$)")


def parse_line(text: str) -> dict | None:
    if m := EPICLANG.match(text):
        sev = m["sev"].lower()
    elif m := BANANA.match(text):
        sev = m["sev"].lower()
    elif m := GENERIC.match(text):
        sev = "major" if m["kind"] == "error" else "minor"
    else:
        return None
    g = m.groupdict()
    return {"file": g["file"].removeprefix("./"), "line": int(g["line"]), "col": int(g.get("col") or 0),
            "sev": sev, "rule": g["rule"], "msg": (g.get("msg") or "")[:200]}


class Collector:
    def __init__(self) -> None:
        self.checked = False
        self._seen: dict[tuple, dict] = {}

    def feed(self, text: str) -> None:
        v = parse_line(text)
        if v:
            self.checked = True
            if len(self._seen) < MAX_TRACKED:
                self._seen.setdefault((v["file"], v["line"], v["col"], v["rule"]), v)
        elif not self.checked and CHECKER_RUN.search(text):
            self.checked = True

    @property
    def counts(self) -> dict:
        c = dict.fromkeys(SEVERITIES, 0)
        for v in self._seen.values():
            c[v["sev"]] += 1
        return c

    @property
    def items(self) -> list[dict]:
        order = {s: i for i, s in enumerate(SEVERITIES)}
        return sorted(self._seen.values(), key=lambda v: (order[v["sev"]], v["file"], v["line"], v["col"]))[:MAX_ITEMS]
