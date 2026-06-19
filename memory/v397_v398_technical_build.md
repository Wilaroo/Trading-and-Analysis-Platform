# v397 / v398 — Technical pillar no-live-quote gap (2026-06-19)

## v397 — read-only cross-tab (paste.rs https://paste.rs/q6EY0)
`backend/scripts/diag_v397_technical_blind.py`. Live DGX (50k alerts):
- RVOL==1.0 default 45.4% · RSI==50 default 47.0% · Levels==50 62.8%
- SNAPSHOT-NONE signature (rvol==1.0 AND rsi==50): 45.2% → the WHOLE 25% Technical
  pillar defaults for ~45% of alerts.
- Within real snapshots (54.8%): levels well-distributed (50:32%, 35:20%, 20:12%,
  45:12%, 100:6%, 95:5%...) → 20-day min/max S/R is FINE; no rework needed.

Root cause: realtime_technical_service.get_technical_snapshot() returns None when
there's no live IB pusher quote at score time (deliberate "no live data = no scan"
guard). None → technical pillar defaults rsi/atr/rvol/levels/trend.

## v398 — fix (paste.rs https://paste.rs/dGfdJ) 2 files, ON TOP OF v391
- realtime_technical_service.py  PRE 570c0919 (git HEAD) → POST fe09904b
  - get_technical_snapshot(..., allow_stale_price=False) new kwarg.
  - When True and no live pusher quote: build quote from latest stored Mongo bar
    (intraday last close, else daily). Scanner/auto-exec keep fail-closed (don't
    pass the flag) → live-trade triggering UNCHANGED.
- technical_quality.py  PRE 1de445fc (v391 POST) → POST d0992e0f
  - TQS technical pillar calls get_technical_snapshot(symbol, allow_stale_price=True).
- Verified live: 8 no-quote symbols now return real price/rsi/support/resistance
  from Mongo bars (were None pre-v398). Committed 1a848ab6.

Minor follow-up noted: RSI can saturate (100/0.0) on thin/one-directional stored
bars — pre-existing snapshot artifact, now surfaced for more symbols. Optional
RSI clamp / min-bars guard later.

## TQS AUDIT — all scoring/data blinds now closed
Setup(Pattern/Tape/EV-honest/SMB✅) · Technical(v398) · Fundamental(Institutional
v391 / Financial v396) · Context(Sector v394) · Execution(Entry-tendency v391).

## STILL OPEN (feed-plumbing + scheduler)
- Tape feed (68% no L2/tape read) — scoring fixed v393; live tape source = plumbing.
- RVOL (45% default 1.0) — secondary volume feed for names outside top-400 push.
- EV (51.5% proxy) — cold-start learning gap; honest since v391; self-heals.
- 🟡 Issue 2 — wire warm-fundamentals into scheduler_service.py for nightly re-warm.
