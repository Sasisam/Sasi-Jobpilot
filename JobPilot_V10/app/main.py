"""JobPilot Pro — multi-user, token-tracked, Created by Sasi."""
import os
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, db, filters, llm, notify, pipeline, portals, resume
from .runner import RUN

STATIC = Path(__file__).resolve().parent.parent / "static"
db.init()


def _bootstrap_admin():
    u = db.get_user_by_username("sasi")
    if u and not u.get("password_hash"):
        db.set_password(u["id"], auth.hash_password("sasi123"))
        print("[JobPilot] Admin 'sasi' default password set to 'sasi123' — change after first login.")


_bootstrap_admin()


@asynccontextmanager
async def lifespan(_app):
    if config.OPEN_BROWSER:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{config.PORT}")).start()
    yield


app = FastAPI(title="JobPilot · by Sasi", lifespan=lifespan)
app.mount("/shots", StaticFiles(directory=str(config.SHOTS)), name="shots")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    path = request.url.path or ""
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


def current_user(request: Request) -> dict:
    return auth.require_user(request)


def _resume_info(user):
    p = resume.active_path(user.get("resume_path"))
    if not p:
        return None
    st = p.stat()
    return {
        "name": p.name,
        "kb": round(st.st_size / 1024),
        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y, %H:%M"),
        "folder": str(config.RESUME_DIR),
        "ext": p.suffix.lower().lstrip("."),
    }


def _start(phase, fn, *args, label=""):
    return {"started": RUN.start(phase, fn, *args, label=label)}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


class LoginBody(BaseModel):
    username: str
    password: str


class SignupBody(BaseModel):
    username: str
    password: str
    name: Optional[str] = ""


@app.post("/api/auth/login")
def login(b: LoginBody, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    username = (b.username or "").strip().lower()
    if auth.is_locked(ip, username):
        raise HTTPException(429, "Too many failed attempts. Wait 5 minutes.")
    user = db.get_user_for_login(username)
    if not user:
        auth.record_fail(ip, username)
        raise HTTPException(401, "Invalid username or password")
    stored = user.get("password_hash") or ""
    if not stored:
        # First-time admin (or empty hash): set password from this login
        if username == "sasi" or user.get("role") == "admin":
            db.set_password(user["id"], auth.hash_password(b.password))
            user = db.get_user(user["id"])
        else:
            auth.record_fail(ip, username)
            raise HTTPException(401, "Invalid username or password")
    elif not auth.verify_password(b.password, stored):
        auth.record_fail(ip, username)
        raise HTTPException(401, "Invalid username or password")
    auth.clear_fails(ip, username)
    token = auth.create_session(user["id"])
    auth.set_session_cookie(response, token)
    db.update_last_login(user["id"])
    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "tokens": user["tokens"],
            "profile": user["profile"],
        },
    }


@app.post("/api/auth/signup")
def signup(b: SignupBody, request: Request, response: Response):
    username = (b.username or "").strip().lower()
    if len(username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if len(b.password or "") < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if db.get_user_by_username(username):
        raise HTTPException(400, "Username already taken")
    if not db.get_user_by_username("sasi"):
        raise HTTPException(400, "System not ready")
    uid = db.create_user(
        username,
        auth.hash_password(b.password),
        role="user",
        tokens=db.DEFAULT_TOKENS,
        profile={"name": (b.name or "").strip()},
    )
    token = auth.create_session(uid)
    auth.set_session_cookie(response, token)
    user = db.get_user(uid)
    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "tokens": user["tokens"],
            "profile": user["profile"],
        },
    }


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE_NAME)
    auth.destroy_session(token)
    auth.clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "tokens": user["tokens"],
        "profile": user["profile"],
    }


