import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


DATA_DIR = Path(os.environ.get("AGORA_DATA_DIR", "./data")).resolve()
DB_PATH = DATA_DIR / "agora.db"
LOGS_DIR = DATA_DIR / "logs"
WORK_DIR = DATA_DIR / "work"

PASSWORD = os.environ.get("AGORA_PASSWORD", "")
SECRET = os.environ.get("AGORA_SECRET", "")
GITHUB_TOKEN = os.environ.get("AGORA_GITHUB_TOKEN", "")

# Number of builds running in parallel. Keep it low on a 2 GB VPS.
WORKERS = _int("AGORA_WORKERS", 2)
CLONE_TIMEOUT = _int("AGORA_CLONE_TIMEOUT", 120)
# Hard cap on stored output per build (bytes). Protects disk from infinite printf loops.
MAX_LOG_BYTES = _int("AGORA_MAX_LOG_BYTES", 2 * 1024 * 1024)

DEFAULT_IMAGE = os.environ.get("AGORA_DEFAULT_IMAGE", "agora-runner:latest")


def ensure_dirs() -> None:
    for d in (DATA_DIR, LOGS_DIR, WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)
