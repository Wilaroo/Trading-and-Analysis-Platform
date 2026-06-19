# v392 / v393 — Blind sub-score diag + Pattern/Tape fixes + Sector probe (2026-06-18)

## v392 — read-only blind sub-score coverage diag (paste.rs https://paste.rs/rBhpE)
`backend/scripts/diag_v392_blind_subscores.py` — measures default-vs-real rates
across persisted live_alerts.tqs_breakdown. Live DGX results (50k alerts,
May29–Jun18):
- Sector   100.0% blind  🔴 (dead — sector_service returns None for whole book)
- Tape      67.9% blind  🔴 (alert.tape_score==0 → else-30)
- Pattern   62.5% blind  🔴 (44 setup_types unmapped in SETUP_BASE_SCORES → 50)
- EV        51.5% proxy  🔴 (cold-start setups w/o strategy stats; 48.5% real)
- RVOL      45.4% default 🟠 (rvol==1.00; live-volume gap, not punitive)

Top unmapped setups (n): daily_squeeze 6329, trend_continuation 3438,
accumulation_entry 3420, power_trend_stack 3339, off_sides 2078, breakdown 2067,
pocket_pivot 1664, rs_leader_break 1373, daily_breakout 1361, stage_2_breakout 1137…

## v393 — Setup pillar fixes (paste.rs https://paste.rs/oVyXs) APPLIES ON TOP OF v391
setup_quality.py  PRE c1ca91932e190b96 (v391) → POST dfc16585849894bf
- PATTERN: when canonical base not in SETUP_BASE_SCORES, derive from setup_taxonomy
  (strategy_family→setup_class): breakout 68 / continuation 66 / reversion 62 /
  reversal 58 / rotation 60 / swing 64 / position 62 / unknown 55. Anchored to the
  explicit tiers; explicit map stays as override. Future-proof (new setups auto-tier).
- TAPE: tape_score==0 = NO tape/L2 reading (not weak) → neutral 50 (was punitive 30).
  Measured-weak (0<score<4) keeps its penalty.
- Verified locally: daily_squeeze→68, trend_continuation→66, accumulation_entry→58,
  pocket_pivot/rs_leader_break→68, orb→80, bull_flag→78, made-up→55; tape 0→50, 7.5→60, 2.0→20.

## v392b — Sector root-cause probe (paste.rs https://paste.rs/HT2GN) READ-ONLY
`backend/scripts/diag_v392b_sector_probe.py`. Root cause (from code):
`sector_analysis_service.get_sector_rankings()` pulls sector-ETF quotes via
`alpaca_service.get_quotes_batch()` — alpaca is DEAD on the ib-direct DGX → empty
rankings → `get_stock_sector_context()` returns None → "unknown" for every alert.
Second cause: STOCK_SECTORS only maps 34 symbols (universe ~1364).
Probe checks: (1) ib_historical_data daily bars for the 10 sector ETFs
(XLK/XLF/XLE/XLV/XLI/XLC/XLY/XLP/XLU/XLB), (2) symbol_adv_cache.sector universe
coverage, (3) alert-symbol coverage. Verdict → FIXABLE via IB bars or names blockers.

### PLANNED Sector fix (pending probe output) — v254-style
Rank sector ETFs from ib_historical_data daily 1d %, map symbol→sector from
symbol_adv_cache.sector, compute stock_vs_sector from the symbol's own daily 1d %
vs its ETF. No alpaca dependency. Gated on probe confirming bars + tags exist.

## Deferred (no honest scoring fix)
- EV: cold-start learning-data gap (strategy_ev_r only stamped when setup has
  strategy stats). v391 already made the proxy honest. Self-heals with outcomes.
- RVOL: not punitive at default; real fix = secondary volume feed (plumbing).
