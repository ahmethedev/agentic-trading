#!/usr/bin/env bash
# Live view of the order path, for supervising a live entry.
#
# Shows the current worker run, what the gate last decided, and every row the
# chain produces: intent -> order -> fill -> position -> protection.
# Read-only; safe to run alongside the worker.
#
#   ./scripts/db-tunnel.sh up
#   ./scripts/watch_entry.sh            # refresh every 5s
#   ./scripts/watch_entry.sh 15         # refresh every 15s
#   RUN_ID=388 ./scripts/watch_entry.sh # pin to one run
#
# Only worker runs are considered: the worker stamps code_version, the pytest
# fixtures do not, so a test suite running against the same database cannot
# hijack the view.
set -euo pipefail
cd "$(dirname "$0")/.."
INTERVAL="${1:-5}"
[ -f .env ] && export "$(grep -E '^DATABASE_URL' .env | xargs)"
: "${DATABASE_URL:?DATABASE_URL not set (is .env present?)}"
export PGOPTIONS='-c search_path=at,public'
RUN_SQL="SELECT coalesce(${RUN_ID:-NULL}, (SELECT max(run_id) FROM runs
         WHERE code_version IS NOT NULL AND stopped_at IS NULL))"

while true; do
  clear
  printf '\033[1m  supervised entry — %s\033[0m\n' "$(date -u '+%Y-%m-%d %H:%M:%SZ')"
  psql "$DATABASE_URL" -X -q -v run_sql="$RUN_SQL" <<SQL
\pset border 2
\set r '($RUN_SQL)'

\echo '\n── run ─────────────────────────────────────────────────────────────'
SELECT run_id, mode, started_at,
       coalesce(notes::jsonb->>'max_entries_per_run','–') AS entry_budget,
       (SELECT count(*) FROM intents i
          WHERE i.run_id = r.run_id AND i.side='buy') AS entries_used
FROM runs r WHERE run_id = :r;

\echo '── last decision per instrument ────────────────────────────────────'
SELECT DISTINCT ON (inst_id) inst_id, action, stage_reached,
       array_to_string(reason_codes, ',') AS why, decided_at
FROM decisions WHERE run_id = :r ORDER BY inst_id, decided_at DESC;

\echo '── intents ─────────────────────────────────────────────────────────'
SELECT intent_id, inst_id, status, qty_requested, entry_reference,
       structural_stop, created_at
FROM intents WHERE run_id = :r ORDER BY intent_id DESC LIMIT 5;

\echo '── orders ──────────────────────────────────────────────────────────'
SELECT client_order_id, purpose, status, qty_requested, qty_filled, avg_px,
       algo_id, terminal_at
FROM orders WHERE run_id = :r ORDER BY created_at DESC LIMIT 6;

\echo '── fills ───────────────────────────────────────────────────────────'
SELECT fill_id, client_order_id, side, px, qty, fee, fee_ccy, ts
FROM fills WHERE run_id = :r ORDER BY ts DESC LIMIT 6;

\echo '── open positions (any run) ────────────────────────────────────────'
SELECT position_id, inst_id, status, qty_open, avg_entry_px, current_stop_px,
       realized_pnl, opened_at
FROM positions WHERE status <> 'CLOSED' ORDER BY position_id DESC;

\echo '── ops events (warn/error, last hour) ──────────────────────────────'
SELECT ts, severity, kind, left(detail::text, 88) AS detail
FROM ops_events
WHERE severity IN ('warn','error') AND ts > now() - interval '1 hour'
ORDER BY ts DESC LIMIT 8;
SQL
  printf '\n  refreshing every %ss — Ctrl-C to stop\n' "$INTERVAL"
  sleep "$INTERVAL"
done
