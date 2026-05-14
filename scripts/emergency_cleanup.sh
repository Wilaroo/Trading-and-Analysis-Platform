#!/usr/bin/env bash
set -u
API="http://localhost:8001"
DRY="true"; [ "${1:-}" = "--execute" ] && DRY="false"
echo "=== v19.34.30 Emergency IB Cleanup -- dry_run=$DRY ==="
HEALTH=$(curl -sS -m 4 "$API/api/ib/pushed-data" -o /dev/null -w "%{http_code}")
[ "$HEALTH" != "200" ] && { echo "[!] Backend unreachable (HTTP $HEALTH)"; exit 1; }
echo
echo "[1] Halt bot"
[ "$DRY" = "false" ] && curl -sS -X POST "$API/api/trading-bot/stop" | python3 -m json.tool || echo "    (skipped in dry-run)"
echo
echo "[2] Read bracket-stacking-audit"
curl -sS -m 10 "$API/api/trading-bot/bracket-stacking-audit" -o /tmp/audit_pre.json
SYMS=$(python3 -c "
import json; d=json.load(open('/tmp/audit_pre.json'))
print(' '.join(s['symbol'] for s in d.get('symbols',[]) if len(s.get('stop_legs',[]))+len(s.get('target_legs',[]))>2))")
echo "    Symbols: $SYMS"
echo
echo "[3] Cancel all legs per symbol (target_qty=0)"
for sym in $SYMS; do
  P=$(printf '{"symbol":"%s","target_qty":0,"dry_run":%s}' "$sym" "$DRY")
  printf "    %-6s -> " "$sym"
  curl -sS -m 10 -X POST "$API/api/trading-bot/cancel-excess-bracket-legs" -H 'Content-Type: application/json' -d "$P" \
   | python3 -c "
import json,sys
try:
  d=json.loads(sys.stdin.read())
  print(f\"cancelled={len(d.get('cancelled',[])or[])} kept={len(d.get('kept_brackets',d.get('kept',[])or[])or[])} errors={len(d.get('errors',[])or[])} ok={d.get('success')}\")
except Exception as e: print(f'parse_error={e}')"
done
if [ "$DRY" = "false" ]; then
  echo
  echo "[4] Poll cancellations queue"
  for i in $(seq 1 24); do
    N=$(curl -sS -m 4 "$API/api/ib/cancellations/pending" | python3 -c "import json,sys;print(len(json.load(sys.stdin).get('cancellations',[])))" 2>/dev/null || echo "?")
    echo "    t=$((i*5))s pending=$N"
    [ "$N" = "0" ] && break
    sleep 5
  done
fi
echo
echo "[5] Re-audit"
curl -sS -m 10 "$API/api/trading-bot/bracket-stacking-audit" -o /tmp/audit_post.json
python3 -c "
import json
pre=json.load(open('/tmp/audit_pre.json')); post=json.load(open('/tmp/audit_post.json'))
def t(d): return sum(len(s.get('stop_legs',[]))+len(s.get('target_legs',[])) for s in d.get('symbols',[]))
print(f'  PRE  legs={t(pre)} syms={len(pre.get(\"symbols\",[]))}')
print(f'  POST legs={t(post)} syms={len(post.get(\"symbols\",[]))}')
for s in post.get('symbols',[]):
  n=len(s.get('stop_legs',[]))+len(s.get('target_legs',[]))
  if n>2: print(f'  still stacked: {s[\"symbol\"]} {n}')"
echo
echo "=== Done. dry_run=$DRY ==="
[ "$DRY" = "true" ] && echo " --> Pass --execute to actually fire."
