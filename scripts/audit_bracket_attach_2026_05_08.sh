#!/usr/bin/env bash
# audit_bracket_attach_2026_05_08.sh
# v19.34.55 — Operator post-incident audit script.
#
# Hypothesis to confirm: morning ADBE/BKNG/LIN brackets DID attach
# at entry-time but were ripped off when v19.34.52 phantom-closed
# their parent trades, leaving the IB position naked. After v19.34.52
# deploy this is impossible to recur, but proving the historical
# sequence helps tag the root cause definitively.
#
# Usage:
#   ./audit_bracket_attach_2026_05_08.sh /tmp/backend.log
# or:
#   ./audit_bracket_attach_2026_05_08.sh /home/spark-1a60/backend.log
#
# Run after market close.

LOG="${1:-/tmp/backend.log}"
echo "=== Bracket attach + phantom close audit ==="
echo "Log: $LOG"
echo

if [[ ! -f "$LOG" ]]; then
    echo "❌ Log file not found: $LOG"
    exit 1
fi

for SYM in ADBE BKNG LIN COIN GOOG AAPL MA EWY RKT; do
    echo "── $SYM timeline ──"
    grep -E "$SYM" "$LOG" \
        | grep -E "attach_oca|place_bracket|external_close_v19_34_15b|REISSUE|fill|reconcile" \
        | head -30
    echo
done

echo "=== Summary counts ==="
echo "Total bracket attach events:    $(grep -cE "attach_oca|place_bracket_order" "$LOG")"
echo "Total external_close events:     $(grep -cE "external_close_v19_34_15b" "$LOG")"
echo "v19.34.52 SKIP events:           $(grep -cE "v19\.34\.52 DRIFT-GUARD" "$LOG")"
echo "v19.34.48 KILL-SWITCH refusals:  $(grep -cE "v19\.34\.48 KILL-SWITCH GATE" "$LOG")"
echo "v19.34.54 watchdog reconnects:   $(grep -cE "v19\.34\.54.*reconnected" "$LOG")"
