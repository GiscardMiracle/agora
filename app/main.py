import csv
import io
import logging
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from . import config, db, repos, users
from .runner import Runner, log_path, remove_logs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC = Path(__file__).resolve().parent.parent / "static"
FILE_NAME_RE = re.compile(r"^[\w.+-]+(/[\w.+-]+)*$")
ACTIVE = ("queued", "running")

runner = Runner()


def _secret() -> str:
    if config.SECRET:
        return config.SECRET
    config.ensure_dirs()
    p = config.DATA_DIR / ".secret"
    if not p.exists():
        p.write_text(secrets.token_hex(32))
        p.chmod(0o600)
    return p.read_text().strip()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    users.bootstrap()
    await runner.start()
    yield
    await runner.stop()


app = FastAPI(title="Agora", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=_secret(), session_cookie="agora_session",
    max_age=7 * 24 * 3600, same_site="lax",
    https_only=os.environ.get("AGORA_HTTPS", "0") == "1",
)


def current_user(request: Request) -> dict | None:
    uid = request.session.get("uid")
    if uid is None:
        return None
    with db.tx() as c:
        u = db.row(c, "SELECT id, username, role, session_version FROM users WHERE id=?", uid)
    return u if u and u["session_version"] == request.session.get("sv") else None


def require_auth(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "not authenticated")
    return user


def require_write(request: Request, user: dict = Depends(require_auth)) -> None:
    """Viewers can read everything but change nothing."""
    if request.method not in ("GET", "HEAD") and user["role"] == "viewer":
        raise HTTPException(403, "read-only account")


def require_admin(user: dict = Depends(require_auth)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "admin only")
    return user


api = APIRouter(prefix="/api", dependencies=[Depends(require_write)])
admin = APIRouter(prefix="/api/users", dependencies=[Depends(require_admin)])
public = APIRouter(prefix="/api")


# ---------------- helpers ----------------

def get_or_404(c, sql: str, *args) -> dict:
    r = db.row(c, sql, *args)
    if not r:
        raise HTTPException(404, "not found")
    return r


def check_file_name(name: str) -> str:
    name = name.strip().lstrip("/")
    if not FILE_NAME_RE.match(name) or any(p in (".", "..") for p in name.split("/")):
        raise HTTPException(400, f"invalid file name: {name!r}")
    return name


def enqueue(c, job_id: int, repo_ids: list[int]) -> int:
    busy = {
        r["repo_id"] for r in db.rows(
            c, "SELECT repo_id FROM builds WHERE job_id=? AND status IN ('queued','running')", job_id
        )
    }
    n = 0
    for rid in repo_ids:
        if rid in busy:
            continue
        c.execute(
            "INSERT INTO builds (job_id, repo_id, status, queued_at) VALUES (?, ?, 'queued', ?)",
            job_id, rid, db.now(),
        )
        n += 1
    return n


def cancel_active(c, where: str, *args) -> list[int]:
    return [r["id"] for r in db.rows(c, f"SELECT id FROM builds WHERE status IN ('queued','running') AND {where}", *args)]


# ---------------- auth ----------------

class Login(BaseModel):
    username: str
    password: str


def public_user(u: dict) -> dict:
    return {"id": u["id"], "username": u["username"], "role": u["role"]}


def open_session(request: Request, user_id: int, session_version: int) -> None:
    request.session["uid"] = user_id
    request.session["sv"] = session_version


@public.post("/login")
def login(body: Login, request: Request):
    with db.tx() as c:
        u = db.row(c, "SELECT * FROM users WHERE username=?", body.username.strip())
    # Hashing is slow on purpose: stay out of the write transaction meanwhile.
    if not users.verify_password(body.password, u["password_hash"] if u else None):
        raise HTTPException(401, "wrong username or password")
    with db.tx() as c:
        c.execute("UPDATE users SET last_login=? WHERE id=?", db.now(), u["id"])
    request.session.clear()
    open_session(request, u["id"], u["session_version"])
    return public_user(u)


@public.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@public.get("/me")
def me(request: Request):
    u = current_user(request)
    return {"user": public_user(u) if u else None}


class PasswordChange(BaseModel):
    current: str
    new: str = Field(min_length=users.MIN_PASSWORD, max_length=200)


