"""SQLite storage. Multi-user ready: auth, sessions, tokens, payments, per-user jobs."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from .config import DB_PATH

_lock = threading.Lock()
AUTO_ATS = ("greenhouse", "lever", "ashby", "naukri", "foundit", "shine", "internshala")

# Default free tokens for new users
DEFAULT_TOKENS = 50

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE,
  password_hash TEXT,
  role TEXT DEFAULT 'user',
  tokens INTEGER DEFAULT 50,
  profile TEXT DEFAULT '{}',
  prefs TEXT DEFAULT '{}',
  resume_path TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires REAL NOT NULL,
  created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS token_usage(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  action TEXT,
  tokens INTEGER DEFAULT 1,
  detail TEXT DEFAULT '',
  created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  amount REAL,
  tokens_added INTEGER,
  note TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER DEFAULT 1,
  source TEXT, ext_id TEXT, ats TEXT,
  title TEXT, company TEXT, location TEXT, url TEXT, description TEXT,
  work_mode TEXT, company_tier TEXT, company_type TEXT,
  score INTEGER DEFAULT 0, matched TEXT DEFAULT '[]', reason TEXT DEFAULT '',
  llm_scored INTEGER DEFAULT 0,
  status TEXT DEFAULT 'new', note TEXT DEFAULT '',
  applied_by TEXT DEFAULT '', apply_mode TEXT DEFAULT '',
  exp TEXT DEFAULT '', salary TEXT DEFAULT '',
  emp_type TEXT DEFAULT '', emp_note TEXT DEFAULT '',
  created TEXT DEFAULT CURRENT_TIMESTAMP, applied_at TEXT,
  UNIQUE(user_id, source, ext_id)
);
CREATE TABLE IF NOT EXISTS emp_cache(
  source TEXT, ext_id TEXT, kind TEXT, reason TEXT,
  checked TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(source, ext_id)
);
"""


@contextmanager
def _db():
    with _lock:
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init():
    with _db() as c:
        c.executescript(SCHEMA)
        # Upgrade jobs table if older schema
        cols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)")}
        for name in ("applied_by", "apply_mode", "exp", "salary", "emp_type", "emp_note"):
            if name not in cols:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT DEFAULT ''")
        # Upgrade users table if older schema (single-user era)
        ucols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        for name, default in (
            ("username", "NULL"),
            ("password_hash", "NULL"),
            ("role", "'user'"),
            ("tokens", "50"),
            ("created_at", "CURRENT_TIMESTAMP"),
            ("last_login", "NULL"),
        ):
            if name not in ucols:
                c.execute(f"ALTER TABLE users ADD COLUMN {name} TEXT DEFAULT {default}" if name != "tokens"
                          else f"ALTER TABLE users ADD COLUMN {name} INTEGER DEFAULT 50")
        c.execute(
            "UPDATE jobs SET apply_mode=CASE WHEN ats IN ('greenhouse','lever','ashby','naukri','foundit','shine','internshala') THEN 'auto' ELSE 'manual' END "
            "WHERE apply_mode='' OR apply_mode IS NULL"
        )
        c.execute("UPDATE jobs SET status='new', note='Interrupted - ready to try again.' WHERE status='applying'")
        c.execute("DELETE FROM jobs WHERE source IN ('remotive','arbeitnow') AND status IN ('new','skipped')")
        c.execute("UPDATE jobs SET applied_by='ai' WHERE status='applied' AND (applied_by='' OR applied_by IS NULL)")
        # Ensure admin "sasi" exists (password set on first run if missing)
        admin = c.execute("SELECT id FROM users WHERE username='sasi'").fetchone()
        if not admin:
            # Temporary placeholder; main.py will set a real password on first boot if needed
            c.execute(
                "INSERT INTO users(username, password_hash, role, tokens, profile) VALUES(?,?,?,?,?)",
                ("sasi", "", "admin", 9999, json.dumps({"name": "Sasi", "email": ""})),
            )


def clear_jobs(uid=1, statuses=("new", "skipped", "manual")):
    q = ",".join("?" * len(statuses))
    with _db() as c:
        return c.execute(f"DELETE FROM jobs WHERE user_id=? AND status IN ({q})", (uid, *statuses)).rowcount


def _user_row(r):
    if not r:
        return None
    return {
        "id": r["id"],
        "username": r["username"],
        "role": r["role"] or "user",
        "tokens": int(r["tokens"] or 0),
        "profile": json.loads(r["profile"] or "{}"),
        "prefs": json.loads(r["prefs"] or "{}"),
        "resume_path": r["resume_path"],
        "created_at": r["created_at"],
        "last_login": r["last_login"],
    }


