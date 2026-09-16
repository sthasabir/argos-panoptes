"""Candidate profile — the ground truth both gates score against.

Sourced from the candidate's resume.

NOTE: upstream was written for a new grad requiring H1B sponsorship. This
profile is an experienced IC with permanent work authorization, so the gates
read the flags below rather than assuming the new-grad case.
"""

CANDIDATE = {
    "name": "Jordan Rivera",
    "level": "senior_ic",            # experienced individual contributor, not new grad
    "years_experience": 7,
    "needs_sponsorship": False,       # U.S. Permanent Resident (Green Card)
    "work_authorization": "U.S. Permanent Resident (Green Card)",
    "locations_ok": ["Remote", "US"],
    "current_title": "Java Full Stack Developer",
    "education": "Bachelor's in Information Technology",
    "certifications": ["AWS Certified Developer – Associate",
                       "AWS Certified Cloud Practitioner"],
    "stack": [
        "Java", "Java 11", "Java 17", "Java 21", "J2EE", "Kotlin", "TypeScript",
        "JavaScript", "SQL", "Python",
        "Spring Boot", "Spring MVC", "Spring Cloud", "Spring Security", "Spring Data",
        "Spring AOP", "Hibernate", "JPA", "JDBC", "REST APIs", "GraphQL", "Microservices",
        "Angular", "React", "Redux", "HTML5", "CSS3", "Tailwind CSS", "Material UI",
        "AWS", "EC2", "S3", "Lambda", "ECS", "EKS", "DynamoDB", "Redshift", "Route 53",
        "Azure", "GCP", "Docker", "Kubernetes", "Jenkins", "Maven", "Gradle", "CI/CD",
        "Grafana", "Prometheus", "Terraform",
        "Oracle", "PL/SQL", "PostgreSQL", "MySQL", "MongoDB", "Cassandra", "Redis",
        "Apache Kafka",
        "JUnit", "Mockito", "Rest-Assured", "Selenium", "JMeter", "Jest", "TDD",
        "Agile", "Scrum", "Swagger", "Postman", "Git", "GitHub Copilot", "LLM",
    ],
    # role families in priority order (earlier = higher priority)
    "target_role_families": ["backend", "fullstack", "swe"],
    "avoid_role_types": ["help_desk", "desktop_support", "manual_qa", "it_support",
                         "sales", "people_management"],
}

# Companies to never apply to. Current employer first — an automated agent applying
# to your own employer is the one failure mode that is actively embarrassing.
# Matched case-insensitively against a normalized company name, so list the variants
# the feeds actually emit (Tsenta returns both "Meridian Financial" and bare "Meridian").
# Override with EXCLUDE_COMPANIES="acme|globex" in .env.
EXCLUDE_COMPANIES = [
    # --- current employer ---
    "meridian financial",
    "meridianfinancial",   # Tsenta emits this unspaced variant — do not remove
    "meridian",
    "meridian corp",

    # --- past employer ---
    # Kept deliberately broad; drop the bare entry if you want similarly-named
    # but unrelated companies back.
    "vantage capital",
    "vantage capital investments",
    "vantage",

    # --- never apply, by request ---
    "skyline it partners",
    "anchor mutual",
    "anchor mutual insurance",

    # --- past employer ---
    "cornerstone bank",
    "cornerstone bancorp",
]

# Staffing agencies, IT-services vendors and job aggregators. These place contractors
# at client sites or resell the same posting, so applying reaches a middleman rather
# than the employer — and the same underlying role often arrives twice under two
# different vendor names. Merged into EXCLUDE_COMPANIES below; drop an entry here to
# allow that firm back.
STAFFING_COMPANIES = [
    "jobgether", "photon", "eclerx", "apogee global rms", "apogee global",
    "ptma financial solutions", "ptma", "synechron", "cognizant", "infosys",
    "tata consultancy", "tcs", "capgemini", "accenture",
    "avance consulting", "htc global", "htc global services", "ntt data",
    "luxoft", "sigma software", "altimetrik", "zensar", "zensar technologies",
    "talenzaa", "softmetrix", "osi engineering", "brightvision", "daxwell",
    "collabera", "teksystems", "kforce", "randstad",
    "apex systems", "diverse lynx", "compunnel", "artech",
    "sunrise systems", "intellectt", "amtex", "vdart", "net2source", "iris software",
    "virtusa", "ust global", "mphasis", "lti", "ltimindtree", "birlasoft", "coforge",
    "persistent systems", "wipro", "hcl", "hcltech", "tech mahindra", "genpact",
    "epam", "globant", "thoughtworks", "wallstreetquants",
    # surfaced by the Indeed sample 2026-08-13 — vendors, not direct employers
    "tekfortune", "rad hires", "aaa global tech", "gallega software",
    "cpc technologies",
]

