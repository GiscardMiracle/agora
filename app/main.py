import asyncio
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

from . import archive, config, db, github, keys, repos, users
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
    purger = asyncio.create_task(archive.purge_loop())
    yield
    purger.cancel()
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
    with db.read() as c:
        u = db.row(c, "SELECT id, username, role, session_version, launch_limit, launch_count FROM users WHERE id=?", uid)
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


def enqueue(c, job_id: int, repo_ids: list[int], user: dict) -> int:
    """Queue builds for `user`. Enforces the SSH key and the launch quota (admins are exempt)."""
    if not keys.has_key(user["id"]):
        raise HTTPException(400, "You have no SSH key, so repositories cannot be cloned. "
                                 "Generate one in \"Account\" and add it to GitHub.")
    if user["role"] != "admin":
        fresh = db.row(c, "SELECT launch_limit, launch_count FROM users WHERE id=?", user["id"])
        if not fresh or fresh["launch_count"] >= fresh["launch_limit"]:
            raise HTTPException(403, f"Launch limit reached ({fresh['launch_limit'] if fresh else 0}). "
                                     "Ask the admin to raise it.")
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
            "INSERT INTO builds (job_id, repo_id, status, queued_at, user_id) VALUES (?, ?, 'queued', ?, ?)",
            job_id, rid, db.now(), user["id"],
        )
        n += 1
    if n and user["role"] != "admin":
        c.execute("UPDATE users SET launch_count=launch_count+1 WHERE id=?", user["id"])
    return n


def job_access(c, job_id: int, user: dict) -> str | None:
    """'owner' (the creator, or any admin), 'shared', or None when the job is hidden from this user."""
    j = db.row(c, "SELECT owner_id FROM jobs WHERE id=?", job_id)
    if not j:
        return None
    if user["role"] == "admin" or j["owner_id"] == user["id"]:
        return "owner"
    if db.row(c, "SELECT 1 AS x FROM job_shares WHERE job_id=? AND user_id=?", job_id, user["id"]):
        return "shared"
    return None


def guard_job(job_id: int, user: dict, owner: bool = False) -> str:
    """404 for a job the user cannot see (its existence is not revealed); 403 if `owner` is required."""
    with db.read() as c:
        role = job_access(c, job_id, user)
    if role is None:
        raise HTTPException(404, "not found")
    if owner and role != "owner":
        raise HTTPException(403, "only the owner of this job can do that")
    return role


def guard_repo(repo_id: int, user: dict, owner: bool = False) -> int:
    with db.read() as c:
        r = db.row(c, "SELECT job_id FROM repos WHERE id=?", repo_id)
    if not r:
        raise HTTPException(404, "not found")
    guard_job(r["job_id"], user, owner)
    return r["job_id"]


def guard_build(build_id: int, user: dict) -> None:
    with db.read() as c:
        b = db.row(c, "SELECT job_id FROM builds WHERE id=?", build_id)
    if not b:
        raise HTTPException(404, "not found")
    guard_job(b["job_id"], user)


VISIBLE = "(j.owner_id = ? OR j.id IN (SELECT job_id FROM job_shares WHERE user_id = ?))"


def cancel_active(c, where: str, *args) -> list[int]:
    return [r["id"] for r in db.rows(c, f"SELECT id FROM builds WHERE status IN ('queued','running') AND {where}", *args)]


# ---------------- auth ----------------

class Login(BaseModel):
    username: str
    password: str


def public_user(u: dict) -> dict:
    out = {"id": u["id"], "username": u["username"], "role": u["role"], "has_key": keys.has_key(u["id"])}
    if "launch_limit" in u:
        out["launch_limit"] = u["launch_limit"]
        out["launch_count"] = u["launch_count"]
    return out


def open_session(request: Request, user_id: int, session_version: int) -> None:
    request.session["uid"] = user_id
    request.session["sv"] = session_version


@public.post("/login")
def login(body: Login, request: Request):
    with db.read() as c:
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


@public.get("/me/ssh-key")
def get_ssh_key(user: dict = Depends(require_auth)):
    with db.read() as c:
        u = db.row(c, "SELECT ssh_public_key FROM users WHERE id=?", user["id"])
    has = keys.has_key(user["id"])
    return {"has_key": has, "public_key": u["ssh_public_key"] if has else None}


