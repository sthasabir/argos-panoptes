import asyncio
from mcp_client import TsentaMCP
from gate1 import gate1, normalize_family


async def main():
    async with TsentaMCP() as mcp:
        jobs = []
        for page in (1, 2, 3):
            data = await mcp.get_recommendations(limit=20, date_posted="30d", page=page)
            batch = data.get("jobs", [])
            jobs.extend(batch)
            if not data.get("hasMore"):
                break
        print(f"Pulled {len(jobs)} recommendations from your live feed.\n")

        kept, dropped = gate1(jobs)
        print(f"=== KEPT: {len(kept)}/{len(jobs)} (survive Gate 1 -> go to Opus scorer) ===")
        for j in kept:
            print(f"  [{j.get('matchScore')}] {normalize_family(j):8} | {j.get('seniorityLevel')} | "
                  f"{j.get('title')} @ {j.get('companyName')} | spon:{j.get('sponsorship')}")
        print(f"\n=== DROPPED: {len(dropped)} ===")
        from collections import Counter
        reasons = Counter(d["reason"].split(":")[0] for d in dropped)
        for r, c in reasons.most_common():
            print(f"  {c:3} x {r}")
        print("\n  sample drops:")
        for d in dropped[:10]:
            print(f"    - {d['title']} @ {d['company']}  ({d['reason']})")


if __name__ == "__main__":
    asyncio.run(main())
