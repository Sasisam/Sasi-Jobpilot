import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
SHOTS = DATA / "shots"
SHOTS.mkdir(exist_ok=True)
DB_PATH = DATA / "jobpilot.db"

# Your resume lives HERE, in the visible "resume" folder next to the app.
RESUME_DIR = BASE / "resume"
RESUME_DIR.mkdir(exist_ok=True)
RESUME_EXTS = (".pdf", ".docx", ".txt")

BROWSER_PROFILES = DATA / "browser_profiles"   # your portal logins live here, on your PC only
BROWSER_PROFILES.mkdir(exist_ok=True)
_PORTALS_FILE = DATA / "portals.json"
_NOTIFY_FILE = DATA / "notify.json"


def _bool(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-20250514").strip()

# Email / alert defaults from .env; can be overridden at runtime via notify.json (UI)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", SMTP_USER).strip()
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "").strip()

AUTO_SUBMIT = _bool("AUTO_SUBMIT", "false")  # safer default: fill only; user approves submit
MIN_MATCH_SCORE = _int("MIN_MATCH_SCORE", 55)
DAILY_APPLY_CAP = _int("DAILY_APPLY_CAP", 25)
RUN_EVERY_MINUTES = _int("RUN_EVERY_MINUTES", 0)
HEADLESS = _bool("HEADLESS", "true")             # Greenhouse / Lever forms
PORTAL_HEADLESS = _bool("PORTAL_HEADLESS", "false")  # Indian portals: visible window is safer
OPEN_BROWSER = _bool("OPEN_BROWSER", "true")
PORT = _int("PORT", 8000)


def _load_notify_overrides():
    """UI-saved email / ntfy settings override .env without restarting."""
    global SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, NOTIFY_EMAIL, NTFY_TOPIC
    try:
        d = json.loads(_NOTIFY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    if d.get("smtp_host"):
        SMTP_HOST = str(d["smtp_host"]).strip()
    if d.get("smtp_port"):
        try:
            SMTP_PORT = int(d["smtp_port"])
        except (TypeError, ValueError):
            pass
    if "smtp_user" in d:
        SMTP_USER = str(d.get("smtp_user") or "").strip()
    if "smtp_pass" in d and d.get("smtp_pass"):
        SMTP_PASS = str(d["smtp_pass"]).strip()
    if "notify_email" in d:
        NOTIFY_EMAIL = str(d.get("notify_email") or "").strip() or SMTP_USER
    if "ntfy_topic" in d:
        NTFY_TOPIC = str(d.get("ntfy_topic") or "").strip()


_load_notify_overrides()


def get_notify_config():
    """Safe view for the dashboard (password never returned)."""
    return {
        "smtp_host": SMTP_HOST,
        "smtp_port": SMTP_PORT,
        "smtp_user": SMTP_USER,
        "notify_email": NOTIFY_EMAIL,
        "ntfy_topic": NTFY_TOPIC,
        "email_ready": bool(SMTP_USER and SMTP_PASS and NOTIFY_EMAIL),
        "push_ready": bool(NTFY_TOPIC),
        "has_pass": bool(SMTP_PASS),
    }


def save_notify_config(data: dict):
    """Persist email / alert settings from the UI and reload into process."""
    global SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, NOTIFY_EMAIL, NTFY_TOPIC
    cur = {}
    try:
        cur = json.loads(_NOTIFY_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    for k in ("smtp_host", "smtp_port", "smtp_user", "notify_email", "ntfy_topic"):
        if k in data and data[k] is not None:
            cur[k] = data[k]
    if data.get("smtp_pass"):
        cur["smtp_pass"] = data["smtp_pass"]
    _NOTIFY_FILE.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    _load_notify_overrides()
    return get_notify_config()


def _portal_state():
    try:
        return json.loads(_PORTALS_FILE.read_text())
    except Exception:
        return {}


def _user_portal_key(uid) -> str:
    return f"user_{int(uid)}"


def portal_connected(pid, uid=None):
    """Per-user portal login state. Each user has their own Naukri/Foundit/etc. session."""
    s = _portal_state()
    if uid is None:
        # Legacy global key (single-user era) — only used if no uid is known
        return bool(s.get(pid))
    user_s = s.get(_user_portal_key(uid)) or {}
    if pid in user_s:
        return bool(user_s[pid])
    # Do NOT fall back to global keys — that was the multi-user bug
    return False


def set_portal_connected(pid, on, uid=None):
    """Mark portal connected/disconnected for one user only."""
    s = _portal_state()
    if uid is None:
        s[pid] = bool(on)
    else:
        key = _user_portal_key(uid)
        user_s = dict(s.get(key) or {})
        user_s[pid] = bool(on)
        s[key] = user_s
    _PORTALS_FILE.write_text(json.dumps(s, indent=2))


def portal_profile_dir(pid, uid) -> Path:
    """Persistent browser profile path for one user + one portal (isolated logins)."""
    return BROWSER_PROFILES / _user_portal_key(uid) / str(pid)
