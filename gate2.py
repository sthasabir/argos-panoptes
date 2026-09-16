"""
Gate 2 — Gemini 3.6 Flash (on Vertex, global endpoint) scores each Gate-1 survivor
0-10, re-checks dealbreakers on the full JD (defense in depth), returns strict JSON.
Only jobs with eligible=true AND fit_score >= THRESHOLD survive, ranked best-first.

First-party model → runs on the free-trial credit, no Marketplace enablement needed.
Model is env-configurable (SCORER_MODEL) so we can swap to Opus 5 later if billing upgrades.
"""
from __future__ import annotations
import json
import os

from google import genai
from google.genai import types

from profile import (CANDIDATE, ROLE_FAMILY_PRIORITY, SENIORITY, MIN_SALARY,
                     REGION_ALLOW_REMOTE)
# REGION_ON, not profile.REQUIRE_REGION: gate1 resolves the flag against the
# environment, and reading the raw constant here would leave this prompt telling the
# scorer to reject non-East-Coast jobs after REQUIRE_REGION=0 had already switched the
# rule off in gate1 — every out-of-region job would pass gate 1 and then score 0.
from gate1 import normalize_family, REGION_ON, effective_floor, pays_enough

SCORER_MODEL = os.environ.get("SCORER_MODEL", "gemini-3.6-flash")
VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT")
if not VERTEX_PROJECT:
    raise RuntimeError("VERTEX_PROJECT is not set — see .env (upstream defaulted this "
                       "to the original author's GCP project)")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "global")
THRESHOLD = float(os.environ.get("SCORE_THRESHOLD", "6.0"))

_client = None

# East Coast restriction, stated in prose because Gate 1 only ever sees the feed's
# `locations` field while the JD often names the real work location. Gate 1 drops
# out-of-region postings on structured data; this catches the ones that reach here
# with a vague or missing location.
_REGION_RULE = ("""
- Is based OUTSIDE THE EAST COAST. The candidate searches the Eastern time zone only:
  ME NH VT MA RI CT NY NJ PA DE MD DC VA WV NC SC GA FL, plus OH MI IN KY TN. Reject
  anything whose work location is a metro outside that list — California, Texas,
  Washington, Colorado, Arizona, Illinois, Utah, Minnesota and the rest of the
  Central/Mountain/Pacific states. """ + (
    "A US-remote role with no required metro is acceptable. If the posting is remote "
    "but requires being near an office outside the East Coast, reject it."
    if REGION_ALLOW_REMOTE else
    "Even fully remote roles must name an East Coast location.")) if REGION_ON else ""


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=VERTEX_PROJECT, location=VERTEX_LOCATION)
    return _client

