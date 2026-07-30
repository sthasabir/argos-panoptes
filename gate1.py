"""
Gate 1 — cheap, rule-based hard exclusions. No LLM.
Runs on every recommendation before any Opus call to fast-fail junk and cut cost.

Operates primarily on Tsenta's STRUCTURED fields (seniorityLevel, yearsOfExperienceMin,
sponsorship, roleFamily) and falls back to title/skill regex for the rest.

Returns (kept, dropped) where each dropped item carries a reason.
"""
from __future__ import annotations
import re

from profile import ROLE_FAMILY_MAP

SENIOR_LEVELS = {"senior", "staff", "principal", "lead", "manager", "director",
                 "architect", "vp", "head", "executive"}
MAX_YOE = 3  # new grad: 3+ required years => drop

# title-based catches for when structured level is null/misleading (e.g. "None" w/ YOE 10)
TITLE_SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|architect|head\s+of|vp|"
    r"distinguished|fellow|founding)\b", re.I)
# intern / co-op / apprenticeship — off-target for a graduated new-grad needing H1B
TITLE_INTERN = re.compile(
    r"\b(intern|internship|co-?op|apprentice(ship)?|working\s+student|werkstudent|praktikum)\b", re.I)
TITLE_BASIC_IT = re.compile(
    r"\b(help\s?desk|desktop\s+support|service\s+desk|it\s+support|tier\s*[12]\s+support|"
    r"manual\s+(qa|test)|field\s+technician|deskside|sales|account\s+executive|recruiter)\b", re.I)
TITLE_CS_RELEVANT = re.compile(
    r"\b(software|engineer|developer|swe|sde|backend|back-?end|full.?stack|front.?end|"
    r"ai|ml|machine\s+learning|data|platform|infrastructure|devops|cloud|api|programmer)\b", re.I)

# sponsorship values Tsenta emits; only an explicit NO is a dealbreaker
SPONSOR_NO = {"NONE", "NO", "NOT_AVAILABLE", "NO_SPONSORSHIP", "US_CITIZEN_ONLY", "CITIZEN_ONLY"}


def normalize_family(job: dict) -> str:
    rf = (job.get("roleFamily") or "").upper()
    return ROLE_FAMILY_MAP.get(rf, "other")


def _drop(job: dict, reason: str) -> dict:
    return {"id": job.get("id"), "title": job.get("title"),
            "company": job.get("companyName"), "reason": reason}


def gate1(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    for j in jobs:
        title = j.get("title") or ""
        level = (j.get("seniorityLevel") or "").strip().lower()
        yoe = j.get("yearsOfExperienceMin")
        sponsor = (j.get("sponsorship") or "").upper()

        # 1) explicit senior level
        if level in SENIOR_LEVELS:
            dropped.append(_drop(j, f"senior level: {j.get('seniorityLevel')}")); continue
        # 2) senior signalled in title even if level field is null/mislabeled
        if TITLE_SENIOR.search(title):
            dropped.append(_drop(j, f"senior title: {title}")); continue
        # 3) too many required years for a new grad
        if isinstance(yoe, (int, float)) and yoe >= MAX_YOE:
            dropped.append(_drop(j, f"requires {yoe}+ YOE")); continue
        # 3b) intern / co-op / apprenticeship (graduated new-grad wants full-time)
        if TITLE_INTERN.search(title):
            dropped.append(_drop(j, f"intern/co-op: {title}")); continue
        # 4) explicit no-sponsorship (UNKNOWN / CASE_BY_CASE pass through to Gate 2)
        if sponsor in SPONSOR_NO:
            dropped.append(_drop(j, f"no sponsorship: {j.get('sponsorship')}")); continue
        # 5) basic-IT / non-eng
        if TITLE_BASIC_IT.search(title):
            dropped.append(_drop(j, f"basic-IT/non-eng: {title}")); continue
        # 6) must look CS-relevant
        if not TITLE_CS_RELEVANT.search(title):
            dropped.append(_drop(j, f"not CS-relevant: {title}")); continue

        kept.append(j)
    return kept, dropped
