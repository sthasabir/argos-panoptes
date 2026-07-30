"""Orchestration: pull recs -> Gate 1 -> full JDs -> Gate 2 -> dedup -> apply top N.
Dry-run by default (scores + ranks, submits nothing). Respects per-run n and daily cap.
"""
from __future__ import annotations
import asyncio
import os
import random
import time

from mcp_client import TsentaMCP
from gate1 import gate1
from gate2 import gate2, THRESHOLD
import sources
import state as st

DAILY_CAP = int(os.environ.get("DAILY_CAP", "100"))
PER_RUN = int(os.environ.get("PER_RUN", "25"))
JITTER = (float(os.environ.get("JITTER_MIN", "4")), float(os.environ.get("JITTER_MAX", "12")))


def _jd_map(resp: dict) -> dict:
    jobs = (resp or {}).get("jobs", []) if isinstance(resp, dict) else (resp or [])
    return {j["id"]: (j.get("description") or "") for j in jobs if j.get("id")}


async def run(n: int = PER_RUN, dry: bool = True, simulate: bool = False,
              date_posted: str = "30d", max_pages: int = 3) -> dict:
    # simulate: record picks as "applied" (so dedup engages) but never call the MCP apply.
    # Used to soak-test scheduling/dedup without spending Tsenta credits.
    t0 = time.monotonic()
    timing = {}
    state = st.load()
    remaining_today = DAILY_CAP - st.applied_today_count(state)
    if remaining_today <= 0:
        return {"status": "daily_cap_reached", "applied": 0, "dry": dry}

    async with TsentaMCP() as mcp:
        balance = await mcp.get_balance()
        credits = balance.get("total", 0)

        # 1) pull recommendations (configurable breadth)
        recs = []
        for page in range(1, max_pages + 1):
            data = await mcp.get_recommendations(limit=20, date_posted=date_posted, page=page)
            recs.extend(data.get("jobs", []))
            if not data.get("hasMore"):
                break

        # 1b) merge external sources (GitHub / LinkedIn / ...) into the same pool.
        #     External jobs carry id "ext:..." + a real apply URL.
        external = []
        try:
            external = sources.gather_external()
        except Exception as e:
            print("sources.gather_external failed:", str(e)[:140])
        pool = recs + external

        # 2) Gate 1 (rules) — works on structured Tsenta fields OR title regex for externals
        kept, dropped1 = gate1(pool)

        # 3) full JDs for survivors — Tsenta jobs by id, external jobs by URL
        jd_by_id = {}
        ext_kept = [j for j in kept if str(j.get("id") or "").startswith("ext:")]
        ids = [j["id"] for j in kept if j.get("id") and not str(j["id"]).startswith("ext:")]
        for i in range(0, len(ids), 20):
            jd_by_id.update(_jd_map(await mcp.get_jobs_by_ids(ids[i:i + 20])))
        for j in ext_kept:
            try:
                jd = await mcp.fetch_job_description(j["url"])
            except Exception as e:
                jd = ""
                print("fetch_job_description failed:", (j.get("title") or "")[:50], str(e)[:80])
            if jd and len(jd) >= 120:
                jd_by_id[j["id"]] = jd
        # drop externals with no usable JD (dead link / login wall) — never apply blind
        kept = [j for j in kept
                if not str(j.get("id") or "").startswith("ext:") or j["id"] in jd_by_id]

        timing["fetch_secs"] = round(time.monotonic() - t0, 1)

        # 4) Gate 2 (Gemini scorer) -> ranked survivors
        _ts = time.monotonic()
        survivors, scored = gate2(kept, jd_by_id)
        timing["scoring_secs"] = round(time.monotonic() - _ts, 1)

        # 5) dedup vs already-applied (by job_id AND normalized company::title,
        #    since Tsenta rotates job_ids for the same posting)
        seen_ids = st.applied_job_ids(state)
        seen_fps = st.applied_fingerprints(state)
        fresh = [s for s in survivors
                 if s.get("job_id") not in seen_ids
                 and st.fingerprint(s.get("company"), s.get("title")) not in seen_fps]
        budget = min(n, remaining_today, len(fresh))
        if not dry:
            budget = min(budget, int(credits))
        chosen = fresh[:budget]

        # 6) apply (or dry-record)
        _ta = time.monotonic()
        applied, errors = [], []
        for i, s in enumerate(chosen):
            if simulate:
                st.record(state, s, "applied")   # counts for dedup + cap, but no MCP call
                applied.append(s)
                continue
            if dry:
                st.record(state, s, "dry")
                applied.append(s)
                continue
            try:
                if str(s.get("job_id") or "").startswith("ext:"):
                    await mcp.apply_to_job(url=s.get("url"),
                                           job_description=jd_by_id.get(s["job_id"], ""))
                else:
                    await mcp.apply_to_job(job_id=s["job_id"])
                st.record(state, s, "applied")
                applied.append(s)
            except Exception as e:
                st.record(state, s, "error")
                errors.append({"job": s.get("title"), "error": str(e)[:160]})
            if i < len(chosen) - 1:
                await asyncio.sleep(random.uniform(*JITTER))

        timing["apply_secs"] = round(time.monotonic() - _ta, 1)
        st.save(state)

    timing["total_secs"] = round(time.monotonic() - t0, 1)
    per_apply = round(timing["apply_secs"] / max(1, len(applied)), 1) if not dry else None
    return {
        "status": "ok",
        "dry": dry,
        "timing": timing,
        "secs_per_apply": per_apply,
        "credits_remaining": credits,
        "pulled": len(recs) + len(external),
        "tsenta_pulled": len(recs),
        "external_pulled": len(external),
        "gate1_kept": len(kept),
        "gate2_survivors": len(survivors),
        "fresh_after_dedup": len(fresh),
        "applied": len(applied),
        "errors": errors,
        "threshold": THRESHOLD,
        "applied_jobs": [
            {"score": s.get("fit_score"), "role": s.get("role_family"),
             "title": s.get("title"), "company": s.get("company"), "url": s.get("url"),
             "reason": s.get("reason")}
            for s in applied
        ],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(asyncio.run(run(n=25, dry=True)), indent=2))
