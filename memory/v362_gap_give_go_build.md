# v362 — `gap_give_go` → DOCTRINE REWRITE (give→consolidation→range-break, 2R)

**Date:** 2026-06-18
**Setup:** `gap_give_go` (INT-34, morning gap-up give-and-go continuation, LONG).
**Verdict:** REWRITE to SMB cheat-sheet doctrine (the live code was a loose VWAP-pullback proxy).
**Live file built against:** `enhanced_scanner.py` whole-file SHA
`8df7dd8c5da7bd92d53d8a5d0d5862d82ae8b22ab3b8bb8e5446d8dca37f7b9e` (post-v361).
`_check_gap_give_go` PRE_FUNC_SHA `c93d0b9eb38b6dead47494911fb56f7f4bd504879a8cd934fc9a5f2d8bf8c1d6`.

## Why a rewrite (not a tighten/suppress)
The operator flagged the **Gap_Give_and_Go_Cheat_Sheet.pdf**. The doctrine is a **1-minute** setup the
live code never modeled:
- Gap UP, then a quick **"give"** (pullback) off the open that **holds above prior close** and closes
  **<50% of the gap** (over-extension guard).
- A **3–7 min mini-consolidation** on **declining volume** (≤50% of prior).
- **ENTER** on the **break of the 1-min consolidation range**, **before 9:45 ET** (opening drive).
- **STOP** **.02 below the consolidation low**; **2 attempts**.
- **EXIT** Move2Move (double-bar-break trail).

The live `_check_gap_give_go` instead used `gap>3% + above_vwap + 0<distVWAP<1.5 + rvol≥2`, a market
entry near VWAP, a **VWAP-based stop**, and a **fixed HOD target** — none of the give/consolidation/
range-break structure.

## Evidence (diag_v362b_gap_give_go_doctrine.py, 180d / 300-sym, 1-min; 1-min history present, ~390 bars/session)
| model | n | win% | winsorAvg(±3) R | note |
|---|---|---|---|---|
| code-mirror (5-min, current logic) | 3398 | 50% | +0.069 | breakeven; +0.018 after slippage levers |
| DOCTRINE double-bar-break exit | 492 | 41% | +0.125 | structure edge confirmed |
| **DOCTRINE 2.0R fixed target, gap≥1% band≤0.6%** | **492** | **47%** | **+0.233** | **SHIPPED config** (detector-only) |
| DOCTRINE 2.0R, gap≥2% band≤0.4% | 128 | 47% | +0.282 | cleaner subset, smaller n |
| DOCTRINE 3.0R, gap≥2% band≤0.4% | 128 | 45% | +0.403 | tail-dependent (rejected: less robust) |
- Ground truth (`diag_setup_ground_truth.py`): 8 real fills, −1.32R — but tiny n and several artifact
  closes (external_close / phantom_swept). The replay drives the verdict.
- A fixed **2.0R target** was chosen over the double-bar-break trail so the rewrite is **detector-only**
  (no exit-management changes) while preserving ~the same EV (+0.233R).

## Action — new `_check_gap_give_go` (v362)
Opening-drive only (`OPENING_AUCTION`/`OPENING_DRIVE`). Fetches 1-min bars via
`self.technical_service._get_intraday_bars_from_db(symbol, "1 min", 60)` (same pattern as the live
vwap_fade detector). Gates: `gap_pct≥1.0`, `prev_close>0`, `day_open>prev_close`. Scans the last
3–7 completed bars for a consolidation with band ≤0.6% of price that (a) sits below the session high
(a give happened), (b) holds above prior close, (c) whose pre-consolidation give filled ≤50% of the
gap, (d) on declining volume (cons avg ≤0.7× give avg). **Entry** = `cons_high+0.01`; fires only when
`cp ≥ entry or last_bar_high ≥ entry` (range break printing). **Stop** = `cons_low−0.02`.
**Target** = `entry + 2.0·risk`. `risk_reward=2.0`.
- Patcher `backend/scripts/patch_v362_gap_give_go_doctrine.py` (anchored-chunk, whole-file PRE-SHA
  `8df7dd8c…` guard, OLD anchor count==1, post-replace self-check **+ py_compile of the patched file**,
  `--check` dry-run, auto-backup `*.v362.bak`).
- Regression test `backend/tests/test_v362_gap_give_go_doctrine.py` (fires w/ correct entry/stop/2R
  geometry; blocked outside opening drive / gap<1% / no break / band too wide / give>50% fill).
- Behaviorally validated locally in a stub harness (valid fire + 5 invalidations) before pasting.

## Deploy (DGX, repo root)
```bash
curl -sS -o /tmp/patch_v362.py https://paste.rs/<id>
.venv/bin/python /tmp/patch_v362.py --check
.venv/bin/python /tmp/patch_v362.py
curl -sS -o backend/tests/test_v362_gap_give_go_doctrine.py https://paste.rs/<test-id>
.venv/bin/python -m pytest backend/tests/test_v362_gap_give_go_doctrine.py -q
git add backend/ memory/ && git commit -m "v362: rewrite gap_give_go to SMB doctrine (give->consolidation->range-break, 2R)" && git push origin main
git status --short
./start_backend.sh --force
```

## Minor fidelity notes
- Replay used the first RTH bar's high for the "give" check; the live detector uses `snapshot.high_of_day`
  (session high) — equivalent for a gap-up-then-give-then-consolidate, slightly stricter.
- The doctrine's double-bar-break trail is replaced by a fixed 2R target to stay detector-only; a future
  enhancement could add the Move2Move trail in position management (replay shows the trail is also +EV).

## Setups adjudicated so far (Replay→Validate, cheat-sheet-aware)
- v353 second_chance, v354 vwap_bounce (suppress), v355 orb (rewrite), v356 daily_breakout (keep),
  v357 fashionably_late (suppress), v358 daily_squeeze (long-only), v359 squeeze (suppress),
  v360 first_move_up/down (suppress), v361 big_dog (tighten: $10 + 1% min-stop),
  v361b big_dog/puppy_dog doctrine re-audit (keep v361, queue P1 doctrine rewrite),
  **v362 gap_give_go (DOCTRINE rewrite, 2R).**

## Next in queue
`spencer_scalp` (consult Spencer+Scalp+Cheat+Sheet.pdf first).
