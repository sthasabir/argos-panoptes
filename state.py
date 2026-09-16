"""Persistence — tracks which jobs we've applied to (dedup + daily cap).
GCS bucket in Cloud Run; local JSON file otherwise.

State shape:
{ "applications": [
    {"date":"2026-07-29","job_id":"...","company":"...","title":"...",
     "url":"...","score":8.5,"status":"applied|dry|error"} ] }
"""
import json
import os
import re
from datetime import datetime, date, timedelta
from pathlib import Path


# Employers that trade under more than one name. Prefix matching cannot connect these,
# so they are listed explicitly. Left side is folded into the right side.
COMPANY_ALIASES = {
    "facebook": "meta", "alphabet": "google", "kar global": "openlane",
    "x corp": "twitter", "square": "block", "snap inc": "snap",
    "downstream ai": "snap", "meridian financial": "meridian", "meridian corp": "meridian",
}

# Title words that mean the same thing. "Sr Software Engineer" and "Senior Software
# Engineer" are one posting, but produced different fingerprints before this.
_TITLE_SYNONYMS = {
    "sr": "senior", "snr": "senior", "jr": "junior",
    "swe": "software engineer", "sde": "software engineer",
    "eng": "engineer", "dev": "developer", "mgr": "manager",
    "fullstack": "full stack", "backend": "back end", "frontend": "front end",
}


def _norm_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)          # drop parentheticals/brackets
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(remote|hybrid|onsite|position|role|inc|llc|ltd|corp|corporation|"
               r"technologies|technology|the|a|an)\b", " ", s)
    words = [_TITLE_SYNONYMS.get(w, w) for w in s.split()]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def fingerprint(company: str, title: str) -> str:
    """Stable key for a posting so we dedup even when Tsenta rotates the job_id."""
    c = _norm_text(company)
    c = COMPANY_ALIASES.get(c, c)
    return f"{c}::{_norm_text(title)}"


def norm_url(url: str) -> str:
    """Apply-URL key: scheme/host/path only. Query strings carry tracking junk
    (utm_source, gh_jid, refId) that differs between sources for one posting."""
    u = (url or "").strip().lower()
    u = u.split("?")[0].split("#")[0].rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u


def applied_urls(state: dict) -> set:
    return {norm_url(a.get("url")) for a in state.get("applications", [])
            if a.get("url") and a.get("status") != "dry"}

_COMPANY_QUALIFIERS = {
    "global", "tech", "technologies", "technology", "international", "intl",
    "labs", "systems", "services", "solutions", "digital", "worldwide",
    "usa", "us", "america", "americas", "enterprises", "group", "holdings",
    "company", "co", "corp", "incorporated", "software", "engineering",
}


def _fp_parts(fp: str) -> tuple[str, str]:
    company, _, title = fp.partition("::")
    return company, title


def same_posting(fp_a: str, fp_b: str) -> bool:
    """True when two fingerprints denote the same job listed under different company names.

    fingerprint() strips Inc/LLC and parentheticals, but not qualifiers: a job Tsenta
    lists under "Walmart" arrives from LinkedIn as "Walmart Global Tech", and likewise
    Garmin/"Garmin International", Kraken/"Kraken Digital". Those produced different
    fingerprints and so would have been applied to TWICE once a second source was added.

    The title must match exactly; only the company is allowed to be a prefix of the
    other. That keeps "Apple"/"Apple Bank" apart unless they also post an identically
    titled role, which is not a realistic collision.
    """
    if fp_a == fp_b:
        return True
    ca, ta = _fp_parts(fp_a)
    cb, tb = _fp_parts(fp_b)
    if not ta or ta != tb or not ca or not cb:
        return False
    long_, short_ = (ca, cb) if len(ca) > len(cb) else (cb, ca)
    if not long_.startswith(short_ + " "):
        return False
    # The extra words must be corporate qualifiers, not a different business.
    # "Walmart Global Tech" IS Walmart; "Apple Bank" is NOT Apple. Without this the
    # prefix rule silently skipped genuinely different employers as duplicates.
    extra = long_[len(short_) + 1:].split()
    return bool(extra) and all(w in _COMPANY_QUALIFIERS for w in extra)


