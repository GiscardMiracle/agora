"""Similarity between the repositories of a job, to spot copied code.

Each clone is reduced to a *fingerprint*: its source files are tokenised with identifiers, numbers
and strings flattened (so renaming variables or changing comments changes nothing), cut into
overlapping runs of K tokens that are hashed, and winnowed (Schleimer et al., "Winnowing") to keep a
small stable subset. Fingerprints are stored; the clone itself is deleted as before.

Comparing two repositories = how much of the smaller one appears in the other. Code that most of the
class shares (the provided skeleton, a header every project includes) is ignored.
"""
import os
import re
import zlib
from array import array
from collections import Counter, defaultdict
from pathlib import Path

K = 7                    # tokens per hash
WINDOW = 4               # winnowing window
MAX_HASHES = 4000        # per repository
MAX_FILE = 300_000       # bytes: bigger files are generated or vendored
MAX_FILES = 400
MIN_HASHES = 40          # fewer than this = too little code to compare
COMMON = 0.25            # a hash found in this fraction of the repositories is boilerplate

SOURCE = {".c", ".h", ".cpp", ".hpp", ".cc", ".hh", ".cs", ".java", ".js", ".ts", ".go", ".rs", ".py", ".sh",
          ".hs", ".ml", ".rb", ".php", ".swift", ".kt", ".lua"}
HASH_COMMENT = {".py", ".sh", ".rb", ".ml"}  # '#' starts a comment there (in C it is a preprocessor line)
SKIP_DIRS = {".git", "node_modules", "build", "dist", "target", "venv", ".venv", "__pycache__", "vendor", "bonus_assets"}

KEYWORDS = set("""auto break case char const continue default do double else enum extern float for goto if inline int long
register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while
class public private protected namespace template typename using new delete try catch throw virtual override final
def elif except finally from global import in is lambda nonlocal not or and pass raise with yield async await
fn let mut impl trait match mod pub use func var interface package fi then done esac function""".split())

TOKEN = re.compile(r"""
    (?P<str>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')
  | (?P<num>0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?)
  | (?P<id>[A-Za-z_]\w*)
  | (?P<op>->|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^~!<>=?:;,.(){}\[\]])
""", re.X)
C_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
HASH_COMMENTS = re.compile(r"#[^\n]*")


def tokens(text: str, ext: str) -> list[str]:
    text = C_COMMENTS.sub(" ", text)
    if ext in HASH_COMMENT:
        text = HASH_COMMENTS.sub(" ", text)
    out = []
    for m in TOKEN.finditer(text):
        kind = m.lastgroup
        if kind == "id":
            w = m[0]
            out.append(w if w in KEYWORDS else "I")
        elif kind == "num":
            out.append("N")
        elif kind == "str":
            out.append("S")
        else:
            out.append(m[0])
    return out


def _hash(gram: tuple) -> int:
    return zlib.crc32(" ".join(gram).encode())


def winnow(toks: list[str]) -> set[int]:
    if len(toks) < K:
        return set()
    hs = [_hash(tuple(toks[i:i + K])) for i in range(len(toks) - K + 1)]
    if len(hs) <= WINDOW:
        return {min(hs)}
    out, last = set(), -1
    for i in range(len(hs) - WINDOW + 1):
        w = hs[i:i + WINDOW]
        m = min(w)
        j = i + len(w) - 1 - w[::-1].index(m)  # rightmost minimum
        if j != last:
            out.add(m)
            last = j
    return out


def _source_files(root: Path):
    """Source files of the clone, never following symlinks (the repository is untrusted)."""
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            path = Path(dirpath) / name
            if path.suffix.lower() in SOURCE and not path.is_symlink():
                yield path


def fingerprint(root: Path) -> set[int]:
    found: set[int] = set()
    for seen, path in enumerate(_source_files(root)):
        if seen >= MAX_FILES:
            break
        try:
            if path.stat().st_size > MAX_FILE:
                continue
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        found |= winnow(tokens(text, path.suffix.lower()))
    return set(sorted(found)[:MAX_HASHES])


def pack(hashes: set[int]) -> bytes:
    return zlib.compress(array("I", sorted(hashes)).tobytes())


def unpack(blob: bytes) -> set[int]:
    a = array("I")
    a.frombytes(zlib.decompress(blob))
    return set(a)


def compare(prints: dict[int, set[int]], threshold: float = 0.5, limit: int = 200) -> list[dict]:
    """prints: repo_id -> hashes. Returns the most similar pairs, best first."""
    n = len(prints)
    if n < 2:
        return []
    df = Counter(h for hs in prints.values() for h in hs)
    cap = max(3, int(COMMON * n))
    cleaned = {r: {h for h in hs if df[h] < cap} for r, hs in prints.items()}
    cleaned = {r: hs for r, hs in cleaned.items() if len(hs) >= MIN_HASHES}
    index: dict[int, list[int]] = defaultdict(list)
    for r, hs in cleaned.items():
        for h in hs:
            index[h].append(r)
    shared: Counter = Counter()
    for owners in index.values():
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                shared[(owners[i], owners[j])] += 1
    pairs = []
    for (a, b), s in shared.items():
        score = s / min(len(cleaned[a]), len(cleaned[b]))
        if score >= threshold:
            pairs.append({"a": a, "b": b, "score": round(score, 3), "shared": s})
    pairs.sort(key=lambda p: (-p["score"], -p["shared"]))
    return pairs[:limit]