@public.post("/me/password")
def change_password(body: PasswordChange, request: Request, user: dict = Depends(require_auth)):
    with db.tx() as c:
        stored = db.row(c, "SELECT password_hash FROM users WHERE id=?", user["id"])["password_hash"]
    if not users.verify_password(body.current, stored):
        raise HTTPException(400, "mot de passe actuel incorrect")
    new_hash = users.hash_password(body.new)
    with db.tx() as c:
        c.execute(
            "UPDATE users SET password_hash=?, session_version=session_version+1 WHERE id=?",
            new_hash, user["id"],
        )
    # Other devices are logged out; this one stays connected.
    open_session(request, user["id"], user["session_version"] + 1)
    return {"ok": True}


# ---------------- users (admin only) ----------------

USERNAME = r"^[\w.@-]{2,60}$"
Role = Literal["admin", "corrector", "viewer"]
Password = Annotated[str, Field(min_length=users.MIN_PASSWORD, max_length=200)]


class UserIn(BaseModel):
    username: str = Field(pattern=USERNAME)
    password: Password
    role: Role


class UserPatch(BaseModel):
    role: Role | None = None
    password: Password | None = None


@admin.get("")
def list_users():
    with db.tx() as c:
        return db.rows(c, "SELECT id, username, role, created_at, last_login FROM users ORDER BY username COLLATE NOCASE")


@admin.post("")
def create_user(body: UserIn):
    password_hash = users.hash_password(body.password)
    try:
        with db.tx() as c:
            cur = c.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                body.username, password_hash, body.role, db.now(),
            )
            return {"id": cur.lastrowid}
    except sqlite3.IntegrityError:
        raise HTTPException(409, "ce nom d'utilisateur existe déjà")


@admin.patch("/{user_id}")
def update_user(user_id: int, body: UserPatch, me: dict = Depends(require_admin)):
    # An admin cannot demote or delete themselves, so there is always at least one admin left.
    if user_id == me["id"] and body.role not in (None, "admin"):
        raise HTTPException(400, "tu ne peux pas changer ton propre rôle")
    password_hash = users.hash_password(body.password) if body.password else None
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM users WHERE id=?", user_id)
        if body.role:
            c.execute("UPDATE users SET role=? WHERE id=?", body.role, user_id)
        if password_hash:
            c.execute(
                "UPDATE users SET password_hash=?, session_version=session_version+1 WHERE id=?",
                password_hash, user_id,
            )
    return {"ok": True}


@admin.delete("/{user_id}")
def delete_user(user_id: int, me: dict = Depends(require_admin)):
    if user_id == me["id"]:
        raise HTTPException(400, "tu ne peux pas supprimer ton propre compte")
    with db.tx() as c:
        c.execute("DELETE FROM users WHERE id=?", user_id)
    return {"ok": True}


# ---------------- jobs ----------------

class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    image: str = Field(default=config.DEFAULT_IMAGE, min_length=1)
    command: str = Field(default="bash /tests/tests.sh", min_length=1)
    timeout: int = Field(default=60, ge=1, le=3600)
    memory_mb: int = Field(default=512, ge=64, le=4096)


@api.get("/jobs")
def list_jobs():
    with db.tx() as c:
        return db.rows(
            c,
            "SELECT j.*, "
            " (SELECT COUNT(*) FROM repos r WHERE r.job_id=j.id) AS repo_count, "
            " (SELECT COUNT(*) FROM builds b WHERE b.job_id=j.id AND b.status IN ('queued','running')) AS active, "
            " (SELECT MAX(COALESCE(finished_at, started_at, queued_at)) FROM builds b WHERE b.job_id=j.id) AS last_activity, "
            " (SELECT COUNT(*) FROM repos r JOIN builds b ON b.id = (SELECT MAX(id) FROM builds WHERE repo_id=r.id) "
            "   WHERE r.job_id=j.id AND b.status='success') AS ok, "
            " (SELECT COUNT(*) FROM repos r JOIN builds b ON b.id = (SELECT MAX(id) FROM builds WHERE repo_id=r.id) "
            "   WHERE r.job_id=j.id AND b.status IN ('failed','timeout','error')) AS ko "
            "FROM jobs j ORDER BY j.updated_at DESC",
        )


@api.post("/jobs")
def create_job(body: JobIn):
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO jobs (name, description, image, command, timeout, memory_mb, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            body.name.strip(), body.description, body.image.strip(), body.command,
            body.timeout, body.memory_mb, db.now(), db.now(),
        )
        return {"id": cur.lastrowid}


