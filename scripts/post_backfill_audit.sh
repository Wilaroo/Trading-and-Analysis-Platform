#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# post_backfill_audit.sh — run this on the DGX after the IB historical
# backfill drains. Hits every read-only inspection endpoint in priority
# order and pipes through `jq` for a quick eyeball check.
#
# Usage:
#   chmod +x scripts/post_backfill_audit.sh
#   ./scripts/post_backfill_audit.sh                      # localhost:8001
#   API=http://localhost:8001 ./scripts/post_backfill_audit.sh
#
# Requires: curl, jq.
# ---------------------------------------------------------------------------
set -u
API="${API:-http://localhost:8001}"

bold()  { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }
warn()  { printf "\033[1;33m%s\033[0m\n" "$*"; }
ok()    { printf "\033[1;32m%s\033[0m\n" "$*"; }

hit() {
  # $1 = label, $2 = path, $3 = jq filter (optional, default = .)
  local label="$1" path="$2" filter="${3:-.}"
  bold "$label   →   GET $path"
  if ! curl -fs --max-time 90 "${API}${path}" | jq -C "${filter}"; then
    warn "  (request failed, timed out, or returned non-JSON)"
  fi
}

bold "POST-BACKFILL AUDIT against ${API}"
date -u +"started: %Y-%m-%dT%H:%M:%SZ"

# 1. The single source of truth: green / yellow / red verdict.
hit "1. READINESS VERDICT" "/api/backfill/readiness" '
  {
    verdict, ready_to_train, summary,
    blockers, warnings, next_steps,
    checks: (.checks | to_entries | map({(.key): .value.status}) | add)
  }'

# 2. Queue must be empty (pending == 0, claimed == 0, no recent failures).
hit "2. QUEUE PROGRESS" "/api/ib-collector/queue-progress" '
  {pending, claimed, completed, failed, total}'

# 3. Recent failed items — what (if anything) didn't make it in.
hit "3. FAILURE ANALYSIS (last 24h)" "/api/ib-collector/failure-analysis" '
  if has("by_error") then
    {total_failed, by_error, by_symbol_top: (.by_symbol // {} | to_entries | sort_by(-.value) | .[0:10])}
  else . end'

# 4. Inventory roll-up — bars per (tier, timeframe).
hit "4. INVENTORY SUMMARY" "/api/ib-collector/inventory/summary" '.'

# 5. Per-timeframe distribution of bars.
hit "5. TIMEFRAME STATS" "/api/ib-collector/timeframe-stats" '.'

# 6. Universe freshness — what % of (symbol, bar_size) cells are fresh.
hit "6. UNIVERSE FRESHNESS HEALTH" "/api/ib-collector/universe-freshness-health" '
  {
    overall_fresh_pct: (.overall.fresh_pct // .fresh_pct),
    universe_size:     (.overall.universe_size // .universe_size),
    per_tier:          (.per_tier // .by_tier // null),
    per_timeframe:     (.per_timeframe // .by_timeframe // null)
  }'

# 7. Coverage — how far back each timeframe goes for the critical symbols.
hit "7. DATA COVERAGE (critical symbols)" \
    "/api/ib-collector/data-coverage?symbols=SPY,QQQ,IWM,AAPL,MSFT,NVDA,GOOGL,META,AMZN,DIA" '.'

# 8. Top-level health roll-up.
hit "8. SYSTEM HEALTH" "/api/ib-collector/system-health" '
  {
    health_status,
    queue,
    data_freshness,
    issues,
    stuck_requests,
    recommendations: (.recommendations | map(select(. != null)))
  }'

bold "DONE"
date -u +"finished: %Y-%m-%dT%H:%M:%SZ"

# Final guidance
echo
ok "Decision rules:"
echo "  • verdict == green  → safe to trigger Train All."
echo "  • verdict == yellow → review .warnings before training."
echo "  • verdict == red    → DO NOT TRAIN. Address .blockers first."
