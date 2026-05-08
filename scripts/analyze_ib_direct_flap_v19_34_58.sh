#!/usr/bin/env bash
# analyze_ib_direct_flap_v19_34_58.sh
# v19.34.58 — clientId=11 IB-direct flap-pattern analysis.
#
# Mines the backend log for v19.34.54 / v19.34.58 IB-direct
# disconnect, watchdog, and heartbeat events. Produces:
#   * total drops + reconnects + reconnect failures
#   * heartbeat-failure count (half-open socket detection)
#   * inter-drop intervals (median / max / min) so the operator can
#     tell if the flap is bursty (many drops in a window) or
#     periodic (idle-eviction every ~N minutes)
#   * drop reasons grouped (disconnectedEvent vs heartbeat_failed:*)
#   * the 5 most-recent drop timestamps with surrounding context
#
# Usage:
#   ./analyze_ib_direct_flap_v19_34_58.sh /tmp/backend.log
# or:
#   ./analyze_ib_direct_flap_v19_34_58.sh /home/spark-1a60/backend.log
#
# Run any time after the watchdog has been live for a few hours.

set -euo pipefail

LOG="${1:-/tmp/backend.log}"

if [[ ! -f "$LOG" ]]; then
    echo "ERROR: log file not found: $LOG" >&2
    exit 1
fi

echo "=== IB-direct (clientId=11) flap analysis ==="
echo "Log: $LOG"
echo "Size: $(stat -c %s "$LOG" 2>/dev/null || stat -f %z "$LOG" 2>/dev/null) bytes"
echo

DROP_COUNT="$(grep -cE "v19\.34\.5[48].*\[IB-DIRECT\] socket dropped|v19\.34\.58 \[IB-DIRECT\] heartbeat failed" "$LOG" || true)"
RECONNECT_COUNT="$(grep -cE "v19\.34\.54 \[IB-DIRECT\] watchdog reconnected" "$LOG" || true)"
RECONNECT_FAIL_COUNT="$(grep -cE "v19\.34\.54 \[IB-DIRECT\] reconnect failed" "$LOG" || true)"
HEARTBEAT_FAIL_COUNT="$(grep -cE "v19\.34\.58 \[IB-DIRECT\] heartbeat failed" "$LOG" || true)"
EVENT_DROP_COUNT="$(grep -cE "v19\.34\.54 \[IB-DIRECT\] socket dropped" "$LOG" || true)"

echo "── Counts ──"
printf "  drops total:               %s\n" "$DROP_COUNT"
printf "  ├─ via disconnectedEvent:  %s\n" "$EVENT_DROP_COUNT"
printf "  └─ via heartbeat failure:  %s  (half-open / frozen sockets)\n" "$HEARTBEAT_FAIL_COUNT"
printf "  reconnects successful:     %s\n" "$RECONNECT_COUNT"
printf "  reconnect failures:        %s\n" "$RECONNECT_FAIL_COUNT"
echo

echo "── Drop reasons (grouped) ──"
grep -hE "v19\.34\.5[48].*(socket dropped|heartbeat failed)" "$LOG" \
    | sed -E 's/.*(socket dropped|heartbeat failed:[A-Za-z_]+|heartbeat failed).*/\1/' \
    | sort | uniq -c | sort -rn || echo "  (no events)"
echo

echo "── Inter-drop intervals ──"
# Drop timestamps (ISO-ish: assume the log line begins with `YYYY-MM-DD HH:MM:SS`)
grep -E "v19\.34\.5[48].*(socket dropped|heartbeat failed)" "$LOG" \
    | awk '{print $1" "$2}' \
    | head -n 200 \
    > /tmp/ib_direct_drop_ts.$$
LINE_COUNT=$(wc -l < /tmp/ib_direct_drop_ts.$$ | tr -d ' ')
if [[ "$LINE_COUNT" -lt 2 ]]; then
    echo "  (need at least 2 drops for interval stats; found $LINE_COUNT)"
else
    python3 - "/tmp/ib_direct_drop_ts.$$" <<'PYEOF'
import sys
from datetime import datetime
path = sys.argv[1]
with open(path) as f:
    rows = [r.strip() for r in f if r.strip()]
ts = []
for r in rows:
    for fmt in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
        try:
            ts.append(datetime.strptime(r[:23] if "," in r else r[:19], fmt))
            break
        except ValueError:
            continue
ts.sort()
deltas = [(ts[i] - ts[i - 1]).total_seconds() for i in range(1, len(ts))]
if not deltas:
    print("  (could not parse timestamps)")
else:
    deltas.sort()
    n = len(deltas)
    median = deltas[n // 2]
    print(f"  count:        {n + 1} drops over {(ts[-1] - ts[0]).total_seconds() / 3600:.1f}h")
    print(f"  median gap:   {median:>8.1f} s   ({median / 60:.1f} min)")
    print(f"  min gap:      {deltas[0]:>8.1f} s")
    print(f"  max gap:      {deltas[-1]:>8.1f} s   ({deltas[-1] / 60:.1f} min)")
    print(f"  mean gap:     {sum(deltas) / n:>8.1f} s")
    short = sum(1 for d in deltas if d < 60)
    if short:
        print(f"  bursty drops: {short} gap(s) under 60s — possible IB-side flap (Gateway restart, login eviction)")
PYEOF
fi
rm -f /tmp/ib_direct_drop_ts.$$
echo

echo "── 5 most-recent drop events (with 2 lines context) ──"
grep -nE "v19\.34\.5[48].*(socket dropped|heartbeat failed)" "$LOG" \
    | tail -5 \
    | while IFS= read -r match; do
        line_num="${match%%:*}"
        start=$(( line_num > 1 ? line_num - 1 : 1 ))
        echo "  ── line $line_num ──"
        sed -n "${start},$((line_num + 1))p" "$LOG" | sed 's/^/    /'
    done
echo

echo "── Watchdog status (most recent log line) ──"
grep -E "v19\.34\.54 \[IB-DIRECT\] watchdog (started|reconnected|cancelled)" "$LOG" \
    | tail -3 || echo "  (watchdog has not started in this log)"
echo

echo "── Hint: GET /api/system/ib-direct/status → \"stability\" block has live counters ──"
