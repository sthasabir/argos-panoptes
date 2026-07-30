"""LIVE apply test: submit 5 real applications, wait 60s, submit 5 more.
Uses the real state file (dedup persists). Aborts round 2 if round 1 all-errored."""
import asyncio, time
from datetime import datetime
import pipeline


def _show(tag, r):
    print(f"\n=== {tag} @ {datetime.now():%H:%M:%S} ===")
    print(f"credits_remaining(before-ish): {r.get('credits_remaining')}  "
          f"pulled {r.get('pulled')} -> gate1 {r.get('gate1_kept')} -> survivors "
          f"{r.get('gate2_survivors')} -> fresh {r.get('fresh_after_dedup')} -> APPLIED {r.get('applied')}")
    for j in r.get("applied_jobs", []):
        print(f"   ✅ [{j['score']}] {j['title']} @ {j['company']}")
    if r.get("errors"):
        print("   errors:")
        for e in r["errors"]:
            print(f"     ❌ {e['job']}: {e['error']}")
    return r.get("applied", 0), [(j["title"], j["company"]) for j in r.get("applied_jobs", [])]


async def main():
    r1 = await pipeline.run(n=5, dry=False)
    n1, p1 = _show("ROUND 1 (live apply 5)", r1)
    if n1 == 0:
        print("\n⛔ Round 1 applied 0 (see errors above). ABORTING round 2 to protect credits.")
        return

    print("\n...waiting 60s (simulating the 6h cron interval)...")
    time.sleep(60)

    r2 = await pipeline.run(n=5, dry=False)
    n2, p2 = _show("ROUND 2 (live apply 5)", r2)

    overlap = set(p1) & set(p2)
    print("\n=== VERDICT ===")
    print(f"round1 applied {n1}, round2 applied {n2}, re-applied duplicates: {len(overlap)}")
    print("DEDUP HOLDS ✅" if not overlap else f"DEDUP BROKEN ❌ {overlap}")


if __name__ == "__main__":
    asyncio.run(main())
