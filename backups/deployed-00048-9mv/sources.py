"""
External job sources — pull fresh postings from outside Tsenta's feed and
normalize them into Tsenta-shaped dicts so they flow through the SAME
Gate 1 -> Gate 2 -> apply pipeline.

Each adapter returns a list of dicts shaped like a Tsenta job:
  {id, title, companyName, url, datePosted, seniorityLevel, yearsOfExperienceMin,
   sponsorship, roleFamily, skillTags, matchScore, source, external}

External jobs carry an id prefixed "ext:" so the pipeline knows to fetch their
JD via `fetch-job-description(url)` and apply via `apply-to-job(url=...)`
instead of a Tsenta jobId.

Zero LLM tokens here — pure HTTP + parsing. Filtering is left to the gates.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from urllib.parse import quote

import httpx

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ---- config (env-tunable) ----
# Multiple Simplify-schema listings.json feeds (pipe-separated). All full-time
# new-grad boards with real ATS apply URLs; merged + de-duped by url downstream.
_DEFAULT_GH_FEEDS = "|".join([
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/vanshb03/New-Grad-2026/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/cvrve/New-Grad/dev/.github/scripts/listings.json",
])
GITHUB_LISTINGS_URLS = [u.strip() for u in os.environ.get(
    "GITHUB_LISTINGS_URLS", _DEFAULT_GH_FEEDS).split("|") if u.strip()]
GITHUB_MAX_AGE_DAYS = float(os.environ.get("GITHUB_MAX_AGE_DAYS", "3"))
GITHUB_MAX = int(os.environ.get("GITHUB_MAX", "40"))
# categories we care about (substring match, case-insensitive)
GITHUB_CATS = tuple(c.strip().lower() for c in os.environ.get(
    "GITHUB_CATEGORIES", "software,ai,machine learning,data science,ml").split(","))

LINKEDIN_QUERIES = [q.strip() for q in os.environ.get(
    "LINKEDIN_QUERIES",
    "AI engineer new grad|software engineer new grad|machine learning engineer new grad",
).split("|") if q.strip()]
LINKEDIN_TPR = os.environ.get("LINKEDIN_TPR", "3600")           # seconds; 3600 = last hour
LINKEDIN_GEOID = os.environ.get("LINKEDIN_GEOID", "103644278")  # United States
LINKEDIN_LOCATION = os.environ.get("LINKEDIN_LOCATION", "United States")
LINKEDIN_MAX = int(os.environ.get("LINKEDIN_MAX", "30"))

# GitHub sponsorship strings -> Tsenta-style enum (gate1 drops SPONSOR_NO)
_SPONSOR_MAP = {
    "does not offer sponsorship": "NO_SPONSORSHIP",
    "u.s. citizenship is required": "US_CITIZEN_ONLY",
    "u.s. citizenship required": "US_CITIZEN_ONLY",
}


def _eid(source: str, url: str) -> str:
    return "ext:%s:%s" % (source, hashlib.sha1((url or "").encode()).hexdigest()[:12])


def _iso(ts: int) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))
    except Exception:
        return ""


# ---------------------------------------------------------------- GitHub
def _fetch_listings(url: str) -> list[dict]:
    try:
        r = httpx.get(url, headers={"User-Agent": BROWSER_UA}, timeout=40)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("sources.github: fetch failed:", url.split("/")[3], str(e)[:100])
        return []


def from_github() -> list[dict]:
    """Simplify-schema new-grad boards (SimplifyJobs + vanshb03 + cvrve). Structured,
    real ATS apply URLs + sponsorship flag. Filter to active + visible + recent +
    relevant category, merge across feeds, newest first, capped."""
    rows = []
    for url in GITHUB_LISTINGS_URLS:
        rows.extend(_fetch_listings(url))

    cutoff = time.time() - GITHUB_MAX_AGE_DAYS * 86400
    out = []
    for j in rows:
        if not (j.get("active") and j.get("is_visible")):
            continue
        dp = j.get("date_posted") or 0
        if dp < cutoff:
            continue
        cat = (j.get("category") or "").lower()
        if not any(c in cat for c in GITHUB_CATS):
            continue
        url = j.get("url") or ""
        if not url:
            continue
        spons = _SPONSOR_MAP.get((j.get("sponsorship") or "").strip().lower())
        out.append({
            "id": _eid("github", url),
            "title": j.get("title"),
            "companyName": j.get("company_name"),
            "url": url,
            "datePosted": _iso(dp),
            "seniorityLevel": None,
            "yearsOfExperienceMin": None,
            "sponsorship": spons,
            "roleFamily": None,
            "skillTags": None,
            "matchScore": None,
            "locations": j.get("locations"),
            "source": "github",
            "external": True,
            "_ts": dp,
        })
    # de-dup across feeds by url (same job listed in multiple repos)
    seen, uniq = set(), []
    for j in out:
        if j["url"] in seen:
            continue
        seen.add(j["url"])
        uniq.append(j)
    uniq.sort(key=lambda x: x.get("_ts", 0), reverse=True)
    return uniq[:GITHUB_MAX]


# ---------------------------------------------------------------- LinkedIn
_LI_ENDPOINT = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                "?keywords={kw}&f_TPR=r{tpr}&location={loc}&geoId={geo}&sortBy=DD&start=0")


def _parse_linkedin(html: str, query: str) -> list[dict]:
    titles = re.findall(r'base-search-card__title">\s*([^<]+)', html)
    comps = re.findall(r'base-search-card__subtitle">\s*<a[^>]*>\s*([^<]+)', html)
    links = re.findall(r'(https://www\.linkedin\.com/jobs/view/[^?"]+)', html)
    dates = re.findall(r'datetime="([0-9-]+)"', html)
    # Every card carries a location ("Irving, TX", "New Jersey, United States",
    # "New York City Metropolitan Area"). It used to be dropped on the floor, which
    # left `locations` empty on every LinkedIn job — and an absent location is waved
    # through by both the US and the region filter, so this whole source bypassed
    # them. One findall per card class keeps the index alignment used above.
    locs = re.findall(r'job-search-card__location">\s*([^<]+)', html)
    rows = []
    n = min(len(titles), len(links))
    for i in range(n):
        url = links[i]
        loc = locs[i].strip() if i < len(locs) else ""
        rows.append({
            "id": _eid("linkedin", url),
            "title": titles[i].strip(),
            "companyName": comps[i].strip() if i < len(comps) else None,
            "url": url,
            "datePosted": dates[i] if i < len(dates) else "",
            "locations": [loc] if loc else None,
            "seniorityLevel": None,
            "yearsOfExperienceMin": None,
            "sponsorship": None,
            "roleFamily": None,
            "skillTags": None,
            "matchScore": None,
            "source": "linkedin",
            "external": True,
        })
    return rows


def from_linkedin() -> list[dict]:
    """LinkedIn guest jobs endpoint — fresh (f_TPR window), date-sorted. No auth.
    URLs are /jobs/view/ pages; the pipeline resolves the real JD/apply link via
    Tsenta's fetch-job-description before applying."""
    seen, out = set(), []
    for q in LINKEDIN_QUERIES:
        url = _LI_ENDPOINT.format(kw=quote(q), tpr=LINKEDIN_TPR,
                                  loc=quote(LINKEDIN_LOCATION), geo=LINKEDIN_GEOID)
        try:
            r = httpx.get(url, headers={"User-Agent": BROWSER_UA}, timeout=30)
            if r.status_code != 200:
                print("sources.linkedin: HTTP", r.status_code, "for", q[:40])
                continue
            for row in _parse_linkedin(r.text, q):
                if row["url"] in seen:
                    continue
                seen.add(row["url"])
                out.append(row)
        except Exception as e:
            print("sources.linkedin: failed for", q[:40], "->", str(e)[:100])
    return out[:LINKEDIN_MAX]