@public.post("/me/ssh-key")
def generate_ssh_key(user: dict = Depends(require_auth)):
    """(Re)generate the key. The previous one stops working as soon as this returns."""
    try:
        pub = keys.generate(user["id"], user["username"])
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    with db.tx() as c:
        c.execute("UPDATE users SET ssh_public_key=? WHERE id=?", pub, user["id"])
    return {"has_key": True, "public_key": pub}


@public.delete("/me/ssh-key")
def remove_ssh_key(user: dict = Depends(require_auth)):
    keys.delete(user["id"])
    with db.tx() as c:
        c.execute("UPDATE users SET ssh_public_key=NULL WHERE id=?", user["id"])
    return {"ok": True}


class PasswordChange(BaseModel):
    current: str
    new: str = Field(min_length=users.MIN_PASSWORD, max_length=200)


@public.post("/me/password")
def change_password(body: PasswordChange, request: Request, user: dict = Depends(require_auth)):
    with db.read() as c:
        stored = db.row(c, "SELECT password_hash FROM users WHERE id=?", user["id"])["password_hash"]
    if not users.verify_password(body.current, stored):
        raise HTTPException(400, "current password is incorrect")
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
    launch_limit: int | None = Field(default=None, ge=0, le=100000)
    reset_count: bool = False


@admin.get("")
def list_users():
    with db.read() as c:
        rows = db.rows(c, "SELECT id, username, role, created_at, last_login, launch_limit, launch_count FROM users ORDER BY username COLLATE NOCASE")
    for r in rows:
        r["has_key"] = keys.has_key(r["id"])
    return rows


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
        raise HTTPException(409, "this username already exists")


@admin.patch("/{user_id}")
def update_user(user_id: int, body: UserPatch, me: dict = Depends(require_admin)):
    # An admin cannot demote or delete themselves, so there is always at least one admin left.
    if user_id == me["id"] and body.role not in (None, "admin"):
        raise HTTPException(400, "you cannot change your own role")
    password_hash = users.hash_password(body.password) if body.password else None
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM users WHERE id=?", user_id)
        if body.role:
            c.execute("UPDATE users SET role=? WHERE id=?", body.role, user_id)
        if body.launch_limit is not None:
            c.execute("UPDATE users SET launch_limit=? WHERE id=?", body.launch_limit, user_id)
        if body.reset_count:
            c.execute("UPDATE users SET launch_count=0 WHERE id=?", user_id)
        if password_hash:
            c.execute(
                "UPDATE users SET password_hash=?, session_version=session_version+1 WHERE id=?",
                password_hash, user_id,
            )
    return {"ok": True}


@admin.delete("/{user_id}")
def delete_user(user_id: int, me: dict = Depends(require_admin)):
    if user_id == me["id"]:
        raise HTTPException(400, "you cannot delete your own account")
    with db.tx() as c:
        # What the user created goes to the admin who deletes the account; shares disappear by cascade.
        c.execute("UPDATE jobs SET owner_id=? WHERE owner_id=?", me["id"], user_id)
        c.execute("UPDATE folders SET owner_id=? WHERE owner_id=?", me["id"], user_id)
        c.execute("DELETE FROM users WHERE id=?", user_id)
    keys.delete(user_id)
    return {"ok": True}


# ---------------- jobs ----------------

FOLDER_SEGMENT = re.compile(r"^[\w][\w .+-]{0,59}$")
MAX_DEPTH = 6


def clean_folder(path: str) -> str:
    """'C / week-1/' -> 'C/week-1'. Empty string is the root."""
    parts = [p.strip() for p in path.replace("\\", "/").split("/") if p.strip()]
    if len(parts) > MAX_DEPTH:
        raise HTTPException(400, f"nested folders: {MAX_DEPTH} levels maximum")
    for p in parts:
        if not FOLDER_SEGMENT.match(p) or p in (".", ".."):
            raise HTTPException(400, f"invalid folder name: {p!r}")
    return "/".join(parts)


def ensure_folder(c, path: str, owner_id: int | None = None) -> None:
    parts = path.split("/") if path else []
    for i in range(1, len(parts) + 1):
        c.execute("INSERT OR IGNORE INTO folders (path, owner_id) VALUES (?, ?)", "/".join(parts[:i]), owner_id)


class JobIn(BaseModel):
    folder: str = ""
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    image: str = Field(default=config.DEFAULT_IMAGE, min_length=1)
    command: str = Field(default="bash /tests/tests.sh", min_length=1)
    timeout: int = Field(default=60, ge=1, le=3600)
    memory_mb: int = Field(default=512, ge=64, le=4096)


