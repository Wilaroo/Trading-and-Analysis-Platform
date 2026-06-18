# v358 — `daily_squeeze` evaluation → LONG-ONLY

**Date:** 2026-06-18
**Setup:** `daily_squeeze` (swing) — TTM-style Bollinger-inside-Keltner volatility squeeze on daily bars.
**Verdict:** REWRITE to LONG-ONLY (suppress the momentum-short branch). Geometry unchanged.
**Live file built against:** `enhanced_scanner.py` whole-file SHA `36067838a2bf786444b825b81d0e328626be8fcbad74ba712fd33ae792d9c182`
`_check_daily_squeeze` PRE_FUNC_SHA `8e497aad92e1189d817efc5609e2e41fd2c88959f1cee7d775f9da1d2cf8fe21`.

## Live detector (no cheat sheet exists)
- 20-SMA + BB(20,2); Keltner = SMA20 ± 1.5·ATR(14). Squeeze ON = BB inside KC.
- Adaptive tightness: bb_width < 0.7 × median(prior bb_widths) (else abs < 15%).
- Direction from momentum (close vs SMA20). Entry = close. Stop = ATR-floored (min 1.5·ATR)
  anchored to 20-bar low/high. Target = entry × 1.10 (long) / 0.90 (short). Fires while squeezed.

## Replay method
`backend/scripts/diag_v358_daily_squeeze_replay.py` (READ-ONLY, paste https://paste.rs/7Kn8D,
sha `7f5f81f3…6f6ab`) reproduces the detector on `1 day` IB bars and scores realized R; supports
`--trigger compression|release`, `--target pct|atr`, `--tmult/--stopatr/--tight/--maxhold`.

## Results (365d, 400-symbol universe)
| Config | LONG winsorAvg (win%) | LONG totW | SHORT winsorAvg (win%) | SHORT totW |
|---|---|---|---|---|
| compression / ±10% (**LIVE**) | **+0.073 (51%)** | **+1532.7** | −0.056 (45%) | −1067.1 |
| release / ±10% | +0.053 (55%) | +396.5 | −0.071 (48%) | −452.7 |
| compression / 2.5ATR | +0.061 (52%) | +1287.5 | −0.041 (46%) | −789.9 |
| release / 2.5ATR | +0.047 (57%) | +348.1 | −0.072 (48%) | −455.7 |
| tight0.5 / hold20 | +0.083 (50%) | +889.5 | −0.088 (42%) | −846.2 |

## Reading
- Unambiguous LONG-only edge: every config shows LONG +EV (winsorAvg +0.05..+0.08, win 50–57%,
  large +totW) and SHORT negative (−0.04..−0.09, win 42–48%, large −totW).
- Shorting a daily squeeze in a drift-up equity tape is structurally losing; the short branch
  was diluting a real long edge to ~breakeven (combined ALL only +0.012).
- Live geometry's LONG side is already best (compression + ±10% target). No geometry change —
  surgical fix = suppress shorts.

## Action
- Patcher `backend/scripts/patch_v358_daily_squeeze_long_only.py` inserts
  `if direction != "long": return None` right after `direction` is computed (anchored-chunk,
  whole-file PRE-SHA `36067838…` guard, --check dry-run, auto-backup).
- Regression test `backend/tests/test_v358_daily_squeeze_long_only.py`
  (long fires / short suppressed).

## Next setup in queue
Intraday `squeeze` (separate detector — needs an intraday BB/KC replay like v357),
then `first_move_up/down`, `big_dog`, `gap_give_go`, `spencer_scalp`.
