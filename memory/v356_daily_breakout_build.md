# v356 — Daily Breakout (swing) evaluation — HIGHEST AUTO-EXEC (74/5d)

## Live _check_daily_breakout (line 8210, takes daily bars)
- Long when close breaks 20-day high by 0.5-8% on adaptive volume (rvol>=1.5/1.3/1.2 by ATR%).
- stop = prev_high - 0.5*ATR; target = entry + 2*(entry-stop); R:R NOT gated. Multi-day hold, 24h expiry.
- setup_type="daily_breakout", swing tier, HIGH priority (auto-fires aggressively).

## diag_v356_daily_breakout_replay.py -> https://paste.rs/SHXU6  sha 596fcb5be739a7bd2ee4370908b742fc1b3ea0fda4b98b0f4eec6399c6aa0272
DAILY-bar replay, exact live logic, multi-day exit (--maxhold), RR buckets. Params:
--days 180 --barsize "1 day" --lookback 20 --minbreak/--maxbreak --maxhold --minrr/--maxrr --cooldown --universe.

## RESULT: VALIDATED +EV — KEEP AS-IS (no patcher). ✅
Replay (180d, 400 syms, IB daily bars):
- 20d lookback/10d hold: n=24086, 41% win, winsorAvg +0.060R, +1455R total, avgRR 2.0
- 50d lookback/10d hold: n=13140, 41% win, +0.041R, +537R
- 20d/5d hold/cooldown5: n=22142, 44% win, +0.051R, +1123R
All +EV across 24k events & variants. Most-auto-executed setup (~15x/day) is profitable & robust.
No rewrite/suppression. All trades in 1.5-2.5 RR band (avgRR 2.0) so a gate would change nothing.
bar_size labels present: '1 day','1 hour','1 min','1 week','15 mins','30 mins','5 mins'.

## Status: AUDITED — KEEP. No deploy needed.
## Next pick offered: (a) fashionably_late [cheat sheet, 10 auto-exec] (b) squeeze/daily_squeeze [no sheet, highest alerts].

## Live baseline whole-file SHA = 30eba7d1faf17f1c4fa0794c564e5790b73e4baf0b35f04095a1cbc16d03b1ac

## NOTE: first_move_up/down deferred — near-dormant (0-1 fires/5d). Operator chose (A) daily_breakout.
## Pending verification (next session, market reopens): diag_live_setup_fires.py --hours 8
##   expect vwap_bounce->0, approaching_orb->0, orb/orb_long_confirmed>0, second_chance continuing.
