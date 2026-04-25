#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# rebuild_and_check.sh — post-backfill quality-of-life fixes.
#
#   1. Rebuild the unified_data_inventory cache (currently shows 39M
#      bars but reality is 196M — 5x stale).
#   2. Re-run the readiness verdict + queue snapshot in one shot.
#
# GOOGL's two stale timeframes (1-min, 15-min) are already in the
# in-flight smart-backfill queue (880 × 1-min + 279 × 15-min requests),
# so we don't need to queue more — we just wait for the queue to drain.
# ---------------------------------------------------------------------------
set -u
API="${API:-http://localhost:8001}"
bold() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }

bold "1. Rebuild unified_data_inventory (~30-60s on 196M-row collection)"
curl -fsS -X POST --max-time 600 "${API}/api/ib-collector/build-inventory" | jq -C '
  if has("by_bar_size") then
    {success, total_entries, unique_symbols,
     by_bar_size: [.by_bar_size[] | {bar_size: ._id, total_bars}]}
  else . end'

bold "2. Updated inventory summary (should now show ~196M total bars)"
curl -fsS --max-time 30 "${API}/api/ib-collector/inventory/summary" | jq -C '
  {
    total_entries, unique_symbols, backtestable, needs_backfill,
    by_bar_size: [.by_bar_size[] | {bar_size: ._id, total_bars}]
  }'

bold "3. Current readiness verdict + queue burndown"
curl -fsS --max-time 90 "${API}/api/backfill/readiness" | jq -C '
  {
    verdict, ready_to_train, summary,
    blockers,
    queue_pending: .checks.queue_drained.pending,
    queue_claimed: .checks.queue_drained.claimed,
    googl_status: (if .checks.critical_symbols_fresh.stale_symbols | index("GOOGL")
                   then "STILL_STALE"
                   else "FRESH"
                   end)
  }'

bold "DONE"
echo "
Watch the queue drain to ZERO with:
  watch -n 30 'curl -fsS ${API}/api/ib-collector/queue-progress | jq .'

When queue_pending=0 AND googl_status=FRESH, fire Train All.
"
