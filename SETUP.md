# Setup

Local setup notes for this clone. The upstream README covers architecture; this
covers getting it running on a Mac and what you personally have to supply.

## What's already done

- Cloned to `~/project/argos-panoptes`
- `.venv` created with Python 3.14 (upstream targets 3.11; all deps installed clean)
- `.env` written with local config — **gitignored**, edit it freely
- `dev.sh` helper added, `tools/offline_check.py` added
- Verified working: external sources, Gate 1, the FastAPI service

```bash
./dev.sh gate1     # 58 live jobs pulled, 50 kept / 8 dropped by the rule filter
./dev.sh serve     # GET / and GET /state both 200
```

## What you still have to supply

The pipeline has two hard external dependencies. Neither can be faked, and
**both are required even for a dry run** — `pipeline.run()` opens the Tsenta MCP
session and calls `get_balance()` before it does anything else.

### 1. Tsenta account (job feed + the thing that actually submits applications)

Sign up at <https://tsenta.com>. 25 applications free, then $19/mo for 600.
The agent talks to it over MCP + OAuth. Then, once:

```bash
./dev.sh auth      # opens a browser, you approve, token lands in .tsenta_token.json
```

After that grant, every run is headless off the refresh token.

### 2. GCP project with Vertex AI (Gate 2 fit scorer)

`gcloud` is installed but has no credentials on this machine yet.

```bash
gcloud auth login
gcloud auth application-default login
gcloud projects create argos-panoptes-<something>   # or reuse an existing one
gcloud config set project <your-project-id>
gcloud services enable aiplatform.googleapis.com
```

Then set `VERTEX_PROJECT` in `.env` to your project id. It currently reads
`TODO-your-gcp-project-id` — and note that `gate2.py` hardcodes the original
author's project (`jobagent-aayush`) as its fallback default, so if you leave the
env var unset it will try to hit a project you don't have access to.

Gemini Flash on a run of ~50 jobs is fractions of a cent, but the project does
need billing enabled.

### 3. Profile — done, and it required more than a name swap

Upstream targets a 2026 new grad who requires H1B sponsorship. This profile is a
7-year Java full-stack IC with a Green Card. Four things fought that, so all four
were changed:

| File | Upstream (new grad) | Now |
| --- | --- | --- |
| `profile.py` | Aayush, May 2026 grad, needs H1B | Jordan, 7 yrs, permanent resident |
| `gate1.py` | dropped `senior\|sr\|staff\|principal\|lead` titles | those are the *target*; drops management/exec instead |
| `gate1.py` | dropped jobs needing ≥3 YOE | `MAX_YOE=10`, and drops entry-level/new-grad postings |
| `gate1.py` | dropped `NO_SPONSORSHIP` roles | only applies when `CANDIDATE["needs_sponsorship"]` is true |
| `gate2.py` | prompt hardcoded "NEW GRAD … REQUIRES H1B" | derives seniority and work auth from `profile.py` |
| `.env` | 3 new-grad GitHub boards + "new grad" LinkedIn queries | GitHub disabled; senior Java LinkedIn queries |

Thresholds live in `profile.py` under `SENIORITY` and are env-overridable
(`MAX_YOE`, `REJECT_ENTRY_LEVEL`).

### Never-apply company list

`EXCLUDE_COMPANIES` in `profile.py` blocks every current and past employer:
Meridian Financial (current), Vantage Capital, Cornerstone Bank. It is rule 0 of
`gate1.py`, so a blocked company can't reach the scorer or the apply call.
Override with `EXCLUDE_COMPANIES="acme|globex"` in `.env`.

Matching normalizes punctuation and corporate suffixes, then matches whole
words — so `Meridian` blocks "Meridian Corp" but not "Meridian Point Media" or
"Meridianer Systems", and unrelated similarly-named companies survive.

**Keep every spelling variant listed.** The feeds emit `Meridian Financial`,
`MeridianFinancial` (no space) and bare `Meridian`; and `Cornerstone Bank`,
`Cornerstone Bancorp`. An unspaced variant once leaked through while all the
unit tests passed — verify blocklist edits against the live feed.

Some bare entries are intentionally broad and may also block unrelated companies
with similar names. Narrow or remove an entry if you want those back.

Verified against live postings: 40 pulled, 40 kept, 0 dropped — all senior Java
roles. On the upstream config the same search returned new-grad boards and Gate 1
would have rejected nearly every one of them on the senior-title rule.