@api.get("/jobs/{job_id}")
def get_job(job_id: int):
    with db.tx() as c:
        job = get_or_404(c, "SELECT * FROM jobs WHERE id=?", job_id)
        job["files"] = db.rows(
            c, "SELECT name, length(content) AS size FROM job_files WHERE job_id=? ORDER BY name", job_id
        )
        job["repos"] = db.rows(
            c,
            "SELECT r.id, r.name, r.url, b.id AS build_id, b.status, b.score, b.exit_code, "
            " b.commit_sha, b.queued_at, b.started_at, b.finished_at "
            "FROM repos r LEFT JOIN builds b ON b.id = (SELECT MAX(id) FROM builds WHERE repo_id=r.id) "
            "WHERE r.job_id=? ORDER BY r.name COLLATE NOCASE",
            job_id,
        )
        return job


@api.put("/jobs/{job_id}")
def update_job(job_id: int, body: JobIn):
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM jobs WHERE id=?", job_id)
        c.execute(
            "UPDATE jobs SET name=?, description=?, image=?, command=?, timeout=?, memory_mb=?, updated_at=? "
            "WHERE id=?",
            body.name.strip(), body.description, body.image.strip(), body.command,
            body.timeout, body.memory_mb, db.now(), job_id,
        )
    return {"ok": True}


@api.post("/jobs/{job_id}/duplicate")
def duplicate_job(job_id: int):
    with db.tx() as c:
        j = get_or_404(c, "SELECT * FROM jobs WHERE id=?", job_id)
        cur = c.execute(
            "INSERT INTO jobs (name, description, image, command, timeout, memory_mb, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            f"{j['name']} (copy)", j["description"], j["image"], j["command"],
            j["timeout"], j["memory_mb"], db.now(), db.now(),
        )
        c.execute(
            "INSERT INTO job_files (job_id, name, content) SELECT ?, name, content FROM job_files WHERE job_id=?",
            cur.lastrowid, job_id,
        )
        return {"id": cur.lastrowid}


@api.delete("/jobs/{job_id}")
def delete_job(job_id: int):
    with db.tx() as c:
        active = cancel_active(c, "job_id=?", job_id)
    for bid in active:
        runner.cancel(bid)
    with db.tx() as c:
        ids = [r["id"] for r in db.rows(c, "SELECT id FROM builds WHERE job_id=?", job_id)]
        c.execute("DELETE FROM jobs WHERE id=?", job_id)
    remove_logs(ids)
    return {"ok": True}


# ---------------- job files ----------------

@api.post("/jobs/{job_id}/files")
async def upload_files(job_id: int, files: list[UploadFile] = File(...)):
    payload = [(check_file_name(f.filename or ""), await f.read()) for f in files]
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM jobs WHERE id=?", job_id)
        for name, content in payload:
            c.execute(
                "INSERT INTO job_files (job_id, name, content) VALUES (?, ?, ?) "
                "ON CONFLICT (job_id, name) DO UPDATE SET content=excluded.content",
                job_id, name, content,
            )
        c.execute("UPDATE jobs SET updated_at=? WHERE id=?", db.now(), job_id)
    return {"ok": True, "count": len(payload)}


@api.get("/jobs/{job_id}/files/{name:path}")
def read_file(job_id: int, name: str):
    with db.tx() as c:
        f = get_or_404(c, "SELECT content FROM job_files WHERE job_id=? AND name=?", job_id, name)
    try:
        return {"name": name, "content": f["content"].decode(), "binary": False}
    except UnicodeDecodeError:
        return {"name": name, "content": "", "binary": True}


class FileIn(BaseModel):
    content: str


@api.put("/jobs/{job_id}/files/{name:path}")
def write_file(job_id: int, name: str, body: FileIn):
    name = check_file_name(name)
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM jobs WHERE id=?", job_id)
        c.execute(
            "INSERT INTO job_files (job_id, name, content) VALUES (?, ?, ?) "
            "ON CONFLICT (job_id, name) DO UPDATE SET content=excluded.content",
            job_id, name, body.content.replace("\r\n", "\n").encode(),
        )
        c.execute("UPDATE jobs SET updated_at=? WHERE id=?", db.now(), job_id)
    return {"ok": True}


@api.delete("/jobs/{job_id}/files/{name:path}")
def delete_file(job_id: int, name: str):
    with db.tx() as c:
        c.execute("DELETE FROM job_files WHERE job_id=? AND name=?", job_id, name)
    return {"ok": True}


# ---------------- repos ----------------

@api.post("/jobs/{job_id}/repos")
async def add_repos(job_id: int, text: str = Form(""), file: UploadFile | None = File(None)):
    content = text
    if file is not None:
        content += "\n" + (await file.read()).decode(errors="replace")
    entries, rejected = repos.parse_list(content)
    added = 0
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM jobs WHERE id=?", job_id)
        for url, name in entries:
            cur = c.execute(
                "INSERT OR IGNORE INTO repos (job_id, name, url, created_at) VALUES (?, ?, ?, ?)",
                job_id, name, url, db.now(),
            )
            added += cur.rowcount
    return {"added": added, "duplicates": len(entries) - added, "rejected": rejected}


