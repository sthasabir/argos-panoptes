"""Offline unit tests for the location filters — no auth, no network.

    .venv/bin/python test_location.py

Deliberately separate from test_gate1.py / test_pipeline.py, which are live
integration scripts that open a Tsenta session. These run anywhere.

The location rules have a history of passing unit tests while leaking in
production ("India, IN" reading as Indiana), so every case below is a string a
feed actually emitted. Passing this file is necessary, not sufficient — audit
against the live feed too.
"""
import os

# Exercise the region logic itself, not whatever the current search policy happens to
# be. gate1 resolves REGION_ON at import time, so this has to be set BEFORE the import
# below — otherwise these cases silently pass whenever REQUIRE_REGION=0 is in the
# environment, testing nothing.
os.environ["REQUIRE_REGION"] = "1"

from gate1 import _us_status, _region_status, is_in_region, gate1  # noqa: E402

FAILED = []


def check(label, got, want):
    if got != want:
        FAILED.append(f"{label}: got {got!r}, want {want!r}")


# ---------------------------------------------------------------- US detection
for loc, want in [
    ("New York, NY", True),
    ("Indianapolis, IN", True),
    ("Remote", True),
    ("Boston, United States", True),
    ("India, IN", False),                      # the Indiana trap
    ("Bengaluru, Karnataka, IN", False),
    ("Toronto, ON, CA", False),
    ("Mississauga Ontario Canada", False),     # no commas at all
    ("15 Tran Bach Dang An Khanh Ward", None),
    # hyphen-joined ATS geo — these were being rejected as non-US
    ("US-VA-McLean", True),
    ("USA-NY-New York", True),
    ("US-CA-San Francisco", True),
    ("US-TX", True),
    # not the ATS shape: real hyphenated city names must not be misread as country-state
    ("Winston-Salem, NC", True),
    # unknown country in the same shape stays undecidable rather than being guessed US
    ("CA-ON-Toronto", None),
    # LinkedIn metro phrasing — these were being rejected as non-US
    ("San Francisco Bay Area", True),
    ("Dallas-Fort Worth Metroplex", True),
    ("New York City Metropolitan Area", True),
    ("Greater Boston", True),
    ("Greater St. Louis", True),
    # still foreign, and metro-stripping must not rescue them
    ("Greater Toronto Area, Canada", False),
    ("Bengaluru, Karnataka, IN", False),
]:
    check(f"_us_status({loc!r})", _us_status(loc), want)


# ---------------------------------------------------------------- region: in
for loc in [
    "New York, NY", "Boston, MA", "Jersey City, NJ", "Washington, DC",
    "Charlotte, NC", "Atlanta, GA", "Tampa, FL", "Columbus, OH", "Detroit, MI",
    "Nashville, TN", "Louisville, KY", "Philadelphia, PA", "Stamford, CT",
    "New Jersey, United States",               # state name in the region slot
    "Arlington, Virginia",                     # ambiguous city, state settles it
    "New York City Metropolitan Area",         # LinkedIn metro phrasing
    "Greater Boston", "Malvern", "Reston", "Research Triangle Park",
    "Remote", "Remote, US", "United States",   # nationwide -> REGION_ALLOW_REMOTE
    "US-VA-McLean", "USA-NY-New York",         # ATS geo carries its own state
]:
    check(f"_region_status({loc!r})", _region_status(loc), True)


# ---------------------------------------------------------------- region: out
for loc in [
    "Austin, TX", "San Francisco, CA", "Seattle, WA", "Denver, CO",
    "Chicago, IL", "Phoenix, AZ", "Minneapolis, MN", "Salt Lake City, UT",
    "Mountain View, CA", "Sunnyvale, California",
    "Remote, TX",                              # state beats the remote fallback
    "Bengaluru, Karnataka, IN", "Mississauga Ontario Canada",
    "US-CA-San Francisco", "US-TX-Austin",     # ATS geo, out of region
]:
    check(f"_region_status({loc!r})", _region_status(loc), False)


# ------------------------------------------------------- region: undecidable
# Real US cities whose two readings straddle the region line. Undecidable is not
# a pass: is_in_region requires a positive placement, so these get dropped.
for loc in ["Portland", "Arlington", "Columbia", "Rochester", "Washington"]:
    check(f"_region_status({loc!r})", _region_status(loc), None)


# ---------------------------------------------------------------- is_in_region
check("no locations field passes", is_in_region({"title": "x"}), True)
check("one in-region loc is enough",
      is_in_region({"locations": ["Austin, TX", "New York, NY"]}), True)
check("all out-of-region drops",
      is_in_region({"locations": ["Austin, TX", "Seattle, WA"]}), False)
check("bare string location", is_in_region({"locations": "Boston, MA"}), True)


# ---------------------------------------------------------------- through gate1
_JOB = {"id": "1", "title": "Senior Java Developer", "companyName": "Acme",
        "seniorityLevel": "senior", "roleFamily": "BACKEND"}
kept, dropped = gate1([
    {**_JOB, "id": "in", "locations": ["Boston, MA"]},
    {**_JOB, "id": "out", "locations": ["Austin, TX"]},
])
check("gate1 keeps in-region", [j["id"] for j in kept], ["in"])
check("gate1 drop reason", dropped[0]["reason"].split(":")[0], "outside region")


if FAILED:
    print(f"FAILED {len(FAILED)}:")
    for f in FAILED:
        print("  -", f)
    raise SystemExit(1)
print("location tests: all passed")