def get_user(uid=1):
    with _db() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not r:
            c.execute("INSERT INTO users(id, tokens) VALUES(?, ?)", (uid, DEFAULT_TOKENS))
            return {"id": uid, "username": None, "role": "user", "tokens": DEFAULT_TOKENS,
                    "profile": {}, "prefs": {}, "resume_path": None, "created_at": None, "last_login": None}
        return _user_row(r)


def get_user_by_username(username: str):
    with _db() as c:
        r = c.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username.strip(),)).fetchone()
        return _user_row(r)


def get_user_for_login(username: str):
    """Like get_user_by_username but includes password_hash for verification only."""
    with _db() as c:
        r = c.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username.strip(),)).fetchone()
        if not r:
            return None
        u = _user_row(r)
        u["password_hash"] = r["password_hash"] or ""
        return u


def create_user(username: str, password_hash: str, role: str = "user", tokens: int = DEFAULT_TOKENS, profile: dict | None = None):
    with _db() as c:
        cur = c.execute(
            "INSERT INTO users(username, password_hash, role, tokens, profile) VALUES(?,?,?,?,?)",
            (username.strip().lower(), password_hash, role, tokens, json.dumps(profile or {})),
        )
        return cur.lastrowid


def set_password(uid: int, password_hash: str):
    with _db() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, uid))


def update_last_login(uid: int):
    with _db() as c:
        c.execute("UPDATE users SET last_login=? WHERE id=?", (datetime.utcnow().isoformat(), uid))


def list_users():
    with _db() as c:
        return [_user_row(r) for r in c.execute("SELECT * FROM users ORDER BY id").fetchall()]


# ── Sessions ──────────────────────────────────────────────────────────────

def create_session(user_id: int, token: str, max_age_seconds: int):
    expires = time.time() + max_age_seconds
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO sessions(token, user_id, expires) VALUES(?,?,?)",
                  (token, user_id, expires))


def delete_session(token: str):
    with _db() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


def get_session_user(token: str):
    with _db() as c:
        r = c.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token=? AND s.expires > ?",
            (token, time.time()),
        ).fetchone()
        return _user_row(r)


def cleanup_sessions():
    with _db() as c:
        c.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))


# ── Tokens & usage ────────────────────────────────────────────────────────

def get_tokens(uid: int) -> int:
    with _db() as c:
        r = c.execute("SELECT tokens FROM users WHERE id=?", (uid,)).fetchone()
        return int(r["tokens"] or 0) if r else 0


def add_tokens(uid: int, amount: int, note: str = ""):
    with _db() as c:
        c.execute("UPDATE users SET tokens = COALESCE(tokens,0) + ? WHERE id=?", (amount, uid))
        if amount > 0:
            c.execute(
                "INSERT INTO payments(user_id, amount, tokens_added, note, status) VALUES(?,?,?,?,?)",
                (uid, 0, amount, note or "manual top-up", "completed"),
            )


def consume_tokens(uid: int, amount: int, action: str, detail: str = "") -> bool:
    """Atomically deduct tokens. Returns False if insufficient balance."""
    with _db() as c:
        r = c.execute("SELECT tokens FROM users WHERE id=?", (uid,)).fetchone()
        bal = int(r["tokens"] or 0) if r else 0
        if bal < amount:
            return False
        c.execute("UPDATE users SET tokens = tokens - ? WHERE id=?", (amount, uid))
        c.execute(
            "INSERT INTO token_usage(user_id, action, tokens, detail) VALUES(?,?,?,?)",
            (uid, action, amount, (detail or "")[:300]),
        )
        return True


