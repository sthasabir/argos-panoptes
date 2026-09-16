"""Offline unit tests for the location-adjusted salary floor.

    .venv/bin/python test_salary.py

No auth, no network. The rule under test: the floor for a job is
max(MIN_SALARY, SALARY_BASELINE * location_index) — location can only RAISE the bar,
never lower it below the absolute floor (requested 2026-08-13).
"""
import os

# resolve flags at import, before gate1 reads them
os.environ["SALARY_LOCATION_ADJUST"] = "1"

from gate1 import effective_floor, pays_enough, _location_multiplier  # noqa: E402
from profile import MIN_SALARY  # noqa: E402

FAILED = []


def check(label, got, want):
    if got != want:
        FAILED.append(f"{label}: got {got!r}, want {want!r}")


def floor_for(*locs):
    return round(effective_floor({"locations": list(locs)}))


# ---------------------------------------------------- the absolute floor holds
# Cheap metros must NOT drop below MIN_SALARY, however low their index is.
for loc in ["Plano, TX", "Tampa, FL", "Nashville, TN", "Charlotte, NC",
            "Columbus, OH", "Atlanta, GA", "Seattle, WA", "Dallas, TX"]:
    check(f"floor({loc})", floor_for(loc), MIN_SALARY)

# ---------------------------------------------------- expensive metros raise it
check("floor(New York, NY)", floor_for("New York, NY"), 184_950)
check("floor(Manhattan)", floor_for("Manhattan"), 184_950)
check("floor(Jersey City, NJ)", floor_for("Jersey City, NJ"), 163_350)
check("floor(Boston, MA)", floor_for("Boston, MA"), 156_600)
check("floor(San Francisco, CA)", floor_for("San Francisco, CA"), 195_750)
check("floor(Reston, VA)", floor_for("Reston, VA"), 143_100)

# city overrides beat the state index
check("NYC beats NY state", floor_for("Brooklyn, NY"), 184_950)
check("Philadelphia over PA", floor_for("Philadelphia, PA"), 143_100)

# ---------------------------------------------------- location parsing reuse
check("metro phrasing", floor_for("New York City Metropolitan Area"), 184_950)
check("ATS geo", floor_for("US-NY-New York"), 184_950)
check("state name", floor_for("Boston, Massachusetts"), 156_600)

# ---------------------------------------------------- unplaceable / remote
check("remote uses flat floor", floor_for("Remote"), MIN_SALARY)
check("no locations", round(effective_floor({})), MIN_SALARY)
check("unknown city", floor_for("Ogallala"), MIN_SALARY)

# ---------------------------------------------------- multi-location: lowest wins
check("NYC+Tampa -> Tampa's floor", floor_for("New York, NY", "Tampa, FL"), MIN_SALARY)
check("NYC+Boston -> Boston's", floor_for("New York, NY", "Boston, MA"), 156_600)

# ---------------------------------------------------- end to end through pays_enough
# Oracle's real posting: $40k-$140k in New York. Top clears the old flat $135k bar,
# but nowhere near what New York actually costs.
oracle_ny = {"salaryMin": 40_000, "salaryMax": 140_000, "locations": ["New York, NY"],
             "salaryCurrency": "USD"}
check("Oracle NY rejected", pays_enough(oracle_ny), False)

# Citigroup Jersey City: $142,320-$213,480. Top clears the $163,350 Jersey City bar.
citi_jc = {"salaryMin": 142_320, "salaryMax": 213_480, "locations": ["Jersey City, NJ"],
           "salaryCurrency": "USD"}
check("Citi JC kept", pays_enough(citi_jc), True)

# A Plano role topping out at $139k is now below the absolute floor.
plano_low = {"salaryMin": 120_000, "salaryMax": 139_000, "locations": ["Plano, TX"],
             "salaryCurrency": "USD"}
check("Plano under 140k rejected", pays_enough(plano_low), False)
plano_ok = {"salaryMin": 120_000, "salaryMax": 145_000, "locations": ["Plano, TX"],
            "salaryCurrency": "USD"}
check("Plano over 140k kept", pays_enough(plano_ok), True)

# missing salary still passes — half the feed has none
check("no salary passes", pays_enough({"locations": ["New York, NY"]}), True)
# non-USD still passes
check("non-USD passes", pays_enough(
    {"salaryMax": 90_000, "salaryCurrency": "EUR", "locations": ["New York, NY"]}), True)

if FAILED:
    print(f"FAILED {len(FAILED)}:")
    for f in FAILED:
        print("  -", f)
    raise SystemExit(1)
print("salary tests: all passed")
