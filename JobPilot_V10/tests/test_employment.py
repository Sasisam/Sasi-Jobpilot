import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app import employment as E


def J(title="DevOps Engineer", company="Acme Tech", desc="", **kw):
    return {"title": title, "company": company, "description": desc, "ats": kw.pop("ats", "naukri"), **kw}


@pytest.mark.parametrize("desc,kind", [
    ("This is a C2H role for 6 months", "c2h"),
    ("Contract to hire opportunity with our client", "c2h"),
    ("Contract-to-Hire, Chennai", "c2h"),
    ("CTH position, immediate joiners", "c2h"),
    ("Temp to perm conversion after 6 months", "c2h"),
    ("Contract with possible conversion to FTE", "c2h"),
    ("Employment Type: Full Time, Temporary/Contractual", "contract"),
    ("Job Type: Contract", "contract"),
    ("Hiring on third party payroll", "contract"),
    ("Role is on contract basis for 12 months", "contract"),
    ("6 months contract, extendable", "contract"),
    ("Fixed term engagement", "contract"),
    ("Freelance DevOps consultant", "contract"),
    ("Employment Type:\nFull Time, Permanent", "permanent"),
    ("We offer a permanent position with benefits", "permanent"),
    ("Direct payroll of the company", "permanent"),
    ("On-roll opportunity", "permanent"),
    ("Strong AWS, Terraform and Jenkins skills required", "unknown"),
    ("Handle temporary credentials via STS and smart contract audits", "unknown"),
    ("Meet contractual SLAs with customers", "unknown"),
    ("Permanent work from home available", "unknown"),
    ("This is not a contract role. Permanent position.", "permanent"),
    ("No C2H. Full time permanent employee.", "permanent"),
    ("Non-contract, regular full-time employee", "permanent"),
])
def test_text(desc, kind):
    assert E.classify(J(desc=desc))["kind"] == kind, desc


def test_title():
    assert E.classify(J(title="DevOps Engineer - C2H"))["kind"] == "c2h"
    assert E.classify(J(title="DevOps Engineer (Contract)"))["kind"] == "contract"
    assert E.classify(J(title="Smart Contract Developer"))["kind"] == "unknown"


def test_agency_names():
    for c in ["ABC Consultants", "XYZ Staffing Solutions", "Quess Corp Limited", "TeamLease Services",
              "Confidential", "Leading MNC", "Randstad India", "Sri Manpower Services", "Michael Page"]:
        assert E.is_agency_name(c), c
    for c in ["Tata Consultancy Services", "Infosys", "Accenture", "Zoho", "Hayes Software"]:
        assert not E.is_agency_name(c), c


def test_agency_vs_permanent():
    assert E.classify(J(company="ABC Consultants", desc="Great DevOps role"))["kind"] == "agency"
    r = E.classify(J(company="ABC Consultants", desc="Permanent position with our client"))
    assert r["kind"] == "permanent" and "recruiter" in r["reason"]
    assert E.classify(J(company="ABC Consultants", desc="C2H role"))["kind"] == "c2h"
    assert E.classify(J(desc="Opening with our client in Chennai"))["kind"] == "agency"


def test_structured_hint():
    assert E.classify(J(employment="contract"))["kind"] == "contract"
    assert E.classify(J(employment="Contract", ats="lever"))["kind"] == "contract"
    assert E.classify(J(employment="permanent"))["kind"] == "permanent"
    assert E.classify(J(employment="Full-time"))["kind"] == "unknown"


def test_direct_flag():
    assert E.classify(J(ats="greenhouse", company="Some Startup"))["direct"]
    assert E.classify(J(company="Google"))["direct"]
    assert not E.classify(J(company="Random Pvt Ltd"))["direct"]


def test_modes():
    u = E.classify(J(company="Random Pvt Ltd"))
    d = E.classify(J(ats="lever"))
    p = E.classify(J(desc="Permanent role"))
    c = E.classify(J(desc="C2H"))
    assert E.allowed(c, "any")[0]
    assert not E.allowed(c, "direct")[0] and not E.allowed(c, "strict")[0]
    assert E.allowed(u, "direct")[0] and not E.allowed(u, "strict")[0]
    assert E.allowed(d, "strict")[0] and E.allowed(p, "strict")[0]


def test_avoid():
    assert E.is_avoided("Wipro Limited", {"avoid_companies": ["wipro"]})
    assert not E.is_avoided("Zoho", {"avoid_companies": ["wipro", ""]})
    assert E.score_bonus(E.classify(J(desc="C2H"))) < 0 < E.score_bonus(E.classify(J(desc="Permanent role")))