def is_duplicate(company: str, title: str, seen_fps) -> bool:
    """Has this posting already been applied to, under any name variant?"""
    fp = fingerprint(company, title)
    if fp in seen_fps:
        return True
    return any(same_posting(fp, s) for s in seen_fps)


LOCAL_PATH = Path(os.environ.get(
    "AGENT_STATE_FILE", str(Path.home() / "Documents" / "JobHunt2026" / "tsenta_agent_state.json")))
GCS_BUCKET = os.environ.get("AGENT_STATE_BUCKET", "")
GCS_OBJECT = "tsenta_agent_state.json"


def _gcs_blob():
    from google.cloud import storage
    return storage.Client().bucket(GCS_BUCKET).blob(GCS_OBJECT)


def load() -> dict:
    if GCS_BUCKET:
        blob = _gcs_blob()
        return json.loads(blob.download_as_text()) if blob.exists() else {"applications": []}
    if not LOCAL_PATH.exists():
        return {"applications": []}
    return json.loads(LOCAL_PATH.read_text())


def save(state: dict) -> None:
    if GCS_BUCKET:
        _gcs_blob().upload_from_string(json.dumps(state, indent=2), content_type="application/json")
        return
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_PATH.write_text(json.dumps(state, indent=2))


def applied_job_ids(state: dict) -> set:
    return {a["job_id"] for a in state.get("applications", []) if a.get("job_id")
            and a.get("status") != "dry"}


def applied_fingerprints(state: dict) -> set:
    """Dedup backstop: normalized company::title of everything already applied,
    so a rotated job_id can't cause a double-apply.

    ALWAYS recomputes -- never trusts the stored `fp`. Records written before a change
    to fingerprint() carry keys in the old format, and comparing an old stored key
    against a newly-computed one silently fails to match. Measured on 2026-08-21: after
    "sr"->"senior" and similar normalisation was added, 70 already-applied jobs (PNC,
    Barclays, Citigroup, Visa, Oracle...) looked fresh again and would have been applied
    to a second time. Both sides must go through the same function.
    """
    return {fingerprint(a.get("company"), a.get("title"))
            for a in state.get("applications", []) if a.get("status") != "dry"}


def norm_company(name: str) -> str:
    """Collapse employer-name variants so the per-company cap can't be dodged by
    "PNC Financial" vs "PNC Financial Services" vs "PNC"."""
    s = re.sub(r"[^a-z0-9]+", " ", (name or "").lower())
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|plc|group|holdings|technologies|"
               r"technology|solutions|services|financial|bank|na|the|and)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def company_counts(state: dict, days: int) -> dict:
    """How many real applications went to each employer in the last `days`."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    counts: dict[str, int] = {}
    for a in state.get("applications", []):
        if a.get("status") != "applied" or (a.get("date") or "") < cutoff:
            continue
        k = norm_company(a.get("company"))
        if k:
            counts[k] = counts.get(k, 0) + 1
    return counts


def applied_today_count(state: dict) -> int:
    today = date.today().isoformat()
    return sum(1 for a in state.get("applications", [])
               if a.get("date") == today and a.get("status") == "applied")


def hold(state: dict, scored: dict, reason: str) -> None:
    """Park a job for human review instead of applying to it.

    Kept in its OWN list, not in `applications`: applied_job_ids() treats every status
    except "dry" as already-applied, so recording a hold there would permanently dedup
    away a job we deliberately did not apply to. Upserted by fingerprint so an hourly
    agent re-holding the same posting doesn't pile up duplicates.
    """
    fp = fingerprint(scored.get("company"), scored.get("title"))
    entries = state.setdefault("held", [])
    for e in entries:
        if e.get("fp") == fp:
            e.update({"last_seen": date.today().isoformat(), "reason": reason})
            return
    entries.append({
        "fp": fp,
        "first_seen": date.today().isoformat(),
        "last_seen": date.today().isoformat(),
        "job_id": scored.get("job_id"),
        "company": scored.get("company"),
        "title": scored.get("title"),
        "url": scored.get("url"),
        "score": scored.get("fit_score"),
        "salary_min": scored.get("salary_min"),
        "salary_max": scored.get("salary_max"),
        "suggested_ask": scored.get("suggested_ask"),
        "reason": reason,
    })


def held(state: dict) -> list:
    """Jobs waiting on a human decision, newest first."""
    return sorted(state.get("held", []), key=lambda e: e.get("last_seen", ""), reverse=True)


def release(state: dict, fp: str) -> bool:
    """Drop a held entry once it's been acted on."""
    entries = state.get("held", [])
    for i, e in enumerate(entries):
        if e.get("fp") == fp:
            entries.pop(i)
            return True
    return False