# ---------------------------------------------------------------- Indeed
# Indeed cannot be reached from this process: the search HTML returns HTTP 403 to a
# plain client, and the legacy publisher API (api.indeed.com) no longer resolves.
# Verified 2026-08-13. So unlike the other adapters this one does NOT fetch anything —
# it reads a file that an operator (Claude, via the Indeed MCP tools) refreshes with
# `tools/indeed_import.py`. The agent stays fully autonomous on Tsenta + LinkedIn and
# treats this file as a bonus source that may be stale or absent.
#
# The file also carries each job's DESCRIPTION, which is load-bearing:
# `fetch-job-description` returns 0 chars for a to.indeed.com link, so without a
# description travelling with the job the pipeline's "never apply blind" rule would
# drop every one of these before Gate 2.
INDEED_FEED_FILE = os.environ.get("INDEED_FEED_FILE", "state/indeed_feed.json")
# Indeed returns postings far older than Tsenta's window — this sample had roles from
# February in an August search. Anything older than this is almost certainly filled.
INDEED_MAX_AGE_DAYS = float(os.environ.get("INDEED_MAX_AGE_DAYS", "30"))


def _age_days(date_str: str) -> float | None:
    """'2026-07-18' -> days since. None if unparseable."""
    try:
        t = time.mktime(time.strptime((date_str or "")[:10], "%Y-%m-%d"))
    except (ValueError, OverflowError):
        return None
    return (time.time() - t) / 86400


