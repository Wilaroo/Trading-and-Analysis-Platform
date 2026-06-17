# v355 — Opening Range Break (ORB) evaluation

## Cheat sheet (SMB Opening Range Break)
- Opening range = high/low of first 5/15/30 min (higher volume -> shorter range).
- Entry: break ABOVE OR-high (long) WITH volume expansion + tape (flood of green).
- Stop: just BELOW the breakout bar (NOT full range low). Or 2-min trailing if rvol>3.
- Target: 2x measured move of the OR (OR_high + 2*OR_height). R:R >= 2:1.
- Time exit 10:30 / 11:30 ET. Trending only (avoid chop). Win rate: not specified.

## Live _check_orb deviations (line ~4895)
- Uses running HOD/LOD as "opening range" (drifts all morning).
- stop = LOD-0.02 (full-day low, far); target = price + 2*(HOD-LOD); R:R hardcoded 2.0.
- Two branches: orb_long_confirmed (broke HOD 0.1-1.5%) + approaching_orb. Morning window, rvol>=2.

## diag_v355_orb_replay.py -> https://paste.rs/xFCEN  sha f2b7f31f3cc677ae5acbcb1748a7d40fd57a10962c9ae8b89c25d09436e5e89f
Arms: LIVE-PROXY (HOD/LOD rule) vs DOCTRINE (true first-N-min OR, stop below breakout bar,
target 2x OR, time-exit, one/day). Params: --ormin 5/15/30 --timeexit 630/690 --volmult --tmult --maxrr.

## Status: AWAITING operator replay output (runs A/B/C).
## Decision: +EV doctrine band beating live -> rewrite _check_orb; else suppress.

## Current live baseline whole-file SHA = 8a02c5232659732e0191e4ffcee086aed6b53e11cf11689d52cabe3069620864
