# Architecture Decision Record

A concise record of the significant choices behind Argos Panoptes and the reasoning at the time each was made. Newest decisions are appended at the end.

## 1. Integrate through the official MCP, not the web dashboard

Context: applications are submitted through a third party job platform that exposes both a web dashboard and an official Model Context Protocol (MCP) server over OAuth.

Decision: integrate exclusively through the official MCP. Do not drive the web dashboard with a headless browser.

Reasoning: the MCP is the sanctioned programmatic path. It is stable across user interface changes and stays within the platform terms of service. Browser automation is fragile and violates those terms.

## 2. Score fit with Gemini on Vertex AI

Decision: use Gemini (Flash tier) on Vertex AI as the fit scorer, with the exact model selectable by environment variable.

Reasoning: the Flash tier is fast, low cost, and returns reliable structured JSON. It is a first party Vertex model, so it runs on existing cloud credit with no marketplace enablement and no separate API key. The task is a calibrated zero to ten judgment, which does not require a frontier model.

## 3. Two gate filter, rules before model

Decision: run a cheap rule based Gate 1 before any model call, then a model based Gate 2 only on the survivors.

Reasoning: Gate 1 fast fails obvious mismatches (senior level, internships, explicit no sponsorship, non engineering roles) at zero token cost. Gate 2 spends model budget only on plausible candidates. The result is lower cost and higher precision.

## 4. Serverless schedule on Cloud Run and Cloud Scheduler

Decision: deploy as a Cloud Run service triggered hourly by Cloud Scheduler.

Reasoning: the pipeline is a short periodic job. Serverless keeps it running around the clock with the laptop off, scales to zero between runs, and costs almost nothing.

## 5. Store the OAuth token in Secret Manager with write back

Decision: keep the OAuth token bundle in Secret Manager. Read it at the start of each run and write the rotated token back as a new secret version.

Reasoning: the secret never lives in the repository, is encrypted at rest, is gated by IAM to the service identity, and every rotation is versioned and auditable.

## 6. Deduplicate on a normalized fingerprint, not only the platform id

Decision: track applications by both the platform job id and a normalized company plus title fingerprint.

Reasoning: the platform rotates job ids for the same posting, and the same role surfaces across multiple sources with different ids and slightly different punctuation. A normalized fingerprint is the only stable cross source key that reliably prevents duplicate applications.

## 7. Merge external job sources into one pipeline

Decision: pull additional postings from public new grad job boards and a live search feed, normalize them into the platform job shape on ingest, and run them through the same gates and apply path.

Reasoning: the platform feed alone is a limited pool that drains quickly. Owned sources widen coverage. Normalizing at the boundary means one pipeline, one filter, and one dedup layer serve every source.

## 8. Refresh the access token with a browser standard client

Decision: mint a fresh short lived access token before each run using a standard browser client, rather than relying on the SDK default refresh.

Reasoning: the token endpoint expects a standard browser client. Performing the refresh explicitly makes headless scheduled runs reliable.

## 9. Order candidates by recency before fit

Decision: bucket survivors by posting day, newest first, then rank by fit score within each day.

Reasoning: fresh postings close quickly. Applying to the newest roles first improves the odds of reaching a human before a posting fills.
