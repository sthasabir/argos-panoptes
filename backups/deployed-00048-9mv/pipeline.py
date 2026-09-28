"""Orchestration: pull recs -> Gate 1 -> full JDs -> Gate 2 -> dedup -> apply top N.
Dry-run by default (scores + ranks, submits nothing). Respects per-run n and daily cap.
"""
from __future__ import annotations
import asyncio
import os
import random
import time

from mcp_client import TsentaMCP
from gate1 import (gate1, _money, suggested_ask, requires_citizenship,
                   requires_advanced_degree, describes_non_us,
                   requires_clearance)
from gate2 import gate2, THRESHOLD
import sources
import state as st
from profile import (MAX_PER_COMPANY, MAX_PER_COMPANY_DAYS, STATED_ASK,
                     HOLD_IF_UNDERASKING, HOLD_ASK_MARGIN)

DAILY_CAP = int(os.environ.get("DAILY_CAP", "100"))
PER_RUN = int(os.environ.get("PER_RUN", "25"))
JITTER = (float(os.environ.get("JITTER_MIN", "4")), float(os.environ.get("JITTER_MAX", "12")))
# Per-URL cap on the external job-description fetch. Bounded here rather than left to
# the MCP session's internal timeout, so a hung URL surfaces as a normal TimeoutError
# we can swallow instead of a session-killing cancellation.
JD_TIMEOUT = float(os.environ.get("JD_TIMEOUT", "45"))
# Max jobs sent to the Gemini scorer per run, to stay inside Cloud Run's 900s deadline.
GATE2_MAX = int(os.environ.get("GATE2_MAX", "250"))
# Extra keyword pulls against the same recommendations endpoint. The default relevance
# feed does not return everything; each term surfaces a different slice. Pipe-separated,
# empty disables.
FEED_SEARCHES = [t.strip() for t in os.environ.get(
    "FEED_SEARCHES", "software engineer|java developer|full stack engineer|backend engineer"
).split("|") if t.strip()]


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
            # 50 is the server maximum. Pulling 20 was reading only ~200 of the ~920
            # jobs actually available, which starved the funnel far more than any filter.
            data = await mcp.get_recommendations(limit=50, date_posted=date_posted, page=page)
            recs.extend(data.get("jobs", []))
            if not data.get("hasMore"):
                break

        # 1a) the same endpoint returns DIFFERENT jobs when given a `search` term — the
        #     default relevance ordering simply never surfaces some of them. Measured
        #     2026-08-14: the plain feed offered 9 unapplied matches while
        #     search="software engineer" offered 18, and 11 postings appeared under a
        #     search that the default query never returned at any page depth. Each term
        #     is merged into the same pool and de-duplicated by job id below.
        for term in FEED_SEARCHES:
            for page in range(1, max_pages + 1):
                data = await mcp.get_recommendations(limit=50, date_posted=date_posted,
                                                     page=page, extra={"search": term})
                batch = data.get("jobs", [])
                recs.extend(batch)
                if not data.get("hasMore") or not batch:
                    break
        seen_rec, uniq = set(), []
        for j in recs:
            k = j.get("id")
            if k and k in seen_rec:
                continue
            if k:
                seen_rec.add(k)
            uniq.append(j)
        if FEED_SEARCHES:
            print(f"feed: {len(uniq)} unique jobs from 1 default + "
                  f"{len(FEED_SEARCHES)} search pulls")
        recs = uniq

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
        # Gate 2 hands back scored summaries, not the source postings; this is how the
        # salary fields are recovered later for the under-asking hold.
        by_id = {j["id"]: j for j in pool if j.get("id")}
        # Summarise WHY things were dropped. Without this the only signal is a single
        # gate1_kept number, which is useless for telling an over-tight filter apart
        # from a genuinely thin feed.
        import collections as _c
        drop_reasons = dict(_c.Counter(d["reason"].split(":")[0] for d in dropped1).most_common())

        # 3) full JDs for survivors — Tsenta jobs by id, external jobs by URL
        jd_by_id = {}
        ext_kept = [j for j in kept if str(j.get("id") or "").startswith("ext:")]
        ids = [j["id"] for j in kept if j.get("id") and not str(j["id"]).startswith("ext:")]
        for i in range(0, len(ids), 20):
            jd_by_id.update(_jd_map(await mcp.get_jobs_by_ids(ids[i:i + 20])))
        # An adapter that already carries the description (Indeed — see sources.py)
        # seeds the map directly. Fetching those would be worse than useless:
        # fetch-job-description returns 0 chars for a to.indeed.com link, so the job
        # would be dropped as "no JD" despite having a perfectly good one in hand.
        for j in ext_kept:
            if j.get("description") and len(j["description"]) >= 120:
                jd_by_id[j["id"]] = j["description"]

        jd_dead = False   # set once the MCP session's cancel scope trips
        for j in ext_kept:
            jd = ""
            if j["id"] in jd_by_id:
                continue
            if jd_dead:
                continue
            try:
                jd = await asyncio.wait_for(
                    mcp.fetch_job_description(j["url"]), timeout=JD_TIMEOUT)
            except (Exception, asyncio.CancelledError) as e:
                # A CancelledError here poisons the whole session: every later call
                # fails instantly against the same dead cancel scope (observed as 33
                # identical failures in one run). Stop fetching rather than burn the
                # remaining time on calls that cannot succeed.
                if isinstance(e, asyncio.CancelledError):
                    jd_dead = True
                    print("JD fetch session cancelled — skipping remaining external JDs")
                # CancelledError is caught DELIBERATELY and must stay listed. It
                # derives from BaseException, not Exception, so a bare `except
                # Exception` lets it through — which is exactly what happened in
                # production: one slow LinkedIn URL hit the MCP session's internal
                # timeout, the cancellation escaped, tore down the session and 500'd
                # the whole run. A single unreachable job posting must never kill the
                # cycle; we just skip its JD and move on.
                print("fetch_job_description failed:", (j.get("title") or "")[:50],
                      type(e).__name__, str(e)[:80])
            if jd and len(jd) >= 120:
                jd_by_id[j["id"]] = jd
        # 3b) citizenship — only checkable now, because it lives in the DESCRIPTION.
        #     The candidate is a permanent resident; federal contract roles that demand
        #     citizenship carry no clearance flag, so nothing else catches them.
        cit_dropped = [j for j in kept if requires_citizenship(jd_by_id.get(j.get("id"), ""))]
        if cit_dropped:
            kept = [j for j in kept if j not in cit_dropped]
            print(f"citizenship-only ({len(cit_dropped)}): " + ", ".join(
                str(j.get("companyName")) for j in cit_dropped[:6]))

        # 3b2) non-US by description — catches postings with an empty `locations` array
        #      that is_us_job() has to wave through. Moniepoint (Nigeria) got applied to
        #      exactly that way.
        foreign_dropped = [j for j in kept if describes_non_us(jd_by_id.get(j.get("id"), ""))]
        if foreign_dropped:
            kept = [j for j in kept if j not in foreign_dropped]
            print(f"non-US description ({len(foreign_dropped)}): " + ", ".join(
                str(j.get("companyName")) for j in foreign_dropped[:6]))

        # 3b3) security clearance — needs US citizenship, which the candidate does not
        #      have. Public Trust is fine and is deliberately excluded from the match.
        clr_dropped = [j for j in kept if requires_clearance(jd_by_id.get(j.get("id"), ""))]
        if clr_dropped:
            kept = [j for j in kept if j not in clr_dropped]
            print(f"clearance required ({len(clr_dropped)}): " + ", ".join(
                str(j.get("companyName")) for j in clr_dropped[:6]))

        # 3c) education — the candidate holds a bachelor's; drop postings requiring a
        #     Master's or PhD with no bachelor's-level alternative. Also description-only.
        deg_dropped = [j for j in kept if requires_advanced_degree(jd_by_id.get(j.get("id"), ""))]
        if deg_dropped:
            kept = [j for j in kept if j not in deg_dropped]
            print(f"advanced-degree required ({len(deg_dropped)}): " + ", ".join(
                str(j.get("companyName")) for j in deg_dropped[:6]))

        # drop externals with no usable JD (dead link / login wall) — never apply blind
        gate1_kept_n = len(kept)   # before external-JD pruning, so the metric means what it says
        kept = [j for j in kept
                if not str(j.get("id") or "").startswith("ext:") or j["id"] in jd_by_id]
        dropped_no_jd = gate1_kept_n - len(kept)

        timing["fetch_secs"] = round(time.monotonic() - t0, 1)

        # 4) Gate 2 (Gemini scorer) -> ranked survivors.
        #    Bounded: one Gemini call per survivor at ~0.9s each, and Cloud Run kills
        #    the request at 900s. Deep pagination can hand Gate 1 several hundred jobs,
        #    so cap what gets scored. The feed arrives relevance-ordered, so the head of
        #    the list is the part worth spending on.
        _ts = time.monotonic()
        to_score = kept[:GATE2_MAX]
        if len(kept) > GATE2_MAX:
            print(f"gate2: scoring first {GATE2_MAX} of {len(kept)} survivors (cap)")
        survivors, scored = gate2(to_score, jd_by_id)
        timing["scoring_secs"] = round(time.monotonic() - _ts, 1)

        # 5) dedup vs already-applied (by job_id AND normalized company::title,
        #    since Tsenta rotates job_ids for the same posting)
        seen_ids = st.applied_job_ids(state)
        seen_fps = st.applied_fingerprints(state)
        fresh = [s for s in survivors
                 if s.get("job_id") not in seen_ids
                 and st.fingerprint(s.get("company"), s.get("title")) not in seen_fps]

        # 5b) throttle per employer. Nine applications went to PNC in two days before
        #     this existed — all auto-generated, all into one ATS queue. Counts prior
        #     applications in the window AND picks made earlier in this same run.
        recent = st.company_counts(state, MAX_PER_COMPANY_DAYS)
        throttled, capped = [], []
        for s in fresh:
            key = st.norm_company(s.get("company"))
            if recent.get(key, 0) >= MAX_PER_COMPANY:
                capped.append(s)
                continue
            recent[key] = recent.get(key, 0) + 1
            throttled.append(s)
        if capped:
            print(f"per-company cap ({MAX_PER_COMPANY}/{MAX_PER_COMPANY_DAYS}d) held back "
                  f"{len(capped)}: " + ", ".join(sorted({str(c.get('company')) for c in capped})[:6]))
        fresh = throttled

        # 5c) hold back postings that pay well ABOVE what we're asking for. Applying
        #     would volunteer a number below their published floor, and a stated figure
        #     caps the negotiation. These wait for a human to raise the ask first.
        held_now = []
        if HOLD_IF_UNDERASKING and STATED_ASK > 0:
            keep = []
            for s in fresh:
                job = by_id.get(s.get("job_id")) or {}
                # Hold on the COMPUTED ask, not the posted floor: the point is to
                # intervene only where the per-job figure beats the one static number
                # the account can carry. Postings whose rule output is just the default
                # anyway need no interruption.
                ask = suggested_ask(job)
                floor = _money(job.get("salaryMin"))
                if ask and ask > STATED_ASK + HOLD_ASK_MARGIN:
                    s["salary_min"], s["salary_max"] = floor, _money(job.get("salaryMax"))
                    s["suggested_ask"] = ask
                    st.hold(state, s, f"ask ${ask:,.0f} vs default ${STATED_ASK:,.0f}"
                                      + (f" (posts from ${floor:,.0f})" if floor else ""))
                    held_now.append(s)
                else:
                    keep.append(s)
            fresh = keep
        if held_now:
            print(f"held for review ({len(held_now)}): " + ", ".join(
                f"{h.get('company')} ask ${h.get('suggested_ask'):,.0f}" for h in held_now[:6]))
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
        "gate1_kept": gate1_kept_n,
        "gate1_drop_reasons": drop_reasons,
        "citizenship_dropped": len(cit_dropped),
        "degree_dropped": len(deg_dropped),
        "non_us_desc_dropped": len(foreign_dropped),
        "clearance_dropped": len(clr_dropped),
        "dropped_no_jd": dropped_no_jd,
        "scored": len(kept),
        "gate2_survivors": len(survivors),
        "fresh_after_dedup": len(fresh),
        "held_for_review": [
            {"company": h.get("company"), "title": h.get("title"),
             "score": h.get("fit_score"), "url": h.get("url"),
             "posted": f"${h.get('salary_min'):,.0f}-${h.get('salary_max') or 0:,.0f}",
             "suggested_ask": h.get("suggested_ask")}
            for h in held_now
        ],
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
