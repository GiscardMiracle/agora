"""Build execution.

Each worker polls SQLite for the oldest queued build, clones the repository on
the host, then runs the job command inside a throwaway Docker container:
no network, capped RAM/CPU/PIDs, repo mounted at /work, job files read-only at
/tests. Output goes through a pseudo-TTY (so students' printf behave like in a
real terminal) and is appended to data/logs/<build_id>.log, which the UI polls.
"""

import asyncio
import base64
import logging
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

from . import config, db

log = logging.getLogger("agora.runner")

KEEP_BUILDS_PER_REPO = int(os.environ.get("AGORA_KEEP_BUILDS", 20))
SCORE_RE = re.compile(rb"AGORA_SCORE:\s*([^\r\n]{1,40})")
ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")

C_INFO = "\x1b[36m"
C_CMD = "\x1b[1;35m"
C_OK = "\x1b[1;32m"
C_KO = "\x1b[1;31m"
C_WARN = "\x1b[1;33m"
C_DIM = "\x1b[2m"
C_RESET = "\x1b[0m"


def container_name(build_id: int) -> str:
    return f"agora-build-{build_id}"


def log_path(build_id: int) -> Path:
    return config.LOGS_DIR / f"{build_id}.log"


def remove_logs(build_ids) -> None:
    for bid in build_ids:
        log_path(bid).unlink(missing_ok=True)


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():  # student code may have chmod'ed things away
        subprocess.run(["chmod", "-R", "u+rwx", str(path)], check=False)
        shutil.rmtree(path, ignore_errors=True)


def _exit_label(code: int) -> str:
    if code > 128:
        try:
            return f"{code} ({signal.Signals(code - 128).name})"
        except ValueError:
            pass
    return str(code)


class LogWriter:
    def __init__(self, path: Path, redact: list[str]):
        self.f = open(path, "wb")
        self.size = 0
        self.truncated = False
        self.redact = [r.encode() for r in redact if r]
        self._line = b""
        self.score: str | None = None

    def write(self, data: bytes) -> None:
        for secret in self.redact:
            data = data.replace(secret, b"********")
        self._scan_score(data)
        if self.truncated:
            return
        room = config.MAX_LOG_BYTES - self.size
        if len(data) > room:
            data = data[:room]
            self.truncated = True
        self.f.write(data)
        self.size += len(data)
        if self.truncated:
            self.meta(f"{C_WARN}output truncated at {config.MAX_LOG_BYTES} bytes{C_RESET}", force=True)
        self.f.flush()

    def _scan_score(self, data: bytes) -> None:
        self._line = (self._line + data)[-8192:]
        *lines, self._line = self._line.split(b"\n")
        for line in lines:
            if m := SCORE_RE.search(ANSI_RE.sub(b"", line)):
                self.score = m[1].strip().decode(errors="replace")

    def meta(self, text: str, force: bool = False) -> None:
        if self.truncated and not force:
            return
        b = f"{C_INFO}[agora]{C_RESET} {text}\r\n".encode()
        self.f.write(b)
        self.size += len(b)
        self.f.flush()

    def cmd(self, text: str) -> None:
        self.meta(f"{C_CMD}$ {text}{C_RESET}")

    def close(self) -> None:
        self._scan_score(b"\n")
        self.f.close()