@app.get("/api/state")
def state(user: dict = Depends(current_user)):
    uid = user["id"]
    u = db.get_user(uid)
    nc = config.get_notify_config()
    return {
        "user": {
            "id": u["id"],
            "username": u["username"],
            "role": u["role"],
            "tokens": u["tokens"],
        },
        "profile": u["profile"],
        "prefs": pipeline.effective_prefs(u["prefs"]),
        "resume": _resume_info(u),
        "ai_enabled": llm.available(),
        "email_enabled": nc["email_ready"],
        "push_enabled": nc["push_ready"],
        "notify": nc,
        "portals": [
            {
                "id": p.id,
                "name": p.name,
                "auto": p.auto,
                "blurb": p.blurb,
                "connected": config.portal_connected(p.id, uid=uid),
            }
            for p in portals.PORTALS.values()
        ],
        "city_presets": filters.CITY_PRESETS,
        "run": {
            "running": RUN.running, "stopping": RUN.stopping, "phase": RUN.phase, "label": RUN.label,
            "done": RUN.done, "total": RUN.total, "current": RUN.current,
            "last_run": RUN.last_run, "summary": RUN.last_summary,
        },
        "stats": db.stats(uid),
        "applied_today": db.applied_today(uid),
        "log": list(RUN.log_lines)[-80:],
        "branding": {"app": "JobPilot", "by": "Sasi"},
    }


@app.post("/api/stop")
def stop(user: dict = Depends(current_user)):
    return {"stopping": RUN.request_stop()}


@app.post("/api/resume")
async def upload_resume(file: UploadFile = File(...), user: dict = Depends(current_user)):
    uid = user["id"]
    MAX_RESUME_BYTES = 8 * 1024 * 1024
    raw = await file.read()
    if len(raw) > MAX_RESUME_BYTES:
        raise HTTPException(400, "Resume too large (max 8 MB).")
    if len(raw) < 80:
        raise HTTPException(400, "File is empty or too small.")
    name = file.filename or "resume.pdf"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in (".pdf", ".docx", ".txt"):
        raise HTTPException(400, "Only PDF, DOCX or TXT resumes are accepted.")
    try:
        from io import BytesIO
        dest = resume.save_upload(BytesIO(raw), name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    text = resume.extract_text(dest)
    if len(text.strip()) < 50:
        resume.remove_active()
        raise HTTPException(400, "Could not read text from this file (scanned image?). Use a text PDF or DOCX.")
    profile = resume.parse_profile(text)
    db.save_user(uid, profile=profile, resume_path=dest)
    return {"profile": profile, "resume": _resume_info(db.get_user(uid))}


@app.post("/api/resume/rescan")
def rescan_resume(user: dict = Depends(current_user)):
    uid = user["id"]
    p = resume.active_path(None)
    if not p:
        raise HTTPException(404, "The resume folder is empty.")
    profile = resume.parse_profile(resume.extract_text(p))
    db.save_user(uid, profile=profile, resume_path=p)
    return {"profile": profile, "resume": _resume_info(db.get_user(uid))}


@app.get("/api/resume/file")
def resume_file(user: dict = Depends(current_user)):
    p = resume.active_path(db.get_user(user["id"])["resume_path"])
    if not p:
        raise HTTPException(404)
    return FileResponse(p, filename=p.name)


@app.delete("/api/resume")
def delete_resume(user: dict = Depends(current_user)):
    resume.remove_active()
    db.save_user(user["id"], resume_path="")
    return {"ok": True}


@app.post("/api/resume/open-folder")
def open_folder(user: dict = Depends(current_user)):
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(config.RESUME_DIR))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(config.RESUME_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(config.RESUME_DIR)])
    except Exception:
        pass
    return {"folder": str(config.RESUME_DIR)}


class Body(BaseModel):
    data: dict


@app.put("/api/profile")
def put_profile(b: Body, user: dict = Depends(current_user)):
    db.save_user(user["id"], profile=b.data)
    return {"ok": True}


@app.put("/api/prefs")
def put_prefs(b: Body, user: dict = Depends(current_user)):
    db.save_user(user["id"], prefs=b.data)
    return {"ok": True}


class SearchBody(BaseModel):
    roles: List[str]
    locations: Optional[List[str]] = None
    work_modes: Optional[List[str]] = None
    company_tiers: Optional[List[str]] = None
    company_types: Optional[List[str]] = None
    portals: Optional[List[str]] = None
    experience_years: Optional[float] = None
    employment_mode: Optional[str] = None


