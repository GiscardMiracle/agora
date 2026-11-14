import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


DATA_DIR = Path(os.environ.get("AGORA_DATA_DIR", "./data")).resolve()
DB_PATH = DATA_DIR / "agora.db"
LOGS_DIR = DATA_DIR / "logs"
WORK_DIR = DATA_DIR / "work"
KEYS_DIR = DATA_DIR / "keys"

# First admin account, created only while the users table is empty.
ADMIN_USER = os.environ.get("AGORA_ADMIN_USER", "admin")
PASSWORD = os.environ.get("AGORA_PASSWORD", "")
SECRET = os.environ.get("AGORA_SECRET", "")
# Read-only token used to list an organisation's repositories and their commit authors.
GITHUB_TOKEN = os.environ.get("AGORA_GITHUB_TOKEN", "")
# Only commit emails ending with this are used to name a group (e.g. "@my-school.eu"). Empty = any real email.
EMAIL_DOMAIN = os.environ.get("AGORA_EMAIL_DOMAIN", "").strip().lower()

# Number of builds running in parallel. Keep it low on a 2 GB VPS.
WORKERS = _int("AGORA_WORKERS", 2)
CLONE_TIMEOUT = _int("AGORA_CLONE_TIMEOUT", 120)
# Hard cap on stored output per build (bytes). Protects disk from infinite printf loops.
MAX_LOG_BYTES = _int("AGORA_MAX_LOG_BYTES", 2 * 1024 * 1024)

# Finished builds (and their logs) older than this are deleted automatically. 0 disables.
RETENTION_DAYS = _int("AGORA_RETENTION_DAYS", 90)

DEFAULT_IMAGE = os.environ.get("AGORA_DEFAULT_IMAGE", "agora-runner:latest")


def ensure_dirs() -> None:
    for d in (DATA_DIR, LOGS_DIR, WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    KEYS_DIR.chmod(0o700)