class Runner:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._cancelled: set[int] = set()

    # ---------- lifecycle ----------

    async def start(self) -> None:
        self._recover()
        for i in range(max(1, config.WORKERS)):
            self._tasks.append(asyncio.create_task(self._loop(i)))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _recover(self) -> None:
        """A restart kills running builds: mark them, and remove leftover containers."""
        with db.tx() as c:
            c.execute(
                "UPDATE builds SET status='error', error='interrupted by server restart', finished_at=? "
                "WHERE status='running'",
                db.now(),
            )
        out = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=agora-build-"],
            capture_output=True, text=True, check=False,
        )
        ids = out.stdout.split()
        if ids:
            subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, check=False)
        for d in config.WORK_DIR.iterdir():
            _rmtree(d)

    # ---------- public API (called from request threads) ----------

    def cancel(self, build_id: int) -> bool:
        with db.tx() as c:
            b = db.row(c, "SELECT status FROM builds WHERE id=?", build_id)
            if not b:
                return False
            if b["status"] == "queued":
                c.execute(
                    "UPDATE builds SET status='cancelled', finished_at=? WHERE id=?",
                    db.now(), build_id,
                )
                return True
            if b["status"] != "running":
                return False
        self._cancelled.add(build_id)
        subprocess.run(["docker", "kill", container_name(build_id)], capture_output=True, check=False)
        return True

    # ---------- worker ----------

    async def _loop(self, worker: int) -> None:
        while True:
            try:
                build = self._claim()
            except Exception:
                log.exception("claim failed")
                build = None
            if not build:
                await asyncio.sleep(1)
                continue
            try:
                await self._run(build)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("build %s crashed", build["id"])
                self._finish(build, "error", error=f"internal error: {e}")
            finally:
                self._cancelled.discard(build["id"])

    def _claim(self) -> dict | None:
        with db.tx() as c:
            b = db.row(
                c,
                "SELECT b.id, b.job_id, b.repo_id, r.url, r.name AS repo_name, j.name AS job_name, "
                "j.image, j.command, j.timeout, j.memory_mb "
                "FROM builds b JOIN repos r ON r.id=b.repo_id JOIN jobs j ON j.id=b.job_id "
                "WHERE b.status='queued' ORDER BY b.id LIMIT 1",
            )
            if not b:
                return None
            c.execute("UPDATE builds SET status='running', started_at=? WHERE id=?", db.now(), b["id"])
            b["files"] = db.rows(c, "SELECT name, content FROM job_files WHERE job_id=?", b["job_id"])
            return b

    def _finish(self, build: dict, status: str, **fields) -> None:
        with db.tx() as c:
            cur = c.execute(
                "UPDATE builds SET status=?, exit_code=?, score=?, commit_sha=?, error=?, finished_at=? "
                "WHERE id=?",
                status, fields.get("exit_code"), fields.get("score"), fields.get("commit_sha"),
                fields.get("error"), db.now(), build["id"],
            )
            if cur.rowcount == 0:  # repo or job deleted while the build was running
                remove_logs([build["id"]])
                return
            old = [
                r["id"] for r in db.rows(
                    c,
                    "SELECT id FROM builds WHERE repo_id=? AND status IN ('success','failed','timeout','cancelled','error') "
                    "ORDER BY id DESC LIMIT -1 OFFSET ?",
                    build["repo_id"], KEEP_BUILDS_PER_REPO,
                )
            ]
            if old:
                c.execute(f"DELETE FROM builds WHERE id IN ({','.join('?' * len(old))})", *old)
        remove_logs(old)

    async def _stream(self, args: list[str], out: LogWriter, timeout: int, env=None, cwd=None,
                      on_timeout=None) -> tuple[int | None, bool]:
        """Run a process, stream its merged output to the log. Returns (exit_code, timed_out)."""
        proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=env, cwd=cwd,
        )

        async def pump():
            while chunk := await proc.stdout.read(65536):
                out.write(chunk)
            return await proc.wait()

        try:
            return await asyncio.wait_for(pump(), timeout), False
        except asyncio.TimeoutError:
            if on_timeout:
                await on_timeout()
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            return proc.returncode, True

    async def _run(self, b: dict) -> None:
        bid = b["id"]
        work = config.WORK_DIR / str(bid)
        repo_dir, tests_dir = work / "repo", work / "tests"
        _rmtree(work)
        tests_dir.mkdir(parents=True)
        out = LogWriter(log_path(bid), redact=[config.GITHUB_TOKEN])
        sha = None
        try:
            out.meta(f"build #{bid} · {b['job_name']} · {b['repo_name']}")

            # 1. clone on the host (network needed, student code not executed yet)
            git = ["git"]
            if config.GITHUB_TOKEN and b["url"].startswith("https://github.com/"):
                cred = base64.b64encode(f"x-access-token:{config.GITHUB_TOKEN}".encode()).decode()
                git += ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {cred}"]
            env = {
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
            }
            out.cmd(f"git clone --depth 1 {b['url']}")
            rc, timed_out = await self._stream(
                [*git, "clone", "--depth", "1", "--no-tags", b["url"], repo_dir.name],
                out, config.CLONE_TIMEOUT, env=env, cwd=work,
            )
            if timed_out or rc != 0:
                msg = "clone timed out" if timed_out else "clone failed (bad URL or no access?)"
                out.meta(f"{C_KO}{msg}{C_RESET}")
                self._finish(b, "error", error=msg)
                return
            r = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
                               capture_output=True, text=True, check=False)
            sha = r.stdout.strip() or None
            out.meta(f"commit {C_DIM}{sha or '(empty repository)'}{C_RESET}")

            # 2. materialize the test files
            for f in b["files"]:
                p = tests_dir / f["name"]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(f["content"])
                p.chmod(0o755)

            if bid in self._cancelled:
                out.meta(f"{C_WARN}cancelled{C_RESET}")
                self._finish(b, "cancelled", commit_sha=sha)
                return

            # 3. run in the sandbox
            name = container_name(bid)
            mem = f"{b['memory_mb']}m"
            args = [
                "docker", "run", "--rm", "--name", name, "-t",
                "--network", "none",
                "--memory", mem, "--memory-swap", mem,
                "--cpus", "1", "--pids-limit", "256",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--tmpfs", "/tmp:rw,exec,nosuid,size=256m",
                "-e", "HOME=/tmp", "-e", "TERM=xterm-256color",
                "-e", "AGORA_REPO=/work", "-e", "AGORA_TESTS=/tests",
                "-v", f"{repo_dir}:/work", "-v", f"{tests_dir}:/tests:ro",
                "-w", "/work",
                b["image"], "sh", "-c", f"exec </dev/null; {b['command']}",
            ]

            async def kill():
                await asyncio.to_thread(
                    subprocess.run, ["docker", "kill", name], capture_output=True, check=False
                )

            out.cmd(b["command"])
            rc, timed_out = await self._stream(args, out, b["timeout"], on_timeout=kill)
            out.write(b"\r\n")

            if bid in self._cancelled:
                out.meta(f"{C_WARN}cancelled{C_RESET}")
                self._finish(b, "cancelled", commit_sha=sha, score=out.score)
            elif timed_out:
                out.meta(f"{C_KO}TIMEOUT after {b['timeout']}s{C_RESET}")
                self._finish(b, "timeout", commit_sha=sha, score=out.score)
            elif rc == 125:
                out.meta(f"{C_KO}docker could not start the container (image '{b['image']}' missing?){C_RESET}")
                self._finish(b, "error", exit_code=rc, commit_sha=sha, error="docker run failed")
            else:
                if rc == 137:
                    out.meta(f"{C_WARN}killed by SIGKILL — probably exceeded the {mem} memory limit{C_RESET}")
                color = C_OK if rc == 0 else C_KO
                out.meta(f"{color}exit code {_exit_label(rc)}{C_RESET}"
                         + (f" · score {out.score}" if out.score else ""))
                self._finish(b, "success" if rc == 0 else "failed",
                             exit_code=rc, commit_sha=sha, score=out.score)
        finally:
            out.close()
            _rmtree(work)