def merge(base: dict, other: dict) -> dict:
    """Union two state snapshots. Applications are keyed by (job_id, ts) so a record
    written by a concurrent run is never lost.

    Needed because save() is last-write-wins on one GCS blob: the hourly Cloud Run job
    and any manual run both load a snapshot, append to it, and overwrite. On 2026-08-18
    that silently dropped two applications (1253 -> 1251), and an application the agent
    no longer knows about is one it will make again.
    """
    out = dict(base or {})
    seen, merged = set(), []
    for rec in list((base or {}).get("applications", [])) + \
               list((other or {}).get("applications", [])):
        key = (rec.get("job_id"), rec.get("ts"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(rec)
    merged.sort(key=lambda r: str(r.get("ts") or ""))
    out["applications"] = merged
    held = {}
    for h in list((base or {}).get("held", [])) + list((other or {}).get("held", [])):
        held[h.get("fp") or id(h)] = h
    out["held"] = list(held.values())
    return out


def save_merged(state: dict) -> dict:
    """Re-read what is stored, merge this run's records into it, then write.

    save() alone overwrites; this keeps a concurrent run's applications. Call it after
    EVERY apply, not once at the end -- a crash between applying and saving leaves the
    application submitted but unrecorded, which is the single most likely way a job gets
    applied to twice.
    """
    try:
        stored = load()
    except Exception:
        stored = {}
    merged = merge(stored, state)
    save(merged)
    state["applications"] = merged.get("applications", [])
    state["held"] = merged.get("held", [])
    return state


async def reconcile_from_tsenta(mcp, state: dict, pages: int = 3) -> int:
    """Fold Tsenta's own application list into local state.

    Tsenta is the authority on what has been applied to; the local JSON is a cache that
    can race, be lost, or miss applications made outside this agent (Brightvision, CVS
    Health and Vanguard all appeared in Tsenta having never been in either state file).
    Returns how many records were added.
    """
    known = {(a.get("job_id"), a.get("company"), a.get("title"))
             for a in state.get("applications", [])}
    known_fps = applied_fingerprints(state)
    added = 0
    for page in range(1, pages + 1):
        try:
            r = await mcp._call_json("list-applications", {"limit": 40, "page": page})
        except Exception:
            break
        rows = r if isinstance(r, list) else (r.get("applications") or r.get("data") or [])
        if not rows:
            break
        for a in rows:
            comp, title = a.get("companyName"), a.get("jobTitle")
            if not (comp or title):
                continue
            fp = fingerprint(comp, title)
            if fp in known_fps or (a.get("jobId"), comp, title) in known:
                continue
            state.setdefault("applications", []).append({
                "date": str(a.get("createdAt") or "")[:10],
                "ts": str(a.get("createdAt") or "")[:19],
                "job_id": a.get("jobId"), "company": comp, "title": title,
                "fp": fp, "url": a.get("url"), "score": None,
                "status": "applied", "source": "tsenta-reconcile",
            })
            known_fps.add(fp)
            added += 1
    return added


def record(state: dict, scored: dict, status: str) -> None:
    state.setdefault("applications", []).append({
        "date": date.today().isoformat(),
        "ts": datetime.utcnow().isoformat(timespec="seconds"),
        "job_id": scored.get("job_id"),
        "company": scored.get("company"),
        "title": scored.get("title"),
        "fp": fingerprint(scored.get("company"), scored.get("title")),
        "url": scored.get("url"),
        "score": scored.get("fit_score"),
        "status": status,
    })
