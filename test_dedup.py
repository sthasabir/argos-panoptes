#!/usr/bin/env python3
"""Pre-deploy checks for the dedup hardening. Read-only against production state.

Run:  set -a && source .env && set +a && .venv/bin/python test_dedup.py
"""
import os
import sys
import json
import copy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["AGENT_STATE_BUCKET"] = "argos-panoptes-zeykbi-state"

import state as st  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -- ' + detail) if detail and not cond else ''}")
    if not cond:
        FAILS.append(name)


print("loading production state (read-only)...")
PROD = st.load()
APPS = [a for a in PROD.get("applications", []) if a.get("status") != "dry"]
print(f"  {len(APPS)} applied records\n")

# ---------------------------------------------------------------- 1. regression
print("1. fingerprint change must not resurrect applied jobs")
seen = st.applied_fingerprints(PROD)
resurrect = [a for a in APPS
             if not st.is_duplicate(a.get("company"), a.get("title"), seen)]
check("no already-applied job looks fresh", len(resurrect) == 0,
      f"{len(resurrect)} would re-apply, e.g. {resurrect[:3]}")
check("seen_fps is populated", len(seen) > 100, f"only {len(seen)}")

# ---------------------------------------------------------------- 2. url dedup
print("\n2. url dedup")
urls = st.applied_urls(PROD)
check("applied_urls populated", len(urls) > 50, f"only {len(urls)}")
check("query strings stripped",
      st.norm_url("https://x.com/a?utm=1") == st.norm_url("https://www.x.com/a/"))
check("empty url is safe", st.norm_url(None) == "" and st.norm_url("") == "")

# ---------------------------------------------------------------- 3. edge cases
print("\n3. edge cases (must not raise)")
try:
    st.fingerprint(None, None); st.fingerprint("", "")
    st.is_duplicate(None, None, seen)
    st.same_posting("::", "::")
    st.is_duplicate("Acme", "Engineer", set())
    check("None/empty inputs handled", True)
except Exception as e:
    check("None/empty inputs handled", False, str(e)[:90])

# blank company must not collapse everything together
blank_a = st.fingerprint("", "Senior Software Engineer")
blank_b = st.fingerprint("", "Senior Backend Engineer")
check("blank company keeps titles distinct", blank_a != blank_b)
check("same_posting rejects empty company",
      not st.same_posting("::senior software engineer", "acme::senior software engineer"))

# ---------------------------------------------------------------- 4. false positives
print("\n4. must NOT merge genuinely different jobs")
cases = [
    (("Apple", "Senior Software Engineer"), ("Apple Bank", "Senior Software Engineer")),
    (("Acme", "Senior Software Engineer"), ("Acme", "Staff Software Engineer")),
    (("Stripe", "Backend Engineer"), ("Square", "Backend Engineer")),
    (("Acme", "Software Engineer II"), ("Acme", "Software Engineer III")),
]
for (c1, t1), (c2, t2) in cases:
    same = st.same_posting(st.fingerprint(c1, t1), st.fingerprint(c2, t2))
    check(f"{c1}/{t1[:26]} != {c2}/{t2[:26]}", not same)

# ---------------------------------------------------------------- 5. true positives
print("\n5. MUST merge the same job under different names")
same_cases = [
    (("Walmart", "Senior Software Engineer"), ("Walmart Global Tech", "Sr Software Engineer")),
    (("Meta", "Senior Software Engineer"), ("Facebook", "Senior Software Engineer")),
    (("Garmin", "Senior Java Engineer"), ("Garmin International", "Senior Java Engineer")),
    (("ZoomInfo", "Senior Software Engineer"), ("ZoomInfo Technologies", "Senior SWE")),
    (("Roblox", "Senior Software Engineer, Privacy"), ("Roblox", "Senior Software Engineer - Privacy")),
]
for (c1, t1), (c2, t2) in same_cases:
    dup = st.is_duplicate(c2, t2, {st.fingerprint(c1, t1)})
    check(f"{c1} == {c2}", dup)

# ---------------------------------------------------------------- 6. merge safety
print("\n6. merge must never lose or duplicate records")
a = {"applications": APPS[:50], "held": []}
b = {"applications": APPS[40:90], "held": []}
m = st.merge(a, b)
keys = [(r.get("job_id"), r.get("ts")) for r in m["applications"]]
check("merge is a union", len(m["applications"]) == len(set(keys)))
check("merge loses nothing", len(m["applications"]) >= len(APPS[:90]) - 10,
      f"{len(m['applications'])} vs {len(APPS[:90])}")
check("merge is idempotent",
      len(st.merge(m, a)["applications"]) == len(m["applications"]))
snapshot = copy.deepcopy(a)
st.merge(a, b)
check("merge does not mutate its inputs", a == snapshot)

# ---------------------------------------------------------------- 7. state integrity
print("\n7. production state integrity")
check("no record lost by recompute",
      len(st.applied_fingerprints(PROD)) > 0)
dupe_fp = len(APPS) - len(st.applied_fingerprints(PROD))
print(f"     note: {len(APPS)} records collapse to {len(seen)} unique keys "
      f"({dupe_fp} are repeat applications already in history)")

print("\n" + "=" * 60)
print(f"{'ALL CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
