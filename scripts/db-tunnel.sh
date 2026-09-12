#!/usr/bin/env bash
# SSH tunnels to the VPS-hosted services, both bound to 127.0.0.1 there:
#   5433 -> Postgres
#   8002 -> dashboard + API
# Neither is exposed publicly; they are reachable only through this tunnel.
set -euo pipefail
VPS="${VPS_HOST:-ahmet@38.242.243.245}"
LOCAL_PORT="${LOCAL_PORT:-5433}"
API_PORT="${API_PORT:-8002}"

case "${1:-up}" in
  up)
    if lsof -ti tcp:"$LOCAL_PORT" >/dev/null 2>&1; then
      echo "tunnel already up on :$LOCAL_PORT"; exit 0
    fi
    ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
        -L "${LOCAL_PORT}:127.0.0.1:5433" \
        -L "${API_PORT}:127.0.0.1:8002" "$VPS"
    echo "tunnel up: localhost:${LOCAL_PORT} -> db, localhost:${API_PORT} -> dashboard"
    ;;
  down)
    pkill -f "L ${LOCAL_PORT}:127.0.0.1:5433" 2>/dev/null || true
    echo "tunnel down"
    ;;
  status)
    lsof -ti tcp:"$LOCAL_PORT" >/dev/null 2>&1 && echo "up" || echo "down"
    ;;
esac
