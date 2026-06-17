## REWRITE decision: true 15-min OR doctrine, RR-gated [1.5,2.5], volmult 1.5.
## Validated (gated): 14d n=59 49% win +0.321R; 21d n=95 42% win +0.183R, avgRR 1.96. Beats live (bleed).
## New _check_orb: fetch _get_intraday_bars_from_db("1 min",120); OR=first 15min; first break
##   above OR-high + vol>=1.5x OR avg; stop = breakout-bar low*(1-0.05%); target = OR_high+2*OR_h;
##   morning window only, time-exit 11:30 (etm<=690), 1 breakout/day. Removed approaching_orb branch.
## BUGFIX during authoring: guard was OR_MIN+2 (17) which blocked the earliest 09:45 breakout
##   (only 16 bars exist by then) -> relaxed to OR_MIN+1 (16).
## setup_type kept "orb_long_confirmed" (matches prior recorded stats).

POST_FUNC_SHA = c4876ae8c64ffe8c790741272b4c5510440c98847ffe2e365ac6507d32936e50
NEW source: /tmp/new_orb.txt (sandbox)
test_v355_orb.py created (6 scenarios, validated locally vs NEW func).
6 local scenarios PASS: fire(stop98.95/target104.0/rr2.26), no-vol, wrong-window, rr>2.5, not-first, cap.

## Patcher BUILT & SIMULATED (anchor matches DGX; preserves _atr_floored_stop & _check_gap_give_go; compiles)
DGX_WHOLE_PRE = 8a02c5232659732e0191e4ffcee086aed6b53e11cf11689d52cabe3069620864
PRE_FUNC_SHA  = 3507ca0a42c60ea28a8db043040dbf4fd2874a7b20c4e4d774c839738248b5dd
POST_FUNC_SHA = c4876ae8c64ffe8c790741272b4c5510440c98847ffe2e365ac6507d32936e50
patch_v355_orb_doctrine.py -> https://paste.rs/9Jw3f  sha 136fe5caf317ba68fda2798504d6e549d2f33bafc61e350e3e017e74cf01c362
test_v355_orb.py           -> https://paste.rs/Ovd5j  sha c463e19be8c0c435f104a4e64aa8f1a94422b487ffd69c9470dbb07d5f409589

## Status: DEPLOYED ✅ (operator applied, 6/6 pytest, committed 8c930d57, backend GREEN 8/8).
## NEW LIVE BASELINE whole-file SHA = bacf7753595c6b2479db0a5cecc8dccf4193fc34b6bebfbb014fe994ae3ebcb7
##   -> use as DGX_WHOLE_PRE for the NEXT patcher (re-extract to confirm).
## Next setup: first_move_up / first_move_down.

## Live baseline whole-file SHA = 8a02c5232659732e0191e4ffcee086aed6b53e11cf11689d52cabe3069620864
