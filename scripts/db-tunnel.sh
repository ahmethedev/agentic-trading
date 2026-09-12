#!/usr/bin/env bash
# SSH tunnel to the VPS-hosted agentic-trade Postgres (bound to 127.0.0.1:5433 there).
# The DB is never exposed publicly; local dev reaches it only through this tunnel.
set -euo pipefail
VPS="${VPS_HOST:-ahmet@38.242.243.245}"
LOCAL_PORT="${LOCAL_PORT:-5433}"

case "${1:-up}" in
  up)
    if lsof -ti tcp:"$LOCAL_PORT" >/dev/null 2>&1; then
      echo "tunnel already up on :$LOCAL_PORT"; exit 0
    fi
    ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
        -L "${LOCAL_PORT}:127.0.0.1:5433" "$VPS"
    echo "tunnel up: localhost:${LOCAL_PORT} -> ${VPS}:5433"
    ;;
  down)
    pkill -f "L ${LOCAL_PORT}:127.0.0.1:5433" 2>/dev/null || true
    echo "tunnel down"
    ;;
  status)
    lsof -ti tcp:"$LOCAL_PORT" >/dev/null 2>&1 && echo "up" || echo "down"
    ;;
esac