# Staffing firms allowed only for remote OR hybrid roles. Not in EXCLUDE_COMPANIES, so
# they pass the blocklist; gate1 drops them when the role is strictly onsite. A missing
# workplaceType still counts as failing — for these firms the condition has to be
# proven, not assumed.
STAFFING_REMOTE_ONLY = [
    "insight global", "robert half", "motion recruitment",
    "mastech", "mastech digital", "optomi",
]
# Workplace types acceptable from the firms above.
STAFFING_ALLOWED_WORKPLACE = {"REMOTE", "HYBRID"}

EXCLUDE_COMPANIES += STAFFING_COMPANIES

# Only apply to US-based or remote-US roles. Upstream had no location filter at all
# (its new-grad boards were US-only), and without this the feed happily returns roles
# in Bangalore, Pune, Nantes and Mississauga — a dry run put four of them in the top
# five picks. `locations_ok` above is descriptive; this is the flag that enforces it.
REQUIRE_US_LOCATION = True

# Narrow the US search to the East Coast, defined as the EASTERN TIME ZONE (by
# request, 2026-08-11). This is the broadest of the three readings of "East Coast":
# it takes the Atlantic seaboard and adds the inland ET states (OH, MI, IN, KY, TN,
# WV), so Columbus, Detroit, Nashville and Cincinnati are in scope alongside NYC,
# Boston, Philly, DC and Charlotte.
#
# States are approximated at whole-state granularity. Four ET states are actually
# split by the time-zone line (FL panhandle, western KY/TN, MI's western edge, most
# of IN's northwest corner) and are counted as in-region in full — a filter that
# argued about counties would drop real Nashville and Tampa roles to be pedantic
# about Pensacola.
# TURNED OFF 2026-08-12, one day after it went in: with the Tsenta plan upgraded to
# 1500 applications/month the constraint became supply, not credits, and the filter was
# dropping ~190 of every ~690 postings. The search is US-wide again (REQUIRE_US_LOCATION
# above still applies). Everything below is left intact and tested — flip this back to
# True, or set REQUIRE_REGION=1 in the environment, to restore the East Coast search.
REQUIRE_REGION = False
REGION_NAME = "Eastern time zone"
REGION_STATES = {
    "ct", "de", "dc", "fl", "ga", "in", "ky", "me", "md", "ma", "mi", "nh", "nj",
    "ny", "nc", "oh", "pa", "ri", "sc", "tn", "vt", "va", "wv",
}

# Whether a posting that says "Remote" (with no state that places it elsewhere)
# clears the region filter. True keeps the funnel usable: a large slice of the feed
# is remote-tagged, and a US-remote role is workable from the East Coast.
#
# This governs the LOCATION TEXT, not the workplaceType field. A job listed in
# "Austin, TX" is dropped even when workplaceType is REMOTE — the posting named a
# metro outside the region, and those listings routinely mean "remote, near our
# office". Set False to require an explicit in-region location on every job.
REGION_ALLOW_REMOTE = True

# Absolute salary floor in USD — never go below this anywhere, by explicit request
# (2026-08-13), including in low-cost metros like Plano or Tampa. 0 disables the filter.
#
# Compared against the TOP of the posted range, not the bottom: bands are wide
# ("$55,000 - $152,375" is a real posting in this feed) and the low end usually
# reflects a cheaper metro or a less senior hire. A job is dropped only when even its
# maximum falls below the floor — i.e. it provably cannot pay enough. Postings with no
# salary data at all are KEPT; roughly half the feed omits it, and dropping those would
# halve the funnel to filter on data that isn't there.
MIN_SALARY = 140000