def usage_history(uid: int, limit: int = 100):
    with _db() as c:
        rows = c.execute(
            "SELECT * FROM token_usage WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (uid, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def payments_history(uid: int | None = None, limit: int = 100):
    with _db() as c:
        if uid is None:
            rows = c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM payments WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def record_payment(uid: int, amount: float, tokens_added: int, note: str = "", status: str = "completed"):
    with _db() as c:
        c.execute(
            "INSERT INTO payments(user_id, amount, tokens_added, note, status) VALUES(?,?,?,?,?)",
            (uid, amount, tokens_added, note, status),
        )
        if status == "completed" and tokens_added:
            c.execute("UPDATE users SET tokens = COALESCE(tokens,0) + ? WHERE id=?", (tokens_added, uid))


def save_user(uid=1, profile=None, prefs=None, resume_path=None):
    get_user(uid)
    with _db() as c:
        if profile is not None:
            c.execute("UPDATE users SET profile=? WHERE id=?", (json.dumps(profile), uid))
        if prefs is not None:
            c.execute("UPDATE users SET prefs=? WHERE id=?", (json.dumps(prefs), uid))
        if resume_path is not None:
            c.execute("UPDATE users SET resume_path=? WHERE id=?", (str(resume_path), uid))


def add_job(uid, j):
    """Insert a job; return its id, or None if we already have it."""
    with _db() as c:
        cur = c.execute(
            """INSERT OR IGNORE INTO jobs
               (user_id,source,ext_id,ats,title,company,location,url,description,
                work_mode,company_tier,company_type,score,matched,reason,status,apply_mode,exp,salary,emp_type,emp_note)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                uid, j["source"], str(j["ext_id"]), j.get("ats", ""), j["title"], j["company"],
                j.get("location", ""), j["url"], (j.get("description") or "")[:20000],
                j.get("work_mode", ""), j.get("company_tier", ""), j.get("company_type", ""),
                j.get("score", 0), json.dumps(j.get("matched", [])), j.get("reason", ""), "new",
                "auto" if j.get("ats") in AUTO_ATS else "manual", j.get("exp", ""), j.get("salary", ""),
                j.get("emp_type", ""), (j.get("emp_note") or "")[:200],
            ),
        )
        return cur.lastrowid if cur.rowcount else None


def _row(r):
    d = dict(r)
    d["matched"] = json.loads(d.get("matched") or "[]")
    return d


def jobs(uid=1, status=None, limit=500):
    q, args = "SELECT * FROM jobs WHERE user_id=?", [uid]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY score DESC, id DESC LIMIT ?"
    args.append(limit)
    with _db() as c:
        return [_row(r) for r in c.execute(q, args).fetchall()]


def get_job(jid, uid=None):
    """Fetch one job. When uid is set, enforce ownership (single-user safe + multi-user ready)."""
    with _db() as c:
        if uid is None:
            r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        else:
            r = c.execute("SELECT * FROM jobs WHERE id=? AND user_id=?", (jid, uid)).fetchone()
        return _row(r) if r else None


def set_job(jid, uid=None, **fields):
    """Update job fields. When uid is set, only updates rows owned by that user."""
    if not fields:
        return 0
    if "matched" in fields:
        fields["matched"] = json.dumps(fields["matched"])
    cols = ", ".join(f"{k}=?" for k in fields)
    with _db() as c:
        if uid is None:
            cur = c.execute(f"UPDATE jobs SET {cols} WHERE id=?", [*fields.values(), jid])
        else:
            cur = c.execute(f"UPDATE jobs SET {cols} WHERE id=? AND user_id=?", [*fields.values(), jid, uid])
        return cur.rowcount


def already_applied_url(uid, url):
    """True if this user already applied (or has ready form) for the same URL."""
    if not url:
        return False
    with _db() as c:
        r = c.execute(
            "SELECT 1 FROM jobs WHERE user_id=? AND url=? AND status IN ('applied','ready') LIMIT 1",
            (uid, url),
        ).fetchone()
        return bool(r)


def applied_today(uid=1):
    """Count real submissions today (status=applied). 'ready' does not consume the daily cap."""
    with _db() as c:
        return c.execute(
            "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='applied' "
            "AND date(applied_at)=date('now')",
            (uid,),
        ).fetchone()[0]


def status_history_note(old_status, new_status, extra=""):
    from datetime import datetime
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    base = f"[{ts}] {old_status} → {new_status}"
    return (base + (f" — {extra}" if extra else ""))[:400]


def stats(uid=1):
    with _db() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) n FROM jobs WHERE user_id=? GROUP BY status", (uid,)
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}


def known_keys(uid=1):
    """(source, ext_id) of every job already stored, so we never re-open or re-add them."""
    with _db() as c:
        return {(r["source"], str(r["ext_id"])) for r in c.execute("SELECT source, ext_id FROM jobs WHERE user_id=?", (uid,))}


def emp_cache_get(source, ext_id, days=14):
    with _db() as c:
        r = c.execute("SELECT kind, reason FROM emp_cache WHERE source=? AND ext_id=? AND checked >= datetime('now', ?)",
                      (source, str(ext_id), f"-{int(days)} days")).fetchone()
        return {"kind": r["kind"], "reason": r["reason"]} if r else None


def emp_cache_put(source, ext_id, kind, reason):
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO emp_cache(source, ext_id, kind, reason, checked) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",
                  (source, str(ext_id), kind, (reason or "")[:200]))


def skip_company_jobs(uid, company):
    """After 'Never apply to this company': move its open jobs to Skipped."""
    with _db() as c:
        return c.execute(
            "UPDATE jobs SET status='skipped', note='Company is on your never-apply list.' "
            "WHERE user_id=? AND lower(company)=lower(?) AND status IN ('new','manual','needs_human','failed','ready')",
            (uid, company)).rowcount