SYSTEM = f"""You score job fit for {CANDIDATE['name']}, an experienced individual
contributor with {CANDIDATE['years_experience']}+ years as a {CANDIDATE['current_title']}.
Work authorization: {CANDIDATE['work_authorization']} — needs NO visa sponsorship and
is authorized to work in the US indefinitely.

Candidate stack: {", ".join(CANDIDATE['stack'])}.
Target role families in priority order: {", ".join(CANDIDATE['target_role_families'])}.

TARGET BAND: mid-level through senior individual contributor. "Software Engineer III",
"Mid-level", "Senior" and "Sr" titles are IN SCOPE — do not penalise them. "Software
Engineer II" is one rung too low and is out. The ceiling is hard: nothing at Lead,
Staff, Principal, Architect, Manager or VP level, however good the stack match.

You are a STRICT gatekeeper. Set eligible=false and fit_score=0 if the job description
reveals ANY dealbreaker the structured fields may have missed:
- The job is NOT located in the United States. The candidate will not relocate abroad.
  Reject anything based in India, Canada, Europe, LATAM, APAC or anywhere outside the
  US, including postings written in a language other than English. "Remote" counts only
  if the posting is remote WITHIN the US. This is about the COUNTRY and is separate from
  the onsite/hybrid rule below: silence about office attendance means remote, but silence
  about country does NOT mean the United States. If the employer describes itself as
  based in Africa, India, Canada, Europe, LATAM or APAC, reject it even when the posting
  says "remote" and names no city.{_REGION_RULE}
- The role's ACTUAL technology stack does not match the candidate's. Read the job
  description and check the real requirements — do not assume a fit just because the
  candidate is a broad full-stack engineer. Reject mobile (iOS/Swift/Android/Kotlin-
  mobile/React Native), embedded/firmware, mainframe/COBOL, Salesforce/ServiceNow/SAP,
  .NET/C#-primary, PHP, Ruby, and Go-primary roles: none are this candidate's stack.
- Is a MANAGER or VP role of any kind — engineering manager, people manager, director,
  head of, VP, SVP, EVP, AVP, Vice President, Assistant Vice President. Reject these
  outright, even at a bank where those are only seniority ranks.
- Is OUTSIDE the Engineer III band. "Software Engineer II"/"Developer II" is one rung
  too low; "Software Engineer IV"/"Engineer 4" and above is too high. Engineer III and
  plain "Senior Software Engineer" are the target.
- Requires MORE than 8 years of experience.
- Is posted by a staffing agency, IT-services vendor, consultancy or job aggregator
  placing candidates at a client site rather than hiring directly.
- Is at LEAD LEVEL OR ABOVE. Reject "Tech Lead", "Team Lead", "Lead Engineer",
  "Sr Lead", "Engineering Lead", and also Staff, Principal, Distinguished, Fellow and
  Architect titles, or any role whose core responsibility is leading/directing other
  engineers. The candidate wants senior individual-contributor roles at or below
  Senior Engineer — reject lead-and-above even when the stack is a perfect match.
- Demands more than {SENIORITY['max_years_required']} years of experience
- Is aimed at new grads / interns / entry level, well below this candidate's band
- Requires a MASTER'S DEGREE or PhD. The candidate holds a Bachelor of Information
  Technology only. "Bachelor's required, Master's preferred" is ACCEPTABLE — reject only
  when an advanced degree is genuinely mandatory with no bachelor's-plus-experience path.
- Requires a US SECURITY CLEARANCE of any level — Confidential, Secret, Top Secret,
  TS/SCI, or any polygraph. Clearances require US citizenship, which the candidate does
  not have, so "must be able to OBTAIN a clearance" is equally disqualifying. PUBLIC
  TRUST is NOT a clearance: it is a suitability check and permanent residents are
  eligible, so do not reject a Public Trust role.
- Requires U.S. CITIZENSHIP. The candidate is a Permanent Resident (green card), NOT a
  citizen. Reject any role stating citizenship is required, including "required per
  contract" federal work with no clearance attached. A posting that says "U.S. Citizen
  OR Permanent Resident / Green Card Holder" is ACCEPTABLE — only reject when
  citizenship is demanded to the exclusion of permanent residents. "Public Trust" alone
  is a suitability check, not a clearance, and permanent residents are eligible.
- REQUIRES ONSITE WORK. Remote is preferred and HYBRID IS ACCEPTABLE ANYWHERE IN THE
  UNITED STATES — the candidate is willing to RELOCATE for a hybrid role. Do NOT reject
  a hybrid job because of which state or city it is in. Charlotte, Austin, Dallas,
  Cincinnati, Phoenix, Seattle, San Francisco, Chicago and every other US metro are all
  acceptable. There is no commuting radius and no "commutable from Example City, MD"
  test — that rule was retired on 2026-08-18 and rejecting on it drops good jobs.
  Gate 1 already enforces the only two excluded hybrid states (New York and Arizona),
  so never re-reject on geography. Fully onsite (5 days, no remote component) roles are
  still out everywhere. Gate 1 has already checked the structured workplaceType — do not
  re-litigate it from a city name. Remote listings almost always name a headquarters or "home office" city, and
  that alone is NOT evidence of onsite work. Reject ONLY when the description states a
  requirement: "must work from our X office", "hybrid, 3 days per week onsite",
  "relocation to X required", or an explicit onsite expectation. When the description is
  silent or ambiguous about location, treat it as remote and do NOT reject.
- PAY. Do NOT do this arithmetic yourself. `salary_check_passed` is the result of a
  deterministic check already run against the posted range, using the location-adjusted
  `minimum_acceptable_base_usd` supplied with this job (the absolute floor anywhere is
  ${MIN_SALARY:,.0f}).
    * `salary_check_passed: true`  -> pay is ACCEPTABLE. Do not raise pay as a
      dealbreaker and do not mention it. This is true even when the BOTTOM of the range
      sits below the minimum: a wide band is judged by its TOP, because the bottom
      reflects a cheaper metro or a more junior hire.
    * `salary_check_passed: false` -> reject on pay.
    * `salary_check_passed: null`  -> the posting published no usable figure. Reject on
      pay ONLY if the description itself states a maximum base below the minimum.
  Never compare the minimum against `salaryMin`. A posting of $91,700-$163,700 against a
  $140,000 floor PASSES, because $163,700 exceeds $140,000.
- Is a contract, contract-to-hire, C2C, 1099, part-time or temporary engagement. Only
  permanent full-time employment.
- Is really IT-support / help-desk / manual-QA / sales / non-engineering
- Is at, or is a staffing listing FOR, any of these employers (current or past):
  Meridian Financial, Meridian, Vantage Capital, Cornerstone Bank / Cornerstone Bancorp. Vendor postings
  sometimes name the end client in the title while listing a staffing firm as the
  company — reject those too.
Note: "no visa sponsorship" is NOT a dealbreaker — the candidate is a permanent resident.

Otherwise score 0-10 on: stack overlap (Java/Spring Boot/microservices/Angular/React/AWS
are the core), seniority match, and role-family match (backend/fullstack/swe strong;
ops/data-entry weak). Be honest and calibrated: a 10 is a senior backend or full-stack
Java role in his stack; a 6 is a reasonable fit; below 6 means don't bother applying."""

