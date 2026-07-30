"""FastAPI wrapper for Cloud Run. Cloud Scheduler POSTs /run every N hours.
Endpoints:
  GET  /            health
  POST /run?n=5&dry=1   run one cycle (dry defaults to TRUE for safety)
  GET  /state       recent applications summary
"""
import os
from fastapi import FastAPI, Request

import pipeline
import state as st

app = FastAPI()
# Safety: live applying requires BOTH ?dry=0 AND env LIVE_APPLY=1 (belt + suspenders)
LIVE_APPLY = os.environ.get("LIVE_APPLY", "0") == "1"


@app.get("/")
def health():
    return {"ok": True, "service": "tsenta-agent", "live_apply_enabled": LIVE_APPLY}


@app.post("/run")
async def run(request: Request):
    q = request.query_params
    n = int(q.get("n", os.environ.get("PER_RUN", "5")))
    dry_param = q.get("dry", "1") != "0"
    dry = dry_param or (not LIVE_APPLY)   # never live unless explicitly enabled both ways
    date_posted = q.get("date", os.environ.get("DATE_POSTED", "30d"))
    max_pages = int(q.get("pages", os.environ.get("MAX_PAGES", "3")))
    result = await pipeline.run(n=n, dry=dry, date_posted=date_posted, max_pages=max_pages)
    print("RUN RESULT:", {k: v for k, v in result.items() if k != "applied_jobs"})
    for j in result.get("applied_jobs", []):
        print(f"  {'APPLIED' if not dry else 'DRY'} [{j.get('score')}] {j.get('title')} @ {j.get('company')}")
    return result


@app.get("/state")
def get_state():
    s = st.load()
    apps = s.get("applications", [])
    from collections import Counter
    return {
        "total": len(apps),
        "by_status": dict(Counter(a.get("status") for a in apps)),
        "applied_today": st.applied_today_count(s),
        "recent": apps[-15:],
    }
