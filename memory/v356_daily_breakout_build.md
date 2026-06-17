# v356 — Daily Breakout (swing) evaluation — HIGHEST AUTO-EXEC (74/5d)

## Live _check_daily_breakout (line 8210, takes daily bars)
- Long when close breaks 20-day high by 0.5-8% on adaptive volume (rvol>=1.5/1.3/1.2 by ATR%).
- stop = prev_high - 0.5*ATR; target = entry + 2*(entry-stop); R:R NOT gated. Multi-day hold, 24h expiry.
- setup_type="daily_breakout", swing tier, HIGH priority (auto-fires aggressively).

## diag_v356_daily_breakout_replay.py -> https://paste.rs/SHXU6  sha 596fcb5be739a7bd2ee4370908b742fc1b3ea0fda4b98b0f4eec6399c6aa0272
DAILY-bar replay, exact live logic, multi-day exit (--maxhold), RR buckets. Params:
--days 180 --barsize "1 day" --lookback 20 --minbreak/--maxbreak --maxhold --minrr/--maxrr --cooldown --universe.

## Status: AWAITING operator replay output. First confirm daily bar_size label (distinct bar_size).
## Decision: +EV overall -> keep; band-only +EV -> gate; negative -> tighten/suppress.

## Live baseline whole-file SHA = 30eba7d1faf17f1c4fa0794c564e5790b73e4baf0b35f04095a1cbc16d03b1ac

## NOTE: first_move_up/down deferred — near-dormant (0-1 fires/5d). Operator chose (A) daily_breakout.
## Pending verification (next session, market reopens): diag_live_setup_fires.py --hours 8
##   expect vwap_bounce->0, approaching_orb->0, orb/orb_long_confirmed>0, second_chance continuing.