# ---------------------------------------------------------------- location adjustment
# A flat national floor is wrong in both directions: the same standard of living costs
# ~$120k in Plano and ~$185k in Manhattan. These indices are each metro's break-even
# base divided by SALARY_BASELINE, derived from a full federal + FICA + state + local
# + rent model against the candidate's current package.
#
# The floor for a job is  max(MIN_SALARY, SALARY_BASELINE * index)  — so the index can
# only ever RAISE the bar. A cheap metro does not buy a discount; $140k is the floor in
# Plano exactly as it is in Baltimore.
SALARY_BASELINE = 135000          # the Maryland package the indices are relative to

# state -> cost index. Absent state = 1.0 (no adjustment).
SALARY_LOCATION_INDEX = {
    "tx": 0.89, "tn": 0.90, "fl": 0.92, "oh": 0.93, "nc": 0.94,
    "ga": 0.97, "wa": 0.97, "md": 1.00, "il": 1.01, "va": 1.06,
    "ma": 1.16, "nj": 1.21, "ny": 1.37, "ca": 1.45, "dc": 1.10,
}

# City overrides, because state granularity is badly wrong in a few places: NYC vs
# upstate New York, and Philadelphia's city wage tax vs the rest of Pennsylvania.
SALARY_LOCATION_INDEX_CITY = {
    "new york": 1.37, "nyc": 1.37, "brooklyn": 1.37, "manhattan": 1.37,
    "queens": 1.37, "jersey city": 1.21, "newark": 1.18, "boston": 1.16,
    "cambridge": 1.16, "philadelphia": 1.06, "san francisco": 1.45,
    "san jose": 1.45, "palo alto": 1.45, "mountain view": 1.45,
    "sunnyvale": 1.45, "seattle": 0.97,
}

# OFF (2026-08-13, final). Measured against a live 646-job feed, the per-metro floors
# changed the outcome for TWO jobs — 95 passed with them, 97 without. That is a lot of
# machinery for 0.3% of the feed, so the rule is a flat MIN_SALARY everywhere. The
# tables above and the resolution logic in gate1 stay intact and tested; flip this to
# True to bring them back.
SALARY_LOCATION_ADJUST = False

# Full-time permanent roles only — no contract, contract-to-hire, part-time or
# temp. Postings that simply omit employmentType are KEPT: ~40% of the feed leaves
# it null, and dropping those would gut the funnel to enforce a field that isn't there.
REQUIRE_FULL_TIME = True

# All workplace types are acceptable — remote, onsite and hybrid.
#
# This briefly held {"REMOTE","HYBRID"} as a proxy for "no in-person interview", since
# no feed exposes interview format. That was reversed on request: onsite roles are
# fine. Interview logistics get handled with the recruiter, not by a filter.
# Narrow this set to re-enable the restriction; empty or all-three disables it.
# Remote anywhere in the US, PLUS hybrid within commuting distance of Example City, MD
# (requested 2026-08-17). Onsite is still out.
#
# Both types are listed here because this set is ALSO sent to the server as a query
# filter — asking for REMOTE only would mean hybrid Virginia roles never reach us to be
# judged. The commute restriction is applied locally, in workplace_ok().
#
# A MISSING workplaceType still passes: roughly a third of the feed omits the field, and
# rejecting those would gut the funnel over data that isn't there.
ALLOWED_WORKPLACE = {"REMOTE", "HYBRID"}

# Hybrid is only worth it where the office is commutable from Example City, MD. Northern
# Virginia is already 70-90 minutes each way; anything further is not a real option.
# Empty set = hybrid allowed anywhere ALLOWED_WORKPLACE permits it.
HYBRID_STATES = {"va", "md", "dc", "de"}

# Philadelphia added 2026-08-17 as CITIES, not as the state of Pennsylvania: Philly is
# ~90 minutes from Example City but Pittsburgh is roughly four hours, and a state-level
# entry cannot tell them apart. These are the Philadelphia-metro entries that exist in
# gate1's city table.
HYBRID_CITIES = {"philadelphia", "malvern", "oaks"}

# Server-side seniority band: mid-level through senior, by request. Anything at lead
# level or above is excluded separately by TITLE_LEAD / TITLE_MANAGEMENT in gate1.py,
# so the target window is MID_LEVEL..EXPERIENCED with a hard ceiling below Lead/VP.
JOB_TYPES = {"MID_LEVEL", "EXPERIENCED"}

# ---------------------------------------------------------------- hold for review
# What we tell employers we want, mirroring `expectedAnnualSalary` in the Tsenta
# profile. Kept here so the agent can reason about it; Tsenta holds the value that
# actually reaches an ATS form.
STATED_ASK = 145000

