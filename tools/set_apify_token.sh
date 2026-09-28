#!/usr/bin/env bash
# Set the Apify API token in .env (local) and optionally in Google Secret Manager +
# Cloud Run (deployed). Prompts for the token silently so it never lands in shell
# history, and never echoes it back.
#
#   ./tools/set_apify_token.sh            # local .env only
#   ./tools/set_apify_token.sh --cloud    # also push to Secret Manager + Cloud Run
#
# Get the token from: Apify console -> Settings -> API & Integrations.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=".env"
PROJECT="argos-panoptes-zeykbi"
REGION="us-central1"
SERVICE="argos-panoptes"
SECRET="apify-token"

# -- read the token without echoing it and without putting it in history -------------
read -rsp "Paste your Apify API token (input hidden): " APIFY_TOKEN
echo

if [ -z "${APIFY_TOKEN}" ]; then
  echo "No token entered. Nothing changed." >&2
  exit 1
fi

# Validate HARD, do not just warn. The prompt hides input, so a mis-paste is invisible:
# on 2026-08-21 a gcloud error message got pasted in and was saved as the token, which
# then broke every shell that sourced .env (exit 126, trying to run "(gcloud...)").
case "$APIFY_TOKEN" in
  apify_api_*) ;;
  *) echo "ERROR: that does not look like an Apify token (must start with 'apify_api_')." >&2
     echo "       Got ${#APIFY_TOKEN} characters starting with: ${APIFY_TOKEN:0:8}" >&2
     echo "       Nothing was changed." >&2
     exit 1 ;;
esac
case "$APIFY_TOKEN" in
  *[[:space:]]*) echo "ERROR: token contains whitespace - that is a mis-paste. Nothing changed." >&2
     exit 1 ;;
esac
echo "Token looks valid: ${#APIFY_TOKEN} chars, starts ${APIFY_TOKEN:0:12}..."

# -- write into .env, replacing any existing line ------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  echo "$ENV_FILE not found (run from the repo root)." >&2
  exit 1
fi

cp "$ENV_FILE" "$ENV_FILE.bak"

if grep -q '^export APIFY_TOKEN=' "$ENV_FILE"; then
  # Rewrite in python rather than sed -i: the token can contain characters sed would
  # treat as delimiters or backreferences.
  APIFY_TOKEN="$APIFY_TOKEN" python3 - "$ENV_FILE" <<'PY'
import os, sys
path = sys.argv[1]
tok = os.environ["APIFY_TOKEN"]
lines = open(path).read().splitlines(keepends=True)
for i, l in enumerate(lines):
    if l.startswith("export APIFY_TOKEN="):
        lines[i] = f"export APIFY_TOKEN={tok}\n"
open(path, "w").writelines(lines)
PY
else
  printf '\nexport APIFY_TOKEN=%s\n' "$APIFY_TOKEN" >> "$ENV_FILE"
fi

echo "Wrote APIFY_TOKEN to $ENV_FILE (backup at $ENV_FILE.bak)"

# -- verify it actually works before declaring success -------------------------------
echo -n "Checking the token against Apify... "
if curl -sS -f -o /dev/null -H "Authorization: Bearer $APIFY_TOKEN" \
     "https://api.apify.com/v2/users/me"; then
  echo "OK"
else
  echo "FAILED - Apify rejected it. The token is saved; fix it and re-run."
fi

# -- optional: push to Secret Manager and Cloud Run ----------------------------------
if [ "${1:-}" = "--cloud" ]; then
  echo "Pushing to Secret Manager..."
  if gcloud secrets describe "$SECRET" --project "$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$APIFY_TOKEN" | gcloud secrets versions add "$SECRET" \
      --data-file=- --project "$PROJECT"
  else
    printf '%s' "$APIFY_TOKEN" | gcloud secrets create "$SECRET" \
      --data-file=- --project "$PROJECT"
  fi
  echo "Wiring the secret into Cloud Run..."
  gcloud run services update "$SERVICE" \
    --region "$REGION" --project "$PROJECT" \
    --update-secrets "APIFY_TOKEN=${SECRET}:latest" --quiet
  echo "Done. The deployed service now reads APIFY_TOKEN from Secret Manager."
fi

unset APIFY_TOKEN
echo
echo "Next:  set -a && source .env && set +a"
echo "Then:  .venv/bin/python -c 'import sources; print(len(sources.from_apify()))'"
