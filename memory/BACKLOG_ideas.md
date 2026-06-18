# Backlog / Future Ideas

## Setup-EV-Audit live dashboard (saved 2026-06-18)
Add `GET /api/scanner/setup-ev-audit` + a small V5 tile that surfaces, per setup:
verdict (preserve / long-only / rewrite / suppressed), last-audited EV (winsorAvg R + win%),
sample size, and audit date. Turns the per-setup build-docs (v353–v359…) into a live dashboard
so the operator can see at a glance which detectors are doctrine-aligned vs pending.
Source of truth: the memory/v3xx_*_build.md docs (could seed a small `setup_ev_audit` Mongo
collection the patchers/diag scripts write to). P2 — do after the setup-alignment queue.

### Adjudicated so far (Replay→Validate→ground-truth template)
- v353 second_chance — re-aligned (gated RR 1.5–2.5)
- v354 vwap_bounce — SUPPRESSED (negative-EV)
- v355 orb — REWRITTEN (true 15-min OR doctrine)
- v356 daily_breakout — PRESERVED (naturally +EV)
- v357 fashionably_late — SUPPRESSED (negative-EV)
- v358 daily_squeeze — LONG-ONLY (short branch -EV)
- v359 squeeze — SUPPRESSED (negative-EV daily-compression duplicate of daily_squeeze)
- v360 first_move_up + first_move_down — BOTH SUPPRESSED (negative-EV counter-trend morning fades)
- v361 big_dog — TIGHTENED (min-price $10 + min-stop 1.0%; baseline breakeven -> +0.097R win53% n=268)

### Queue remaining
gap_give_go → spencer_scalp