### Region filter — East Coast only

`REQUIRE_REGION` in `profile.py` narrows the US search to the **Eastern time
zone** (requested 2026-08-11): ME NH VT MA RI CT NY NJ PA DE MD DC VA WV NC SC
GA FL, plus the inland ET states OH MI IN KY TN. It is rule 0c of `gate1.py`,
right after the US check, and `gate2.py` re-checks it against the full JD.

States are whole-state, not county-accurate — FL, KY, TN, MI and IN are split by
the real time-zone line and count as in-region in full.

`REGION_ALLOW_REMOTE` (default on) lets a posting whose location text is
"Remote", "Remote, US" or a bare "United States" through. It governs the
**location text, not `workplaceType`**: a job listed in "Austin, TX" is dropped
even when `workplaceType` is REMOTE.

Placement rules, in order — the scan runs **right-to-left** because feeds put the
state last, which is what keeps "Washington, DC" from resolving as Washington
state:

| Location | Verdict |
| --- | --- |
| `Boston, MA`, `New Jersey, United States` | in-region (state slot) |
| `Austin, TX`, `Remote, TX` | out (an explicit state beats the remote fallback) |
| `Malvern`, `New York City Metropolitan Area`, `Greater St. Louis` | placed via the city map |
| `Portland`, `Arlington`, `Columbia`, `Rochester`, `Washington` | **undecidable → dropped** |
| `US-VA-McLean`, `USA-NY-New York` | hyphen-joined ATS geo — country/state/city |

Some ATS feeds write a location as `US-VA-McLean` — country, state and city
joined by hyphens with no commas. The comma parser read that as one unplaceable
token and rejected genuine US jobs as **non-US** (two Steampunk roles in McLean
were lost this way). `_ats_state()` now recognises the `US-`/`USA-` form and
extracts the state, so those jobs are judged on merit. Only the US form is
matched positively; `CA-ON-Toronto` still falls through to undecidable. Real
hyphenated city names are unaffected — "Winston-Salem" fails the country group
(7 letters) and "Dallas-Fort Worth" fails the 2-letter state group.

Those five bare city names are real US cities whose two readings straddle the
region line (Portland OR/ME, Arlington VA/TX). They stay in `US_CITY_STATE` with
a `None` state, so they still count as US — only the region is undecidable, and
an unplaceable job is rejected rather than waved through, same as the US rule.

Verified against the live feed, not just unit tests: of 145 US postings that
reached the rule, 29 were dropped and **all 29 resolved to a positive
out-of-region verdict** — none were lost to an unparseable string. 31/31
LinkedIn jobs now carry a parsed location.

`test_location.py` covers this offline (`.venv/bin/python test_location.py`) —
no auth, no network, unlike the other two test files.

**One known hole:** 11 of 150 Tsenta postings carry no `locations` field at all.
Those bypass both the US and the region rule by design (rejecting on absent data
would gut the funnel) and are caught by Gate 2 reading the JD.

### Indeed — a file-backed source, not an autonomous one

Tsenta's index misses whole sectors: no Amazon/Google/Microsoft/Apple, no airlines,
no UnitedHealth/Optum, and most large insurers. Indeed covers them, so
`sources.from_indeed()` exists — but **it never makes a network call**.

Two hard facts force that design, both verified 2026-08-13:

| | |
| --- | --- |
| `indeed.com/jobs?...` from this process | **HTTP 403** — bot-blocked |
| `api.indeed.com` (legacy publisher API) | DNS does not resolve — retired |
| Tsenta `fetch-job-description` on a `to.indeed.com` link | **0 chars** |

So the adapter reads `state/indeed_feed.json`, which an operator (Claude, using the
Indeed MCP tools) refreshes via `tools/indeed_import.py`. The third row above is why
each entry must carry its own `description`: without one the pipeline's "never apply
blind" rule drops the job before Gate 2, and no fetch can recover it.
`get_job_details` returns the full JD, so paste that in.

```bash
.venv/bin/python tools/indeed_import.py new_jobs.json   # merge (dedups by url)
.venv/bin/python tools/indeed_import.py --prune         # age out stale rows only
```

Enable with `EXTERNAL_SOURCES=linkedin,indeed`. A missing or stale file is harmless —
the adapter returns `[]` and the agent runs on Tsenta + LinkedIn as before, so the
hourly Cloud Run agent stays fully autonomous.

