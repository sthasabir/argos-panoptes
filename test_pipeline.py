import asyncio
from mcp_client import TsentaMCP
from gate1 import gate1
from gate2 import gate2


def _extract_jds(resp) -> dict:
    """Map job id -> description text from get-jobs-by-ids response (shape-tolerant)."""
    jobs = resp.get("jobs") if isinstance(resp, dict) else resp
    jobs = jobs or []
    out = {}
    for j in jobs:
        jid = j.get("id")
        desc = j.get("description") or j.get("jobDescription") or j.get("descriptionText") or ""
        if jid:
            out[jid] = desc
    return out


async def main():
    async with TsentaMCP() as mcp:
        recs = []
        for page in (1, 2, 3):
            data = await mcp.get_recommendations(limit=20, date_posted="30d", page=page)
            recs.extend(data.get("jobs", []))
            if not data.get("hasMore"):
                break
        print(f"Pulled {len(recs)} recs.")

        kept, dropped = gate1(recs)
        print(f"Gate 1: kept {len(kept)}, dropped {len(dropped)}.")

        # fetch full JDs for survivors (bulk, <=20 per call)
        jd_by_id = {}
        ids = [j["id"] for j in kept if j.get("id")]
        for i in range(0, len(ids), 20):
            try:
                r = await mcp.get_jobs_by_ids(ids[i:i+20])
                jd_by_id.update(_extract_jds(r))
            except Exception as e:
                print("  get-jobs-by-ids failed:", str(e)[:150])
        print(f"Fetched {sum(1 for v in jd_by_id.values() if v)} full JDs.\n")

        survivors, scored = gate2(kept, jd_by_id)

        print(f"=== FINAL: {len(survivors)} jobs worth applying to (eligible + score>=6.0), ranked ===")
        for s in survivors:
            print(f"  [{s['fit_score']:.1f}] {s.get('role_family'):8} | {s['title']} @ {s['company']}")
            print(f"        matched: {', '.join(s.get('matched_skills', [])[:6])}  |  {s.get('reason','')}")

        killed = [s for s in scored if s not in survivors]
        print(f"\n=== Gate 2 killed {len(killed)} that passed Gate 1 (score<6 or hidden dealbreaker) ===")
        for s in killed:
            db = ", ".join(s.get("dealbreakers", [])) or f"low score {s.get('fit_score')}"
            print(f"  [{s.get('fit_score')}] {s['title']} @ {s['company']}  ({db})")


if __name__ == "__main__":
    asyncio.run(main())
