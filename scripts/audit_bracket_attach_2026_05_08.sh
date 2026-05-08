#!/usr/bin/env bash
# audit_bracket_attach_2026_05_08.sh
# v19.34.58 — Operator post-incident audit script (enhanced).
#
# Hypothesis to confirm: morning ADBE/BKNG/LIN brackets DID attach
# at entry-time but were ripped off when v19.34.52 phantom-closed
# their parent trades, leaving the IB position naked. After v19.34.52
# deploy this is impossible to recur, but proving the historical
# sequence helps tag the root cause definitively.
#
# Output now includes:
#   * Per-symbol timeline (attach → fill → reconcile → close)
#   * Aggregated counters across the whole log
#   * Cross-correlation: how many brackets attached vs how many
#     external_close events fired (the smoking gun is when
#     `external_close` count >> 0 BEFORE v19.34.52 was deployed).
#
# Usage:
#   ./audit_bracket_attach_2026_05_08.sh /tmp/backend.log
# or:
#   ./audit_bracket_attach_2026_05_08.sh /home/spark-1a60/backend.log
#
# Run after market close.

set -uo pipefail

LOG="${1:-/tmp/backend.log}"
echo "=== Bracket attach + phantom close audit ==="
echo "Log: $LOG"
echo

if [[ ! -f "$LOG" ]]; then
    echo "❌ Log file not found: $LOG"
    exit 1
fi

SYMBOLS=(ADBE BKNG LIN COIN GOOG AAPL MA EWY RKT)
for SYM in "${SYMBOLS[@]}"; do
    echo "── $SYM timeline ──"
    grep -E "\b$SYM\b" "$LOG" \
        | grep -E "attach_oca|place_bracket|external_close_v19_34_15b|REISSUE|fill|reconcile|v19\.34\.52 DRIFT-GUARD" \
        | head -30
    echo
done

echo "=== Summary counts ==="
ATTACH_COUNT="$(grep -cE "attach_oca|place_bracket_order" "$LOG" || true)"
EXT_CLOSE_COUNT="$(grep -cE "external_close_v19_34_15b" "$LOG" || true)"
SKIP_COUNT="$(grep -cE "v19\.34\.52 DRIFT-GUARD" "$LOG" || true)"
KILL_REFUSAL_COUNT="$(grep -cE "v19\.34\.48 KILL-SWITCH GATE" "$LOG" || true)"
WATCHDOG_RECONNECT="$(grep -cE "v19\.34\.54.*reconnected" "$LOG" || true)"
HEARTBEAT_FAIL="$(grep -cE "v19\.34\.58 \[IB-DIRECT\] heartbeat failed" "$LOG" || true)"

printf "  bracket attach events:        %s\n" "$ATTACH_COUNT"
printf "  external_close events:         %s   ← was the phantom-close firing?\n" "$EXT_CLOSE_COUNT"
printf "  v19.34.52 SKIP events:         %s   ← guard intercepts (HIGHER = more close attempts blocked)\n" "$SKIP_COUNT"
printf "  v19.34.48 KILL-SWITCH refusals:%s\n" "$KILL_REFUSAL_COUNT"
printf "  v19.34.54 watchdog reconnects: %s\n" "$WATCHDOG_RECONNECT"
printf "  v19.34.58 heartbeat failures:  %s\n" "$HEARTBEAT_FAIL"
echo

# v19.34.58 — verdict line. Operator-friendly summary so the audit
# script tells you the answer, not just the data.
echo "=== Verdict ==="
if [[ "$EXT_CLOSE_COUNT" -gt 0 && "$SKIP_COUNT" -eq 0 ]]; then
    echo "⚠ external_close fired and the v19.34.52 guard was NEVER engaged."
    echo "  → Either the guard is missing or this log predates the patch."
elif [[ "$EXT_CLOSE_COUNT" -gt 0 && "$SKIP_COUNT" -gt 0 ]]; then
    echo "✓ external_close was attempted $EXT_CLOSE_COUNT times AND the guard"
    echo "  intercepted $SKIP_COUNT of them. v19.34.52 is doing its job."
elif [[ "$EXT_CLOSE_COUNT" -eq 0 && "$ATTACH_COUNT" -gt 0 ]]; then
    echo "✓ $ATTACH_COUNT bracket attachments observed; no external_close calls."
    echo "  → Healthy day. Brackets are protecting positions as designed."
else
    echo "ℹ Insufficient activity in this log slice to render a verdict."
fi