**`INDEED_MAX_AGE_DAYS` (default 30) matters more here than anywhere else.** Indeed
returns postings far outside Tsenta's window — in the first real sample, **11 of 18
rows were older than 30 days**, some by five months. Those are almost all filled.

Known rough edges:

- `to.indeed.com` URLs are **not stable** — the same job returns a different short
  link on each API call, so url-based dedup can admit a duplicate. The state layer's
  `company::title` fingerprint is the real backstop.
- **Applying to an Indeed URL is unproven.** Tsenta can't read those pages, so
  `apply-to-job(url=...)` may fail even though Gate 2 scores the job fine.
- Indeed surfaces more staffing vendors; `Tekfortune`, `Rad Hires`, `AAA Global Tech`,
  `Gallega Software` and `CPC Technologies` were added to `STAFFING_COMPANIES` from
  the first sample alone. Expect to keep adding.

### Salary floor — one flat number everywhere

`MIN_SALARY = 140000` applies to every posting regardless of location (requested
2026-08-13). New York, Plano and remote are all judged against the same $140,000.

A per-state cost-of-living adjustment is **built but switched off**
(`SALARY_LOCATION_ADJUST = False`). It computes:

```
floor(job) = max(MIN_SALARY, SALARY_BASELINE * location_index)
```

where each index is that metro's break-even base against the candidate's Maryland
package after federal + FICA + state + local tax and rent. Turning it on
(`SALARY_LOCATION_ADJUST=1`) would produce $143,100 for Reston, $156,600 for Boston,
$163,350 for Jersey City, $184,950 for New York and $195,750 for San Francisco, while
leaving cheap metros at the $140,000 floor — the index can only ever raise the bar.

The argument for it, if it's ever wanted back: Oracle's real "$40,000 – $140,000" New
York posting clears a flat bar on a ceiling almost nobody is paid.

Mechanics, should it be re-enabled:

- Location resolution **reuses `_city_key()` / `_ats_state()`**, so `"Jersey City, NJ"`,
  `"New York City Metropolitan Area"` and `"US-NY-New York"` all resolve identically.
- **City beats state** where state granularity is wrong — NYC vs upstate New York,
  Philadelphia's city wage tax vs the rest of Pennsylvania.
- **Multi-location postings take the LOWEST index**, matching `is_in_region()`'s `any()`
  semantics. A job listing both New York and Tampa is judged at Tampa's floor.
- **Remote uses the flat floor deliberately** — a remote role can be worked from the
  current low-cost metro, which is the best outcome available.
- Gate 2 receives the resolved figure per job as `minimum_acceptable_base_usd`, so the
  scorer and the rule filter are never working from different numbers.
- `SALARY_LOCATION_ADJUST=0` restores a flat national floor.

`test_salary.py` covers this offline (`.venv/bin/python test_salary.py`).

## Running it

```bash
./dev.sh gate1     # no auth needed — sanity check
./dev.sh dry       # full pipeline, scores and ranks, submits nothing
./dev.sh serve     # service on :8080, then: curl -XPOST 'localhost:8080/run?n=5&dry=1'
./dev.sh state     # what it has recorded
```

## Going live

Live submission is deliberately hard to trigger — it needs **both**
`LIVE_APPLY=1` in the environment **and** `?dry=0` on the request. Watch several
dry runs first and read the picks. `DAILY_CAP` is set to 20 here rather than
upstream's 100.

## Deploying to Cloud Run (later)

```bash
gcloud run deploy argos-panoptes --source . --region us-central1 --project <id>
```

Cloud Run needs `MCP_AUTH_MODE=secret`, a `tsenta-refresh-token` secret holding
the token bundle from `.tsenta_token.json`, and `AGENT_STATE_BUCKET` pointing at
a GCS bucket for state. Get it working locally first.

## Notes on the code

- `profile.py` shadows the Python stdlib `profile` module. Harmless because the
  repo directory wins on `sys.path`, but it means you must run from the repo root.
- `test_gate1.py` / `test_pipeline.py` are live integration scripts, not unit
  tests — they open a Tsenta session and will fail without OAuth.
- The LinkedIn adapter scrapes the guest jobs endpoint by regex. It works today
  (18 jobs), but it's unauthenticated scraping — expect it to break when the
  markup changes, and be aware it sits outside LinkedIn's terms of service. The
  GitHub board feeds are plain JSON and much more stable.
