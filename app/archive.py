"""Export a job's history as a ZIP, and purge old builds.

ZIP layout (one per job):
    builds.csv                    every stored build: repo, status, score, commit, dates, log file
    logs/<repo-slug>/<build>.log  raw terminal output (ANSI colours kept)
"""
import asyncio
import csv
import io
import logging
import re
import zipfile
from datetime import datetime

from . import config, db
from .runner import log_path, remove_logs

log = logging.getLogger("agora.archive")
PURGE_EVERY = 6 * 3600


def slug(text: str) -> str:
    return re.sub(r"[^\w.@+-]+", "_", text).strip("_")[:80] or "repo"


def _iso(ts) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else ""


def build_zip(job_id: int) -> tuple[str, bytes]:
    with db.read() as c:
        job = db.row(c, "SELECT name FROM jobs WHERE id=?", job_id)
        if not job:
            raise KeyError(job_id)
        builds = db.rows(
            c,
            "SELECT b.id, b.status, b.score, b.exit_code, b.commit_sha, b.error, b.queued_at, b.started_at, "
            " b.finished_at, r.name AS repo_name, r.url AS repo_url "
            "FROM builds b JOIN repos r ON r.id=b.repo_id WHERE b.job_id=? ORDER BY r.name COLLATE NOCASE, b.id",
            job_id,
        )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["build", "repo", "url", "status", "score", "exit_code", "commit", "error", "queued_at", "started_at", "finished_at", "log"])
        for b in builds:
            p = log_path(b["id"])
            name = f"logs/{slug(b['repo_name'])}/{b['id']}.log"
            has_log = p.is_file()
            if has_log:
                try:
                    z.write(p, name)
                except OSError:
                    has_log = False  # purged while we were zipping
            w.writerow([b["id"], b["repo_name"], b["repo_url"], b["status"], b["score"] or "",
                        "" if b["exit_code"] is None else b["exit_code"], b["commit_sha"] or "", b["error"] or "",
                        _iso(b["queued_at"]), _iso(b["started_at"]), _iso(b["finished_at"]), name if has_log else ""])
        z.writestr("builds.csv", out.getvalue())
    return f"{slug(job['name'])}-{datetime.now():%Y%m%d}.zip", buf.getvalue()


def purge_old(days: int | None = None) -> int:
    """Delete finished builds (and their logs) older than the retention. Returns how many."""
    days = config.RETENTION_DAYS if days is None else days
    if days <= 0:
        return 0
    cutoff = db.now() - days * 86400
    with db.tx() as c:
        ids = [r["id"] for r in db.rows(
            c,
            "SELECT id FROM builds WHERE status IN ('success','failed','timeout','cancelled','error') "
            "AND COALESCE(finished_at, queued_at) < ?", cutoff,
        )]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            c.execute(f"DELETE FROM builds WHERE id IN ({','.join('?' * len(chunk))})", *chunk)
    remove_logs(ids)
    # Logs whose build no longer exists (crash between delete and unlink) are cleaned too.
    with db.read() as c:
        alive = {r["id"] for r in db.rows(c, "SELECT id FROM builds")}
    for p in config.LOGS_DIR.glob("*.log"):
        if p.stem.isdigit() and int(p.stem) not in alive and p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
    return len(ids)


async def purge_loop() -> None:
    while True:
        try:
            n = await asyncio.to_thread(purge_old)
            if n:
                log.info("purged %d builds older than %d days", n, config.RETENTION_DAYS)
        except Exception:
            log.exception("purge failed")
        await asyncio.sleep(PURGE_EVERY)