@api.get("/jobs")
def list_jobs(user: dict = Depends(require_auth)):
    where, args = ("", ()) if user["role"] == "admin" else (f"WHERE {VISIBLE} ", (user["id"], user["id"]))
    with db.read() as c:
        return db.rows(
            c,
            "SELECT j.*, u.username AS owner_name, "
            " (SELECT COUNT(*) FROM job_shares s WHERE s.job_id=j.id) AS share_count, "
            " (SELECT COUNT(*) FROM repos r WHERE r.job_id=j.id) AS repo_count, "
            " (SELECT COUNT(*) FROM builds b WHERE b.job_id=j.id AND b.status IN ('queued','running')) AS active, "
            " (SELECT MAX(COALESCE(finished_at, started_at, queued_at)) FROM builds b WHERE b.job_id=j.id) AS last_activity, "
            " (SELECT COUNT(*) FROM repos r JOIN builds b ON b.id = (SELECT MAX(id) FROM builds WHERE repo_id=r.id) "
            "   WHERE r.job_id=j.id AND b.status='success') AS ok, "
            " (SELECT COUNT(*) FROM repos r JOIN builds b ON b.id = (SELECT MAX(id) FROM builds WHERE repo_id=r.id) "
            "   WHERE r.job_id=j.id AND b.status IN ('failed','timeout','error')) AS ko "
            "FROM jobs j LEFT JOIN users u ON u.id=j.owner_id " + where + "ORDER BY j.updated_at DESC",
            *args,
        )


@api.post("/jobs")
def create_job(body: JobIn, user: dict = Depends(require_auth)):
    folder = clean_folder(body.folder)
    with db.tx() as c:
        ensure_folder(c, folder, user["id"])
        cur = c.execute(
            "INSERT INTO jobs (name, description, image, command, timeout, memory_mb, folder, owner_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            body.name.strip(), body.description, body.image.strip(), body.command,
            body.timeout, body.memory_mb, folder, user["id"], db.now(), db.now(),
        )
        return {"id": cur.lastrowid}


@api.get("/jobs/{job_id}")
def get_job(job_id: int, user: dict = Depends(require_auth)):
    role = guard_job(job_id, user)
    with db.read() as c:
        job = get_or_404(c, "SELECT j.*, u.username AS owner_name FROM jobs j LEFT JOIN users u ON u.id=j.owner_id WHERE j.id=?", job_id)
        job["access"] = role
        if role == "owner":
            job["shares"] = [r["user_id"] for r in db.rows(c, "SELECT user_id FROM job_shares WHERE job_id=?", job_id)]
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
def update_job(job_id: int, body: JobIn, user: dict = Depends(require_auth)):
    guard_job(job_id, user, True)
    folder = clean_folder(body.folder)
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM jobs WHERE id=?", job_id)
        ensure_folder(c, folder, user["id"])
        c.execute(
            "UPDATE jobs SET name=?, description=?, image=?, command=?, timeout=?, memory_mb=?, folder=?, updated_at=? "
            "WHERE id=?",
            body.name.strip(), body.description, body.image.strip(), body.command,
            body.timeout, body.memory_mb, folder, db.now(), job_id,
        )
    return {"ok": True}


@api.post("/jobs/{job_id}/duplicate")
def duplicate_job(job_id: int, user: dict = Depends(require_auth)):
    guard_job(job_id, user)
    with db.tx() as c:
        j = get_or_404(c, "SELECT * FROM jobs WHERE id=?", job_id)
        cur = c.execute(
            "INSERT INTO jobs (name, description, image, command, timeout, memory_mb, folder, owner_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            f"{j['name']} (copy)", j["description"], j["image"], j["command"],
            j["timeout"], j["memory_mb"], j["folder"], user["id"], db.now(), db.now(),
        )
        c.execute(
            "INSERT INTO job_files (job_id, name, content) SELECT ?, name, content FROM job_files WHERE job_id=?",
            cur.lastrowid, job_id,
        )
        return {"id": cur.lastrowid}


@api.delete("/jobs/{job_id}")
def delete_job(job_id: int, user: dict = Depends(require_auth)):
    guard_job(job_id, user, True)
    with db.read() as c:
        active = cancel_active(c, "job_id=?", job_id)
    for bid in active:
        runner.cancel(bid)
    with db.tx() as c:
        ids = [r["id"] for r in db.rows(c, "SELECT id FROM builds WHERE job_id=?", job_id)]
        c.execute("DELETE FROM jobs WHERE id=?", job_id)
    remove_logs(ids)
    return {"ok": True}


