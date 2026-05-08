#!/usr/bin/env bash
# zombie_sweep_v19_34_59.sh
# v19.34.59 — One-shot zombie cleanup.
#
# Hits the existing `/api/trading-bot/reconcile-share-drift` endpoint
# with `zombie_detect_only=false` — overrides the env-flag default
# (`SHARE_DRIFT_ZOMBIE_AUTO_HEAL=false`) for this single call. Lets
# the operator heal a zombie population without a backend restart.
#
# What it does:
#   1. GET /api/trading-bot/zombie-trades         → enumerate population
#   2. POST /api/trading-bot/reconcile-share-drift
#      { auto_resolve: true, zombie_detect_only: false }
#      → for each zombie: close it (`zombie_cleanup_v19_34_19`) AND
#        spawn `reconciled_excess_slice` to bracket the IB position
#   3. GET /api/trading-bot/zombie-trades         → confirm count→0
#
# Usage:
#   ./zombie_sweep_v19_34_59.sh
#   ./zombie_sweep_v19_34_59.sh --dry-run        # detect only, no heal
#
# Backend must be running on http://localhost:8001.

set -euo pipefail

API="${API:-http://localhost:8001}"
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

echo "=== v19.34.59 Zombie Sweep ==="
echo "API: $API"
echo "Mode: $([[ "$DRY_RUN" == "true" ]] && echo "DRY-RUN (detect only)" || echo "HEAL")"
echo

echo "── Step 1: enumerate current zombies ──"
BEFORE=$(curl -fsS "$API/api/trading-bot/zombie-trades")
echo "$BEFORE" | python3 -m json.tool || echo "$BEFORE"
COUNT_BEFORE=$(echo "$BEFORE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count', 0))" 2>/dev/null || echo 0)
echo
echo "Zombie count before sweep: $COUNT_BEFORE"
echo

if [[ "$COUNT_BEFORE" == "0" ]]; then
    echo "✓ No zombies. Nothing to do."
    exit 0
fi

if [[ "$DRY_RUN" == "true" ]]; then
    echo "── DRY-RUN: skipping reconcile call. Re-run without --dry-run to heal. ──"
    exit 0
fi

echo "── Step 2: reconcile-share-drift with zombie_detect_only=false ──"
HEAL_RESPONSE=$(curl -fsS -X POST "$API/api/trading-bot/reconcile-share-drift" \
    -H "Content-Type: application/json" \
    -d '{"auto_resolve": true, "zombie_detect_only": false}')
echo "$HEAL_RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(json.dumps({
    'success':            d.get('success'),
    'detected':           len(d.get('drifts_detected') or []),
    'resolved':           len(d.get('drifts_resolved') or []),
    'skipped':            len(d.get('skipped') or []),
    'errors':             len(d.get('errors') or []),
    'resolved_symbols':   [r.get('symbol') for r in d.get('drifts_resolved') or []],
    'resolved_kinds':     sorted({r.get('kind') for r in d.get('drifts_resolved') or [] if r.get('kind')}),
    'zombies_closed':     [r.get('zombies_closed') for r in d.get('drifts_resolved') or [] if r.get('zombies_closed')],
    'new_trade_ids':      [r.get('new_trade_id') for r in d.get('drifts_resolved') or [] if r.get('new_trade_id')],
}, indent=2))
" 2>/dev/null || echo "$HEAL_RESPONSE"
echo

echo "── Step 3: re-enumerate zombies (should be 0) ──"
sleep 1
AFTER=$(curl -fsS "$API/api/trading-bot/zombie-trades")
COUNT_AFTER=$(echo "$AFTER" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count', 0))" 2>/dev/null || echo "?")
echo "Zombie count after sweep:  $COUNT_AFTER"
echo

if [[ "$COUNT_AFTER" == "0" ]]; then
    echo "✓ Sweep successful. All $COUNT_BEFORE zombies cleaned up."
    echo
    echo "Next: confirm bot is now tracking IB-positions correctly:"
    echo "  curl -s $API/api/trading-bot/share-drift-status | python3 -m json.tool"
else
    echo "⚠ $COUNT_AFTER zombies remain. Inspect:"
    echo "$AFTER" | python3 -m json.tool || echo "$AFTER"
    echo
    echo "If they keep returning, hunt the upstream creator:"
    echo "  grep '\\[v19.34.59 ZOMBIE-LOAD\\]' /tmp/backend.log | tail -20"
fi
