"""Search -> filter -> score (discover), then apply (auto, or after your click), then notify.
Every loop calls RUN.check()/RUN.sleep(), so the Stop button works within a second or two."""
import random
from datetime import datetime

from . import applier, config, db, employment, filters, matcher, notify, portals, resume, sources
from .runner import RUN, Stopped, log


def effective_prefs(prefs):
    p = {**filters.DEFAULT_PREFS, **(prefs or {})}
    p["min_score"] = int(p.get("min_score") or config.MIN_MATCH_SCORE)
    p["daily_cap"] = int(p.get("daily_cap") or config.DAILY_APPLY_CAP)
    return p


class Sessions:
    """Keeps one logged-in browser window per portal open during a run, closes all at the end.
    Always bound to a single JobPilot user so portal cookies never leak across accounts."""

    def __init__(self, user_id=1):
        self.user_id = int(user_id) if user_id is not None else 1
        self.open = {}

    def get(self, portal):
        if portal.id not in self.open:
            s = portals.Session(portal, user_id=self.user_id)
            s.__enter__()
            self.open[portal.id] = s
        return self.open[portal.id]

    def close(self):
        for s in self.open.values():
            s.__exit__()
        self.open.clear()


def _years(profile, prefs):
    y = prefs.get("experience_years")
    if y in (None, ""):
        y = profile.get("years_experience") or 0
    try:
        return int(float(y))
    except (TypeError, ValueError):
        return 0


def _emp_gate(j, prefs, counts, defer_unknown=False):
    """Classify the posting and decide if it may be kept. Returns True when the job stays.
    defer_unknown: portal card with no type yet - keep it for now, the deep check will read the full JD."""
    emp = employment.classify(j)
    j["_emp"] = emp
    if defer_unknown and emp["kind"] == "unknown":
        return True
    ok, why = employment.allowed(emp, prefs["employment_mode"])
    if ok:
        return True
    counts[emp["kind"]] = counts.get(emp["kind"], 0) + 1
    j["_why"] = why
    return False


