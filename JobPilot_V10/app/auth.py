"""Authentication, sessions, password hashing (scrypt), brute-force protection."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

from fastapi import Cookie, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from . import db

# Cookie name + settings
COOKIE_NAME = "jp_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 14  # 14 days
SESSION_BYTES = 32

# Brute-force protection (in-memory; resets on restart)
_fail: dict[str, list[float]] = {}
MAX_FAILS = 8
LOCK_SECONDS = 300


def _now() -> float:
    return time.time()


def _clean_fails(key: str) -> None:
    if key not in _fail:
        return
    cutoff = _now() - LOCK_SECONDS
    _fail[key] = [t for t in _fail[key] if t > cutoff]
    if not _fail[key]:
        del _fail[key]


def is_locked(ip: str, username: str = "") -> bool:
    key = f"{ip}:{username}"
    _clean_fails(key)
    return len(_fail.get(key, [])) >= MAX_FAILS


def record_fail(ip: str, username: str = "") -> None:
    key = f"{ip}:{username}"
    _clean_fails(key)
    _fail.setdefault(key, []).append(_now())


def clear_fails(ip: str, username: str = "") -> None:
    key = f"{ip}:{username}"
    _fail.pop(key, None)


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Return 'scrypt$N$r$p$salt_hex$hash_hex'."""
    if salt is None:
        salt = os.urandom(16)
    # Reasonable params for interactive login
    n, r, p = 2**14, 8, 1
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n_s, r_s, p_s, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
        return hmac.compare_digest(h, expected)
    except Exception:
        return False


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(SESSION_BYTES)
    db.create_session(user_id, token, COOKIE_MAX_AGE)
    return token


def destroy_session(token: str | None) -> None:
    if token:
        db.delete_session(token)


def get_user_from_session(token: str | None) -> Optional[dict]:
    if not token:
        return None
    return db.get_session_user(token)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # local tool; set True behind HTTPS
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def require_user(request: Request) -> dict:
    """Dependency-style helper: raise 401 if not logged in."""
    token = request.cookies.get(COOKIE_NAME)
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def require_admin(user: dict) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
