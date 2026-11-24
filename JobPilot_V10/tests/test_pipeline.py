import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app import config, db, pipeline, portals, sources


def job(i, title, company, desc, ats="greenhouse", **kw):
    return {"source": f"{ats}:{company}" if ats in ("greenhouse", "lever", "ashby") else ats, "ext_id": str(i), "ats": ats,
            "title": title, "company": company, "location": "Chennai, India", "url": f"https://x.test/{i}",
            "description": desc, "remote": False, "exp": "", "salary": "", **kw}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()
    prof = {"skills": ["aws", "terraform", "jenkins", "docker"], "target_roles": ["DevOps Engineer"], "years_experience": 5}
    db.save_user(1, profile=prof, prefs={"roles": ["DevOps Engineer"], "portals": ["naukri"], "avoid_companies": ["Blocked Corp"]})
    monkeypatch.setattr(config, "portal_connected", lambda pid: True)

    class FakeSessions:
        def get(self, portal): return object()
        def close(self): pass
    monkeypatch.setattr(pipeline, "Sessions", FakeSessions)
    return prof


def run(monkeypatch, open_jobs, portal_jobs, details):
    monkeypatch.setattr(sources, "collect_open", lambda *a, **k: list(open_jobs))
    monkeypatch.setattr(portals, "search", lambda *a, **k: list(portal_jobs))
    monkeypatch.setattr(portals, "fetch_detail", lambda sess, url: details.get(url, ""))
    monkeypatch.setattr(pipeline.RUN, "sleep", lambda s: None)
    pipeline.discover(1)
    return {j["title"]: j for j in db.jobs(1)}


def test_discover_filters_c2h(env, monkeypatch):
    open_jobs = [
        job(1, "DevOps Engineer", "Zoho", "AWS Terraform Jenkins. Permanent position."),
        job(2, "DevOps Engineer - Cloud", "Freshworks", "AWS Terraform Docker", ats="lever", employment="Full-time"),
        job(3, "DevOps Engineer C2H", "Acme", "AWS Terraform Jenkins"),
        job(4, "DevOps Engineer", "Nova", "AWS Terraform. 6 months contract, extendable", ats="ashby"),
        job(5, "DevOps Engineer II", "Blocked Corp", "AWS Terraform Jenkins Docker"),
        job(6, "DevOps Engineer III", "Mega", "AWS Terraform", ats="lever", employment="Contract"),
    ]
    portal_jobs = [
        job(10, "DevOps Engineer Naukri A", "Alpha Pvt Ltd", "AWS Terraform", ats="naukri"),
        job(11, "DevOps Engineer Naukri B", "Beta Pvt Ltd", "AWS Terraform", ats="naukri"),
        job(12, "DevOps Engineer Naukri C", "Gamma Pvt Ltd", "AWS Terraform", ats="naukri"),
        job(13, "DevOps Engineer Naukri D", "XYZ Staffing Solutions", "AWS Terraform", ats="naukri"),
    ]
    details = {
        "https://x.test/10": "Role: DevOps\nEmployment Type: Full Time, Temporary/Contractual\nAWS Terraform",
        "https://x.test/11": "Role: DevOps\nEmployment Type:\nFull Time, Permanent\nAWS Terraform Jenkins Docker " * 3,
        "https://x.test/12": "",   # page unreadable -> stays 'unknown', still allowed in default mode
    }
    got = run(monkeypatch, open_jobs, portal_jobs, details)
    assert set(got) == {"DevOps Engineer", "DevOps Engineer - Cloud", "DevOps Engineer Naukri B", "DevOps Engineer Naukri C"}
    assert got["DevOps Engineer"]["emp_type"] == "permanent"
    assert got["DevOps Engineer Naukri B"]["emp_type"] == "permanent"
    assert got["DevOps Engineer Naukri C"]["emp_type"] == "unknown"
    assert got["DevOps Engineer - Cloud"]["score"] >= 60      # direct employer bonus
    # permanent ranks above unknown from the same portal
    assert got["DevOps Engineer Naukri B"]["score"] > got["DevOps Engineer Naukri C"]["score"]
    # the blocked ones are remembered, so the next search does not re-open them
    assert db.emp_cache_get("naukri", "10")["kind"] == "contract"


def test_strict_mode(env, monkeypatch):
    db.save_user(1, prefs={"roles": ["DevOps Engineer"], "portals": ["naukri"], "employment_mode": "strict"})
    got = run(monkeypatch,
              [job(1, "DevOps Engineer", "Freshworks", "AWS Terraform Docker", ats="lever")],
              [job(2, "DevOps Engineer P", "Alpha Pvt Ltd", "AWS Terraform", ats="naukri"),
               job(3, "DevOps Engineer Q", "Beta Pvt Ltd", "AWS Terraform", ats="naukri")],
              {"https://x.test/2": "Employment Type: Full Time, Permanent. AWS Terraform"})
    assert set(got) == {"DevOps Engineer", "DevOps Engineer P"}     # unverified Naukri job (3) dropped


def test_any_mode_keeps_everything_ranked_lower(env, monkeypatch):
    db.save_user(1, prefs={"roles": ["DevOps Engineer"], "portals": [], "employment_mode": "any"})
    got = run(monkeypatch, [job(1, "DevOps Engineer", "Zoho", "AWS Terraform Jenkins. Permanent role"),
                            job(2, "DevOps Engineer ", "Acme", "AWS Terraform Jenkins. C2H role", ats="ashby")], [], {})
    assert len(got) == 2
    c2h = next(j for j in got.values() if j["emp_type"] == "c2h")
    perm = next(j for j in got.values() if j["emp_type"] == "permanent")
    assert c2h["score"] < perm["score"]


def test_apply_gate_blocks_old_rows(env, monkeypatch):
    jid = db.add_job(1, {**job(7, "DevOps Engineer", "Acme", "AWS. Contract to hire"), "source": "naukri", "ats": "naukri", "score": 90})
    monkeypatch.setattr(pipeline.resume, "active_path", lambda p: Path(__file__))
    assert pipeline.process_application(jid, 1, submit=False) == "skipped"
    row = db.get_job(jid)
    assert row["status"] == "skipped" and "Contract-to-hire" in row["note"]
