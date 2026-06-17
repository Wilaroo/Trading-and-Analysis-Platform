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

## Status: AWAITING operator `extract_func.py _check_orb` on DGX (expect whole-file 8a02c523...).
## Then build patch_v355_orb_doctrine.py pinned to DGX PRE + POST c4876ae8.

## Live baseline whole-file SHA = 8a02c5232659732e0191e4ffcee086aed6b53e11cf11689d52cabe3069620864
