# v353 — Second Chance Scalp rewrite (build state)

## Decision
LIVE `_check_second_chance` is a near-VWAP momentum filter → NEGATIVE EV.
Replay (diag_v353): LIVE-PROXY winsorAvg −0.062R over 3761 fires (−233R).
DOCTRINE (resistance break → low-vol retest → confirm), RR-gated 1.5–2.5:
  - 14d vol-filter 1.3: n=211, 39% win, +0.092R, avgRR 1.92
  - 21d no vol-filter:  n=381, 38% win, +0.048R, avgRR 1.89
→ SHIP rewrite, RR gate [1.5, 2.5], vol filter 1.3, 2 attempts/day.

## Doctrine params (locked in NEW func)
RESLOOK=15 RUSHWIN=6 RETTEST=4 RETTOL=0.20 SUPPORTTOL=0.15 MINBREAK=0.10
VOLMULT=1.3 MAXBREAKMULT=1.0 MIN_RR=1.5 MAX_RR=2.5
stop = turn_low − 0.02 ; target = rush_high ; entry = confirm-bar close
caps key = f"{symbol}:{today}:long", max 2/day. New attr: self._second_chance_daily_caps

## Patcher anchors
FILE = backend/services/enhanced_scanner.py
POST_FUNC_SHA = 7830560a5aca78cc42f2c553e3883c37b486e8b3d9f081d2692ca2efd562d892
NEW_B64: stored in /tmp/new_second_chance.txt (sandbox) — regenerate via base64 of that file.
SANDBOX PRE_FUNC_SHA = 877ae4b7dae11ab687e685c4916b705e3b37887b926cbea5cba53d33ae8b164b
SANDBOX whole-file SHA = 8a3a82fffae1128664e3ab90532343ad5504708994eadc530a261c212e3c2ec5
DGX whole-file SHA + PRE_FUNC_SHA + OLD_B64 = PENDING operator extractor run (paste.rs/9dRHd).

## Scripts (paste.rs)
diag_v353_second_chance_replay.py → https://paste.rs/zbraX (sha 0453cdede28f...)
extract_v353_second_chance.py     → https://paste.rs/9dRHd (sha b3aeeeea0962...)

## DGX pinned values (from extractor on DGX)
DGX_WHOLE_PRE = 907581dcf313c5d1ba4e275d2de548dbf8f5119ecd479129c8dad63d77f0a50e
PRE_FUNC_SHA  = 3b3d1209aa10f8032323154952387de633c0a0931ff1e2bfc20b19bbb7862cb1
POST_FUNC_SHA = 7830560a5aca78cc42f2c553e3883c37b486e8b3d9f081d2692ca2efd562d892

## SHIPPED (paste.rs) — round-trip verified
patch_v353_second_chance_doctrine.py → https://paste.rs/jDGfl  sha 547f642d9da7fb01108661bd93293e10de734948f51d0ecd334c8e75d3ab43ed
test_v353_second_chance.py           → https://paste.rs/OpbLr  sha f4270eafc66350756525d617a970c5f7ff0427494f5bf30f320f2535a2c2f2f4
All 6 test scenarios validated locally vs the NEW function (fire stop=99.98/target=100.60/RR=1.82; 5 no-fire guards).

## Status: DEPLOYED ✅ (operator applied, 6/6 pytest, committed, backend GREEN 8/8).
## NEW LIVE BASELINE whole-file SHA (enhanced_scanner.py) = 3611da4854a7fff120793d4c882de141c3e1a663cd08bd9ba8cc25928635d0af
##   -> use this as DGX_WHOLE_PRE for the NEXT patcher (re-extract to confirm).

## NEXT MOMENTUM SETUPS (by frequency, same replay→validate→patch flow)
vwap_bounce, orb, first_move_up, first_move_down, fashionably_late, daily_breakout,
big_dog, gap_give_go, spencer_scalp. Then +EV research for squeeze, relative_strength_long,
daily_squeeze (no cheat sheet). Cheat sheets available as artifacts (get_assets_tool).
