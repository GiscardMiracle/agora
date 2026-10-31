"""Accounts: password hashing, first admin creation, and a recovery command.

Reset a password or recreate an admin from the server:
    python -m app.users <username>
"""
import getpass
import hashlib
import hmac
import secrets
import sys

from . import config, db

ROLES = ("admin", "corrector", "viewer")
MIN_PASSWORD = 8
_N, _R, _P = 2**14, 8, 1
# Verified when the username is unknown, so response time does not reveal which accounts exist.
_DUMMY_SALT = secrets.token_bytes(16)


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}${_scrypt(password, salt).hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        _scrypt(password, _DUMMY_SALT)
        return False
    salt, digest = stored.split("$")
    return hmac.compare_digest(_scrypt(password, bytes.fromhex(salt)).hex(), digest)


def bootstrap() -> None:
    """Create the first admin from AGORA_PASSWORD. Does nothing once an account exists."""
    with db.tx() as c:
        if db.row(c, "SELECT id FROM users LIMIT 1"):
            return
        if not config.PASSWORD:
            sys.exit("No account yet and AGORA_PASSWORD is not set: cannot create the first admin.")
        c.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
            config.ADMIN_USER, hash_password(config.PASSWORD), db.now(),
        )


def _reset(username: str) -> None:
    password = getpass.getpass(f"New password for {username}: ")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"Password too short (minimum {MIN_PASSWORD}).")
    db.init()
    with db.tx() as c:
        changed = c.execute(
            "UPDATE users SET password_hash=?, session_version=session_version+1 WHERE username=?",
            hash_password(password), username,
        ).rowcount
        if not changed:
            c.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
                username, hash_password(password), db.now(),
            )
    print("Password updated." if changed else f"Admin {username} created.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.users <username>")
    _reset(sys.argv[1])
