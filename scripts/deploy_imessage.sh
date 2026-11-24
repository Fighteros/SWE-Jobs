#!/usr/bin/env bash
set -euo pipefail

# Never use the default Compose project or a main checkout.
cd "${1:?set the separate iMessage checkout path}"
test "$(git branch --show-current)" = imessage
export STACK=swejobs-imessage DELIVERY_CHANNEL=imessage APP_PORT=8001
compose=(docker compose --project-name swejobs-imessage --profile imessage)

# Fresh databases run all migrations on init; existing ones need this one
# before the new backend starts. It is safe to apply again.
"${compose[@]}" up -d --wait --wait-timeout 120 db
"${compose[@]}" exec -T db sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
    < postgres/migrations/010_imessage_inbound.sql

if ! "${compose[@]}" up -d --build --wait --wait-timeout 120; then
    "${compose[@]}" ps
    "${compose[@]}" logs --tail 50 backend imessage-sidecar
    exit 1
fi
"${compose[@]}" exec -T backend python -c '
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5) as response:
    if json.load(response).get("channel") != "imessage":
        raise SystemExit("backend is not in iMessage mode")
'
