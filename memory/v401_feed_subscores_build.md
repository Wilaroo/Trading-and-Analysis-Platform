# v401 — Feed-vs-Drop TQS sub-scores (Entry Tendency, Tape, AI-Model) — 2026-06-23

Context: TQS Data Coverage report (7d, 84.6% real) showed dead/thin sub-scores.
Decision: FEED the feedable ones (don't just renorm-drop). Per-sub-score verdict:
- Entry Tendency 0% → pure wiring gap (FEED). execution_tracker already computes
  entry_slippage; pillar never read it live.
- Tape 95.7% no-data → structurally L2-slot-bound (DROP for slow horizons; bias
  scarce slots + JIT read for fast).
- AI Model 41% no-data → <20 daily bars OR confidence<threshold (PRE-WARM bars).
- Sector / EV / Fundamentals → self-heal / parser fix (NOT in this batch).

## Shipped (all env-gated, reversible)

### A — Entry Tendency live-derivation  [services/tqs/execution_quality.py]
- `_derive_live_execution_state` now also reads `execution.entry_slippage_percent`
  → returns avg_entry_slippage_pct / entry_sample / tends_to_chase.
- `calculate_score`: when EOD trader_profiles empty, derive entry slippage+chase
  LIVE from trade_outcomes (mirrors the existing exit-tendency path). Backfilled
  closes (execution={}) correctly treated as no-data.
- Flag: `TQS_EXEC_ENTRY_LIVE` (default ON).
- Tests: tests/test_entry_tendency_live_v401.py (4, pass).

### B1 — Horizon-aware Tape drop  [services/tqs/setup_quality.py + tqs_engine.py]
- `calculate_score(trade_style=...)`: for swing/position, tape forced absent
  (verdict "No data" → renorm drops it). Kept for scalp/intraday.
- tqs_engine passes `trade_style=_scoring_style`.
- Flag: `TQS_TAPE_HORIZON_AWARE` (default ON).

### B2 — L2 routing fast-horizon bias  [services/l2_router.py]
- `_compute_desired_l2` sort key now (fast, priority, tqs, -age); fast=1 for
  scalp/intraday via horizon_of(setup_type). 3 scarce L2 slots prefer fast setups.
- Flag: `L2_PREFER_FAST_HORIZON` (default ON).

### C — JIT tape confirmation  [services/tape_confirm_service.py + trade_execution.py]
- get_tape_confirmation(symbol,direction): top-of-book read via EXISTING pusher
  /rpc/quote-snapshot (no new pusher endpoint) → analyze_tape_from_quote_data →
  tape_score + imbalance + confirms. Fail-open (None).
- Hooked into trade_execution.execute_trade for scalp/intraday entries: stamps
  tape onto trade.notes/tape_score + logs. Blocking gate (reject on opposing
  tape) opt-in.
- Flags: `TAPE_JIT_CONFIRM` (default OFF — dormant), `TAPE_JIT_GATE` (default OFF).
- Tests: tests/test_tape_horizon_v401.py (B1+C, pass).

### D — AI-Model bar pre-warm  [server.py: POST /api/ai/prewarm-forecast-bars]
- Finds scan-universe symbols with <min_bars (default 25) DAILY bars in
  ib_historical_data and backfills via collector.start_collection(bar_size="1 day",
  duration="6 M", force_refresh=True). Candidate source: request list > active
  alerts > liquid universe. Body: {symbols?, min_bars?, duration?, limit?, dry_run?}.
- Dry-run verified in preview. Real backfill needs live IB (DGX-side).

## Operator verification (DGX, after pull + restart)
- Entry Tendency: after a few live scalp/intraday closes, TQS execution pillar
  `entry_tendency` should leave "No data" and show real slippage. Coverage report
  Entry Tendency should climb above 0%.
- Tape: swing/position cards should show "Tape n/a for this horizon"; scalp/
  intraday keep tape. L2 router status `last_desired` should favor fast names.
- AI Model: `curl -X POST .../api/ai/prewarm-forecast-bars -d '{"dry_run":true}'`
  to see below_min count, then run without dry_run to backfill.
- JIT tape stays OFF until reviewed: set TAPE_JIT_CONFIRM=on (advisory) first,
  watch trade.notes "[tape ...]" tags, then TAPE_JIT_GATE=on to block.

## NOT done (next)
- Sector backfill fallback (23.6% no-data).
- EV threshold 5→3 (self-heals as outcomes accumulate).
- Fundamentals `growth`/ProjLTGrowthRate parser fix (P2).
- v393 renorm post-open validation (score_sd widening, scalp inversion).

## ⏰ 2026-06-24 — POST-OPEN PROBE RESULT + SCHEDULED RE-CHECK
First post-deploy `tqs-integrity` read (days=30, n≈26.9k score samples):
- ✅ **Compression SOLVED**: score SD **8.99**, `ok_spread` (p10/50/90 = 55/60/80). v393 renorm worked.
  → **v394 pillar-renorm is NOT needed — do not build it.**
- ✅ Config fix: `MAX_L2_SLOTS` was 6 but IB entitlement is 3 → set to **3** (was starving desired#2 XBI
  and nullifying B2). Now `max_l2_slots=3`, cap_rejections cleared.
- ❌ **Scalp grade still INVERTED** (TQS grade, confirmed via pnl_compute trade_grade=tqs_grade):
  `grade_by_horizon` scalp = A:-0.081(n29) B:-0.073(n52) C:**+0.116**(n65). Intraday clean/monotonic
  (A:0.019 B:-0.053 C:-0.189). Swing/position ~flat.
- ⚠️ **But it's NOT actionable yet — all noise at current n:** scalp inversion t≈0.9 (p≈0.38); every
  scalp pillar |corr|<0.09 at n=123 (needs ≈0.18 for p<0.05). Reweighting now = overfitting noise.
- 📊 One consistent (not-yet-significant) signal: **execution = most predictive pillar** (intraday
  corr 0.209, hi_R 0.223 vs lo_R -0.251 = 0.47R spread; position 0.19) — exactly what v401 Entry-Tendency
  feeds. Weighted only ~10% scalp / 15% intraday today.

**⏰ RE-CHECK on/after 2026-07-08** (earliest 2026-07-01) once v401-scored closes fill the window. Decision
rule + likely action (bump execution weight on scalp/intraday, NOT a renorm) recorded in PRD.md top block
and ROADMAP.md "SCHEDULED RE-CHECKS". Parsers below.

### Probe parsers (reusable — double-quote -c, single quotes inside; DGX terminal mangles escaped quotes)
grade_by_horizon + headline:
```
curl -s "http://localhost:8001/api/slow-learning/tqs-integrity/report?days=30" -o /tmp/tqs.json
python3 -c "
import json
d = json.load(open('/tmp/tqs.json'))['report']
print('HEADLINE:', d.get('headline'))
print('score SD :', d.get('score_discrimination',{}).get('sd'), d.get('score_discrimination',{}).get('verdict'))
print('inverted :', d.get('grade_by_horizon',{}).get('inverted_horizons'))
for h in d.get('grade_by_horizon',{}).get('horizons',[]):
    cells = ' '.join('%s:%s(n%s)' % (r['grade'], r['avg_r'], r['n']) for r in h['by_grade'] if r['avg_r'] is not None)
    print(' ', h['horizon'].ljust(9), cells, ('<<<INV' if h.get('inverted') else ''))
"
```
pillar_predictiveness by horizon:
```
python3 -c "
import json
d = json.load(open('/tmp/tqs.json'))['report']
for h in d.get('pillar_predictiveness',{}).get('horizons',[]):
    print(); print(h['horizon'].upper(), 'n=', h['n'])
    for p in h['pillars']:
        print('   %-12s corr=%-7s sd=%-6s hi=%-7s lo=%-7s' % (p['pillar'], str(p.get('corr_with_r')), str(p.get('score_sd')), str(p.get('avg_r_top_half')), str(p.get('avg_r_bottom_half'))))
"
```
