"""Employment-type detection.

Goal: apply only to direct-payroll / on-roll (permanent) jobs and skip contract-to-hire (C2H),
contract, third-party-payroll and staffing-agency posts.

classify(job, extra_text="") -> {"kind", "reason", "direct"}
  kind   permanent | c2h | contract | agency | unknown
  direct True when the job comes from the employer's own career page or a well-known company

allowed(emp, mode) -> (ok, why)
  mode "any"     keep everything
  mode "direct"  drop c2h / contract / agency, keep permanent + not-stated   (default)
  mode "strict"  keep only confirmed permanent, or not-stated jobs from a direct employer
"""
import json
import re

from .config import DATA

LABELS = {
    "permanent": "Permanent",
    "c2h": "Contract-to-hire",
    "contract": "Contract",
    "agency": "Staffing agency",
    "unknown": "Type not stated",
}
MODES = ("any", "direct", "strict")
DEFAULT_MODE = "direct"

_F = re.I

# ---- strong "this is not a normal permanent job" signals --------------------
C2H_PATTERNS = [
    r"\bc2h\b", r"\bcth\b", r"\bc2p\b",
    r"contract[\s\-/]*(?:to|2)[\s\-/]*(?:hire|perm(?:anent)?|full[\s\-]?time|fte)",
    r"temp[\s\-]*to[\s\-]*(?:perm|hire)",
    r"contract(?:ual)?\s+(?:with|and)\s+(?:a\s+)?(?:possible\s+|potential\s+)?(?:conversion|extension|absorption)",
    r"(?:conversion|convert(?:ed)?|absorb(?:ed)?)\s+(?:to|into|as)\s+(?:a\s+)?(?:full[\s\-]?time|permanent|fte|perm|employee)\b",
]
CONTRACT_PATTERNS = [
    r"\bcontractual\b(?!\s+(?:obligation|requirement|sla|agreement|term|commitment|document|negotiation|compliance))",
    r"\bon\s+contract\b",
    r"\bcontract\s+(?:role|position|basis|job|employee|employment|opportunity|assignment|duration|period|hiring|resource|engagement)\b",
    r"(?<!smart )(?<!smart-)\bcontract\s+(?:of|for)\s+\d+\s*(?:months?|mos?|yrs?|years?)\b",
    r"\b\d+\s*(?:\+\s*)?(?:months?|mos?|yrs?|years?)\s+(?:of\s+)?contract\b",
    r"\b(?:fixed|short)[\s\-]?term\s+(?:contract|role|position|assignment|employment|basis)\b",
    r"\bfixed[\s\-]term\b",
    r"\b(?:third|3rd)[\s\-]*party\b[^.\n]{0,40}\b(?:payroll|contract|role|employment|company|vendor)\b",
    r"\b(?:vendor|agency|staffing|partner|consultancy|contractor)(?:'s)?\s+payroll\b",
    r"\bpayroll\s+of\s+(?:a\s+|the\s+|our\s+)?(?:third|3rd|vendor|partner|staffing|agency)\b",
    r"\btemporary\s+(?:position|role|assignment|employee|employment|basis|job|opening)\b",
    r"\btemporary\s*/\s*contractual\b",
    r"\bfreelanc(?:e|er|ing)\b",
    r"\b(?:extendable|renewable|extension)\b[^.\n]{0,30}\b(?:contract|performance|project)\b",
    r"\bcontract\s+(?:is\s+)?(?:extendable|renewable)\b",
]
# title-only (short text, so a bare word is a safe signal)
TITLE_C2H = re.compile(r"\b(?:c2h|cth|c2p)\b|contract[\s\-]*to[\s\-]*(?:hire|perm)", _F)
TITLE_CONTRACT = re.compile(r"(?<!smart )(?<!smart-)\b(?:contract(?:or|ual)?|freelance|temporary|temp)\b", _F)

# ---- explicit permanent / on-roll signals -----------------------------------
PERMANENT_PATTERNS = [
    r"\bdirect[\s\-]*payroll\b",
    r"\bon[\s\-]?roll\b",
    r"\bon\s+(?:our|the\s+company'?s?|client'?s?)\s+(?:direct\s+)?payroll\b",
    r"\bpermanent\s+(?:position|role|job|employee|employment|opportunity|basis|full[\s\-]?time|payroll)\b",
    r"\bfull[\s\-]?time\s*[,/&\-]?\s*permanent\b",
    r"\bregular\s+(?:full[\s\-]?time\s+)?(?:employee|employment|position)\b",
    r"\bpermanent\b(?!\s*(?:work[\s\-]*from[\s\-]*home|wfh|remote|resident|address|account))",
]

# "Employment Type: Full Time, Permanent"  (Naukri / foundit / Shine detail pages and many JDs)
LABEL_RX = re.compile(
    r"(?:employment|job|hiring|engagement|position|work)\s*(?:type|mode|nature)\s*(?:of\s+employment)?\s*[:\-–]?\s*([^\n.;|]{0,80})", _F)

_NEG_BEFORE = re.compile(
    r"\b(?:not?|non|without|never|isn'?t|aren'?t|neither|nor)\b[\s\-:,/(]*(?:a\s+|an\s+|the\s+|any\s+|being\s+|just\s+|purely\s+|only\s+|on\s+)?$", _F)

_C2H = [re.compile(p, _F) for p in C2H_PATTERNS]
_CONTRACT = [re.compile(p, _F) for p in CONTRACT_PATTERNS]
_PERM = [re.compile(p, _F) for p in PERMANENT_PATTERNS]

