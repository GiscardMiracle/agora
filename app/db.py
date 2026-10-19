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


def init() -> None:
    config.ensure_dirs()
    conn = _connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def rows(conn: Conn, sql: str, *args) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, *args).fetchall()]


def row(conn: Conn, sql: str, *args) -> dict | None:
    r = conn.execute(sql, *args).fetchone()
    return dict(r) if r else None
