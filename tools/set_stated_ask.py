#!/usr/bin/env python3
"""Set the account-level expectedAnnualSalary in Tsenta to a new flat constant.

This is the SAFE way to change the ask: one permanent write, no per-job set/reset, so
nothing can be stranded mid-run. Do NOT turn this into a per-job loop -- Tsenta fills
ATS forms minutes after apply-to-job returns, with no completion signal, so a per-job
set->apply->reset races Tsenta's own background worker. That is what left the field at
$165,000 for four minutes on 2026-08-14 while other applications went out.

Why $155,000 (measured 2026-08-19, 30 qualifying jobs, 21 with a published range):
    median top of range          $170,000
    ask $145,000 -> below the posted FLOOR on 29% of postings, above top on 5%
    ask $155,000 -> below the posted FLOOR on 19% of postings, above top on 24%
Asking below a posted floor is strictly dominated -- the employer has already said they
would pay more, so it only loses money and can read as a junior signal. Asking slightly
above a posted top is a normal negotiating position and no verified evidence was found
that ATS systems auto-reject on it.

Run:
    cd ~/project/argos-panoptes
    set -a && source .env && set +a
    .venv/bin/python tools/set_stated_ask.py            # dry run
    .venv/bin/python tools/set_stated_ask.py --write
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mcp_client  # noqa: E402

NEW_ASK = 155000
PROFILE_ID = "cms97bsal00z0r4xs1vxosb24"


async def main() -> None:
    write = "--write" in sys.argv

    async with mcp_client.TsentaMCP() as m:
        # There is no get-personal-info tool. The value is readable only inside the
        # resume profile's workPreferences block; set-personal-info is the writer.
        async def read_ask() -> str | None:
            prof = await m._call_json("get-resume-profile", {"resumeProfileId": PROFILE_ID})
            wp = (prof.get("data") or {}).get("workPreferences") or {}
            return wp.get("expectedAnnualSalary")

        cur = await read_ask()
        print("BEFORE expectedAnnualSalary:", repr(cur))

        if not write:
            print(f"\nWOULD SET -> {NEW_ASK}")
            print("(dry run -- re-run with --write to apply)")
            return

        # set-personal-info does NOT accept salary (its schema is name/phone/address/
        # links/summary only). The writer is set-application-preferences, which takes the
        # whole workPreferences block -- so read it, change one key, send it all back,
        # otherwise canRelocate/canWorkInPerson/etc. would be dropped.
        prof = await m._call_json("get-resume-profile", {"resumeProfileId": PROFILE_ID})
        wp = dict((prof.get("data") or {}).get("workPreferences") or {})
        wp["expectedAnnualSalary"] = str(NEW_ASK)
        # The stored block carries keys the tool's schema rejects (howDidYouHearAboutRole)
        # and nulls where it wants strings (expectedHourlySalary), so filter to the
        # schema and drop Nones -- sending it back verbatim fails validation.
        allowed = {"canWorkInPerson", "canRelocate", "canStartImmediately",
                   "hasTransportation", "hasAccommodations", "noticePeriodDays",
                   "expectedAnnualSalary", "expectedHourlySalary"}
        wp = {k: v for k, v in wp.items() if k in allowed and v is not None}
        resp = await m._call_json("set-application-preferences",
                                  {"workPreferences": wp, "resumeProfileId": PROFILE_ID})
        if isinstance(resp, dict) and "error" in str(resp).lower():
            print("set-application-preferences said:", json.dumps(resp)[:300])

        got = await read_ask()
        print("AFTER  expectedAnnualSalary:", repr(got))

        if str(got) == str(NEW_ASK):
            print(f"\nOK -- ask is now ${NEW_ASK:,}")
        else:
            print(f"\n!! did not stick -- reads {got!r}. Set it in the Tsenta UI.")


if __name__ == "__main__":
    asyncio.run(main())
