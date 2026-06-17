# v357 — `fashionably_late` evaluation → SUPPRESSED

**Date:** 2026-06-17
**Setup:** `fashionably_late` (INT-26) — SMB "Fashionably Late Scalp" (9-EMA × VWAP momentum cross).
**Verdict:** SUPPRESS (`return None`), mirroring `vwap_bounce` (v354).
**Live file built against:** `enhanced_scanner.py` whole-file SHA `30eba7d1faf17f1c4fa0794c564e5790b73e4baf0b35f04095a1cbc16d03b1ac`
`_check_fashionably_late` PRE_FUNC_SHA `baf371bf9e324ae6457513fc1761e2453aa603f96ef960f852a9d039b1401303`.

## Doctrine (cheat sheet: the_fashionably_late_scalp_cheat_sheet)
- LONG: an UP-sloping 9-EMA crosses a FLAT-to-DOWN-sloping VWAP; enter at the cross.
  measured move = (cross_price − LOD); target = cross + measured_move;
  hard stop = ⅓ of the (VWAP→LOD) distance below VWAP → clean ~3:1 RR. SHORT inverted (HOD).
- Ideal times: 10:00–10:45 & 10:46–13:30 ET. Claimed stats: **60% win, 3:1 RR**.
- Discretionary boosters: convergence-volume > divergence-volume; fast/steady turn off the low;
  avoid if 9-EMA goes flat > 15 min after the turn (chop).

## Replay method
`backend/scripts/diag_v357_fashionably_late_replay.py` (READ-ONLY): rebuilds session VWAP +
9-EMA on intraday IB bars, detects the cross (with EMA-slope + VWAP-slope + time-window gates),
and scores realized R under (1) doctrine measured-move 3:1 and (2) the live ATR-floored-stop
geometry. TZ-sanity block confirmed correct ET bucketing (median 78 RTH bars/session on 5-min;
ET-hours 09–15h; `--tz auto` = treat naive timestamps as UTC).

## Results (120d, 300-symbol universe, 5-min bars unless noted)
| Cut | n | win% | winsorAvg R | totW |
|---|---|---|---|---|
| Doctrine strict (vwapslope on, window on) ALL | 1056 | 31% | −0.149 | −157.8 |
| Doctrine strict LONG / SHORT | 556 / 500 | 30% / 33% | −0.182 / −0.113 | — |
| Quality (vol-conv + fast-turn, strict) ALL | 126 | 30% | −0.233 | −29.3 |
| Doctrine loose (vwapslope off) ALL | 30340 | 51% | −0.028 (medR +0.025) | −859.8 |
| **Quality (loose, vol-conv + fast-turn) ALL — best** | 3021 | 54% | **−0.018** (avgRR 0.67) | −53.9 |
| **Current LIVE ATR-stop ALL** | 1056 | 23% | **−0.265** | −279.5 |
| Current LIVE on 1-min | 853 | 13% | −0.529 (avgRR 12.4) | −451.2 |

## Reading
- Doctrine claims 60% win @ 3:1; mechanical reality is 31% win, negative EV.
- EVERY geometry/quality cut is negative on total winsorized R. The single best subset
  (loose + vol-convergence + fast-turn) is −0.018 R/trade **before** commissions/slippage,
  and its positive median (+0.074) is an artifact of many tiny +R winners that the full
  −1R losers swamp (avgRR collapses to 0.67).
- The current production ATR-floored-stop geometry is the WORST variant everywhere
  (−0.27 to −0.53 R/trade): the `vwap − atr*0.33` stop + measured target inflates RR to
  4.3–12.4×, so targets almost never fill (win 13–23%).
- The cheat sheet's edge depends on discretionary read (convergence/divergence volume
  texture, steady speed off the turn, chop avoidance) that does not survive mechanization.

## Action
- Patcher: `backend/scripts/patch_v357_fashionably_late_suppress.py` (anchored-chunk, whole-file
  PRE-SHA guard + exact OLD-bytes match, --check dry-run, auto-backup). Swaps the function body
  for `return None` + this rationale docstring.
- Regression test: `backend/tests/test_v357_fashionably_late_suppress.py`.
- Diag paste: https://paste.rs/3I33Q  (sha 97dcf456…900b2).

## Next setup in queue
`squeeze` / `daily_squeeze` (high-fire, no cheat sheet → research generic +EV params), then
`first_move_up/down`, `big_dog`, `gap_give_go`, `spencer_scalp`.