@app.post("/api/search")
def search(b: SearchBody, user: dict = Depends(current_user)):
    uid = user["id"]
    if not db.consume_tokens(uid, 1, "search", f"roles={','.join((b.roles or [])[:3])}"):
        raise HTTPException(402, "Insufficient tokens. Ask admin to top-up.")
    prefs = dict(db.get_user(uid)["prefs"] or {})
    if b.roles:
        prefs["roles"] = b.roles
    if b.locations is not None:
        prefs["locations"] = b.locations
    if b.work_modes is not None:
        prefs["work_modes"] = b.work_modes
    if b.company_tiers is not None:
        prefs["company_tiers"] = b.company_tiers
    if b.company_types is not None:
        prefs["company_types"] = b.company_types
    if b.portals is not None:
        prefs["portals"] = b.portals
    if b.experience_years is not None:
        prefs["experience_years"] = b.experience_years
    if b.employment_mode is not None:
        prefs["employment_mode"] = b.employment_mode
    db.save_user(uid, prefs=prefs)
    return _start("search", pipeline.run_once, uid, label="Search jobs")


@app.post("/api/portals/{pid}/connect")
def portal_connect(pid: str, user: dict = Depends(current_user)):
    # Pass this user's id so Naukri/Foundit/etc. login is stored only for them
    return _start("login", portals.connect, pid, user["id"], label=f"Connect {pid}")


@app.post("/api/portals/done")
def portal_done(user: dict = Depends(current_user)):
    """User finished logging in on the portal — signal connect() to continue (do NOT stop)."""
    RUN.done_event.set()
    return {"ok": True}


@app.post("/api/portals/{pid}/disconnect")
def portal_disconnect(pid: str, user: dict = Depends(current_user)):
    config.set_portal_connected(pid, False, uid=user["id"])
    return {"ok": True}


@app.get("/api/portals/links")
def portal_links(role: str = "", loc: str = "", user: dict = Depends(current_user)):
    return portals.manual_links(role, loc)


@app.get("/api/jobs")
def list_jobs(status: str = "", roles: str = "", user: dict = Depends(current_user)):
    uid = user["id"]
    items = db.jobs(uid, status=status or None)
    if roles:
        want = {r.strip().lower() for r in roles.split(",") if r.strip()}
        if want:
            items = [j for j in items if any(w in (j.get("title") or "").lower() for w in want)]
    return {"jobs": items}


@app.post("/api/jobs/clear")
def clear_jobs(user: dict = Depends(current_user)):
    return {"removed": db.clear_jobs(user["id"])}


@app.post("/api/run")
def run_now(user: dict = Depends(current_user)):
    uid = user["id"]
    if not db.consume_tokens(uid, 1, "run", "search+auto-apply"):
        raise HTTPException(402, "Insufficient tokens. Ask admin to top-up.")
    return _start("auto-run", pipeline.run_once, uid, label="Search + auto-apply")


class ApplyBody(BaseModel):
    ids: List[int]
    submit: bool = False


@app.post("/api/apply")
def apply_selected(b: ApplyBody, user: dict = Depends(current_user)):
    uid = user["id"]
    if not b.ids:
        raise HTTPException(400, "No jobs selected")
    if not resume.active_path(db.get_user(uid)["resume_path"]):
        raise HTTPException(400, "Upload your resume first.")
    owned = [jid for jid in b.ids[:50] if db.get_job(jid, uid=uid)]
    if not owned:
        raise HTTPException(400, "No valid jobs to apply")
    if not db.consume_tokens(uid, 1, "apply", f"batch={len(owned)}"):
        raise HTTPException(402, "Insufficient tokens. Ask admin to top-up.")
    prefs = pipeline.effective_prefs(db.get_user(uid)["prefs"])
    if b.submit and db.applied_today(uid) >= prefs["daily_cap"]:
        raise HTTPException(400, f"Daily apply cap ({prefs['daily_cap']}) already reached.")
    return _start("apply", pipeline.apply_batch, owned, uid, b.submit, label="Auto-applying")


@app.post("/api/jobs/{jid}/approve")
def approve(jid: int, user: dict = Depends(current_user)):
    uid = user["id"]
    if not db.get_job(jid, uid=uid):
        raise HTTPException(404)
    prefs = pipeline.effective_prefs(db.get_user(uid)["prefs"])
    if db.applied_today(uid) >= prefs["daily_cap"]:
        raise HTTPException(400, f"Daily apply cap ({prefs['daily_cap']}) already reached.")
    return _start("apply", pipeline.process_application, jid, uid, True, label="Submitting application")


