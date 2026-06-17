# v354 — VWAP Bounce (audit suppression)

## Decision: SUPPRESS (disable -> return None). No +EV config exists in IB data.
diag_v354 replay (14d, 300 syms):
- LIVE-PROXY (shipped near-VWAP state): n=2387, 59% win, winsorAvg -0.101R, -242R total, avgRR 0.85 -> BLEEDS.
- DOCTRINE (First VWAP Pullback: up-leg -> pullback holds VWAP -> confirm, measured-move target):
  - legmult 1.0: all -0.108R; best band (1.5-2.5) +0.001R (breakeven)
  - legmult 0.5 minleg0.5: all -0.100R; best -0.049R
  - legmult 0.5 minleg1.0: all -0.145R
  - legmult 0.75:        all -0.093R; best -0.058R
  Doctrine entry only 30-43% win regardless of target -> no positive band.
- Open-only (09:35-09:45) variant: n=0 (18-bar lookback impossible that early; needs separate micro model).

## Suppression function
POST_FUNC_SHA = 31514bf95f71512c07e5e2dfa23780ca28515c1f3712926eab12b9d61ec1e5c7
NEW_B64 source: /tmp/new_vwap_bounce.txt (sandbox)

## Scripts (paste.rs)
diag_v354_vwap_bounce_replay.py (legmult) -> https://paste.rs/rvPQZ  sha dfa82bad533de15ba85fe48d256b97bf478dbd3553dc7e92799a7730ef5d8b12
extract_func.py (generic)                 -> https://paste.rs/IrjYa  sha c571d8baea5d913f03dbba24311504df4c124479c685aa6b7697a68944c66ea9

## Suppression patcher — BUILT & SIMULATED (preserves _atr_floored_stop; patched compiles)
DGX_WHOLE_PRE = 3611da4854a7fff120793d4c882de141c3e1a663cd08bd9ba8cc25928635d0af
PRE_FUNC_SHA  = 31de305d0cae62d395e228f2d38dfe846886a08ddc2775a1b9a96186853857a6
POST_FUNC_SHA = 31514bf95f71512c07e5e2dfa23780ca28515c1f3712926eab12b9d61ec1e5c7
patch_v354_vwap_bounce_suppress.py -> https://paste.rs/XrPs8  sha 14ff9063ae0c0b7e2501dea63eef61ee80e701fab82f091f232d79ff78212977
test_v354_vwap_bounce.py           -> https://paste.rs/GWV7u  sha 610fa5589798eb7a36052c0196844e35898111dab5e1dbf2661369ece8daf4f2

## BUGFIX: extract_func.py over-captured when the next sibling was a sync `def` or comment
## (it swallowed _atr_floored_stop). FIXED to stop at first `\n    \S` (4-space sibling).
## Fixed extractor -> https://paste.rs/MMZzt  sha 7cf7f39edab1e8b70b6eba71343ec677e6ab7d58c11e93b048ebbc5852309b6c
## NOTE: v353 second_chance was UNAFFECTED (next sibling was async def _check_backside).

## Status: DEPLOYED ✅ (operator applied, 1/1 pytest, committed, backend GREEN 8/8).
## NEW LIVE BASELINE whole-file SHA = 8a02c5232659732e0191e4ffcee086aed6b53e11cf11689d52cabe3069620864
##   -> use as DGX_WHOLE_PRE for the NEXT patcher (re-extract to confirm).

## Next
1. Operator runs extract_func.py _check_vwap_bounce on DGX -> paste whole-file SHA(=expect 3611da48...)+PRE+OLD_B64.
2. Assemble patch_v354_vwap_bounce_suppress.py pinned to DGX values (POST=31514bf9).
3. test_v354_vwap_bounce.py: assert _check_vwap_bounce returns None for the prior fire snapshot.
4. Apply, pytest, commit, restart.

## Then continue MOMENTUM sweep: orb, first_move_up, first_move_down, fashionably_late,
##   daily_breakout, big_dog, gap_give_go, spencer_scalp. Cheat sheets are uploaded artifacts.
