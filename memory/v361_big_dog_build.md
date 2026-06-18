# v361 — `big_dog` evaluation → TIGHTENED (min-price $10 + min-stop 1.0%)

**Date:** 2026-06-18
**Setup:** `big_dog` (INT-44, tight-consolidation HOD breakout, LONG). Alias `puppy_dog` left unchanged.
**Verdict:** TIGHTEN (NOT suppress) — big_dog is +EV once the slippage tail is gated out.
**Live file built against:** `enhanced_scanner.py` whole-file SHA
`0569a72496a91696dffc954223197f5d32ae2a10c9205a510743a38f50de6314` (post-v360).
`_check_big_dog` PRE_FUNC_SHA `5df2f5831f541da147782d2cc776b6824667c26f14e1d94a395ff5f3ee4070b0`.

## Structural finding
`_check_big_dog` fires LONG when the session is tight (`daily_range_pct<2%`), price is above
VWAP + 9-EMA with `rvol>=1.2`, and price is coiled within 1% below HOD. The live trigger is a
buy-stop at HOD; stop = ATR-floored `ema_9-0.02` (anchored to cp), target = HOD+1.5·ATR. The
realized RR collapses to ~1.05 (entry at HOD sits well above the cp-anchored stop), so at a 46%
win the raw setup is breakeven. The losses concentrate entirely on **tight-stop fires on
low-priced/illiquid names** that gap *through* the stop.

## Evidence
1. **Intraday replay** (`diag_v361_big_dog_replay.py`, 180d / 300-sym, 5-min; LIVE trigger@HOD cut):
   | cut | n | win% | winsorAvg(±3) R | medR | avgRR |
   |---|---|---|---|---|---|
   | baseline | 38166 | 46% | −0.009 | +0.000 | 1.05 |
   | + min-stop≥1% + price≥$10 | 268 | 53% | **+0.097** | +0.132 | 1.32 |
   | tighter coil only (range<1.5%, distHOD<0.5%) | 27331 | 44% | −0.013 | +0.000 | 1.07 |
   | all combined | 31 | 61% | +0.235 | +0.329 | 1.41 |
   The stop/price floor is the lever; **tightening the coil alone does nothing**. The combined
   cut (n=31) has higher EV but too thin to gate on — production uses the n=268 floor config.
2. **Ground truth** (`diag_setup_ground_truth.py`, 5 real closed fills): avgR **−2.0**, win 20%,
   net −$1,959 — every loss a sub-1% stop on a <$30 name (e.g. KRG $25.86, stop 25.74 → gapped
   to 25.53). Exactly the population the v361 gates exclude. (puppy_dog n=2 +0.3R — too thin, left as-is.)
3. **MKT@signal** cut was −0.025R (worse than trigger@HOD) → the HOD breakout buy-stop is the
   correct execution; no entry-anchor rewrite needed, only the slippage gates.

## Action
- Patcher `backend/scripts/patch_v361_big_dog_gates.py` (anchored-chunk, whole-file PRE-SHA
  `0569a724…` guard, `--check` dry-run, auto-backup). Two additions to `_check_big_dog`:
  1. `current_price >= 10.0` in the entry gate (drop illiquid).
  2. Precompute the ATR-floored `stop`; if `(cp - stop)/cp*100 < 1.0` → `return None` (reject
     tight-stop blow-throughs). The surviving `LiveAlert` reuses that `stop`.
  Everything else (coil/VWAP/EMA9/rvol gates, geometry, target) is unchanged.
- Regression test `backend/tests/test_v361_big_dog_gates.py` (price floor / min-stop floor block;
  clean liquid coil fires with a ≥1% stop; original rvol gate still applies).
- Diag: `diag_v361_big_dog_replay.py` (faithful HOD-breakout model + market-at-signal cut +
  `--min-stop-pct`/`--min-price`/coil/window probes).

## Deploy (DGX, repo root)
```bash
curl -sS -o /tmp/patch_v361.py https://paste.rs/<id>
.venv/bin/python /tmp/patch_v361.py --check
.venv/bin/python /tmp/patch_v361.py
curl -sS -o backend/tests/test_v361_big_dog_gates.py https://paste.rs/<test-id>
.venv/bin/python -m pytest backend/tests/test_v361_big_dog_gates.py -q
git add backend/ memory/ && git commit -m "v361: big_dog +\$10 min-price +1% min-stop gates (cut slippage tail)" && git push origin main
git status --short
./start_backend.sh --force
```

## Setups adjudicated so far (Replay→Validate template)
- v353 second_chance (re-aligned), v354 vwap_bounce (suppressed), v355 orb (rewritten),
  v356 daily_breakout (preserved +EV), v357 fashionably_late (suppressed),
  v358 daily_squeeze (long-only), v359 squeeze (suppressed),
  v360 first_move_up + first_move_down (suppressed),
  **v361 big_dog (tightened: min-price $10 + min-stop 1.0%).**

## Next in queue
`gap_give_go`, `spencer_scalp`.
