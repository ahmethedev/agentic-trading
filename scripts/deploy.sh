#!/usr/bin/env bash
# Deploy worker + API to the VPS. Idempotent; safe to re-run.
#
# Layout created on the VPS:
#   ~/agentic-trade/docker-compose.yml   db + worker + api (one project)
#   ~/agentic-trade/app/                 synced source, build context
#   ~/agentic-trade/.env                 POSTGRES_PASSWORD
#   ~/agentic-trade/.env.app             OKX credentials + runtime settings
set -euo pipefail
VPS="${VPS_HOST:-ahmet@38.242.243.245}"
REMOTE="${REMOTE_DIR:-/home/ahmet/agentic-trade}"
cd "$(dirname "$0")/.."

echo "==> building dashboard"
(cd dashboard && npm run build >/dev/null)

echo "==> syncing source"
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
  --exclude 'vendor/atk/node_modules' --exclude 'dashboard/node_modules' \
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.ruff_cache' \
  --exclude '.env' --exclude '*.log' --exclude 'deploy' \
  ./ "$VPS:$REMOTE/app/"

echo "==> installing compose file"
scp -q deploy/compose.yml "$VPS:$REMOTE/docker-compose.yml"

echo "==> building and starting"
ssh "$VPS" "cd $REMOTE && docker compose up -d --build worker api"

echo "==> applying schema (idempotent)"
ssh "$VPS" "docker exec -i agentic-trade-db psql -U agentic -d agentic_trade -q" \
  < src/agentic_trade/db/schema.sql

echo "==> status"
ssh "$VPS" "docker ps --filter name=agentic-trade --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'"
