# Snapshot of the code running in revision argos-panoptes-00048-9mv

Image `sha256:ffb04e8c...`, built 2026-08-19 13:01 (revision 00043-48p; 00044-00048
are config-only changes that reuse the same image).

These three files are the ONLY ones that differ from the working tree as of
2026-08-21 — gate1.py, gate2.py, profile.py, main.py and mcp_client.py are unchanged
and already live.

## To roll back

Do NOT restore these files and redeploy — that rebuilds and takes minutes. Cloud Run
keeps every revision and its image, so shifting traffic back is instant:

    gcloud run services update-traffic argos-panoptes \
      --region us-central1 --project argos-panoptes-zeykbi \
      --to-revisions=argos-panoptes-00048-9mv=100

Verify with:

    gcloud run services describe argos-panoptes --region us-central1 \
      --format='value(status.traffic[0].revisionName)'

These files exist so the source can be reconstructed if the revision is ever deleted.