def discover(uid=1):
    """Find jobs for the user's roles in India, filter, score, save. No applying.
    Contract / C2H / staffing-agency posts are removed here (prefs: employment_mode)."""
    user = db.get_user(uid)
    profile = user["profile"]
    if not profile or not (profile.get("skills") or profile.get("target_roles")):
        log("No resume yet - upload your resume first.")
        return 0
    prefs = effective_prefs(user["prefs"])
    mode = prefs["employment_mode"] = prefs.get("employment_mode") if prefs.get("employment_mode") in employment.MODES else employment.DEFAULT_MODE
    roles = prefs.get("roles") or profile.get("target_roles") or []
    years = _years(profile, prefs)
    mode_name = {"any": "everything", "direct": "no contract / C2H", "strict": "confirmed permanent only"}[mode]
    log(f"Searching India for: {', '.join(roles) or '(no roles)'}  |  experience {years} yr  |  job type: {mode_name}")
    RUN.progress(0, 1, "Searching job sources")

    raw = sources.collect_open(profile, prefs, filters.load_boards(), RUN.check)
    log(f"Company pages + Adzuna: {len(raw)} postings")

    deep_on = bool(prefs.get("deep_check", True)) and int(prefs.get("deep_check_limit") or 0) > 0
    blocked = {}          # kind -> how many were dropped (shown in the log)
    avoided = 0
    cands = []            # jobs that passed every cheap filter
    known = db.known_keys(uid)

    def prefilter(batch):
        nonlocal avoided
        for j in batch:
            RUN.check()
            if (j["source"], str(j["ext_id"])) in known:
                continue
            j = filters.enrich(j)
            if not filters.passes(j, prefs, years):
                continue
            if employment.is_avoided(j["company"], prefs):
                avoided += 1
                continue
            cached = db.emp_cache_get(j["source"], j["ext_id"])
            if cached and cached["kind"] in ("c2h", "contract", "agency") and mode != "any":
                blocked[cached["kind"]] = blocked.get(cached["kind"], 0) + 1
                continue
            if not _emp_gate(j, prefs, blocked, defer_unknown=deep_on and j["ats"] in portals.PORTALS):
                db.emp_cache_put(j["source"], j["ext_id"], j["_emp"]["kind"], j["_emp"]["reason"])
                continue
            kw = matcher.keyword_score(profile, j, roles)
            if kw["score"] < 30:
                continue
            j.update(kw)
            cands.append(j)

    prefilter(raw)
    sess = Sessions(user_id=uid)
    try:
        portal_raw = []
        for pid in prefs.get("portals", []):
            RUN.check()
            portal = portals.PORTALS.get(pid)
            if not portal or not portal.auto:
                continue
            if not config.portal_connected(pid, uid=uid):
                log(f"{portal.name}: not connected for this user - skipped (connect it in Portals).")
                continue
            RUN.progress(current=f"Searching {portal.name}")
            try:
                portal_raw += portals.search(portal, sess.get(portal), profile, prefs, roles)
            except Stopped:
                raise
            except Exception as e:
                log(f"{portal.name} search error: {str(e)[:150]}")
        prefilter(portal_raw)

        # Deep check: portal cards are short, so open each unsure job once and read the whole JD.
        todo = [j for j in cands if j["ats"] in portals.PORTALS and j["_emp"]["kind"] in ("unknown", "agency")
                and mode != "any"]
        todo.sort(key=lambda x: -x["score"])
        limit = int(prefs.get("deep_check_limit") or 0) if prefs.get("deep_check", True) else 0
        todo = todo[:limit]
        dropped = set()
        for n, j in enumerate(todo):
            RUN.check()
            RUN.progress(n, len(todo), f"Reading job details ({n + 1}/{len(todo)}) - checking for contract / C2H")
            try:
                text = portals.fetch_detail(sess.get(portals.PORTALS[j["ats"]]), j["url"])
            except Stopped:
                raise
            except Exception as e:
                log(f"Could not read {j['title'][:40]}: {str(e)[:80]}")
                continue
            if text:
                if len(text) > len(j.get("description") or ""):
                    j["description"] = text
                    j.update(matcher.keyword_score(profile, j, roles))   # richer text -> better score
                if not _emp_gate(j, prefs, blocked):
                    db.emp_cache_put(j["source"], j["ext_id"], j["_emp"]["kind"], j["_emp"]["reason"])
                    dropped.add(id(j))
            RUN.sleep(random.uniform(1.2, 3.0))
        # anything the strict filter could not confirm (not opened because of the limit) stays out
        for j in cands:
            if id(j) not in dropped and not employment.allowed(j["_emp"], mode)[0]:
                blocked[j["_emp"]["kind"]] = blocked.get(j["_emp"]["kind"], 0) + 1
                dropped.add(id(j))
        cands = [j for j in cands if id(j) not in dropped]
    finally:
        sess.close()

    added = 0
    for j in cands:
        RUN.check()
        emp = j.pop("_emp")
        j.pop("_why", None)
        j["emp_type"], j["emp_note"] = emp["kind"], emp["reason"]
        j["score"] = max(0, min(100, j["score"] + employment.score_bonus(emp)))
        if emp["kind"] == "permanent":
            j["reason"] = (j.get("reason") or "") or emp["reason"]
        if db.add_job(uid, j):
            added += 1
    if mode != "any" and (blocked or avoided):
        parts = [f"{v} {employment.LABELS[k].lower()}" for k, v in blocked.items() if v]
        if avoided:
            parts.append(f"{avoided} from companies you blocked")
        log("Skipped " + ", ".join(parts) + " posts")
    log(f"{added} new matching jobs saved")

    pending = [x for x in db.jobs(uid, status="new") if not x["llm_scored"]][:40]
    for n, job in enumerate(pending):
        RUN.check()
        RUN.progress(n, len(pending), "AI scoring jobs")
        res = matcher.llm_score(profile, job)
        if res:
            blended = int(0.35 * job["score"] + 0.65 * float(res.get("score", job["score"])))
            db.set_job(job["id"], score=blended, reason=str(res.get("reason", ""))[:300], llm_scored=1)
        else:
            db.set_job(job["id"], llm_scored=1)
    log("Search finished")
    return added


