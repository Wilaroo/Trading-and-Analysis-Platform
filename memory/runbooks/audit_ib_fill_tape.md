# Runbook: Audit an IB Fill Tape vs `bot_trades`

**Created v19.34.4 (2026-05-04). Use whenever you want to confirm the bot's internal accounting matches what IB actually filled, including phantom shares, partial-fill drift, or orphan adoptions.**

## Phase 1 — Capture the IB tape

In TWS:
1. **Trades** pane → filter to today (or whichever range).
2. **Select all rows** → copy to clipboard.
3. Paste into `~/Trading-and-Analysis-Platform/memory/audit/<YYYY-MM-DD>_ib_fill_tape.txt`.

The parser is tolerant of the multi-line TWS paste format (symbol → summary → action row → time → price → amount → fees), including thousand-separator quantities and either `Bot` or `Bought` action words.

## Phase 2 — Run the standalone audit

```bash
cd ~/Trading-and-Analysis-Platform/backend
python -m scripts.audit_ib_fill_tape \
    --input ../memory/audit/2026-05-04_ib_fill_tape.txt \
    --out /tmp/audit_2026_05_04.md \
    --json /tmp/audit_2026_05_04.json
```

Output:
- `/tmp/audit_2026_05_04.md` — operator findings (top), summary, per-symbol leg detail with FIFO PnL.
- `/tmp/audit_2026_05_04.json` — same data, machine-readable.

### Verdict labels

| Verdict | Meaning |
|---|---|
| `CLEAN_ROUND_TRIP` | One LONG leg, opened and closed today. Clean. |
| `MULTI_LEG_LONG` | Multiple LONG round-trips today. Heavy churn but directionally clean. |
| `MULTI_LEG_SHORT` | Multiple SHORT round-trips today. Confirm `bot_trades.direction='short'`. |
| `MULTI_LEG_MIXED` | Both LONG and SHORT legs same day — bot flipped direction. Confirm v19.29's 30s stability gate fired correctly. |
| `INVERSION_SHORT_COVER` | Sold first then bought (single short round-trip). |
| `CARRYOVER_FLATTENED` | Sold > bought today. Most likely a prior-day position was flushed; IB is now flat. **Cross-check `bot_trades` for an `executed_at < today_start_ET` row covering the residual.** If absent, those are orphan shares the bot doesn't track. |
| `OPEN_POSITION_LONG` | Bought > sold. Bot still holds the residual. Match against `/api/sentcom/positions`. |

## Phase 3 — Cross-check against `bot_trades` (Mongo)

This is the actual reconciliation step.

```bash
cd ~/Trading-and-Analysis-Platform/backend
python -m scripts.export_bot_trades_for_audit \
    --date 2026-05-04 \
    --out /tmp/bt_2026_05_04.json
```

The script queries `bot_trades` for any row whose `executed_at`, `closed_at`, OR `created_at` falls within the ET trading day window (04:00–04:00 UTC). It includes the v19.31.13 + v19.34.3 provenance fields (`entered_by`, `synthetic_source`, `prior_verdict_conflict`, `trade_type`, `account_id_at_fill`).

Then re-run the auditor with the cross-check sidecar:

```bash
python -m scripts.audit_ib_fill_tape \
    --input ../memory/audit/2026-05-04_ib_fill_tape.txt \
    --bot-trades-json /tmp/bt_2026_05_04.json \
    --out /tmp/audit_2026_05_04_with_xcheck.md
```

The new report will include a **Cross-check vs `bot_trades`** section that flags:

- **Symbols in IB tape NOT in `bot_trades`** — orphan executions the bot didn't record (executor failure or pusher/Mongo write failure).
- **Symbols in `bot_trades` NOT in IB tape** — phantom rows in Mongo with no broker-side fills (sweep candidates).
- **qty mismatches** — when bot's row count's `total_qty` ≠ IB tape's `max(bought, sold)`.

## Phase 4 — Investigate any flag

| Flag | Action |
|---|---|
| Symbol in IB but not bot | Run `GET /api/diagnostics/orphan-origin/{symbol}?days=7` to map the source. If verdict = `manual_or_external`, click **RECONCILE** in V5 Open Positions to materialize a `bot_trade` row. |
| Symbol in bot but not IB | Likely a phantom from before v19.31's external-close sweep; query `db.bot_trades.find({symbol:"X", status:"open"})` and verify against IB snapshot. |
| qty mismatch | Diff individual fills — usually the executor failed to claim a partial. |
| `prior_verdict_conflict=true` on a row | The bot adopted a position it had been rejecting. Reconciler chose either `synthetic_source: 'last_verdict'` (smart stop pulled from real numbers) or `'default_pct'` (pure synthetic). Check `prior_verdicts` array on the row. |

## Phase 5 — Add the report to the audit folder

After cross-checking, save the final report:

```bash
mv /tmp/audit_2026_05_04_with_xcheck.md \
   ~/Trading-and-Analysis-Platform/memory/audit/2026-05-04_audit_with_xcheck.md
git add memory/audit/ && git commit -m "Audit 2026-05-04 fill tape"
```

Builds a permanent audit trail for AI training data integrity.

## Caveats

- **FIFO matching is venue-blind.** The auditor doesn't know which IB parent order produced a partial fill. If the bot's executor splits a 1000-share order into 50 venue-specific child orders, the auditor sees 50 fills but the bot may have a single row. The qty totals will still match; only the fill count will diverge — that's expected.
- **`CARRYOVER_FLATTENED` verdicts ALWAYS need Phase 3 cross-check.** Without it, you can't tell whether the residual was a real prior-day bot trade or an unaccounted-for orphan.
- **Time zones**: All TWS times are ET; the auditor stores them as raw strings + minutes-since-00:00. The Mongo export uses ET trading-day boundaries (04:00 UTC – 04:00 UTC next day) which covers ET premarket through after-hours.
- **Paper-only on this run**: account `DUN615665` starts with `DU*` per `account_guard.classify_account_id`, so all rows are PAPER. If you swap to a LIVE account, the same auditor works but each fill is real money.