# ---- staffing agencies --------------------------------------------------------
AGENCY_NAME = re.compile(
    r"\b(?:staffing|manpower|recruit(?:ment|ers?|ing)|placements?|resourcing|human\s+(?:capital|resources)|"
    r"hr\s+(?:services|solutions|consult\w*|outsourc\w*)|talent\s+(?:solutions|acquisition|partners?)|"
    r"headhunt\w*|executive\s+search|consultants|outsourcing)\b", _F)
HIDDEN_NAME = re.compile(
    r"^\s*(?:confidential|reputed|leading|top|well[\s\-]?known|our\s+client|client\s+of|a\s+leading|a\s+reputed|mnc|multinational)\b|"
    r"\bconfidential\b", _F)
CLIENT_PHRASE = re.compile(
    r"\b(?:our\s+client|on\s+behalf\s+of\s+(?:our|a)\s+client|for\s+one\s+of\s+our\s+clients?|client\s+requirement)\b", _F)
_KNOWN_GOOD = re.compile(r"\b(?:tata\s+consultancy|tcs)\b", _F)   # 'consultancy' singular = real IT company, not an agency
DIRECT_ATS = ("greenhouse", "lever", "ashby")


def _staffing_names():
    try:
        d = json.loads((DATA / "staffing.json").read_text(encoding="utf-8"))
        return [str(x).lower().strip() for x in d.get("agencies", []) if str(x).strip()]
    except Exception:
        return []


def is_agency_name(company):
    c = (company or "").strip().lower()
    if not c or _KNOWN_GOOD.search(c):
        return False
    if AGENCY_NAME.search(c) or HIDDEN_NAME.search(c):
        return True
    return any(re.search(r"\b" + re.escape(a) + r"\b", c) for a in _staffing_names())


def is_avoided(company, prefs):
    """True if the company is on the user's own 'never apply' list."""
    c = (company or "").lower()
    return bool(c) and any(a.strip().lower() in c for a in (prefs.get("avoid_companies") or []) if a and a.strip())


# ---- helpers ------------------------------------------------------------------
def _find(patterns, text):
    """First pattern hit that is not negated ('not a contract role', 'no C2H')."""
    for rx in patterns:
        for m in rx.finditer(text):
            before = text[max(0, m.start() - 30):m.start()]
            if not _NEG_BEFORE.search(before):
                return m.group(0).strip()
    return None


def _label_kind(text):
    for m in LABEL_RX.finditer(text):
        val = m.group(1).lower()
        if re.search(r"contract|temporary|freelanc|c2h|cth|third[\s\-]?party|consultant", val):
            return "contract", m.group(0).strip()[:70]
        if re.search(r"permanent|regular|on[\s\-]?roll", val):
            return "permanent", m.group(0).strip()[:70]
    return None, ""


def _hint_kind(hint):
    h = (hint or "").lower()
    if not h:
        return None
    if re.search(r"contract|temporar|freelanc|fixed", h):
        return "contract"
    if re.search(r"permanent|regular", h):
        return "permanent"
    return None


def is_direct(job):
    """Employer's own career page (Greenhouse / Lever / Ashby) or a company we know by name."""
    if job.get("ats") in DIRECT_ATS:
        return True
    from .filters import classify_company
    return classify_company(job.get("company"))[1] != "unknown" and not is_agency_name(job.get("company"))


def classify(job, extra_text=""):
    title = job.get("title") or ""
    company = job.get("company") or ""
    body = f"{job.get('description') or ''}\n{extra_text or ''}"
    direct = is_direct(job)

    def out(kind, reason):
        return {"kind": kind, "reason": reason, "direct": direct}

    # 1) structured field from the source (Adzuna contract_type, Lever commitment, Ashby employmentType)
    hk = _hint_kind(job.get("employment"))
    if hk == "contract":
        return out("contract", f"Source says: {job.get('employment')}")

    # 2) title
    m = TITLE_C2H.search(title)
    if m:
        return out("c2h", f"'{m.group(0)}' in the job title")
    m = TITLE_CONTRACT.search(title)
    if m and not _NEG_BEFORE.search(title[:m.start()]):
        return out("contract", f"'{m.group(0)}' in the job title")

    # 3) explicit C2H / contract wording anywhere in the posting
    hit = _find(_C2H, body)
    if hit:
        return out("c2h", f"Posting says '{hit}'")
    lk, lreason = _label_kind(body)
    if lk == "contract":
        return out("contract", lreason)
    hit = _find(_CONTRACT, body)
    if hit:
        return out("contract", f"Posting says '{hit}'")

    # 4) positive proof
    positive = None
    if lk == "permanent":
        positive = lreason
    elif hk == "permanent":
        positive = f"Source says: {job.get('employment')}"
    else:
        positive = _find(_PERM, body)

    # 5) recruiter / agency posts
    agency = is_agency_name(company) or bool(CLIENT_PHRASE.search(body))
    if agency and not positive:
        return out("agency", "Posted by a staffing agency / hidden employer")
    if positive:
        note = f"Posting says '{positive}'"
        if agency:
            note += " (recruiter post, but it states permanent)"
        return out("permanent", note)
    return out("unknown", "Employment type not stated")


def allowed(emp, mode=DEFAULT_MODE):
    """-> (ok, why_not)"""
    if mode not in MODES:
        mode = DEFAULT_MODE
    if mode == "any":
        return True, ""
    k = emp["kind"]
    if k in ("c2h", "contract", "agency"):
        return False, f"{LABELS[k]} - {emp['reason']}"
    if mode == "strict" and k == "unknown" and not emp.get("direct"):
        return False, "Employment type not stated (strict mode wants confirmed permanent)"
    return True, ""


def score_bonus(emp):
    b = 0
    if emp["kind"] == "permanent":
        b += 10
    if emp.get("direct"):
        b += 6
    if emp["kind"] in ("c2h", "contract"):
        b -= 40
    elif emp["kind"] == "agency":
        b -= 25
    return b
