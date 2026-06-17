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

## Next
1. Operator runs extract_func.py _check_vwap_bounce on DGX -> paste whole-file SHA(=expect 3611da48...)+PRE+OLD_B64.
2. Assemble patch_v354_vwap_bounce_suppress.py pinned to DGX values (POST=31514bf9).
3. test_v354_vwap_bounce.py: assert _check_vwap_bounce returns None for the prior fire snapshot.
4. Apply, pytest, commit, restart.

## Then continue MOMENTUM sweep: orb, first_move_up, first_move_down, fashionably_late,
##   daily_breakout, big_dog, gap_give_go, spencer_scalp. Cheat sheets are uploaded artifacts.
