<div align="center">

<img src="assets/logo.png" alt="Argos Panoptes" width="560"/>

**An autonomous, multi source job application agent that watches every board with a hundred eyes, filters with a two gate pipeline, and applies to genuine fits around the clock.**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Google Cloud Run](https://img.shields.io/badge/Cloud_Run-serverless-4285F4?logo=googlecloud&logoColor=white)
![Vertex AI](https://img.shields.io/badge/Vertex_AI-Gemini-4285F4?logo=googlegemini&logoColor=white)
![MCP](https://img.shields.io/badge/Protocol-MCP-6E56CF)
![Cloud Scheduler](https://img.shields.io/badge/Cloud_Scheduler-hourly-4285F4?logo=googlecloud&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-E0A83A)

</div>

---

## Overview

Argos Panoptes named after the hundred eyed watchman of Greek myth is a serverless agent that runs every hour, pulls fresh postings from several job sources, filters them through a rules gate and a model gate, removes duplicates across sources, and submits applications only to roles that are a genuine fit. It runs entirely in the cloud so it works with the laptop closed.

The design goal is capture, not spray. The agent aims to catch essentially every good new grad role that exists while refusing to apply to anything that does not clear a real quality bar.

## Architecture

```mermaid
flowchart TD
    SCH[Cloud Scheduler, hourly] --> RUN[Cloud Run service]
    subgraph Sources
        TS[Platform MCP feed]
        GH[GitHub new grad boards]
        LI[LinkedIn last hour]
    end
    RUN --> TS
    RUN --> GH
    RUN --> LI
    TS --> NORM[Normalize to one job shape]
    GH --> NORM
    LI --> NORM
    NORM --> G1[Gate 1, rule filter]
    G1 --> JD[Fetch full job descriptions]
    JD --> G2[Gate 2, Gemini fit score]
    G2 --> DED[Dedup by id and fingerprint]
    DED --> APP[Apply via MCP]
    APP --> ST[(GCS state)]
    SEC[(Secret Manager token)] -.-> RUN
```

## How one application flows

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant R as Cloud Run
    participant M as Platform MCP
    participant G as Gemini on Vertex
    participant St as State on GCS

    S->>R: POST /run (hourly trigger)
    R->>M: get recommendations and external sources
    R->>R: Gate 1 rule filter
    R->>M: fetch full job descriptions
    R->>G: score fit 0 to 10 as structured JSON
    G-->>R: eligible and fit_score
    R->>St: dedup check by id and fingerprint
    R->>M: apply to the freshest good fits
    M-->>R: application confirmed
    R->>St: record applied
```

## Job sources

| Source | What it adds | Auth |
| --- | --- | --- |
| Platform MCP feed | The vendor recommendation feed | OAuth |
| SimplifyJobs, vanshb03, cvrve | Structured new grad boards with real ATS apply URLs | None |
| LinkedIn last hour | The freshest postings, date sorted | None |

Every source is normalized into one common job shape on ingest, so a single pipeline, a single filter, and a single dedup layer serve all of them.

## The two gate filter

**Gate 1** is a cheap rule pass with zero token cost. It fast fails senior and staff titles, internships, explicit no sponsorship or citizenship only roles, basic IT and non engineering roles, and anything that does not read as a software role.

**Gate 2** is a Gemini model on Vertex AI that scores each survivor from 0 to 10 on genuine fit and re checks the dealbreakers against the full job description. Only eligible roles at or above the score threshold are kept, ranked newest first.

## Stack

| Layer | Technology |
| --- | --- |
| Runtime | Python on Cloud Run |
| Schedule | Cloud Scheduler, hourly |
| Model | Gemini on Vertex AI |
| Integration | Model Context Protocol (MCP) over OAuth |
| Secrets | Secret Manager with token write back |
| State | Google Cloud Storage |

## Deploy

```bash
gcloud run deploy argos-panoptes \
  --source . \
  --region us-central1 \
  --project <your-project>
```

Runtime configuration is environment driven, including the source list, the recency window, the score threshold, and the daily cap. See `DECISIONS.md` for the reasoning behind each architectural choice.

## Project layout

| File | Role |
| --- | --- |
| `main.py` | FastAPI entrypoint, the `/run` and `/state` endpoints |
| `pipeline.py` | Orchestration, pull to filter to apply |
| `sources.py` | External source adapters, normalized on ingest |
| `gate1.py` | Rule based hard exclusions |
| `gate2.py` | Gemini fit scorer |
| `mcp_client.py` | MCP client wrapper and token handling |
| `state.py` | Dedup and daily cap state |
| `profile.py` | Candidate profile and role priorities |

## The Swarm

A stylized rendering of the agent as a recursive swarm. Artistic, not the literal architecture.

<div align="center">
<img src="assets/swarm.png" alt="The Swarm" width="360"/>
</div>

## License

MIT. See [LICENSE](LICENSE).