class SharesIn(BaseModel):
    user_ids: list[int]


@api.put("/jobs/{job_id}/shares")
def set_shares(job_id: int, body: SharesIn, user: dict = Depends(require_auth)):
    """Choose who else can see this job (owner and admins always can)."""
    guard_job(job_id, user, True)
    with db.tx() as c:
        owner = db.row(c, "SELECT owner_id FROM jobs WHERE id=?", job_id)["owner_id"]
        valid = {r["id"] for r in db.rows(c, "SELECT id FROM users WHERE role != 'admin'")}
        ids = sorted(i for i in set(body.user_ids) if i in valid and i != owner)
        c.execute("DELETE FROM job_shares WHERE job_id=?", job_id)
        for i in ids:
            c.execute("INSERT INTO job_shares (job_id, user_id) VALUES (?, ?)", job_id, i)
    return {"shares": ids}


@api.get("/directory")
def directory(user: dict = Depends(require_auth)):
    """Users a job can be shared with (admins already see everything)."""
    with db.read() as c:
        return db.rows(c, "SELECT id, username, role FROM users WHERE role != 'admin' AND id != ? ORDER BY username COLLATE NOCASE", user["id"])


def folder_owned(c, path: str, user: dict) -> bool:
    """True if the user may restructure this folder: admin, or everything inside is theirs."""
    if user["role"] == "admin":
        return True
    like = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
    uid = user["id"]
    bad_folder = db.row(c, "SELECT 1 AS x FROM folders WHERE (path = ? OR path LIKE ? ESCAPE '\\') AND COALESCE(owner_id, -1) != ? LIMIT 1", path, like, uid)
    bad_job = db.row(c, "SELECT 1 AS x FROM jobs WHERE (folder = ? OR folder LIKE ? ESCAPE '\\') AND COALESCE(owner_id, -1) != ? LIMIT 1", path, like, uid)
    return not bad_folder and not bad_job


# ---------------- folders ----------------

class FolderIn(BaseModel):
    path: str


class FolderMove(BaseModel):
    src: str
    dst: str


@api.get("/folders")
def list_folders(user: dict = Depends(require_auth)):
    """Admins see every folder; others see their own plus the ones holding a job they can see."""
    with db.read() as c:
        if user["role"] == "admin":
            paths = {r["path"] for r in db.rows(c, "SELECT path FROM folders")}
            paths |= {r["folder"] for r in db.rows(c, "SELECT DISTINCT folder FROM jobs WHERE folder != ''")}
        else:
            uid = user["id"]
            paths = {r["path"] for r in db.rows(c, "SELECT path FROM folders WHERE owner_id = ?", uid)}
            paths |= {r["folder"] for r in db.rows(
                c, f"SELECT DISTINCT j.folder AS folder FROM jobs j WHERE j.folder != '' AND {VISIBLE}", uid, uid)}
    full = set()
    for p in paths:  # ancestors of a job folder created before folders existed
        parts = p.split("/")
        full |= {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}
    return sorted(full, key=str.lower)


@api.post("/folders")
def create_folder(body: FolderIn, user: dict = Depends(require_auth)):
    path = clean_folder(body.path)
    if not path:
        raise HTTPException(400, "empty folder name")
    with db.tx() as c:
        ensure_folder(c, path, user["id"])
    return {"path": path}


@api.post("/folders/move")
def move_folder(body: FolderMove, user: dict = Depends(require_auth)):
    """Rename or move a folder together with everything inside it."""
    src, dst = clean_folder(body.src), clean_folder(body.dst)
    if not src or not dst:
        raise HTTPException(400, "empty path")
    if dst == src:
        return {"path": dst}
    if dst.startswith(src + "/"):
        raise HTTPException(400, "cannot move a folder into itself")
    like = src.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
    with db.tx() as c:
        if not folder_owned(c, src, user):
            raise HTTPException(403, "you can only move folders that contain nothing but your own work")
        existing = {r["path"] for r in db.rows(c, "SELECT path FROM folders")}
        if dst in existing:
            raise HTTPException(409, "a folder with this name already exists")
        ensure_folder(c, "/".join(dst.split("/")[:-1]), user["id"])
        c.execute("UPDATE folders SET path = ? || substr(path, ?) WHERE path = ? OR path LIKE ? ESCAPE '\\'",
                  dst, len(src) + 1, src, like)
        c.execute("UPDATE jobs SET folder = ? || substr(folder, ?) WHERE folder = ? OR folder LIKE ? ESCAPE '\\'",
                  dst, len(src) + 1, src, like)
        ensure_folder(c, dst, user["id"])
    return {"path": dst}


