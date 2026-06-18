# v363 — `spencer_scalp` → DOCTRINE REWRITE (LONG-only, range-break, 2R)

**Date:** 2026-06-18
**Setup:** `spencer_scalp` (INT-22, methodical-accumulation breakout, LONG).
**Verdict:** REWRITE to SMB cheat-sheet doctrine, LONG-only (the live code was a loose near-HOD proxy).
**Live file built against:** `enhanced_scanner.py` whole-file SHA
`e77006287b3ce31c327f41c6bb5dd7dfedd72cdb4388f98d9826433736c55692` (post-v362).
`_check_spencer_scalp` PRE_FUNC_SHA `e11acffc33a03e6300f5539d6420f5b211b70d7ff58da070f3d645167fd5684b`.

## Doctrine (Spencer+Scalp cheat sheet) vs prior code
Doctrine: an "in-play" stock consolidates **≥20 min** in the **upper 1/3 of the day's range** in a
**tight band (<20% of the day range)** on sustained volume; a **low-volume pause then a volume surge**
breaks the range → enter the break, **stop .02 beyond the range**, **measured-move scale-out**
(½@1R, ½@2R, ½@3R). Works long & short.

Prior `_check_spencer_scalp`: `dist_from_hod<1% + daily_range_pct<3% + rvol≥1.5`, LONG-only,
trigger=HOD, **stop=cp−0.5·ATR**, **target=HOD+1.5·ATR** — modeled none of the 20-min-range / range
stop / measured-move structure, and **never filled live** (ground truth: 0 closed, 9 simulated).

## Evidence (diag_v363_spencer_scalp_doctrine.py, 180d / 300-sym, 1-min; ~390 bars/session)
| cut | side | n | win% | winsorAvg(±3) R | medR |
|---|---|---|---|---|---|
| baseline scaled exit | LONG | 27948 | 51% | +0.036 | +0.043 |
| baseline scaled exit | SHORT | 24916 | 50% | +0.012 | +0.000 |
| **band<0.15 + vol-surge 1.3, scaled** | **LONG** | **17729** | **52%** | **+0.063** | +0.113 |
| band<0.15 + vol-surge 1.3, scaled | SHORT | 15406 | 50% | +0.017 | +0.000 |
| fixed 2.0R + price≥$10 | LONG | 25946 | 45% | +0.043 | −0.185 |
| morning-only 09:59–11:00 | ALL | 1700 | 46% | **−0.055** | −0.170 |
- **SHORT ~0** across cuts → dropped (kept LONG-only). **Morning-only −EV** → kept all-day (`_RTH_ALL_DAY`).
- Edge is **thin** (~+0.04..0.06R) — far below gap_give_go (+0.233) — but real and doctrine-faithful.
- Shipped a **detector-only fixed 2.0R target** (the scaled 1R/2R/3R exit needs position-management work).

## Action — new `_check_spencer_scalp` (v363, LONG-only)
Fetches 1-min bars via `self.technical_service._get_intraday_bars_from_db(symbol, "1 min", 60)`.
Gates: day_range>0; consolidation = last **20 bars**, band `< 0.15·day_range`, with `range_low ≥
low_of_day + 0.667·day_range` (upper 1/3); break-bar volume `≥ 1.3×` the consolidation avg.
**Entry** = `range_high+0.01` (fires only when `cp ≥ entry or last_bar_high ≥ entry`).
**Stop** = `range_low−0.02`. **Target** = `entry + 2.0·risk`. `risk_reward=2.0`. All-day (RTH).
- Patcher `backend/scripts/patch_v363_spencer_scalp_doctrine.py` (anchored-chunk, whole-file PRE-SHA
  `e7700628…` guard, OLD anchor count==1, post-replace self-check **+ py_compile**, `--check`,
  auto-backup `*.v363.bak`). Built via programmatic decode→rewrite→encode off the operator extract.
- Regression test `backend/tests/test_v363_spencer_scalp_doctrine.py` (fires w/ correct 2R geometry;
  blocked when not upper-1/3 / band too wide / no vol surge / no break). Behaviorally validated locally.

## Deploy (DGX, repo root)
```bash
curl -sS -o /tmp/patch_v363.py https://paste.rs/<id>
.venv/bin/python /tmp/patch_v363.py --check
.venv/bin/python /tmp/patch_v363.py
curl -sS -o backend/tests/test_v363_spencer_scalp_doctrine.py https://paste.rs/<test-id>
.venv/bin/python -m pytest backend/tests/test_v363_spencer_scalp_doctrine.py -q
git add backend/ memory/ && git commit -m "v363: rewrite spencer_scalp to SMB doctrine (LONG-only, range-break, 2R)" && git push origin main
git status --short
./start_backend.sh --force
```

## Setups adjudicated — scalp/intraday queue COMPLETE
v353 second_chance, v354 vwap_bounce (suppress), v355 orb (rewrite), v356 daily_breakout (keep),
v357 fashionably_late (suppress), v358 daily_squeeze (long-only), v359 squeeze (suppress),
v360 first_move_up/down (suppress), v361 big_dog (tighten), v361b big_dog/puppy_dog doctrine re-audit,
v362 gap_give_go (doctrine rewrite, 2R), **v363 spencer_scalp (doctrine rewrite, LONG-only, 2R).**

## Future enhancements logged
- Scaled measured-move exit (1R/2R/3R) for spencer_scalp + gap_give_go's Move2Move double-bar-break
  trail (position-management layer).
- big_dog/puppy_dog doctrine rewrite (mid-day window + above-PDH + consolidation-base stop + trail).
