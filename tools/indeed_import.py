"""Merge Indeed postings into the feed file that `sources.from_indeed()` reads.

Indeed is NOT reachable from this process — its search HTML 403s a plain client and
the legacy publisher API no longer resolves (verified 2026-08-13). The only route is
the Indeed MCP tools, which an operator (Claude) can call interactively. This script
is the seam between the two: hand it a JSON array of postings and it validates,
normalizes, de-duplicates and ages them into `state/indeed_feed.json`.

    .venv/bin/python tools/indeed_import.py new_jobs.json      # merge a file
    cat jobs.json | .venv/bin/python tools/indeed_import.py -  # or from stdin
    .venv/bin/python tools/indeed_import.py --prune            # drop stale rows only

Each input row needs `title`, `companyName`, `url`; everything else is optional:

    {"title": "...", "companyName": "...", "url": "https://to.indeed.com/x",
     "locations": ["Redmond, WA"], "datePosted": "2026-07-18",
     "salaryMin": 102100, "salaryMax": 219200, "employmentType": "FULL_TIME",
     "description": "full JD text from get_job_details"}

`description` is strongly recommended: the pipeline drops external jobs it has no
description for, and Tsenta cannot fetch one from a to.indeed.com URL.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import INDEED_FEED_FILE, INDEED_MAX_AGE_DAYS, _age_days  # noqa: E402

REQUIRED = ("title", "companyName", "url")
MIN_JD = 120          # matches the pipeline's "never apply blind" threshold


def _path() -> str:
    p = INDEED_FEED_FILE
    if not os.path.isabs(p):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), p)
    return p


def load_existing() -> list[dict]:
    try:
        with open(_path()) as fh:
            rows = json.load(fh)
        return rows if isinstance(rows, list) else []
    except FileNotFoundError:
        return []


def main() -> int:
    args = [a for a in sys.argv[1:]]
    prune_only = "--prune" in args
    args = [a for a in args if a != "--prune"]

    incoming: list[dict] = []
    if not prune_only:
        if not args:
            print(__doc__)
            return 2
        raw = sys.stdin.read() if args[0] == "-" else open(args[0]).read()
        incoming = json.loads(raw)
        if not isinstance(incoming, list):
            print("input must be a JSON array"); return 2

    rows = {r["url"]: r for r in load_existing() if r.get("url")}
    before = len(rows)
    added = updated = rejected = no_jd = 0

    for r in incoming:
        missing = [k for k in REQUIRED if not (r.get(k) or "").strip()]
        if missing:
            print(f"  reject (missing {','.join(missing)}): {str(r)[:70]}")
            rejected += 1
            continue
        if len(r.get("description") or "") < MIN_JD:
            # kept, but flagged — the pipeline will drop it before Gate 2
            no_jd += 1
        url = r["url"].strip()
        if url in rows:
            rows[url].update(r)
            updated += 1
        else:
            rows[url] = r
            added += 1

    # age out anything past the window the adapter would ignore anyway
    fresh, stale = {}, 0
    for url, r in rows.items():
        age = _age_days(r.get("datePosted"))
        if age is not None and age > INDEED_MAX_AGE_DAYS:
            stale += 1
            continue
        fresh[url] = r

    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w") as fh:
        json.dump(list(fresh.values()), fh, indent=1)

    print(f"{_path()}")
    print(f"  was {before} rows -> now {len(fresh)}")
    print(f"  added {added}, updated {updated}, rejected {rejected}, "
          f"pruned as stale {stale}")
    if no_jd:
        print(f"  WARNING: {no_jd} row(s) have no usable description — the pipeline "
              f"will drop these before Gate 2. Add `description` from get_job_details.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