def from_indeed() -> list[dict]:
    """Read the operator-refreshed Indeed feed file. Never makes a network call."""
    import json as _json
    path = INDEED_FEED_FILE
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    try:
        with open(path) as fh:
            rows = _json.load(fh)
    except FileNotFoundError:
        return []
    except Exception as e:
        print("sources.indeed: unreadable feed file:", str(e)[:120])
        return []

    out, stale = [], 0
    for j in rows if isinstance(rows, list) else []:
        url = (j.get("url") or "").strip()
        if not url or not (j.get("title") or "").strip():
            continue
        age = _age_days(j.get("datePosted"))
        if age is not None and age > INDEED_MAX_AGE_DAYS:
            stale += 1
            continue
        out.append({
            "id": _eid("indeed", url),
            "title": j.get("title"),
            "companyName": j.get("companyName"),
            "url": url,
            "datePosted": (j.get("datePosted") or "")[:10],
            "seniorityLevel": None,
            "yearsOfExperienceMin": None,
            "sponsorship": None,
            "roleFamily": None,
            "skillTags": None,
            "matchScore": None,
            "locations": j.get("locations") or None,
            "salaryMin": j.get("salaryMin"),
            "salaryMax": j.get("salaryMax"),
            "salaryCurrency": j.get("salaryCurrency") or "USD",
            "employmentType": j.get("employmentType"),
            # carried through to the pipeline so no JD fetch is attempted
            "description": j.get("description") or "",
            "source": "indeed",
            "external": True,
        })
    if stale:
        print(f"sources.indeed: skipped {stale} postings older than "
              f"{INDEED_MAX_AGE_DAYS:g} days")
    return out


# ---------------------------------------------------------------- gather
_ADAPTERS = {"github": from_github, "linkedin": from_linkedin, "indeed": from_indeed}


def gather_external(sources: str | None = None) -> list[dict]:
    """Run the enabled adapters and return the merged, de-duplicated (by url) pool."""
    enabled = [s.strip() for s in (sources
               if sources is not None else os.environ.get("EXTERNAL_SOURCES", "")).split(",")
               if s.strip()]
    seen, merged = set(), []
    for name in enabled:
        fn = _ADAPTERS.get(name)
        if not fn:
            print("sources: unknown source", name)
            continue
        try:
            for j in fn():
                u = j.get("url")
                if u and u in seen:
                    continue
                if u:
                    seen.add(u)
                merged.append(j)
        except Exception as e:
            print("sources: adapter", name, "crashed:", str(e)[:120])
    return merged


if __name__ == "__main__":
    import json
    os.environ.setdefault("EXTERNAL_SOURCES", "github,linkedin")
    jobs = gather_external()
    print(f"gathered {len(jobs)}")
    for j in jobs[:10]:
        print(f"  [{j['source']}] {j['title']} @ {j['companyName']} ({j['datePosted']})")
        print(f"        {j['url']}")
