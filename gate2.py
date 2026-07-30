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

from profile import CANDIDATE, ROLE_FAMILY_PRIORITY
from gate1 import normalize_family

SCORER_MODEL = os.environ.get("SCORER_MODEL", "gemini-3.6-flash")
VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT", "jobagent-aayush")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "global")
THRESHOLD = float(os.environ.get("SCORE_THRESHOLD", "6.0"))

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=VERTEX_PROJECT, location=VERTEX_LOCATION)
    return _client

SYSTEM = f"""You score job fit for {CANDIDATE['name']}, a Computer Science NEW GRAD
(graduating {CANDIDATE['grad_date']}) who REQUIRES H1B visa sponsorship.

Candidate stack: {", ".join(CANDIDATE['stack'])}.
Target role families in priority order: {", ".join(CANDIDATE['target_role_families'])}.

You are a STRICT gatekeeper. Set eligible=false and fit_score=0 if the job description
reveals ANY dealbreaker the structured fields may have missed:
- Actually senior/staff/principal/lead/architect/manager despite a junior-looking title
- Requires >=3 years professional experience (internships/projects do NOT count)
- Requires security clearance / US citizenship / explicitly no sponsorship
- Is really IT-support / help-desk / manual-QA / sales / non-engineering
Otherwise score 0-10 on: stack overlap, genuine new-grad/entry fit, and role-family match
(fullstack/backend/ai_ml/swe strong; ops/data-entry weak). Be honest and calibrated:
a 10 is a perfect entry-level backend/AI role in his stack that sponsors; a 6 is a
reasonable fit; below 6 means don't bother applying."""

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
    return json.dumps({
        "title": job.get("title"),
        "company": job.get("companyName"),
        "seniorityLevel": job.get("seniorityLevel"),
        "yearsOfExperienceMin": job.get("yearsOfExperienceMin"),
        "sponsorship": job.get("sponsorship"),
        "roleFamily": job.get("roleFamily"),
        "skillTags": job.get("skillTags"),
        "matchScore": job.get("matchScore"),
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
    survivors.sort(key=lambda s: (
        str(s.get("datePosted") or "")[:10],          # YYYY-MM-DD, newest day first (reverse below)
        float(s.get("fit_score", 0)),                 # best fit within the same day
        -ROLE_FAMILY_PRIORITY.get(s.get("role_family", "other"), 9),
    ), reverse=True)
    return survivors, scored
