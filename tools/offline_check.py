"""No-auth sanity check: pull live external jobs and run Gate 1 on them.

Exercises everything that does not need Tsenta OAuth or Vertex AI, so you can
confirm the install and see the rule filter working on today's real postings.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sources
from gate1 import gate1

# NOT setdefault: .env exports EXTERNAL_SOURCES="" (set-but-empty), and setdefault will
# not overwrite that — this check reported "kept 0, dropped 0" and exited 0.
if not os.environ.get("EXTERNAL_SOURCES", "").strip():
    os.environ["EXTERNAL_SOURCES"] = "github,linkedin"
    print("EXTERNAL_SOURCES empty -> defaulting to github,linkedin for this check")

pool = sources.gather_external()
by_source = collections.Counter(j["source"] for j in pool)
print(f"pulled {len(pool)} jobs {dict(by_source)}\n")

kept, dropped = gate1(pool)
print(f"Gate 1: kept {len(kept)}, dropped {len(dropped)}\n")

print("=== kept (would go to Gate 2 for scoring) ===")
for j in kept[:15]:
    print(f"  {j['title']} @ {j['companyName']}  ({j['datePosted']})")
if len(kept) > 15:
    print(f"  ... and {len(kept) - 15} more")

print("\n=== dropped, with reason ===")
for d in dropped[:15]:
    print(f"  {d['reason']}")
