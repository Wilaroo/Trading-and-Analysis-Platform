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

## Next
1. Operator runs extractor on DGX → paste output.
2. Assemble patch_v353_second_chance_doctrine.py (--check/--apply/--rollback) pinned to DGX values.
3. test_v353_second_chance.py unit test (synthetic bars → fires w/ correct stop/target; non-pattern → no fire).
4. Apply, pytest, commit BEFORE restart, ./start_backend.sh --force.
