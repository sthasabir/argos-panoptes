#!/usr/bin/env python3
"""Turn ON Tsenta's autoApproveResume so applications stop parking in the review queue.

Why this exists (2026-08-18): the agent applied 25 times that day and Tsenta logged and
charged for all 25, but only 5 reached employers. The other 20 sat at
PENDING_RESUME_REVIEW because the account had:

    autoSubmitApplication: true     <- Tsenta will submit...
    autoApproveResume:     false    <- ...but not until a human approves the resume

apply-to-job has no flag that skips this; the account setting is the only lever, and
Claude Code's permission classifier blocks the agent from writing it, since it governs
whether documents go out in the candidate's name. So it is run by hand:

    cd ~/project/argos-panoptes
    set -a && source .env && set +a
    .venv/bin/python tools/enable_auto_approve.py

Prints the preferences before and after. Pass --off to put it back.

NOTE: this may only affect NEW applications. Anything already queued at
PENDING_RESUME_REVIEW probably still needs approving in the Tsenta UI -- check the
pending count this prints at the end.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mcp_client  # noqa: E402


async def main() -> None:
    want = "--off" not in sys.argv

    async with mcp_client.TsentaMCP() as m:
        before = await m._call_json("get-apply-preferences", {})
        print("BEFORE:", json.dumps(before, indent=1))

        if before.get("autoApproveResume") is want:
            print(f"\nalready autoApproveResume={want} -- nothing to change")
        else:
            await m._call_json("set-apply-preferences", {"autoApproveResume": want})
            after = await m._call_json("get-apply-preferences", {})
            print("\nAFTER :", json.dumps(after, indent=1))
            if after.get("autoApproveResume") is not want:
                print(f"\n!! setting did NOT stick -- still {after.get('autoApproveResume')}")
                print("   Change it in the Tsenta UI instead.")
                return

        # How many are still held?
        r = await m._call_json("list-applications", {"limit": 40})
        apps = r if isinstance(r, list) else (r.get("applications") or r.get("data") or [])
        if isinstance(r, dict) and not apps:
            for v in r.values():
                if isinstance(v, list) and v:
                    apps = v
                    break
        pending = [a for a in apps if a.get("status") == "PENDING_RESUME_REVIEW"]
        print(f"\nstill PENDING_RESUME_REVIEW: {len(pending)} of the last {len(apps)}")
        for a in pending[:25]:
            title = str(a.get("jobTitle") or "")[:40]
            print(f"   {title:40s} | {a.get('companyName')}")
        if pending:
            print("\nThese were applied for and charged, but have NOT reached the employer.")
            print("Approve them in the Tsenta UI -- look for a bulk approve in the queue.")


if __name__ == "__main__":
    asyncio.run(main())
