"""Prove the recurring-run behavior: fire twice 60s apart, 5 'applies' each,
and confirm run 2 dedups (picks 5 DIFFERENT jobs, never re-applies)."""
import asyncio, time, os
from datetime import datetime

os.environ["AGENT_STATE_FILE"] = "/tmp/cron_test_state.json"
if os.path.exists("/tmp/cron_test_state.json"):
    os.remove("/tmp/cron_test_state.json")

import pipeline  # imports after env is set


def _titles(res):
    return [(j["title"], j["company"]) for j in res["applied_jobs"]]


async def main():
    print(f"RUN 1  @ {datetime.now():%H:%M:%S}")
    r1 = await pipeline.run(n=5, simulate=True)
    p1 = _titles(r1)
    for t, c in p1:
        print(f"   applied: {t} @ {c}")
    print(f"   run1 applied={r1['applied']}\n   ...waiting 60s (simulating the cron interval)...\n")

    time.sleep(60)

    print(f"RUN 2  @ {datetime.now():%H:%M:%S}")
    r2 = await pipeline.run(n=5, simulate=True)
    p2 = _titles(r2)
    for t, c in p2:
        print(f"   applied: {t} @ {c}")
    print(f"   run2 applied={r2['applied']}")

    overlap = set(p1) & set(p2)
    print("\n=== VERDICT ===")
    print(f"run1 jobs: {len(p1)} | run2 jobs: {len(p2)} | OVERLAP (re-applied): {len(overlap)}")
    print("DEDUP WORKS ✅ (zero repeats)" if not overlap else f"DEDUP BROKEN ❌ repeats: {overlap}")
    import state as st
    s = st.load()
    print(f"total applications recorded across both runs: {len(s['applications'])}")


if __name__ == "__main__":
    asyncio.run(main())