@api.delete("/folders")
def delete_folder(path: str, user: dict = Depends(require_auth)):
    path = clean_folder(path)
    like = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
    with db.tx() as c:
        if not folder_owned(c, path, user):
            raise HTTPException(403, "you can only delete your own folders")
        busy = db.row(c, "SELECT id FROM jobs WHERE folder = ? OR folder LIKE ? ESCAPE '\\' LIMIT 1", path, like)
        if busy:
            raise HTTPException(409, "this folder contains jobs: move or delete them first")
        c.execute("DELETE FROM folders WHERE path = ? OR path LIKE ? ESCAPE '\\'", path, like)
    return {"ok": True}


# ---------------- job files ----------------

@api.post("/jobs/{job_id}/files")
async def upload_files(job_id: int, files: list[UploadFile] = File(...), user: dict = Depends(require_auth)):
    guard_job(job_id, user, True)
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
def read_file(job_id: int, name: str, user: dict = Depends(require_auth)):
    guard_job(job_id, user)
    with db.read() as c:
        f = get_or_404(c, "SELECT content FROM job_files WHERE job_id=? AND name=?", job_id, name)
    try:
        return {"name": name, "content": f["content"].decode(), "binary": False}
    except UnicodeDecodeError:
        return {"name": name, "content": "", "binary": True}


class FileIn(BaseModel):
    content: str


@api.put("/jobs/{job_id}/files/{name:path}")
def write_file(job_id: int, name: str, body: FileIn, user: dict = Depends(require_auth)):
    guard_job(job_id, user, True)
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
def delete_file(job_id: int, name: str, user: dict = Depends(require_auth)):
    guard_job(job_id, user, True)
    with db.tx() as c:
        c.execute("DELETE FROM job_files WHERE job_id=? AND name=?", job_id, name)
    return {"ok": True}


# ---------------- repos ----------------

@api.post("/jobs/{job_id}/repos")
async def add_repos(job_id: int, text: str = Form(""), file: UploadFile | None = File(None), user: dict = Depends(require_auth)):
    guard_job(job_id, user, True)
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


class SyncIn(BaseModel):
    org: str = ""
    pattern: str = ""


@api.post("/jobs/{job_id}/repos/sync")
def sync_repos(job_id: int, body: SyncIn, user: dict = Depends(require_auth)):
    guard_job(job_id, user, True)
    """Create or refresh the repository list from GitHub. Remembers org + pattern for the next press."""
    with db.read() as c:
        job = get_or_404(c, "SELECT id, github_org, repo_pattern FROM jobs WHERE id=?", job_id)
    org = body.org.strip() or job["github_org"]
    pattern = body.pattern.strip() or job["repo_pattern"]
    if not org or not pattern:
        raise HTTPException(400, "Enter the GitHub organization and a pattern (e.g. day06-*).")
    try:
        names = github.list_repos(org, pattern)
        with db.read() as c:
            known = {r["url"]: r for r in db.rows(c, "SELECT id, url, name, renamed FROM repos WHERE job_id=?", job_id)}
        if not names:
            raise HTTPException(409, "No repository matches this pattern: nothing was changed.")
        # Names (commit authors) are only fetched for new repos and for ones nobody renamed by hand.
        urls = {n: f"git@github.com:{org}/{n}.git" for n in names}
        # Re-asking GitHub for the authors of a repo already named after them is wasted time.
        to_name = [n for n in names if urls[n] not in known
                   or (not known[urls[n]]["renamed"] and "@" not in known[urls[n]]["name"])]
        titles = github.names_for(org, to_name)
    except github.GitHubError as e:
        raise HTTPException(502, str(e))
    added = updated = 0
    gone = []
    with db.tx() as c:
        c.execute("UPDATE jobs SET github_org=?, repo_pattern=?, updated_at=? WHERE id=?", org, pattern, db.now(), job_id)
        current = {r["url"]: r for r in db.rows(c, "SELECT id, url, name, renamed FROM repos WHERE job_id=?", job_id)}
        wanted = set(urls.values())
        for n in names:
            u = urls[n]
            if u not in current:
                c.execute("INSERT INTO repos (job_id, name, url, created_at) VALUES (?, ?, ?, ?)", job_id, titles[n], u, db.now())
                added += 1
            elif n in titles and not current[u]["renamed"] and current[u]["name"] != titles[n]:
                c.execute("UPDATE repos SET name=? WHERE id=?", titles[n], current[u]["id"])
                updated += 1
        for u, r in current.items():
            if u not in wanted:
                gone.append(r["id"])
    for rid in gone:
        delete_repo(rid, user)
    return {"added": added, "updated": updated, "removed": len(gone), "total": len(names)}


