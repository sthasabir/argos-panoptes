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
from datetime import datetime, date
from pathlib import Path


def fingerprint(company: str, title: str) -> str:
    """Stable key for a posting so we dedup even when Tsenta rotates the job_id.
    Lowercase, strip punctuation/extra spaces, drop common noise words."""
    def norm(s: str) -> str:
        s = (s or "").lower()
        s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)          # drop parentheticals/brackets
        s = re.sub(r"[^a-z0-9]+", " ", s)
        s = re.sub(r"\b(remote|hybrid|onsite|position|role|inc|llc|the|a|an)\b", " ", s)
        return re.sub(r"\s+", " ", s).strip()
    return f"{norm(company)}::{norm(title)}"

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
    so a rotated job_id can't cause a double-apply."""
    return {a.get("fp") or fingerprint(a.get("company"), a.get("title"))
            for a in state.get("applications", []) if a.get("status") != "dry"}


def applied_today_count(state: dict) -> int:
    today = date.today().isoformat()
    return sum(1 for a in state.get("applications", [])
               if a.get("date") == today and a.get("status") == "applied")


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
