#!/usr/bin/env bash
# Local dev helper. Usage:  ./dev.sh <command>
#
#   ./dev.sh sources    — pull live jobs from GitHub + LinkedIn (no auth needed)
#   ./dev.sh gate1      — sources + rule filter, offline (no auth needed)
#   ./dev.sh auth       — one-time interactive Tsenta OAuth (opens a browser)
#   ./dev.sh dry        — full pipeline, dry run (needs Tsenta + Vertex)
#   ./dev.sh serve      — run the FastAPI service on :8080
#   ./dev.sh state      — print the local application state
#
# Deployed (Cloud Run):
#   ./dev.sh cloud      — deployment status: service, scheduler, last runs
#   ./dev.sh logs       — recent picks and errors from Cloud Run
#   ./dev.sh cloudstate — everything the deployed agent has recorded
#   ./dev.sh trigger    — run the hourly job right now, don't wait for the cron
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=argos-panoptes-zeykbi
REGION=us-central1
SERVICE=argos-panoptes
JOB=argos-panoptes-hourly
BUCKET=gs://argos-panoptes-zeykbi-state

[ -f .env ] && source .env
PY=.venv/bin/python

case "${1:-help}" in
  sources) $PY sources.py ;;
  gate1)   $PY tools/offline_check.py ;;
  auth)    $PY mcp_client.py ;;
  dry)     $PY -c "import asyncio,json,pipeline; print(json.dumps(asyncio.run(pipeline.run(n=int('${PER_RUN:-5}'), dry=True)), indent=2))" ;;
  serve)   .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8080 --reload ;;
  state)   $PY -c "import json,state; print(json.dumps(state.load(), indent=2))" ;;

  cloud)
    echo "--- service ---"
    gcloud run services describe $SERVICE --region=$REGION --project=$PROJECT \
      --format="table[box](status.url,status.latestReadyRevisionName)"
    echo "--- LIVE_APPLY (0 = submits nothing) ---"
    gcloud run services describe $SERVICE --region=$REGION --project=$PROJECT \
      --format="value(spec.template.spec.containers[0].env.filter(\"name:LIVE_APPLY\").extract(value))"
    echo "--- scheduler (empty status = healthy) ---"
    gcloud scheduler jobs describe $JOB --location=$REGION --project=$PROJECT \
      --format="table[box](state,schedule,scheduleTime,status.code)"
    echo "--- last 5 runs ---"
    gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE AND textPayload:\"POST /run\"" \
      --project=$PROJECT --limit=5 --format="value(timestamp,textPayload)" --freshness=1d
    ;;
  logs)
    gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE" \
      --project=$PROJECT --limit=60 --format="value(timestamp,textPayload)" --freshness=1d \
      | grep -Ei "RUN RESULT|DRY \[|APPLIED \[|error|failed" | head -30
    ;;
  cloudstate) gcloud storage cat $BUCKET/tsenta_agent_state.json ;;
  trigger)    gcloud scheduler jobs run $JOB --location=$REGION --project=$PROJECT && echo "triggered — check ./dev.sh logs in ~60s" ;;

  *)       sed -n '2,16p' "$0" ;;
esac
