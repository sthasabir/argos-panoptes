#!/usr/bin/env python3
"""Fill in the blank `major` on the Tsenta education record.

Why (2026-08-19): two applications failed with errorCode=PROFILE_INCOMPLETE --
Highmark Health and Downstream.ai, both Workday. Workday education forms usually make
"field of study" a required field, and the profile had:

    degree:     "Bachelor of Information Technology"
    university: "<redacted>"   (dates redacted)
    major:      ""      <- blank, so the form could not be completed

The candidate confirmed the major is Information Technology.

Run:
    cd ~/project/argos-panoptes
    set -a && source .env && set +a
    .venv/bin/python tools/fix_education.py

Prints the education record before and after. Read-only unless --write is passed.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mcp_client  # noqa: E402

PROFILE_ID = "cms97bsal00z0r4xs1vxosb24"
MAJOR = "Information Technology"


async def main() -> None:
    write = "--write" in sys.argv

    async with mcp_client.TsentaMCP() as m:
        prof = await m._call_json("get-resume-profile", {"resumeProfileId": PROFILE_ID})
        edu = (prof.get("data") or {}).get("education") or []
        print("BEFORE:", json.dumps(edu, indent=1))

        if not edu:
            print("\n!! no education record to patch -- add one in the Tsenta UI first")
            return

        updated = []
        for e in edu:
            e = dict(e)
            if not (e.get("major") or "").strip():
                e["major"] = MAJOR
            updated.append(e)

        if not write:
            print("\nWOULD SET major =", MAJOR)
            print("(dry run -- re-run with --write to apply)")
            return

        await m._call_json("set-education", {"education": updated})

        prof2 = await m._call_json("get-resume-profile", {"resumeProfileId": PROFILE_ID})
        after = (prof2.get("data") or {}).get("education") or []
        print("\nAFTER :", json.dumps(after, indent=1))

        got = (after[0].get("major") or "").strip() if after else ""
        if got == MAJOR:
            print(f"\nOK -- major is now {got!r}")
            print("Highmark Health and Downstream.ai can be re-applied to; both had")
            print("canReapply=False, so they may need re-applying as fresh postings.")
        else:
            print(f"\n!! did not stick -- major reads {got!r}. Set it in the Tsenta UI.")


if __name__ == "__main__":
    asyncio.run(main())