@api.delete("/repos/{repo_id}")
def delete_repo(repo_id: int):
    with db.tx() as c:
        active = cancel_active(c, "repo_id=?", repo_id)
    for bid in active:
        runner.cancel(bid)
    with db.tx() as c:
        ids = [r["id"] for r in db.rows(c, "SELECT id FROM builds WHERE repo_id=?", repo_id)]
        c.execute("DELETE FROM repos WHERE id=?", repo_id)
    remove_logs(ids)
    return {"ok": True}


@api.get("/repos/{repo_id}/builds")
def repo_builds(repo_id: int):
    with db.tx() as c:
        repo = get_or_404(c, "SELECT * FROM repos WHERE id=?", repo_id)
        repo["builds"] = db.rows(c, "SELECT * FROM builds WHERE repo_id=? ORDER BY id DESC", repo_id)
        return repo


# ---------------- runs ----------------

class RunIn(BaseModel):
    repo_ids: list[int] | None = None


@api.post("/jobs/{job_id}/run")
def run_job(job_id: int, body: RunIn):
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM jobs WHERE id=?", job_id)
        all_ids = [r["id"] for r in db.rows(c, "SELECT id FROM repos WHERE job_id=? ORDER BY name COLLATE NOCASE", job_id)]
        ids = all_ids if body.repo_ids is None else [i for i in body.repo_ids if i in set(all_ids)]
        return {"queued": enqueue(c, job_id, ids)}


@api.post("/repos/{repo_id}/run")
def run_repo(repo_id: int):
    with db.tx() as c:
        r = get_or_404(c, "SELECT job_id FROM repos WHERE id=?", repo_id)
        queued = enqueue(c, r["job_id"], [repo_id])
        last = db.row(c, "SELECT MAX(id) AS id FROM builds WHERE repo_id=?", repo_id)
        return {"queued": queued, "build_id": last["id"]}


@api.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    with db.tx() as c:
        active = cancel_active(c, "job_id=?", job_id)
    return {"cancelled": sum(runner.cancel(bid) for bid in active)}


@api.post("/builds/{build_id}/cancel")
def cancel_build(build_id: int):
    return {"ok": runner.cancel(build_id)}


@api.get("/builds/{build_id}")
def get_build(build_id: int):
    with db.tx() as c:
        return get_or_404(
            c,
            "SELECT b.*, r.name AS repo_name, r.url AS repo_url, j.name AS job_name "
            "FROM builds b JOIN repos r ON r.id=b.repo_id JOIN jobs j ON j.id=b.job_id WHERE b.id=?",
            build_id,
        )


@api.get("/builds/{build_id}/log")
def build_log(build_id: int, offset: int = 0):
    """Incremental log: returns raw bytes from `offset`; the client polls until X-Done is 1."""
    with db.tx() as c:
        b = get_or_404(c, "SELECT status FROM builds WHERE id=?", build_id)
    finished = b["status"] in db.FINISHED  # read status *before* the file to never miss a tail
    data = b""
    p = log_path(build_id)
    if p.exists():
        with open(p, "rb") as f:
            f.seek(max(0, offset))
            data = f.read(512 * 1024)
    nxt = offset + len(data)
    done = finished and (not p.exists() or nxt >= p.stat().st_size)
    return Response(
        content=data, media_type="application/octet-stream",
        headers={"X-Next-Offset": str(nxt), "X-Done": "1" if done else "0", "X-Status": b["status"],
                 "Cache-Control": "no-store"},
    )


@api.get("/jobs/{job_id}/export.csv")
def export_csv(job_id: int):
    job = get_job(job_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "url", "status", "score", "exit_code", "commit", "finished_at"])
    for r in job["repos"]:
        fin = datetime.fromtimestamp(r["finished_at"]).isoformat(timespec="seconds") if r["finished_at"] else ""
        w.writerow([r["name"], r["url"], r["status"] or "", r["score"] or "", r["exit_code"] if r["exit_code"] is not None else "",
                    r["commit_sha"] or "", fin])
    safe = re.sub(r"[^\w.-]+", "_", job["name"]) or "job"
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.csv"'})


app.include_router(public)
app.include_router(admin)
app.include_router(api)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.api_route("/", methods=["GET", "HEAD"])
def index():
    return FileResponse(STATIC / "index.html")
