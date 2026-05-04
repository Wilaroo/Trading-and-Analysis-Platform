# Diagnose Today's Trades — v19.31.7 Operator Runbook

## TL;DR

If `CLOSE TODAY` reads `0` on the dashboard but you know the bot took
trades, this runbook helps you trace exactly what happened. After
v19.31.7 the dashboard auto-corrects this — but if you're still seeing
zero, run these checks in order.

---

## Step 1 — What does the bot say it did today?

```bash
# Daily stats (in-memory counter on TradingBotService)
curl -s http://localhost:8001/api/trading-bot/status \
  | python3 -c "import sys,json; d=json.load(sys.stdin); ds=d.get('daily_stats',{}); print(json.dumps(ds, indent=2))"
```

Look for:
- `trades_executed`: how many times the bot fired `place_bracket_order`.
- `trades_won` / `trades_lost`: counted at close time.
- `gross_pnl` / `net_pnl`: P&L the bot is aware of.

If `trades_executed > 0` but the dashboard's CLOSE TODAY = 0, there's
a write-path gap (Step 3).

If `trades_executed == 0` but you saw fills in TWS, the bot didn't
actually fire — those positions came from somewhere else (manual
trade, leftover bracket from yesterday, etc.).

## Step 2 — What's actually in `bot_trades` Mongo?

```bash
# All trades grouped by status + date
curl -s "http://localhost:8001/api/trading-bot/trades?limit=200" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
for bucket in ('pending','open','closed'):
    rows = d.get(bucket, [])
    print(f'\n=== {bucket.upper()} ({len(rows)}) ===')
    for t in rows[:20]:
        print(f\"  {t.get('symbol'):<6} {t.get('direction'):<6} {t.get('shares')}sh \"
              f\"status={t.get('status'):<8} \"
              f\"executed={t.get('executed_at')} \"
              f\"closed={t.get('closed_at')} \"
              f\"realized=\${t.get('realized_pnl', 0):.2f} \"
              f\"reason={t.get('close_reason') or '-'}\")
"
```

If `closed: 0` but the bot's `trades_executed > 0`, the write to
`bot_trades` is failing OR the close path isn't stamping `status='closed'`.

## Step 3 — Force-pull what `/api/sentcom/positions` returns

```bash
curl -s http://localhost:8001/api/sentcom/positions \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"open positions: {d.get('count')}\")
print(f\"closed today:   {d.get('closed_today_count')}\")
print(f\"  wins:        {d.get('wins_today')}\")
print(f\"  losses:      {d.get('losses_today')}\")
print(f\"\")
print(f\"P&L today (realized + unrealized): \${d.get('total_pnl_today', 0):.2f}\")
print(f\"  realized:    \${d.get('total_realized_pnl', 0):.2f}\")
print(f\"  unrealized:  \${d.get('total_unrealized_pnl', 0):.2f}\")
print(f\"\")
print('--- closed today ---')
for c in d.get('closed_today', []):
    print(f\"  {c.get('symbol'):<6} {c.get('direction'):<6} \"
          f\"realized=\${c.get('realized_pnl', 0):>+8.2f} \"
          f\"closed_at={c.get('closed_at')} \"
          f\"reason={c.get('close_reason')}\")"
```

This is exactly what the dashboard sees. After the v19.31.7 fix,
`closed_today` should match `bot_trades` Mongo for status=closed
since 04:00 UTC today.

## Step 4 — Common gaps and fixes

### Gap A: IB closes a position via OCA, bot doesn't notice

Symptoms: `bot_trades.realized_pnl` = 0 / NULL even though IB
realizedPNL > 0 for the symbol.

Fix: v19.31.1 external-close phantom sweep should catch this. Verify:

```bash
grep "v19.31 EXTERNAL-CLOSE-SWEEP\|phantom_v19_31_oca_closed_swept" \
  /var/log/supervisor/backend.err.log | tail -10
```

If you see entries here but `realized_pnl` is still 0 in Mongo, the
sweep path isn't stamping the field. Bug — file a P0.

### Gap B: Trade closed but `closed_at` is NULL

Symptoms: `bot_trades` has `status='closed'` but `closed_at` field is
None or missing.

Fix: v19.31.7 `/positions` falls back to `executed_at` for these legacy
rows. To clean them up:

```bash
mongosh tradecommand --eval '
  db.bot_trades.updateMany(
    {status: "closed", closed_at: null, executed_at: {$ne: null}},
    [{$set: {closed_at: "$executed_at"}}]
  )
'
```

### Gap C: Reset script wiped today's records

Symptoms: `daily_stats.trades_executed` is high but `bot_trades` is
empty / stale.

Fix: v19.31.1 reset-survival guard prevents this. Verify:

```bash
# Most recent reset-log entry
mongosh tradecommand --eval 'db.bot_trades_reset_log.find({}).sort({timestamp:-1}).limit(1).pretty()'
```

If a reset ran during RTH and `force=true` was passed, that's why.

## Step 5 — Add realized PnL to the dashboard (now automatic)

After v19.31.7, the top HUD's P&L tile shows:
- **P&L $X.XX** — total day P&L (realized + unrealized) in big text
- **R $X.XX** — realized only (small, below)
- **U $X.XX** — unrealized only (small, below)

Hover the tile for the full split in a tooltip. Falls back to the
legacy single-line "P&L" display if the backend hasn't been updated
to v19.31.7 yet.

---

**Last updated**: 2026-05-04 (v19.31.7)