SCHEMA = {
    "type": "object",
    "properties": {
        "role_family": {"type": "string", "enum": ["fullstack", "backend", "ai_ml", "swe", "other"]},
        "fit_score": {"type": "number"},
        "eligible": {"type": "boolean"},
        "matched_skills": {"type": "array", "items": {"type": "string"}},
        "dealbreakers": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["role_family", "fit_score", "eligible", "reason"],
}

def _build_config(thinking: bool) -> types.GenerateContentConfig:
    kw = dict(
        system_instruction=SYSTEM,
        temperature=0,
        max_output_tokens=4096,          # room for thinking + full JSON (was truncating at 600)
        response_mime_type="application/json",
        response_schema=SCHEMA,
    )
    if not thinking:
        try:
            kw["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass
    return types.GenerateContentConfig(**kw)


# some Gemini 3.x models reject thinking_budget=0; fall back to thinking-on if so
_CONFIG = _build_config(thinking=False)
_CONFIG_FALLBACK = _build_config(thinking=True)


def _brief(job: dict, jd_text: str) -> str:
    # pays_enough() answers True for an unpriced posting (half the feed has no salary),
    # which would tell the scorer "pay is acceptable" about a job that published no
    # figure at all. Distinguish the two: null means "nothing to check, read the JD".
    _has_figure = bool(job.get("salaryMax") or job.get("salaryMin"))
    return json.dumps({
        "title": job.get("title"),
        "company": job.get("companyName"),
        "seniorityLevel": job.get("seniorityLevel"),
        "yearsOfExperienceMin": job.get("yearsOfExperienceMin"),
        "sponsorship": job.get("sponsorship"),
        "roleFamily": job.get("roleFamily"),
        "skillTags": job.get("skillTags"),
        "matchScore": job.get("matchScore"),
        # Salary is handed over BOTH as structured numbers and as an already-decided
        # verdict. Asking the model to parse a range out of prose and compare it was a
        # real bug: an Optum posting of $91,700-$163,700 against a $140,000 floor was
        # rejected as "salary maximum below acceptable base" — the model had compared
        # the BOTTOM of the range. gate1 does this arithmetic deterministically and
        # correctly, so the answer is supplied rather than re-derived.
        "salaryMin": job.get("salaryMin"),
        "salaryMax": job.get("salaryMax"),
        "salaryCurrency": job.get("salaryCurrency"),
        # Per-job, because the bar is location-adjusted: a New York posting has to
        # clear ~$185k while a Plano one clears $140k.
        "minimum_acceptable_base_usd": round(effective_floor(job)),
        "salary_check_passed": pays_enough(job) if _has_figure else None,
        "locations": job.get("locations"),
        "description": (jd_text or "")[:4000],
    }, ensure_ascii=False)


def _score_one(job: dict, jd_text: str) -> dict:
    brief = _brief(job, jd_text)
    client = _get_client()
    try:
        resp = client.models.generate_content(model=SCORER_MODEL, contents=brief, config=_CONFIG)
    except Exception:
        resp = client.models.generate_content(model=SCORER_MODEL, contents=brief, config=_CONFIG_FALLBACK)
    out = json.loads(resp.text)
    out["job_id"] = job.get("id")
    out["title"] = job.get("title")
    out["company"] = job.get("companyName")
    out["url"] = job.get("url")
    out["datePosted"] = job.get("datePosted")
    out.setdefault("role_family", normalize_family(job))
    out["workplace"] = (job.get("workplaceType") or "").upper()
    return out


def gate2(jobs: list[dict], jd_by_id: dict[str, str]) -> tuple[list[dict], list[dict]]:
    scored = []
    for j in jobs:
        try:
            scored.append(_score_one(j, jd_by_id.get(j.get("id"), "")))
        except Exception as e:
            scored.append({"job_id": j.get("id"), "title": j.get("title"),
                           "company": j.get("companyName"), "fit_score": 0, "eligible": False,
                           "dealbreakers": [f"scorer error: {e}"], "reason": "scorer failed",
                           "role_family": normalize_family(j)})
    survivors = [s for s in scored if s.get("eligible") and float(s.get("fit_score", 0)) >= THRESHOLD]
    # PRIORITIZE RECENT: bucket by posting DAY (newest first), then best-fit within the day.
    # So freshly-added roles get applied first; ties broken by Gemini fit score, then role family.
    # Remote/hybrid are PREFERRED, not required — so workplace ranks above fit score
    # but below recency: onsite roles still get applied to, just after the others.
    workplace_rank = {"REMOTE": 2, "HYBRID": 2, "": 1, "ONSITE": 0}
    survivors.sort(key=lambda s: (
        str(s.get("datePosted") or "")[:10],          # YYYY-MM-DD, newest day first (reverse below)
        workplace_rank.get(s.get("workplace", ""), 1),  # remote/hybrid ahead of onsite
        float(s.get("fit_score", 0)),                 # best fit within the same bucket
        -ROLE_FAMILY_PRIORITY.get(s.get("role_family", "other"), 9),
    ), reverse=True)
    return survivors, scored
