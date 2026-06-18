# v359 — intraday `squeeze` evaluation → SUPPRESSED

**Date:** 2026-06-18
**Setup:** `squeeze` (INT, "intraday" TTM Bollinger-inside-Keltner momentum fire).
**Verdict:** SUPPRESS (`return None`) — dedupe of a negative-EV daily-compression duplicate.
**Live file built against:** `enhanced_scanner.py` whole-file SHA `dbe2a191fca7cca6e4e83e3b18c003b6bb839f042ce7dc266841b10ccfcfc9a1`
`_check_squeeze` PRE_FUNC_SHA `a3cf366bbb4161118fddaa9a08b15914c18d9fdb369d021e7393a812a1082892`.

## Structural finding
`_check_squeeze` is labelled intraday but consumes snapshot fields that
`realtime_technical_service` builds **entirely from DAILY bars**: `squeeze_on`/`bb_width` from
daily-close BB(20,2) inside Keltner(20, 1.5·ATR); `atr = _calculate_atr(daily_bars,14)`;
`rvol` = 20-day volume ratio. So it is a DAILY-timeframe signal evaluated live, structurally
identical to `daily_squeeze`. It has **no tightness gate** (only `rvol≥1.0`) → fires ~46k/yr
across 400 symbols. Direction = sign(squeeze_fire) = sign(cp − SMA20). Geometry: entry =
max(bb_upper, cp) (long); stop = max(bb_lower, entry−1·ATR); target = entry+2.5·ATR.

## Evidence
1. **Ground truth** (`diag_v359b`, 473 closed bot_trades, synthetic excluded):
   | cut | n | win% | winsorAvg(±5) | totR |
   |---|---|---|---|---|
   | ALL | 473 | 31% | −0.158 | −128.8 |
   | LONG | 285 | 30% | −0.080 | −32.5 |
   | SHORT | 188 | 32% | −0.277 | −96.3 |
   Negative on every cut (the +$77k net P&L is a position-sizing/bookkeeping artifact; the
   risk-normalized R edge is the signal-quality test and it is negative).
2. **Sim** (`diag_v359`, paste rZJqJ): market-order fill (its real execution) = −0.475 R/trade
   (18% win, n=46,675); only an unrealistic buy-stop trigger model was positive (+0.195).
3. **Redundancy**: `daily_squeeze` (long-only after v358) already harvests the genuine +EV
   daily-compression LONG edge with sound geometry (tightness gate + ±10% target). `squeeze`
   is a higher-frequency, worse-geometry duplicate.

## Action
- Patcher `backend/scripts/patch_v359_squeeze_suppress.py` (anchored-chunk, whole-file
  PRE-SHA `dbe2a191…` guard, --check dry-run, auto-backup) swaps the body for `return None`.
- Regression test `backend/tests/test_v359_squeeze_suppress.py`.
- Diags: `diag_v359_squeeze_replay.py` (paste rZJqJ), `diag_v359b_squeeze_ground_truth.py` (paste ulL54).

## Setups adjudicated so far (Replay→Validate template)
- v353 second_chance (re-aligned), v354 vwap_bounce (suppressed), v355 orb (rewritten),
  v356 daily_breakout (preserved +EV), v357 fashionably_late (suppressed),
  v358 daily_squeeze (long-only), v359 squeeze (suppressed).

## Next in queue
`first_move_up` / `first_move_down`, `big_dog`, `gap_give_go`, `spencer_scalp`.
