#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# inspect_symbol.sh — quick "what's the latest bar I have for $SYMBOL on
# every timeframe?" probe. Hits the Mongo collection directly through a
# small backend helper if available, falling back to the FastAPI
# endpoints we already have.
#
# Usage:
#   ./scripts/inspect_symbol.sh GOOGL
#   API=http://localhost:8001 ./scripts/inspect_symbol.sh AAPL
# ---------------------------------------------------------------------------
set -u
SYMBOL="${1:-}"
if [[ -z "$SYMBOL" ]]; then
  echo "usage: $0 SYMBOL"
  exit 2
fi
API="${API:-http://localhost:8001}"

echo "=== Latest bar per timeframe for $SYMBOL ==="
curl -fs --max-time 30 "${API}/api/ib-collector/symbol-request-history?symbol=${SYMBOL}" \
  | jq -C 'if has("by_bar_size") then
              .by_bar_size
            elif has("history") then
              .history
            else . end' 2>/dev/null \
  || echo "  (symbol-request-history not available — using data endpoint)"

echo
echo "=== Per-timeframe data preview ==="
curl -fs --max-time 30 "${API}/api/ib-collector/data/${SYMBOL}" | jq -C '
  {symbol, by_bar_size: (.by_bar_size // .data // null)}'

echo
echo "=== Suggested action ==="
cat <<EOF
If any timeframe shows latest_date older than its STALE_DAYS budget
(1m/5m: 3d, 15m/30m: 5d, 1h: 7d, 1d: 3d, 1w: 14d), trigger an
incremental update — only fetches missing days, doesn't re-do
historical data:

  curl -fsS -X POST "${API}/api/ib-collector/incremental-update?max_symbols=100&max_days_lookback=7" | jq .

Then wait ~60s for the 4 turbo collectors to drain the queue and
re-run ./scripts/post_backfill_audit.sh for the new verdict.

Alternatively, to surgically fix only the critical 10 symbols:

  curl -fsS -X POST "${API}/api/ib-collector/smart-backfill?tier_filter=intraday&freshness_days=1" | jq .
EOF