def process_application(job_id, uid=1, submit=None, sessions=None):
    user = db.get_user(uid)
    prefs = effective_prefs(user["prefs"])
    job = db.get_job(job_id, uid=uid)
    if not job:
        return "failed"
    if submit is None:
        submit = bool(prefs.get("auto_submit", False))
    who = f"{job['title']} @ {job['company']}"
    RUN.progress(current=who)

    # Daily cap only counts real submissions
    if submit and db.applied_today(uid) >= prefs["daily_cap"]:
        db.set_job(job_id, uid=uid, status="new", note=f"Daily cap ({prefs['daily_cap']}) reached. Try again tomorrow.")
        log(f"CAP REACHED  {who}")
        return "skipped"

    # Skip duplicate URL already applied
    if job.get("status") == "applied":
        log(f"ALREADY      {who}")
        return "applied"
    if db.already_applied_url(uid, job.get("url")) and job.get("status") != "ready":
        db.set_job(job_id, uid=uid, status="skipped", note="Duplicate URL — already applied from another listing.")
        log(f"DUPLICATE    {who}")
        return "skipped"

    if employment.is_avoided(job["company"], prefs):
        db.set_job(job_id, uid=uid, status="skipped", note="Company is on your never-apply list.")
        log(f"AVOIDED      {who}")
        return "skipped"
    emp = employment.classify(job)
    ok, why = employment.allowed(emp, prefs.get("employment_mode", employment.DEFAULT_MODE))
    if not ok:
        db.set_job(job_id, uid=uid, status="skipped", note=f"Skipped: {why}", emp_type=emp["kind"], emp_note=emp["reason"])
        log(f"SKIPPED      {who} - {why}")
        return "skipped"

    rpath = resume.active_path(user["resume_path"])
    if not rpath:
        db.set_job(job_id, uid=uid, status="needs_human", note="No resume found. Upload one in My Resume.")
        log(f"NO RESUME    {who}")
        return "needs_human"
    if job.get("apply_mode") != "auto":
        db.set_job(job_id, uid=uid, status="manual", note="External site - open the link, apply, then press 'I applied'.")
        log(f"MANUAL       {who}")
        return "manual"

    before = job["status"]
    db.set_job(job_id, uid=uid, status="applying", note="Opening the page...")
    log(f"APPLYING     {who}")
    own = sessions is None
    sessions = sessions or Sessions(user_id=uid)
    try:
        status, note = applier.apply(job, user["profile"], str(rpath), submit, sessions, prefs)
    except Stopped:
        db.set_job(job_id, uid=uid, status=before if before != "applying" else "new", note="Stopped by you before it finished.")
        raise
    finally:
        if own:
            sessions.close()
    fields = {"status": status, "note": note}
    if status in ("applied", "ready"):
        fields["applied_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        fields["applied_by"] = "ai"
    db.set_job(job_id, uid=uid, **fields)

    if status == "applied":
        notify.notify(f"Applied: {who}", f"Application submitted by JobPilot.\nMatch score: {job['score']}", link=job["url"])
    elif status == "ready":
        notify.notify(f"Ready to approve: {who}", "Form is filled. Open JobPilot and press Approve & submit.", link=job["url"])
    elif status in ("needs_human", "failed"):
        notify.notify(f"Need your help: {who}", note, urgent=True, link=job["url"])
    log(f"{status.upper():12} {who} - {note}")
    return status


def apply_batch(ids, uid=1, submit=False):
    """The 'Auto apply' button. One job at a time, with human-like pauses, stoppable at any moment.
    Daily cap is enforced on every submission (not only on scheduled runs)."""
    prefs = effective_prefs(db.get_user(uid)["prefs"])
    cap = prefs["daily_cap"]
    # Deduplicate ids while preserving order
    seen, ordered = set(), []
    for jid in ids:
        if jid not in seen:
            seen.add(jid)
            ordered.append(jid)
    ids = ordered

    RUN.progress(0, len(ids))
    sessions = Sessions(user_id=uid)
    done = False
    try:
        for n, jid in enumerate(ids):
            RUN.check()
            if submit and db.applied_today(uid) >= cap:
                log(f"Daily cap ({cap}) reached — stopping batch.")
                remaining = len(ids) - n
                if remaining:
                    RUN.count("cap_stopped")
                break
            RUN.progress(n, len(ids))
            st = process_application(jid, uid, submit, sessions)
            RUN.count(st)
            RUN.progress(n + 1, len(ids))
            if n < len(ids) - 1 and st in ("applied", "ready"):
                RUN.progress(current="Short pause (looks human, protects your account)")
                RUN.sleep(random.uniform(12, 30))
        done = True
    finally:
        sessions.close()
        summary = ("Auto-apply done: " if done else "Auto-apply stopped: ") + (
            ", ".join(f"{v} {k}" for k, v in RUN.counts.items() if v) or "nothing applied")
        RUN.last_summary = summary
        log(summary)
        if done:
            notify.notify("Auto-apply finished", summary)


def run_once(uid=1):
    """'Run now' / scheduled: discover, then auto-apply the best matches."""
    discover(uid)
    prefs = effective_prefs(db.get_user(uid)["prefs"])
    left = max(prefs["daily_cap"] - db.applied_today(uid), 0)
    todo = [x for x in db.jobs(uid, status="new") if x["score"] >= prefs["min_score"]]
    auto = [x["id"] for x in todo if x["apply_mode"] == "auto"][:left]
    manual = [x for x in todo if x["apply_mode"] != "auto"]
    log(f"{len(auto)} auto-apply jobs above score {prefs['min_score']}, {len(manual)} need manual apply")
    if auto:
        apply_batch(auto, uid, bool(prefs.get("auto_submit", False)))
    if manual:
        notify.notify("Manual applications waiting", f"{len(manual)} good-fit jobs are on external sites.", urgent=False)