class RepoPatch(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@api.patch("/repos/{repo_id}")
def rename_repo(repo_id: int, body: RepoPatch, user: dict = Depends(require_auth)):
    guard_repo(repo_id, user, True)
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM repos WHERE id=?", repo_id)
        c.execute("UPDATE repos SET name=?, renamed=1 WHERE id=?", body.name.strip(), repo_id)
    return {"ok": True}


@api.delete("/repos/{repo_id}")
def delete_repo(repo_id: int, user: dict = Depends(require_auth)):
    guard_repo(repo_id, user, True)
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
def repo_builds(repo_id: int, user: dict = Depends(require_auth)):
    guard_repo(repo_id, user)
    with db.read() as c:
        repo = get_or_404(c, "SELECT * FROM repos WHERE id=?", repo_id)
        repo["builds"] = db.rows(c, "SELECT * FROM builds WHERE repo_id=? ORDER BY id DESC", repo_id)
        return repo


# ---------------- runs ----------------

class RunIn(BaseModel):
    repo_ids: list[int] | None = None


@api.post("/jobs/{job_id}/run")
def run_job(job_id: int, body: RunIn, user: dict = Depends(require_auth)):
    guard_job(job_id, user)
    with db.tx() as c:
        get_or_404(c, "SELECT id FROM jobs WHERE id=?", job_id)
        all_ids = [r["id"] for r in db.rows(c, "SELECT id FROM repos WHERE job_id=? ORDER BY name COLLATE NOCASE", job_id)]
        ids = all_ids if body.repo_ids is None else [i for i in body.repo_ids if i in set(all_ids)]
        return {"queued": enqueue(c, job_id, ids, user)}


@api.post("/repos/{repo_id}/run")
def run_repo(repo_id: int, user: dict = Depends(require_auth)):
    guard_repo(repo_id, user)
    with db.tx() as c:
        r = get_or_404(c, "SELECT job_id FROM repos WHERE id=?", repo_id)
        queued = enqueue(c, r["job_id"], [repo_id], user)
        last = db.row(c, "SELECT MAX(id) AS id FROM builds WHERE repo_id=?", repo_id)
        return {"queued": queued, "build_id": last["id"]}


@api.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, user: dict = Depends(require_auth)):
    guard_job(job_id, user)
    with db.read() as c:
        active = cancel_active(c, "job_id=?", job_id)
    return {"cancelled": sum(runner.cancel(bid) for bid in active)}


@api.post("/builds/{build_id}/cancel")
def cancel_build(build_id: int, user: dict = Depends(require_auth)):
    guard_build(build_id, user)
    return {"ok": runner.cancel(build_id)}


@api.get("/builds/{build_id}")
def get_build(build_id: int, user: dict = Depends(require_auth)):
    guard_build(build_id, user)
    with db.read() as c:
        return get_or_404(
            c,
            "SELECT b.*, r.name AS repo_name, r.url AS repo_url, j.name AS job_name "
            "FROM builds b JOIN repos r ON r.id=b.repo_id JOIN jobs j ON j.id=b.job_id WHERE b.id=?",
            build_id,
        )


@api.get("/builds/{build_id}/log")
def build_log(build_id: int, offset: int = 0, user: dict = Depends(require_auth)):
    guard_build(build_id, user)
    """Incremental log: returns raw bytes from `offset`; the client polls until X-Done is 1."""
    with db.read() as c:
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
def export_csv(job_id: int, user: dict = Depends(require_auth)):
    guard_job(job_id, user)
    job = get_job(job_id, user)
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


@api.get("/jobs/{job_id}/archive.zip")
def export_archive(job_id: int, user: dict = Depends(require_auth)):
    guard_job(job_id, user)
    """Full history (CSV + raw logs) as a ZIP, to keep before the automatic purge."""
    try:
        filename, data = archive.build_zip(job_id)
    except KeyError:
        raise HTTPException(404, "not found")
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


app.include_router(public)
app.include_router(admin)
app.include_router(api)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.api_route("/", methods=["GET", "HEAD"])
def index():
    return FileResponse(STATIC / "index.html")