@app.post("/api/jobs/{jid}/retry")
def retry(jid: int, user: dict = Depends(current_user)):
    uid = user["id"]
    if not db.get_job(jid, uid=uid):
        raise HTTPException(404)
    return _start("apply", pipeline.process_application, jid, uid, False, label="Retrying")


class StatusBody(BaseModel):
    status: str


@app.post("/api/jobs/{jid}/status")
def set_status(jid: int, b: StatusBody, user: dict = Depends(current_user)):
    uid = user["id"]
    if b.status not in ("new", "skipped", "applied", "manual"):
        raise HTTPException(400, "bad status")
    if not db.get_job(jid, uid=uid):
        raise HTTPException(404)
    fields = {"status": b.status}
    if b.status == "applied":
        fields.update(
            applied_by="human",
            applied_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            note="Applied by you.",
        )
    if not db.set_job(jid, uid=uid, **fields):
        raise HTTPException(404)
    return {"ok": True}


class AvoidBody(BaseModel):
    company: str


@app.post("/api/avoid")
def avoid_company(b: AvoidBody, user: dict = Depends(current_user)):
    uid = user["id"]
    name = b.company.strip()
    if not name:
        raise HTTPException(400, "No company")
    prefs = dict(db.get_user(uid)["prefs"] or {})
    lst = list(prefs.get("avoid_companies") or [])
    if name.lower() not in [x.lower() for x in lst]:
        lst.append(name)
    prefs["avoid_companies"] = lst
    db.save_user(uid, prefs=prefs)
    return {"ok": True, "skipped": db.skip_company_jobs(uid, name)}


@app.get("/api/notify")
def get_notify(user: dict = Depends(current_user)):
    return config.get_notify_config()


@app.put("/api/notify")
def put_notify(b: Body, user: dict = Depends(current_user)):
    return config.save_notify_config(b.data or {})


@app.post("/api/test-notify")
def test_notify(user: dict = Depends(current_user)):
    return {"sent": notify.notify(
        "Test notification",
        "JobPilot can reach you here. If you got this, email / alerts are working.",
    )}


@app.get("/api/usage")
def usage(user: dict = Depends(current_user)):
    uid = user["id"]
    return {
        "tokens": db.get_tokens(uid),
        "history": db.usage_history(uid, 80),
        "payments": db.payments_history(uid, 40),
    }


@app.get("/api/owner/users")
def owner_users(user: dict = Depends(current_user)):
    auth.require_admin(user)
    return {"users": db.list_users()}


class TopupBody(BaseModel):
    user_id: int
    tokens: int
    note: Optional[str] = ""


@app.post("/api/owner/topup")
def owner_topup(b: TopupBody, user: dict = Depends(current_user)):
    auth.require_admin(user)
    if b.tokens <= 0:
        raise HTTPException(400, "tokens must be positive")
    db.add_tokens(b.user_id, b.tokens, note=b.note or f"Top-up by {user['username']}")
    return {"ok": True, "tokens": db.get_tokens(b.user_id)}


class CreateUserBody(BaseModel):
    username: str
    password: str
    tokens: Optional[int] = 50
    role: Optional[str] = "user"


@app.post("/api/owner/create-user")
def owner_create_user(b: CreateUserBody, user: dict = Depends(current_user)):
    auth.require_admin(user)
    username = (b.username or "").strip().lower()
    if len(username) < 3:
        raise HTTPException(400, "Username too short")
    if db.get_user_by_username(username):
        raise HTTPException(400, "Username taken")
    uid = db.create_user(username, auth.hash_password(b.password), role=b.role or "user", tokens=b.tokens or 50)
    return {"ok": True, "id": uid}



class ResetPwBody(BaseModel):
    user_id: int
    password: str


@app.post("/api/owner/reset-password")
def owner_reset_password(b: ResetPwBody, user: dict = Depends(current_user)):
    auth.require_admin(user)
    if len(b.password or "") < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    target = db.get_user(b.user_id)
    if not target:
        raise HTTPException(404, "User not found")
    db.set_password(b.user_id, auth.hash_password(b.password))
    return {"ok": True, "username": target.get("username")}


@app.get("/api/owner/payments")
def owner_payments(user: dict = Depends(current_user)):
    auth.require_admin(user)
    return {"payments": db.payments_history(None, 100)}
