#!/usr/bin/env python3
"""Ask Tsenta whether it can drive a given ATS host, by attempting one real apply.

Tsenta refuses unsupported hosts with "we don't support that application system yet"
and does NOT charge a credit for the refusal (verified 2026-08-21 against
careers.walmart.com, careers.garmin.com, careers.leidos.com, www.uline.jobs and
linkedin.com -- balance unchanged at 1455 across all five). So this probe is free when
the answer is no, and submits a real application when the answer is yes.

Only probe hosts you would be happy to apply to, and only with postings that already
passed the filters.

    cd ~/project/argos-panoptes
    set -a && source .env && set +a
    .venv/bin/python tools/probe_ats_support.py
"""
import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gate1  # noqa: E402
import mcp_client  # noqa: E402
import sources  # noqa: E402


def _as_job(j: dict) -> dict:
    """Shape a Hiring.Cafe row enough for gate1 to judge it."""
    loc = j.get("location") or j.get("locations")
    return {
        "id": "probe", "title": j.get("title"),
        "companyName": j.get("companyName") or j.get("company"),
        "url": j.get("applyUrl") or "",
        "workplaceType": (j.get("workplaceType") or "").upper() or None,
        "locations": [loc] if isinstance(loc, str) and loc else (loc or None),
        "salaryMin": j.get("salaryMin"), "salaryMax": j.get("salaryMax"),
        "employmentType": sources._apify_str(j.get("commitment") or j.get("employmentType")),
        "seniorityLevel": j.get("seniorityLevel"), "yearsOfExperienceMin": None,
        "description": str(j.get("description") or ""),
    }

# Hosts seen in Hiring.Cafe output that are not yet on sources.SUPPORTED_ATS.
WANT = ("ultipro.com", "myjobs.adp.com")


def scrape():
    token = os.environ["APIFY_TOKEN"]
    body = {"query": "senior software engineer java", "country": "US", "maxItems": 30}
    req = urllib.request.Request(
        "https://api.apify.com/v2/acts/blackfalcondata~hiringcafe-scraper"
        "/run-sync-get-dataset-items?timeout=300",
        data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=360) as r:
        return json.load(r)


async def main() -> None:
    rows = scrape()
    picks = {}
    for j in rows:
        url = j.get("applyUrl") or ""
        # Probe with a job that would actually be applied to. On 2026-08-21 this loop
        # took the first row matching the host and submitted a real application to
        # "Graduate Engineer III - Water Resources" -- a civil engineering role, in the
        # candidate's name, for one credit. A host probe must never bypass the filters
        # that exist to stop precisely that.
        if not gate1.gate1([_as_job(j)])[0]:
            continue
        for w in WANT:
            if w in url and w not in picks:
                picks[w] = (url,
                            j.get("title"),
                            j.get("companyName") or j.get("company"),
                            str(j.get("description") or "")[:1500])
    print("test URLs found for:", list(picks) or "(none)")
    if not picks:
        return

    async with mcp_client.TsentaMCP() as m:
        start = (await m.get_balance()).get("total")
        print(f"credits before: {start}")
        for host, (url, title, comp, desc) in picks.items():
            print(f"\n{host}  |  {str(title)[:44]} @ {comp}")
            print(f"  {url[:100]}")
            try:
                res = await m.apply_to_job(
                    url=url,
                    job_description=desc or "Senior software engineer. Java, Spring "
                                            "Boot, microservices, AWS, Kubernetes. " * 6)
                r0 = (res.get("results") or [{}])[0]
                print(f"  success={r0.get('success')}  {str(res.get('summary'))[:120]}")
            except Exception as e:
                print("  ERROR", str(e)[:120])
        end = (await m.get_balance()).get("total")
        print(f"\ncredits after: {end}  (spent {start - end})")


if __name__ == "__main__":
    asyncio.run(main())