# EVERY posted salary is treated as BASE, by explicit decision (2026-08-14). Some
# postings publish OTE or total compensation instead, which would make a percentile of
# that range an inflated base figure — that is accepted and deliberately NOT detected.
# Do not add OTE/total-comp handling back without asking; its absence is a choice.
#
# Where in a posting's published band to aim when the band pays above STATED_ASK.
# 0.70 = 70th percentile, not the midpoint: a posted range spans the whole level, and a
# 7-year IC with a matching stack is not a bottom-half hire. Across this candidate's own
# feed the 70th percentile beat the midpoint by ~$11,600 per posting. Above ~0.80 you
# start reading as out-of-band, so this is the assertive-but-credible end.
ASK_PERCENTILE = 0.75

# Don't auto-apply when the posting's own FLOOR is comfortably above what we're asking
# for. A job posted at $160,000-$180,000 while the profile says $140,000 means naming a
# number $20,000 below their published minimum — and a stated figure is a ceiling on the
# negotiation, not a floor. These are held for review instead, so the ask can be raised
# on that specific application first.
#
# Only fires when the posting publishes a real floor; unpriced jobs apply as normal.
# OFF (2026-08-14, final). Per-job asking is abandoned: expectedAnnualSalary is a single
# account-level box and Tsenta fills ATS forms minutes after the apply call, so setting
# it per job races the form-fill — an earlier application can inherit a later job's
# number. Rather than keep a mechanism that needs a human step per job and still cannot
# be verified, every application now goes out at the flat STATED_ASK.
#
# suggested_ask() in gate1 is left intact but is no longer used for anything.
HOLD_IF_UNDERASKING = False
# No tolerance (2026-08-14): hold ANY posting whose computed ask beats the $140,000
# default, however small the gap. Measured over 103 live postings, a $10,000 margin
# saved 8 reviews but silently gave up $41,000 of asking power; at zero, nothing is
# given up. A job computing exactly $140,000 still auto-applies, since the default is
# already the right answer for it.
HOLD_ASK_MARGIN = 0

# Max applications to the same employer per rolling window. Without this the agent
# sent 9 applications to PNC in two days — every one auto-generated, all landing in
# the same ATS queue.
MAX_PER_COMPANY = 2
MAX_PER_COMPANY_DAYS = 7

# Seniority band we want. Upstream hard-dropped senior titles; for this profile
# they are the target. People-management tracks are still excluded — this is an
# IC search.
SENIORITY = {
    # Target band: mid-level to senior IC. Nothing at lead level or above, and no
    # "Engineer II" — that rung sits below the intended band.
    "accept_titles": ["senior", "sr", "iii", "iv", "mid level", "mid-level"],
    # Hard no: lead-and-above (by request), plus management/executive and anything
    # below this candidate's experience level. Note this does cost some genuine senior
    # IC matches — at banks and large enterprises "Lead Software Engineer", "Staff" and
    # "Principal" are frequently hands-on IC bands rather than management.
    "reject_titles": ["lead", "tech lead", "team lead", "leader",
                      "staff", "principal", "architect", "distinguished", "fellow",
                      "manager", "director", "head of", "chief", "president",
                      "vp", "svp", "evp", "vice president", "avp", "assistant vice president",
                      "engineer ii", "developer ii", "software engineer ii",
                      "intern", "internship", "co-op", "apprentice"],
    # drop a posting only if it demands MORE than this many years
    "max_years_required": 8,
    # drop a posting if it is clearly aimed at brand-new grads
    "reject_entry_level": True,
}

# Tsenta roleFamily / title → our normalized family
ROLE_FAMILY_MAP = {
    "SOFTWARE_ENGINEERING": "swe",
    "MACHINE_LEARNING": "ai_ml",
    "DATA_SCIENCE": "ai_ml",
    "AI": "ai_ml",
    "FRONTEND": "fullstack",
    "FULLSTACK": "fullstack",
    "FULL_STACK": "fullstack",
    "BACKEND": "backend",
    "DEVOPS": "backend",
    "PLATFORM": "backend",
}

ROLE_FAMILY_PRIORITY = {"backend": 0, "fullstack": 1, "swe": 2, "ai_ml": 3, "other": 9}
