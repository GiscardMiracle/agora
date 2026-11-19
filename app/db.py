import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    image       TEXT NOT NULL,
    command     TEXT NOT NULL,
    timeout     INTEGER NOT NULL DEFAULT 60,
    memory_mb   INTEGER NOT NULL DEFAULT 512,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS folders (
    path TEXT PRIMARY KEY   -- "C/week-1": every ancestor has its own row too
);

CREATE TABLE IF NOT EXISTS job_shares (
    job_id  INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (job_id, user_id)
);

CREATE TABLE IF NOT EXISTS job_files (
    id      INTEGER PRIMARY KEY,
    job_id  INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    name    TEXT NOT NULL,
    content BLOB NOT NULL,
    UNIQUE (job_id, name)
);

CREATE TABLE IF NOT EXISTS repos (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    url        TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (job_id, url)
);

CREATE TABLE IF NOT EXISTS builds (
    id          INTEGER PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    repo_id     INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    status      TEXT NOT NULL,   -- queued | running | success | failed | timeout | cancelled | error
    exit_code   INTEGER,
    score       TEXT,
    commit_sha  TEXT,
    error       TEXT,
    queued_at   REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);

CREATE INDEX IF NOT EXISTS builds_repo ON builds(repo_id, id);
CREATE INDEX IF NOT EXISTS builds_status ON builds(status, id);

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('admin', 'corrector', 'viewer')),
    -- Bumped on password change: invalidates the sessions opened before it.
    session_version INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    last_login      REAL
);
"""

FINISHED = ("success", "failed", "timeout", "cancelled", "error")


def now() -> float:
    return time.time()


class Conn(sqlite3.Connection):
    """execute(sql, *params) instead of execute(sql, (params,))."""

    def execute(self, sql, *args):
        return super().execute(sql, args)


def _connect() -> Conn:
    conn = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None, factory=Conn)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def tx():
    """One short-lived connection per unit of work, wrapped in a transaction."""
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@contextmanager
def read():
    """Read-only unit of work: a plain deferred transaction, so readers never wait for (or block) the writer (WAL)."""
    conn = _connect()
    try:
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()


# Columns added after the first release: (table, column, definition).
MIGRATIONS = [
    ("users", "launch_limit", "INTEGER NOT NULL DEFAULT 15"),
    ("users", "launch_count", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "ssh_public_key", "TEXT"),
    ("builds", "user_id", "INTEGER"),
    ("jobs", "owner_id", "INTEGER"),
    ("folders", "owner_id", "INTEGER"),
    ("jobs", "folder", "TEXT NOT NULL DEFAULT ''"),
    ("jobs", "github_org", "TEXT NOT NULL DEFAULT ''"),
    ("jobs", "repo_pattern", "TEXT NOT NULL DEFAULT ''"),
    ("repos", "renamed", "INTEGER NOT NULL DEFAULT 0"),
    ("repos", "note", "TEXT NOT NULL DEFAULT ''"),
    ("builds", "failed_tests", "TEXT"),  # JSON [[section, label], ...] of the tests printed as failed
]


def _migrate(conn: Conn) -> None:
    for table, column, definition in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    # Jobs and folders created before ownership existed belong to the first admin.
    first = conn.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
    if first:
        conn.execute("UPDATE jobs SET owner_id=? WHERE owner_id IS NULL", first["id"])
        conn.execute("UPDATE folders SET owner_id=? WHERE owner_id IS NULL", first["id"])


def init() -> None:
    config.ensure_dirs()
    conn = _connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
    finally:
        conn.close()


def rows(conn: Conn, sql: str, *args) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, *args).fetchall()]


def row(conn: Conn, sql: str, *args) -> dict | None:
    r = conn.execute(sql, *args).fetchone()
    return dict(r) if r else None
