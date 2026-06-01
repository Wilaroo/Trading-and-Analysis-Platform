## 2026-06-01 — v19.34.207 SMB 5-VARIABLE SCORING WIRED INTO LIVE SCANNER (Setup-pillar de-starvation)

### Why
`smb_score_total` was a flat **25** for every alert. Root cause: the live
scanner's only call to `populate_smb_fields` (`enhanced_scanner._process_new_alert`)
built the context with just `{market_regime, tape_score}` — it **never passed an
`smb_score`**, so the `SMBVariableScore` branch was skipped and the dataclass
default 25 stuck. That flat 25 then fed the TQS Setup pillar's SMB component
(15% weight), collapsing the spread.

### Fix (Approach A — canonical 11-point checklist)
- `services/enhanced_scanner.py` — new `async _compute_smb_5var(alert)` maps the
  alert's `TechnicalSnapshot` + fire-time fields into the canonical 11-point SMB
  checklist (`scoring_engine.evaluate_smb_checklist`) and folds it into the
  5-variable score (`smb_unified_scoring.convert_checklist_to_smb_score`). The
  `_process_new_alert` SMB block now injects `smb_score` (+ `earnings_score`)
  into the context. Snapshot→checklist mapping: gap/rvol→catalyst+volume,
  ema9/ema20/ema50+price→trend+MAs, support/resistance→S/R+R:R+exit,
  vwap/prev_close→MTF, rs/change%→relative-strength, setup_type→proven-success,
  regime→sentiment. Fails safe to the old default on any error.
### Verify
- `tests/test_v19_34_207_smb_5var.py` (4/4). Canonical-path spread:
  STRONG=46/50 (A+), PARTIAL=38/50 (B+), WEAK=25/50 (baseline). No more flat 25.
- DGX live: `/tmp/verify_v19_34_207.py` checks `live_alerts/bot_trades`
  `smb_score_total` distribution at next scan session.

---

## 2026-06-01 — v19.34.205 + v19.34.206 INSTITUTIONAL OWNERSHIP (R4 — final TQS Fundamental pillar component)

### v205 — type-2-only sum (correct bucket)
IB `ReportsOwnership` groups holders by `<type>`; summing ALL types double-counts
(~2x shares-out → 100% everywhere). Sum ONLY `type==2` (13F investment advisors).
Also fetch `shares_outstanding` from ReportSnapshot for the denominator when not
cached. AMD validated at 75.5%.

### v206 — control-stake / stale-artifact exclusion
type-2 alone still over-counted for some names because IB's Refinitiv feed carries
stale **controlling-stake** rows (AB: `AXA Financial`=182% of shares-out; AAMI:
`HNA Capital`=64%) — divested parents far above any free-float 13F position.
`parse_reports_ownership` now EXCLUDES any single type-2 holder whose quantity
exceeds `max_single_holder_frac` (default **50%**) of shares-outstanding, then
caps at 100%. Records `excluded_control_holders` for observability.
### Verify (live IB)
- AMD 75.5% (unchanged), AB 100%→31%, AAMI 100%→67%. Cache spread after refresh:
  93 syms, mean 65.6%, range 1.1–100%, 61/93 in the 20–99% band (was 62/84 at 100%).
- `tests/test_v19_34_206_institutional_ownership.py` (8/8).
- **Known limitation (P2):** ~20 high-institutional large-caps (GS, MS, SBUX…)
  still hit the 100% cap due to intra-type-2 parent/child overlap (e.g. "BlackRock
  Inc" + "BlackRock Fund Advisors" both filing, each <50%). Directionally correct;
  de-saturating needs fragile entity-name dedup → deferred.

---


## 2026-06-02 — v19.34.202 IB-SOURCED FUNDAMENTALS: FLOAT + SHORT-INTEREST% (R2+R3)

### Why (IB probe proof)
`probe_ib_fundamentals.py` (clientId 77, read-only) confirmed the operator's IB
account DOES serve Reuters fundamentals, and that **ReportSnapshot (~10KB)
already carries float + shares-outstanding**:
    <SharesOut Date="2026-04-29" TotalFloat="1623871179.0">1630600639.0</SharesOut>
→ shares-out = element text, float = `TotalFloat` attr. (ReportsOwnership also
works but is 3.6 MB/symbol — too heavy for per-symbol cache fills; institutional
ownership R4 deferred to a low-cadence job.)

Also confirmed the legacy `ib_service` fundamentals path is dead on this deploy
(every cached doc historically `source=finnhub`) → fundamentals must route
through the LIVE `ib_direct` clientId-11 socket.

### Fix
- `services/ib_direct_service.py` — new `get_fundamental_report(symbol,
  report_type="ReportSnapshot")` via `reqFundamentalDataAsync` on the live
  socket (mirrors the `get_contract_industry` guard pattern; 20s timeout).
- `services/ib_fundamentals_parser.py` — `parse_report_snapshot` now extracts
  `shares_outstanding` (`<SharesOut>` text) + `float_shares` (`TotalFloat` attr).
- `services/unified_fundamentals_cache.py`:
  * IB step now prefers `ib_direct` ReportSnapshot (legacy ib_service kept as a
    fallback only if ib_direct is down) → fills `float_shares` (**R3**).
  * New short-interest step: `short_interest_percent = FINRA short shares ÷ IB
    shares-outstanding` via `ShortInterestService.get_short_data_for_symbol`
    (**R2**). FINRA is bi-monthly — the accurate cadence for short interest.
  * New pure helper `compute_short_interest_pct()` (unit-tested).

### Verify
- `backend/tests/test_v19_34_202_ib_fundamentals.py` — 5/5 pass (SharesOut/Float
  parse from real AMD XML, missing-SharesOut safe, SI% math + guards). Lint clean
  on changed regions; all 3 services import OK.
- ✅ VERIFIED LIVE ON DGX (2026-06-01, commit 8f2a9d3b): cleared cache + forced
  in-backend fetch via `/api/tqs/breakdown/{sym}` for AMD/AVGO/ALAB →
  `source=ib_direct_report_snapshot+finnhub+finra_short`, with real
  `float_shares` (AMD 1.62B, AVGO 4.64B, ALAB 153M) and `short_interest_percent`
  (AMD 1.98, AVGO 1.11, ALAB 7.89). The IB ReportSnapshot fetch ONLY fires inside
  the backend process (where the live clientId-11 socket lives) — a standalone
  script has no IB connection and correctly falls back to Finnhub.
- NOTE: the 174 pre-existing cache docs backfill on their own 24h TTL (or force a
  symbol with `verify_v19_34_202.py`).

### Still ahead (this pillar)
R0 earnings_calendar persistence (Finnhub free, 15%), R4 institutional ownership
(IB ReportsOwnership — low-cadence job, 15%).

---


## 2026-06-02 — v19.34.201 FUNDAMENTAL PILLAR: CATALYST/NEWS WIRING (the 30% lever)

### Why (live diag proof)
`diag_fundamental_sources.py` on the DGX confirmed the fundamental pillar's
biggest component — **catalyst (30%)** — was permanently stuck at the
"no catalyst" floor of **40**. Root cause: `tqs_engine.set_services()` only
passed `ib_service` to the fundamental pillar, **never `news_service` or `db`**,
so `FundamentalQualityService._news_service`/`._db` were always None. The
pillar's news + earnings-calendar lookups were dead code → catalyst always 40,
contributing to the flat ~57 fundamental score on every trade.

The probe also proved `news_service.get_ticker_news()` IS alive (Finnhub
company-news + IB news, carries a `sentiment` STRING bullish/bearish/neutral).

### Fix
- `services/tqs/tqs_engine.py` — `set_services()` + `init_tqs_engine()` now
  accept and propagate `news_service` + `db` into the fundamental pillar.
- `server.py` — passes the live `news_service` + `db` into `init_tqs_engine`.
- `services/tqs/fundamental_quality.py`:
  * **News→catalyst enrichment** in `calculate_score`: when the caller didn't
    supply catalyst data and `_news_service` is wired, fetch recent ticker
    news (last 72h, placeholder items excluded), map the sentiment STRING to a
    float (bullish→+1 / bearish→−1 / neutral→0), average it, and route through
    the existing `has_recent_news` branch → catalyst score 50–85 instead of 40.
  * **Latent crash fixed**: `if self._db:` (pymongo `bool(Database)` raises
    `NotImplementedError` per AGENTS.md §6) → `is not None`; and
    `self._db.get("earnings_calendar")` (invalid on Database) → `self._db[...]`.
    These were dormant only because `_db` was always None; wiring it would have
    crashed the pillar without this fix.

### Verify
- `backend/tests/test_v19_34_201_fundamental_news_wire.py` — 5/5 pass (bullish
  lifts catalyst >floor, no-news-service keeps floor, placeholder ignored,
  bearish supports short, explicit caller args override news). Lint clean;
  `server.py` compiles. (Live-server `test_tqs_*_integration` failures in the
  sandbox are pre-existing — empty `REACT_APP_BACKEND_URL`, not this change.)
- ⚠️ OPERATOR LIVE-CHECK after restart: fundamental pillar's catalyst component
  should move off a flat 40 for symbols with recent news; re-run
  `diag_tqs_pillars.py` to confirm fundamental scores start spreading.

### Still ahead (this pillar)
R2 short-interest% (FINRA shares ÷ derived shares-out), R3 float, R0 earnings
persistence, R4 institutional (IB ReportsOwnership). News is the biggest single
lever and ships first.

---


## 2026-06-02 — v19.34.200 NIGHTLY learning_stats REBUILD (TQS setup-pillar data feed)

### Why
The TQS **setup pillar** reads `get_contextual_win_rate(setup_type=base)` from
`learning_stats`. That collection was sitting EMPTY despite a backlog of
`trade_outcomes` (the incremental `run_daily_analysis` path only aggregates
*today's* `reviewed:False` rows and wasn't persisting history). With no row,
the pillar defaults to `win_rate=0.5` → score 50 → TQS compresses into the "C"
band → every trade sized at ~0.30×. This is **data starvation, not weighting**
(STYLE_WEIGHTS are horizon-aware and correct — do NOT rebalance them).

### Fix
- `services/learning_loop_service.py`
  * New pure aggregator `_compute_learning_stats(context_key, outcomes)` —
    reads outcome dicts directly (stored docs are flatter than
    `TradeOutcome.from_dict` expects, which silently zeroed stats). Writes the
    exact fields the pillar reads (`win_rate`, `expected_value_r`,
    `total_trades`) + extras. Shared 1:1 with the manual backfill script.
  * New `async rebuild_learning_stats_from_all_outcomes()` — full, idempotent
    rebuild from ALL `trade_outcomes`, grouped by the NORMALIZED setup key the
    pillar queries (`lower().replace("_long","").replace("_short","")`).
    Upserts by `context_key`. Returns # contexts written.
- `services/trading_scheduler.py`
  * New nightly job `learning_stats_rebuild` @ **5:30 PM ET** →
    `_run_learning_stats_rebuild()`. Keeps the setup-pillar feed fresh so TQS
    spreads honestly over time.
  * `run_task_now("learning_stats_rebuild")` on-demand trigger wired (exposed
    via `POST /api/scheduler/run/learning_stats_rebuild`) so the operator can
    refresh without waiting for 5:30 PM.

### Verify
- `backend/tests/test_v19_34_200_learning_stats_rebuild.py` — 5/5 pass
  (win-rate/EV/PF math, all-losses, breakeven excluded from WR denominator,
  empty, bad/missing fields). Lint + syntax clean.
- ⚠️ OPERATOR LIVE-CHECK after deploy+restart: hit
  `POST /api/scheduler/run/learning_stats_rebuild` (or wait for 5:30 PM ET),
  then confirm `learning_stats` is populated and the setup pillar starts
  spreading off a flat 50. **Effect is forward-looking** (only new trades
  scored after the rebuild see the richer win-rate feed).

---


## 2026-06-01 — v19.34.199 RESTORE-PATH GRADE HYDRATION (honest TQS grade)

### Root cause (found via diag_sizing_provenance.py on live DGX)
Open swing trades (power_trend_stack / stage_2_breakout / pocket_pivot) showed
`unified_grade`/`tqs_grade` = EMPTY despite `entry_context.tqs.unified_grade`
being populated (C/C+). The card's `unifiedGrade()` then fell back to the legacy
`quality_grade` (B) and **labeled it "TQS B" — when real TQS was C/C+.**

`restore_open_trades` (the active boot restorer in bot_persistence.py)
constructs BotTrade from a HARDCODED field subset that omits
unified_grade/tqs_grade/tqs_score. So every restart returned multi-day trades
with empty grades, and the periodic persist then overwrote the DB (incl. the
v175 backfill) with those empties. New trades (created in-session) were fine;
only RESTORED trades lost the grade.

### Fix — `services/bot_persistence.py`
- New pure resolver `resolve_restore_grades(trade_doc, entry_context)` mirroring
  the v175 backfill priority: top-level field → `entry_context.tqs.unified_grade`
  → `post_gate_grade` → (unified only) legacy `quality_grade`.
- `restore_open_trades` now calls it after restoring `entry_context`, so the
  REAL TQS grade survives restarts and the UI label is honest (sizing already
  used the right TQS grade — this fixes the record + label only).
- Tests: `tests/test_v19_34_199_restore_grades.py` (6 cases incl. the exact
  swing-trade C+ derivation + reconciled "R" fallback). All green.

### Diagnostics added (read-only)
- `scripts/diag_sizing_provenance.py` — per-open-trade multiplier chain, sizing
  vs displayed stop, budget-vs-realized risk. Proved sizing is CORRECT (TQS-C
  trades sized at 0.30× as designed) and that "B sized as C" was a label bug,
  not a sizing bug.
- `scripts/diag_tqs_distribution.py` — TQS score/grade histogram + legacy-vs-TQS
  label divergence + per-setup mean TQS, to test whether TQS compresses into the
  C band.

### NOTE: NOT a sizing change
The earlier "Fix 1" (fall back to quality_grade in the sizer) was REJECTED after
the diagnostic proved these are genuinely TQS-C/C+ trades. Inflating them to B
size would resurrect the exact lenient-grade double-count v175 removed. Sizing
left untouched.

---

## 2026-06-01 — v19.34.198 SESSION-AWARE CHART CACHE TTL (5 PM ET rollover)

### Context
Operator set `CHART_CACHE_TTL_INTRADAY_S=28800` (8h) so same-session chart
revisits are instant (2ms cache hit + chart-tail WS backfill). Risk of a flat
8h TTL: an entry cached late in the session would bleed the closing-print
skeleton into the evening and the next premarket open.

### Fix — `services/chart_response_cache.py`
- New `_seconds_until_session_rollover(now, rollover_hour_et=17)` helper.
- `chart_cache_ttl_for(timeframe, now=None)` now CLAMPS the intraday TTL so an
  entry never outlives the next **5 PM ET** rollover. Same-session revisits stay
  instant; each new session rebuilds fresh. Examples (base 8h):
  10:00 ET → 7h · 3:55 PM → 1h · 4:30 PM → 30m · post-5 PM → full 8h.
- Floor of 30s prevents TTL=0 right at the boundary. Daily TTL untouched.
- Env: `CHART_CACHE_ROLLOVER_HOUR_ET` (default 17), `CHART_CACHE_SESSION_AWARE`
  ("false" disables the clamp → flat base TTL).

### Widen pre-warm — `routers/sentcom_chart.py`
- `POST /chart/warm` defaults: timeframes `["5min"]` → `["1min","5min","15min"]`;
  symbol cap 32 → 48. A single warm call now primes the operator's intraday set.

### Tests
- `tests/test_v19_34_198_session_aware_ttl.py` — 7 tests (rollover math, clamp,
  base-when-far, daily-never-clamped, disable flag, custom hour, zero floor).
- `tests/test_v19_34_197_chart_cache_ttl.py` — pinned `CHART_CACHE_SESSION_AWARE=false`
  so the base-TTL contract stays deterministic. **11/11 passing** locally.

### Deploy
`paste.rs` idempotent script `deploy_v19_34_198.py` (patch → pytest → git
commit+push → restart prompt). Dry-run verified: patches apply, 11 green,
2nd run fully idempotent (all skip).

---

## 2026-?? — v19.34.197 CHART COLD-LOAD LATENCY FIX (18-21s → ~3s)

### Diagnosis (read-only diag_chart_latency.py on the live DGX)
Cold INTRADAY `/chart` loads measured **18,000-21,000 ms**; daily was <300ms.
NOT payload (~85KB / 245 bars) and NOT Mongo (`get_bars` fast — daily proves
it). Root cause: the per-miss live pusher-RPC merge (`fetch_latest_session_bars`
→ `rpc.latest_bars`, an on-demand IB historical request for quote-subscribed
symbols) blocked the whole chart load with NO timeout. Daily skips the merge →
fast. Cache works (warm = 1-4ms) but the 30s intraday TTL + warm-only-top-12
meant most clicks were cold misses paying the full 18s.

### Fix
- `routers/sentcom_chart.py` — TIME-BOUND the merge with
  `asyncio.wait_for(CHART_LIVE_MERGE_TIMEOUT_S, default 3.0s)`. On timeout serve
  the historical window immediately; the chart-tail WS/poll backfills the live
  bars within ~5s, and the slow RPC still warms `live_bar_cache` for the next
  load. Cold worst case 18-21s → ~3s.
- `services/chart_response_cache.chart_cache_ttl_for` — env-tunable; intraday
  default 30s → 60s (`CHART_CACHE_TTL_INTRADAY_S` / `CHART_CACHE_TTL_DAILY_S`)
  to halve cold-miss frequency. Safe because the WS tail keeps the chart live.

### Verify
4/4 tests (`test_v19_34_197_chart_cache_ttl.py`); py_compile + ruff clean.
Deploy paste.rs `00uTK` (patch `SDNl1`). ⚠️ Operator: after restart re-run
`diag_chart_latency.py` — cold intraday should drop ~18s → ~3s.

---

## 2026-?? — v19.34.194–196 QUALITY GATE + DUAL TIMESTAMPS + OPERATOR FORCE-FLATTEN

Three operator-requested features (each with passing pytest; deploy wrapper
`https://paste.rs/a3R1H`, patch `https://paste.rs/FKfax`):

### v19.34.194 — $BIL quality gate (volatility floor + cash-equivalent blocklist)
`services/opportunity_evaluator.py` — two env-tunable hard gates early in
`evaluate_opportunity` (both fail-OPEN, drops logged via `record_rejection`):
  * `CASH_EQUIVALENT_BLOCKLIST` (default: BIL,BILS,SGOV,SHV,SHY,ICSH,… T-bill /
    ultra-short ETFs) → reason `cash_equivalent_blocklist`.
  * `MIN_TRADE_ATR_PCT` daily ATR% floor (FRACTION; default 0.003 = 0.3% — below
    SPY/QQQ ~0.7-1.4% so index ETFs pass, but catches $BIL ~0.1%). ATR% sourced
    from alert atr/price, else `symbol_adv_cache.atr_pct`. 0 disables; blocks
    ONLY when a measurement exists. Stops ultra-low-vol tickers becoming trades
    (the BIL R:R 0.02 incident). 6/6 tests.

### v19.34.195 — dual-shape timestamps on bot_trades + shadow_decisions
`bot_persistence.persist_trade` + `save_trade` and `shadow_tracker.log_decision`
now stamp `ts` (ISO) + `ts_dt` (BSON), anchored to `created_at` (stable across
updates), via `utils/timestamps.stamps()`. Completes the v172 normalization;
prevents silent cross-collection query misses. 4/4 tests.

### v19.34.196 — operator force-flatten orphaned IB positions by symbol
New `POST /api/trading-bot/positions/{symbol}/flatten` (`routers/trading_bot.py`)
— reads the live IB position via ib_direct, cancels every working order for the
symbol (clears OCA brackets that trip IB's 15-order cap), then sends a MKT to
flatten the net position. Operator-initiated → bypasses the post-stop cooldown.
The V5 `CloseTradeModal.jsx` now detects orphan rows (no `trade_id`), shows an
amber "Orphaned IB position" banner + "Force-flatten <SYM>" button, and routes
to this endpoint instead of erroring "Missing trade_id". 6/6 tests.

### Verify (hardware-bound — manual, NOT testing agent)
16/16 new tests pass; py_compile + ruff + eslint clean. Frontend hot-reloads.
⚠️ Operator: after deploy+restart, watch `/tmp/backend.log` for the v194 gate
logs, confirm new docs carry `ts`/`ts_dt`, and test Force-flatten on an orphan.

---

## 2026-?? — v19.34.193 SCANNER UNIVERSE-COVERAGE HARDENING (alphabetical A/B-only bug)

### Context (operator: "all Friday trades were A/B/C symbols")
A read-only coverage diagnostic proved the bot was blind to ~9,150 of ~9,400
symbols. Root cause chain:
  * The weekly ADV scheduler (`server.py`, Sundays 10 PM ET) called the legacy
    `scripts/recalculate_adv_cache.py`, which `delete_many()`'d
    `symbol_adv_cache` and rewrote 9,200 docs with ONLY `avg_volume` (share
    count) and NO `avg_dollar_volume`.
  * The wave-scanner ranks tier2/tier3 by `avg_dollar_volume >= $50M / $10M`,
    so both pools collapsed to 0 (`tier2_pool_size=0`, `tier3_roster_size=0`).
  * With tiers 2/3 empty, the scanner silently degraded to the 50-symbol
    ALPHABETICAL fallback watchlist → every trade an A/B name, every Sunday.

### Immediate data repair (operator-run, no code)
`POST /api/ib-collector/rebuild-adv-from-ib` → rebuilt 9,412 symbols with
`avg_dollar_volume` + ATR% + tier (intraday 1,145 / swing 844 / investment 507).

### Code fix (this patch — prevents recurrence)
- `server.py::_run_adv_recalc` now calls the CANONICAL
  `IBHistoricalCollector.rebuild_adv_from_ib_data()` (writes
  `avg_dollar_volume`+`atr_pct`+`tier`) instead of the footgun script.
- `scripts/recalculate_adv_cache.py::recalculate_adv_cache()` is DISABLED
  (raises `RuntimeError`, no `delete_many`) so a manual run can't wipe it.
- `services/wave_scanner.py`:
    * self-heals its db handle (`get_database()`) if a db-less singleton
      slipped through the init race;
    * BYPASSES the 10-min TTL while pools are empty (fast self-heal right after
      a rebuild — no 10-min blind window);
    * on the wipe signature (docs exist, 0 match `avg_dollar_volume>=$10M`)
      raises a LOUD alarm and falls back to an `avg_volume`-ranked liquid set —
      NEVER collapses to alphabetical again.

### Verify
- `backend/tests/test_v19_34_193_scanner_coverage_hardening.py` — 5/5 pass
  (healthy ADV-rank, broken-cache→avg_volume fallback non-alphabetical,
  empty-pool TTL bypass, populated-pool TTL honored, footgun disabled).
- py_compile + ruff clean.
- Deploy: paste.rs wrapper `https://paste.rs/Ksyzp` (patch `https://paste.rs/O6DNk`).
- ⚠️ OPERATOR LIVE-CHECK after restart (~90s): `tier2_pool_size ~200`,
  `tier3_roster_size ~1989`, live subs ADV-ranked (not all A/B).

### Diagnostics created
`/tmp/diag_scan_coverage_v19_34_193.py`, `/tmp/diag_adv_cache_fields_v19_34_193.py`.

---

## 2026-02-?? — v19.34.192 EOD/CLOSE BRACKET-CANCEL VIA IB_DIRECT (master clientId 11)

### Context (recurring P0 — EOD MKT-close deadlock)
At 15:45 ET EOD, `close_at_eod=True` positions repeatedly failed to flatten with
`bracket_cancel_timeout_race_risk`, and cross-session DAY/GTC bracket children
threw IB `10147 OrderId not found`. Root-caused in the close path:
`_cancel_ib_bracket_orders` dispatched its cancels through
`routers.ib._ib_service.cancel_order()` — the legacy `IBService` worker thread,
which on this DGX deployment is the **stale/disconnected** direct-ib_insync
worker (PRD v170) serialized on a 1-worker queue. The cancel never reached IB
before the 8s+5s terminal-wait expired → every close aborted. The throttle is
NOT a deliberate IB-pacing safeguard (IB's real limit is ~50 msg/s); it is an
unintended stale+serialized bottleneck.

### Fix (`services/trade_executor_service.py`, safety-critical path — dispatch only)
- New `_dispatch_bracket_cancel_v192(oid, symbol)` routes the cancel through the
  DGX-native `ib_direct` socket (IB Gateway **Master API client ID = 11**,
  v19.34.190). `ib_direct.cancel_order` cancels via the **live order OBJECT**
  (which carries `permId`) looked up from the `_ib.trades()` cache that
  `_fetch_live_open_order_ids` freshly populates via `reqAllOpenOrders`
  immediately before the loop. Master clientId 11 lets clientId-11 cancel
  cross-session orders → dodges `10147`.
- Both the primary cancel loop and the v19.34.73 retry loop now use the helper.
- Legacy `IBService` retained ONLY as a fallback (ib_direct down/None) so a
  cancel is never silently dropped.
- **The OCA-race contract is UNTOUCHED**: the 8s primary + 5s retry
  terminal-wait, the filled/timeout abort, and the v189 fresh-openorders
  re-check all remain exactly as before. Only the cancel TRANSPORT changed.

### Verify
- `backend/tests/test_v19_34_192_eod_cancel_dispatch.py` — 6 tests, all pass
  (prefers ib_direct; falls back on failure / None / disconnected; no-transport
  returns False; `_cancel_ib_bracket_orders` routes through the helper).
- `py_compile` clean. (7 adjacent failures in v189/v191/70a/v40 suites are
  PRE-EXISTING stale-mock / sandbox-env artifacts — confirmed identical with the
  patch stashed; not introduced here.)
- Deploy: paste.rs wrapper `https://paste.rs/orhz4` (patch `https://paste.rs/8CZIM`)
  — applies, runs the test, commits+pushes BEFORE restart.
- ⚠️ OPERATOR LIVE-CHECK (15:45 ET): grep `/tmp/backend.log` for
  `v19.34.192 eod-cancel ... via ib_direct (master clientId 11, permId-aware)`;
  every `close_at_eod=True` position flat by 15:59:30, NO
  `bracket_cancel_timeout_race_risk` aborts.

---

## 2026-02-?? — v19.34.191 EOD SUPERVISOR CRASH HARDENING

### Context
During a 16:00 ET EOD auto-close while IB Gateway was wedged, two P0 Python
bugs surfaced in the scan/EOD loop:
1. **PyMongo `bool(Database)` crash** — `NotImplementedError: Database objects
   do not implement truth value testing`, raised by `<Database> or <Database>`
   and `if <Database>:` checks.
2. **`_broadcast_event` AttributeError** — the method was dropped during the
   unified-stream migration, leaving ~9 EOD/orphan HUD call sites raising
   (swallowed) AttributeError → HUD banners silently dead.

### Changes
- **BUG 1 (17 sites, 6 files):** Replaced every `bool(Database)` truthiness
  trap with explicit `is not None` / `is None` checks and None-safe ternaries.
  - `position_manager.py` (1× `or`-pattern, 6× `if bot._db:`, 1× `if not bot._db:`)
  - `opportunity_evaluator.py` (4× `or`-pattern)
  - `position_consolidator.py` (2× `or self.db`)
  - `position_reconciler.py` (1× `or`-pattern)
  - `dynamic_risk_engine.py` (1× `if not self._db:`)
  - `simulation_engine.py` (1× `if bars and self._db:`)
- **BUG 2:** Restored `TradingBotService._broadcast_event` as a thin shim that
  maps the legacy `{"type", "timestamp", **extra}` payloads onto
  `emit_stream_event` (kind=`alert` for alarm/critical/blocked, else `system`;
  auto-humanized text line; extra fields → `metadata`). All 9 call sites work
  unchanged.

### Verify
- `backend/tests/test_v19_34_191_eod_crash_hardening.py` — 7 tests, all pass
  (NoBool sentinel proves truthiness fix; shim payload mapping + severity +
  bad-input safety).
- `py_compile` clean on all 7 touched files. Grep confirms zero residual
  `or`-on-Database or bare `if (bot|self)._db:` patterns.
- Deploy: paste.rs wrapper `https://paste.rs/Ew8Zg` (patch `YZ9CI`, test
  `vUsBm`) — commits+pushes before restart.

---

## 2026-05-29 — v19.34.190 MASTER-CLIENTID STARTUP GUARD + RUNBOOK

### Context
Follow-up to the CF/BAP close saga: the real fix for orphaned-bracket
cancellation was the IB Gateway **"Master API client ID = 11"** setting (lets
clientId-11 cancel cross-session/prior-process orders). That setting lives in
the Gateway's `jts.ini` on the Windows box — NOT in this repo — so it's lost on
a Gateway reinstall. Nothing to hardcode in the bot (it already connects as
`IB_DIRECT_CLIENT_ID`, default 11); we just lock it in with docs + a guard.

### Changes (additive, logging + doc only — zero trading-path impact)
- `services/ib_direct_service.py` — on every IB connect, compare `client_id`
  against `IB_EXPECTED_MASTER_CLIENT_ID` (default 11). Loud **WARN** if they
  differ ("bot may be UNABLE to cancel orphaned/cross-session brackets → IB
  10147"); calm **INFO** confirming master authority when they match.
- `memory/runbooks/ib_gateway_master_clientid.md` (NEW) — documents the
  required Gateway setting, the two in-sync values (`IB_DIRECT_CLIENT_ID` ↔
  Gateway Master API client ID), the symptom signature (10147 +
  PendingCancel→Submitted flap), and the re-set steps after any Gateway
  reinstall.

### Verify
`grep -iE 'v19.34.190|clientId=' /tmp/backend.log | tail -5` → expect
"clientId=11 matches documented master — cross-session/orphaned-order cancels
enabled". Compile-checked; the two E702 lint hits are pre-existing legacy.

---



## 2026-05-29 — v19.34.189 CLOSE-GUARD AUTHORITATIVE OPEN-ORDERS FIX

### Bug (operator-reported: BAP/CF wouldn't close)
Clicking **Close** aborted with `bracket_cancel_timeout_race_risk` and the
position never closed. Root-caused live on the DGX:
- The v19.34.64 OCA-race guard waits for each bracket child to reach a
  terminal status before sending the MKT close. Its v19.34.70A pre-filter
  partitioned tracked child orderIds against **`_ib.trades()`** — an
  in-memory CACHE.
- That cache (a) freezes an order's status at disconnect and is **never
  purged on socket-reconnect**, and (b) cannot be marked terminal by this
  client's error handler when the order was placed under a **different
  clientId** (the pusher) — `ib_async` keys `self.trades[(clientId, oid)]`,
  so the `cancelOrder→Error 10147 "not found"→auto-Cancelled` path misses.
- Net: orders already dead at IB showed as `Submitted`/`PreSubmitted`
  forever → `wait_for_orders_terminal` timed out → **every** close (manual
  + manage-loop) aborted. Confirmed: after a full backend restart (fresh IB
  object) BAP's cancelled orders vanished from the audit, proving stale cache.

### Fix (`services/trade_executor_service.py`, safety-critical path)
- New `_fetch_live_open_order_ids()` — AUTHORITATIVE set of orderIds open at
  IB across all clients via a fresh `reqAllOpenOrders` round-trip. Returns
  `None` on any failure (conservative: caller keeps the block-and-confirm path
  so flip-protection is never weakened on a transient query error).
- New pure `_partition_oids_by_live_set(oids, live_ids)` → `(present, gone)`.
- `_cancel_ib_bracket_orders` now pre-filters against the FRESH set (was the
  stale cache): children NOT in IB's live open-orders are `gone` → safe
  (`unknown`), skipped. Added a **post-wait** re-check too: any child that
  times out but is absent from a fresh `reqAllOpenOrders` is reclassified
  timeout→safe (catches OCA siblings IB auto-cancels mid-wait).
- Genuinely-live brackets still appear in the fresh set → still cancelled +
  confirmed before close → the 2026-05-20 direction-flip protection is intact.

### Verification
- 7/7 unit tests (`test_v19_34_189_close_guard_authoritative_orders.py`):
  partition contract (all-live/all-dead/mixed/empty) + fresh-fetch fallback
  (set / None-on-disconnect / None-on-exception). Backend compiles; lint clean
  (the one E722 is pre-existing legacy). No automated agent (hardware-bound).
- ⚠️ OPERATOR LIVE-CHECK: with TWS closed + bot connected, click Close on a
  stuck position; `grep 'v19.34.189 fresh-openorders' /tmp/backend.log`.

---



## 2026-05-30 — v19.34.188 MISSION CONTROL LIFECYCLE EMITS + INLINE SAFETY ACK

### What
Completes the Mission Control observability follow-ups noted in v19.34.184:
the live cockpit now shows the *whole* position-management + execution
lifecycle, and the operator can acknowledge a safety alarm inline (no tab
switch). (Re-tagged from a v19.34.186 collision with the BBAI tick-rounding
patch — see operator request.)

### Backend — new lifecycle emits (all fire-and-forget, never block the path)
- `services/stop_manager._record_stop_adjustment` — single chokepoint for
  trailing + breakeven + activation moves → emits **`stop_to_breakeven`**
  (Position lane, success) or **`trailing_stop_moved`** (Position lane, info).
- `services/trade_execution` — emits **`order_submitted`** (Execution lane)
  right before `place_bracket_order` so the operator sees intent before fill.
- `services/trade_executor_service` (partial branch) — emits **`partial_fill`**
  (Execution lane) with filled/remaining qty.
- All four classify into the correct lane in `stream_bus.classify_lane`
  (verified — no router change needed).

### Frontend — inline safety acknowledge
- `components/missioncontrol/SafetyRow.jsx` (NEW) — System/Safety strip row:
  alarm rows get an **"Ack + Unlock"** button → `POST /api/safety/reset-kill-switch`
  (the real operator re-arm), plus a local **dismiss (×)**. Non-alarm rows just
  render + dismiss.
- `pages/MissionControlPage.jsx` — System/Safety strip now renders `SafetyRow`
  (was the plain `StreamRow`), with a locally-dismissed-id set so muted rows
  stay hidden. Header count reflects visible (non-dismissed) rows.

### Verification
- 4 new lane-contract tests (`test_v19_34_188_lifecycle_emit_lanes.py`) +
  14 existing stream-bus tests = 18/18 pass. Both backend + frontend lint clean;
  all 3 backend services compile.
- Frontend mounts cleanly: `mission-control-page` + `mc-system-strip` testids
  present (no live data in the sandbox — connects live on the DGX). No automated
  testing agent per AGENTS.md (hardware-bound).
- ⚠️ OPERATOR LIVE-CHECK (RTH): open Mission Control — Execution lane should show
  `order_submitted` / `partial_fill`; Position lane should show stop→breakeven /
  trailing moves; trip + reset a kill-switch alarm via the inline "Ack + Unlock".

---



## 2026-05-30 — v19.34.185 F-F: GAMEPLAN-AWARE PRIORITIZATION (+ premarket gameplan scheduler)

### Why
The premarket Gameplan and the live bot were disconnected — the bot ranked
alerts purely on TQS/priority and ignored the operator's pre-open prep. Goal:
let the Gameplan softly steer slot allocation. **Accuracy pre-flight (audit)
revealed** the gameplan was only generated ON-DEMAND (when the journal tab is
opened) → today's plan was intraday-generated, all `live_scanner`, Neutral
bias. Boosting that would be circular. So F-F needs a stable PREMARKET plan
first.

### Part A — Premarket gameplan generation (data foundation)
`eod_generation_service`: new scheduled job **09:00 ET, Mon–Fri** that
FORCE-regenerates today's `game_plan` before the open (`delete_one` + 
`create_game_plan(auto_populate=True)`). At 09:00 the scanner buffer holds the
real conviction names — `pm_` premarket gappers + swing/position daily setups —
so `stocks_in_play` becomes genuine pre-open prep (`premarket_scanner` /
`daily_scanner` sources) and stays stable all session.
- New: `auto_generate_premarket_gameplan(date)`; logged via `_log_generation`.

### Part B — F-F soft conviction boost
`trading_bot_service._get_trade_alerts._alert_rank` (the v179 quality slot
ranker): TQS dimension now gets a mild, env-tunable additive boost:
- **+`GAMEPLAN_WATCHLIST_BOOST`** (default 8) if the symbol is on today's
  premarket/daily gameplan watchlist.
- **+`GAMEPLAN_BIAS_BOOST`** (default 4) if direction aligns with `market_bias`
  (long when Bullish / short when Bearish; nothing when Neutral).
- **Ranking-only**: never changes the stored TQS grade or any gate decision;
  the priority bucket still dominates (a low-priority gameplan name can't jump
  a high-priority non-gameplan one). A clearly-better non-gameplan setup
  (≥ boost higher TQS) still wins the slot.
- New helpers: `_compute_gameplan_boost` (static, pure) + `_get_gameplan_conviction`
  (reads only premarket/daily-sourced names + bias, cached ~5 min so the 09:00
  regeneration is picked up same session).

### Verification
- 11 F-F unit tests (watchlist hit, bias align/misalign, neutral, stacking,
  case-insensitivity, tunable-to-zero, mild-additive ranking effect). 51/51
  across v179/v182/v183/v184/v185 — no regressions. Both services compile.
- ⚠️ LIVE CONFIRMATION REQUIRED TOMORROW AM: after deploy + restart, the 09:00
  ET job runs; re-run the F-F audit (paste.rs/Npujw) → it should show
  "generated PREMARKET ✅" with `premarket_scanner`/`daily_scanner` names in
  stocks_in_play. ONLY THEN is the boost operating on real conviction data.
  (Today's intraday plan = nothing meaningful to boost yet.)
- Tunable kill-switch: set `GAMEPLAN_WATCHLIST_BOOST=0` and
  `GAMEPLAN_BIAS_BOOST=0` to disable the boost entirely.

---



## 2026-05-30 — v19.34.184 MISSION CONTROL (live multi-lane pipeline cockpit)

### What
A new top-level **Mission Control** tab: a live, always-on "cockpit" that
streams the bot's decision bus into 5 lanes — **Scanner | Gates | Execution |
Position | Reconciler** — plus a **System/Safety** strip, a heartbeat pip,
AGGREGATE/RAW scanner mode, severity filters, and click-through to a symbol's
recent-decision drawer.

### Why this design (coverage audit drove it)
A `sentcom_thoughts` audit over 7d showed the event bus already captures the
whole pipeline (~362k events), so we **reuse the existing bus** instead of
building a parallel system. Key finding: the **Scanner lane is a firehose**
(~324k `scanner_skip`/7d, peak ~600 events/min), NOT thin. So the architecture
centers on throttling that volume, not adding events.

### Performance (the operator's explicit concern: "will B slow the app?")
No — the trading hot path is untouched:
  • `StreamBus.publish()` is **synchronous, allocation-cheap, never awaits/sends**
    — a background ~300ms flush loop does the per-connection send.
  • **Zero idle overhead**: when no client is connected, `publish()` early-returns
    (after cheaply bumping the scanner roll-up counter).
  • **Scanner firehose handling (hybrid)**: in `aggregate` mode skips/rejects are
    NOT buffered — only counted and summarized via a periodic `scan_pulse`.
    `scanner_trigger` always streams. `raw` mode streams everything (buffered
    only when a raw subscriber exists). Hard `_MAX_BUFFER` load-shed on bursts.
  • **Always-on persistence**: `sentcom_thoughts` is written 24/7 regardless of
    the tab; the WS is only the live delivery channel (so nothing is lost when
    the tab is closed — reopen → backfill + resume).

### Backend
- `services/stream_bus.py` (NEW) — loop-local broadcaster + `classify_lane` /
  `severity_of` (action_type-primary, source/kind tie-breakers).
- `services/sentcom_service.py` — `emit_stream_event` now fans out to the bus
  (sync, fail-open).
- `server.py` — `@app.websocket("/api/ws/stream")` with subscribe (lanes +
  severities + mode), 20s keepalive, graceful disconnect.
- **New lane emits**: v183 guards (`wrong_side_stop_recomputed`,
  `position_stop_capped`) → Gates lane (live proof they fire); `target_hit`
  scale-out → Position lane.

### Frontend
- `pages/MissionControlPage.jsx` (NEW) — orchestrator (backfill + live tail).
- `hooks/useStreamSocket.js` (NEW) — WS client, backoff reconnect, sub push.
- `lib/laneClassify.js` (NEW) — client mirror of the server classifier (backfill).
- `components/missioncontrol/{StreamRow,LaneColumn,TrailDrawer}.jsx` (NEW).
- `App.js` + `Sidebar.js` — new "Mission Control" nav tab (Radio icon).

### Verification
- 14 stream-bus unit tests (lane classify, severity, firehose aggregate/raw,
  per-connection flush filter, scan_pulse). 48/48 across v169/v181/v182/v183/v184.
- **Live WS handshake verified** on the local backend (connect → lane-filtered
  subscribe → ping/pong).
- Frontend: lint clean, compiles with no module errors; smoke screenshot shows
  5 lanes + System strip + heartbeat + AGGREGATE/RAW + severity filters
  rendering (IDLE in the mirror — no REACT_APP_BACKEND_URL/live data; connects
  live on the DGX).
- Deploy patch: https://paste.rs/21jcv (14 files), `git apply --check` clean on
  v183 tree (DGX HEAD 7863a27d).

### Follow-ups (deferred, noted)
- More lifecycle emits (stop→breakeven, trailing-stop move, order_submitted,
  partial_fill, EOD-flatten-initiated) to further enrich Position/Execution.
- Inline "acknowledge" action on System/Safety alarms (currently click-through
  to the recent-decision drawer only).
- ⚠️ OPERATOR LIVE-CHECK: open Mission Control on the DGX during RTH — heartbeat
  should go LIVE, Scanner pulse should tick (triggers/skips/rejects), Gates
  should fill with rejection reasons; flip RAW to see the skip firehose.

---



## 2026-05-30 — v19.34.183 STOP-GEOMETRY SANITY (squeeze stale-trigger + evaluator guards)

### Why (found while validating v182 gameplan accuracy — now visible, not hidden)
With v182 surfacing real alert levels, three live alerts exposed bad stop
geometry: DIA `squeeze` long had `stop 505.82 ABOVE entry 501.63` (inverted),
and BMO `stage_2_breakout` carried a 16.8% structural stop. Root cause traced:
the alert dict maps `stop_price = alert.stop_loss`, and the evaluator only
recomputes a stop when one is MISSING (`if not stop_price`) — so detector
stops flow straight into sizing/brackets, inverted or over-wide.

### Bugs fixed
1. **DIA squeeze stale trigger (detector).** `_check_squeeze` set
   `trigger_price = bb_upper` (long) but anchored stop/target to *current
   price*. Once price has already broken out and run past the band, bb_upper
   is stale and an ATR stop (current_price − 1·ATR) lands ABOVE it → inverted
   long. Fix: anchor entry to `max(bb_upper, current_price)` (long) /
   `min(bb_lower, current_price)` (short), and compute stop+target+R:R off that
   single consistent `entry`. Normal pre-breakout case unchanged (entry =
   band). Option (i): fix the geometry, do NOT suppress the signal.
2. **Inverted stop reaches sizer (evaluator, defense-in-depth).** New wrong-side
   guard right after the stop resolve: if a long's stop ≥ entry (or short's
   stop ≤ entry), discard it and recompute via `calculate_atr_based_stop`
   (always correct-side). Catches ALL ~38 detectors, not just squeeze.
3. **v169 5% stop-cap bypassed for detector stops (evaluator).** v169's
   position/investment 5%-of-entry cap lives inside `calculate_atr_based_stop`,
   which only runs when no stop is supplied. stage_2_breakout / weekly_breakout
   supply their own wide structural stops, bypassing it → reopened the "1–3
   share" tiny-sizing problem. New cap applies the same 5% ceiling (env
   `MAX_STOP_PCT_POSITION` / `MAX_STOP_PCT_INVESTMENT`) to detector-supplied
   stops on position/investment horizons. Only TIGHTENS; never loosens.

### Not bugs (confirmed working)
- BOXX `three_week_tight` R:R 0.60 → v181 auto-ladder re-derives the target to
  clear the swing R:R floor. Working as designed.
- `LiveAlert.atr` persisting as 0.0 in diagnostics is a cosmetic display gap
  (detector used a real ATR ~5.1) — left as a future nit.

### Files changed
- `backend/services/enhanced_scanner.py` (`_check_squeeze` entry anchor)
- `backend/services/opportunity_evaluator.py` (wrong-side guard + detector stop-cap)
- `backend/tests/test_v19_34_183_stop_geometry.py` (new, 10 tests)

### Verification
- 10/10 new tests pass (3 exercise the REAL `_check_squeeze`; 7 mirror the
  evaluator guard logic). 62/62 across v169+v181+v179+v112+v182+v183 — no
  regressions. Both services compile; lint clean on the edited regions.
- Deploy patch: paste.rs URL provided in chat (3 files).
- Path touched is the ENTRY/sizing path, not the safety-critical close path.
- ⚠️ OPERATOR LIVE-CHECK: next session, grep `/tmp/backend.log` for
  `v19.34.183 wrong-side-stop` / `v19.34.183 stop-cap` to confirm the guards
  fire; confirm position-tier setups (stage_2_breakout) now size with sane
  share counts instead of 1–3.

---



## 2026-05-30 — v19.34.182 GAMEPLAN DATA-ACCURACY FIXES

### Why (operator confirmed live: stocks_in_play=0, empty key levels, $0 stops)
`gameplan_service._auto_populate_game_plan` had three data-accuracy bugs that
made the V5 Gameplan/Briefing card show blank/zero data — a hard prerequisite
for F-F (wiring premarket intelligence into the bot's prioritization).

### Bugs fixed
1. **$0 stops/targets** — entries read `getattr(alert,'stop_price')` /
   `'target_price'`, which don't exist on the `LiveAlert` dataclass (canonical
   fields are `stop_loss` / `target`). Every stop/target rendered as $0.
2. **Swing/position setups dropped** — `daily_alerts` (scan_tier swing/position)
   were computed then NEVER appended to `stocks_in_play`. Now appended (deduped)
   between the premarket and intraday tiers.
3. **Empty key levels** — `big_picture.key_levels` was never populated. Now
   filled with SPY/QQQ support+resistance (realtime technical service,
   `mongo_only=True`) and VIX (regime engine `volume_vix.signals.vix_price`).
4. **(bonus) Day-2 strict date−1** — looked up `date - 1 day`, landing on
   weekends/holidays with no plan (zero Day-2 names every Monday). Now queries
   the most recent PRIOR game plan (`{"date": {"$lt": date}}` sort desc).
5. **(bonus) reasoning List[str]** — coerced to text via `_reasoning_text`
   (was stored as a list / sliced as a list in if_then notes).

### Refactor
Extracted the duplicated entry-building into `_alert_to_stock_entry(alert,
source)` (single correct field mapping, used by all 3 tiers) + `_reasoning_text`
helper + `_populate_key_levels` helper. All best-effort / fail-open.

### Files changed
- `backend/services/gameplan_service.py`
- `backend/tests/test_v19_34_182_gameplan_accuracy.py` (new, 8 tests)

### Verification
- 8/8 new unit tests pass (pure logic; no DB/IB needed); 14/14 with the
  existing gameplan-narrative suite. Lint clean. Patch verified to `git apply
  --check` cleanly on the v181 tree (DGX HEAD 8f21c0f6).
- Deploy patch: https://paste.rs/i5pbj (gameplan_service.py + test).
- ⚠️ RUNTIME NOTE: `GET /journal/gameplan/today` only re-creates the plan when
  none exists for today. To see the fix on a day where a (buggy) plan already
  exists, delete today's `game_plans` row OR call `POST /journal/gameplan
  ?auto_populate=true` to regenerate. Tomorrow's open is clean automatically.

---



## 2026-05-29 — v19.34.181 OPENING-VOLATILITY TIME GATE + R:R AUTO-LADDER FALLBACK

### Why (operator-driven, from live 10:05 ET scanner review)
1. Swing/position/investment/multi-day setups were firing in the opening 30
   min — operator wants them gated to **10:15 ET+** (scalp/intraday stay
   all-day). Root cause: `_is_setup_valid_now` only blocks setups LISTED in
   `STRATEGY_TIME_WINDOWS`; none of the longer-horizon setups were listed, so
   the gate returned True (all-day) for them.
2. Longer-horizon setups were almost all rejected at the `min_risk_reward`
   gate at absurd R:R (BIL 0.02, BOXX 0.03, stage_2 0.57-0.76). Root cause:
   their detectors supply their OWN targets (set near daily structure, close
   to entry) paired with wide 2.5-3× ATR stops → R:R ≪ 1. The auto R-ladder
   only ran when NO targets were supplied, so it never rescued them.

### Fixes shipped
- **Time gate (enhanced_scanner):** new `LATER_HORIZON_STYLES`
  {swing, position, investment, multi_day} + `LATER_HORIZON_START_ET=(10,15)`.
  `_later_horizon_window_ok(alert)` blocks those styles before 10:15 ET; wired
  right after `_check_setup` so it gates on the alert's FINAL `trade_style`
  (an intraday-classified `squeeze` correctly stays all-day even though
  STRATEGY_CONFIG tags it swing). Scalp/intraday/unknown pass any time.
  Fail-open.
- **R:R auto-ladder fallback (opportunity_evaluator):** extracted the v112
  trade-style ladder into `_target_ladder_rungs(alert, setup_type)` (behavior
  identical). At the R:R gate, when a detector-supplied target yields
  sub-threshold R:R, re-derive the target from the ACTUAL per-share risk using
  the ladder, picking the smallest rung that clears `effective_min_rr`
  (swing→2.5R, position→2R), leaving the stop untouched. Only applies if the
  recomputed R:R actually clears the floor; otherwise rejects as before.
  Logs `🪜 ... auto-ladder fallback`.

### Files changed
- `backend/services/enhanced_scanner.py`
- `backend/services/opportunity_evaluator.py`
- `backend/tests/test_v19_34_112_scalp_sl_tp_fix.py` (anchored to new helper)
- `backend/tests/test_v19_34_181_timegate_and_rr_fallback.py` (new, 8 tests)

### Verification
- 8 new tests pass; 121/121 across all ladder/RR/exposure/TQS/prioritization
  suites green; both services compile.
- Live (post-deploy): R:R fallback verifiable now (`grep "auto-ladder fallback"
  /tmp/backend.log`; longer-horizon setups should start clearing the R:R gate).
  Time gate verifiable at TOMORROW's open (no swing/pos/inv/m-day alerts before
  10:15 ET; they appear at 10:15).
- ⚠️ Deploy restarts the backend mid-session → account-guard re-trips
  (re-acknowledge once account chip is green) and open positions get re-adopted
  by the reconciler. Prefer deploying when flat / after close.

---


## 2026-05-29 — v19.34.180 PUT /risk-params now persists MONGO_WINS fields

### Why
During v179 ops, setting `max_open_positions=25` via `POST /api/trading-bot/risk-params`
returned 25 in-memory but `effective-limits` kept reading 10. Root cause: the
endpoint persists via a fire-and-forget `asyncio.create_task(_save_state())`,
which races the `state_integrity` watchdog. `max_open_positions` (and 5 other
limits) are `MONGO_WINS`, so the watchdog reverted in-memory 25 back to the
stale Mongo 10 before the deferred save landed. The operator's API change
silently didn't stick (had to write Mongo directly + force-resync).

### Fix
`trading_bot_service.update_risk_params` now writes any updated `MONGO_WINS`
fields **synchronously** to `bot_state.risk_params.*` before the async save.
Sync pymongo is safe here — the method runs from a sync FastAPI route
(threadpool), not the event loop. Affects: `max_open_positions`,
`max_position_pct`, `max_daily_loss_pct`, `min_risk_reward`,
`reconciled_default_stop_pct`, `reconciled_default_rr`. MEMORY_WINS fields
(`starting_capital`, `setup_min_rr`, etc.) are intentionally excluded.

### Files changed
- `backend/services/trading_bot_service.py` (update_risk_params sync persist)
- `backend/tests/test_v19_34_180_risk_params_sync_persist.py` (new, 4 tests)

### Verification
- 4/4 unit tests pass; file compiles.
- Live (post-deploy): `POST /risk-params {max_open_positions:24}` → effective
  reads 24 with NO manual Mongo write or resync; restore to 25 confirmed.
- Ops note: live max_open_positions raised 10 → 25 (kill switch already 25).

---


## 2026-05-29 — v19.34.179 PRIORITIZATION + SLOT ALLOCATION + EXPOSURE + POS-CAP

### Why
Read-only audit of premarket prep / trade prioritization / scalp time-decay
surfaced four concrete defects. Fixed all four + the operator's
`max_open_positions` alignment question.

### Fixes shipped
- **F-A — inverted alert priority sort (P0)**. `enhanced_scanner.get_live_alerts`
  used `sort(key=(priority_order, created_at), reverse=True)` with
  `priority_order={CRITICAL:0…LOW:3}`, so `reverse=True` flipped the bucket
  order and **CRITICAL/HIGH alerts sorted LAST**. The bot intake
  (`_get_trade_alerts` → `[:20]` → slot fill) burned its position slots on
  LOW-priority alerts first and could truncate CRITICAL off the end. Replaced
  with a **stable two-pass sort** (recency desc, then priority asc) → CRITICAL
  first, newest-first within bucket. Proven: pre-fix order
  `[LOW,MED,HIGH,CRIT]`; post-fix `[CRIT_new,CRIT_old,HIGH,MED,LOW]`. The same
  file already used the correct convention at L1115 (CRITICAL=4) — confirming
  `get_live_alerts` was the outlier.
- **F-B — quality-ranked slot allocation**. `_get_trade_alerts` returned
  `alerts[:20]` in scanner order with no quality ranking. Added `_alert_rank`
  (priority bucket → tqs_score → trigger_probability → score, all desc) before
  the slice so the scarce `max_open_positions` slots go to the BEST ideas.
- **F-C — portfolio exposure caps now apply to autopilot**. The v96/98
  position-style (30%) + long-horizon (55%) caps via
  `portfolio_exposure_guard.compute_exposure` were wired ONLY into the manual
  `submit_trade` router path. Unattended bot entries could pile simultaneous
  long-horizon bets past the intended concentration (starving scalp/intraday
  buying power). Mirrored the clamp into `opportunity_evaluator.evaluate_opportunity`
  (autonomous path), right after final sizing: clamps shares to the remaining
  cap room, or rejects (`reason_code="portfolio_exposure_cap"`) when saturated.
  Fail-open. Per-symbol (v123) cap still applies independently.
- **F-E — morning-readiness false YELLOW**. `morning_readiness_service` expected
  EOD at 15:55; canonical is 15:45 (v181). Widened the accepted band to
  15:40–15:58 so the daily autopilot check stops throwing a spurious YELLOW.

### max_open_positions alignment (operator question — "isn't it 25 now?")
- **Code default bumped 10 → 25** (`RiskParameters.max_open_positions`). This is
  only the fallback; the LIVE value is Mongo `bot_state.risk_params.max_open_positions`.
- **Intake gate now uses the EFFECTIVE cap** = `min(bot value,
  SAFETY_MAX_POSITIONS)`. Previously the scan-loop intake (`:4097`) used the
  bot value alone while the kill switch enforced the min — so a bot=25 /
  kill-switch=5 config wasted evaluation on trades that would be blocked at
  execution. Gate can now only TIGHTEN (strictly safe).
- ⚠️ OPERATOR ACTION: the binding cap is `min(bot, SAFETY_MAX_POSITIONS)`. The
  kill-switch env default is **5**. If you want 25 live, set BOTH:
    - Mongo: `db.bot_state.updateOne({_id:"bot_state"},{$set:{"risk_params.max_open_positions":25}})`
    - DGX env: `SAFETY_MAX_POSITIONS=25` (then restart). Confirm via
      `GET /api/trading-bot/effective-limits` → `effective.max_open_positions`.

### F-D — scalp time-decay tagging audit (read-only script)
`backend/scripts/audit_scalp_timeframe_tagging_v19_34_179.py`. `check_scalp_decay`
only fires for `timeframe=="scalp"`, which is set from
`STRATEGY_CONFIG[setup_type]["timeframe"]` (default INTRADAY). Any scalp detector
missing/mis-tagged silently never time-decays (closes only at EOD). Run on DGX:
`DB_NAME=tradecommand python -m backend.scripts.audit_scalp_timeframe_tagging_v19_34_179`
→ prints mismatches; if any, add/correct the setup's STRATEGY_CONFIG timeframe.

### Files changed
- `backend/services/enhanced_scanner.py` (F-A)
- `backend/services/trading_bot_service.py` (F-B + pos-cap default + effective intake gate)
- `backend/services/opportunity_evaluator.py` (F-C autonomous exposure clamp)
- `backend/services/morning_readiness_service.py` (F-E)
- `backend/scripts/audit_scalp_timeframe_tagging_v19_34_179.py` (new, F-D)
- `backend/tests/test_v19_34_179_prioritization_and_caps.py` (new, 8 tests)

### Verification
- 8/8 new unit tests pass; 52/52 existing TQS + exposure-cap tests still green.
- All five changed files compile; F-C guard import + clamp math validated.
- ⚠️ No automated agent (hardware-bound). OPERATOR LIVE-CHECK: confirm
  CRITICAL alerts get slots first; run the F-D audit; set the pos-cap env/Mongo.

---


## 2026-05-29 — v19.34.177 PORTABLE CLOSED-TRADES FEED (foundation for pipeline tabs + V6)

### Why
Operator is planning a V5 layout change (pipeline-stage feeds as persistent
tabs) but V6 is on the horizon with a different layout philosophy. Decision:
build only the **layout-agnostic, V6-portable** pieces now and DEFER the
V5-only tab-container/layout restructure. Strict constraint: **zero impact on
the running app.**

### Shipped (fully additive)
- **Backend** `GET /api/sentcom/closed-trades?range=today|7d|30d` (new route in
  `routers/sentcom.py`). Sourced from `bot_trades`, reuses the EXACT v141 dedup
  key + flags synthetic/reconciler closes, computes a server-side summary
  (count / WR / net / ΣR / avg / worst / best). Rich rows: unified TQS grade,
  dir, shares, entry/exit price, **entry/exit time + hold duration**, realized $,
  R, MAE/MFE (R), close reason, trade type. Does NOT touch any existing route.
- **Frontend** `components/sentcom/v5/ClosedTradesTable.jsx` — portable,
  presentational, sortable rich table (data via props, emits onRowClick /
  onRangeChange). Drops into the future V5 Close tab AND V6 history view with no
  rework.
- **Frontend** `components/sentcom/preview/ClosedTradesPreview.jsx` — isolated
  harness (self-fetch + 15s live refresh) reachable ONLY at
  `?preview=closedfeed`. NOT mounted in the live tree.
- **App.js** — added the `?preview=closedfeed` escape-hatch branch (mirrors the
  existing `?preview=v6mock` pattern). Normal app render path unchanged.

### Verification
- Endpoint tested via curl across all 3 ranges: dedup confirmed (phantom NVDA
  dropped), range filtering confirmed, summary accurate. Proxy path confirmed.
- Real component renders real endpoint data in the V5 aesthetic (screenshot).
- Frontend compiles clean; lint passes. Zero changes to existing endpoints or
  the live command-center tree.

### Deferred (V5-only, pending V6 timing decision)
- Pipeline-feed tab container (HUD tiles → tabs), badge pulse, 3-column layout
  restructure, right-column → bot-stream move. Hold until operator confirms V6
  timeline (replace vs coexist).

---

## 2026-05-29 — v19.34.176 REGIME ENGINE: COMPOSITE SPY/QQQ/IWM TREND + TOLERANCE

### Why
The `market_regime_engine.py` TrendSignalBlock (35% of the composite regime
score that drives `bot._current_regime` → position sizing + direction bias)
was **SPY-only**: it accepted `qqq_bars` but never used it, ignored IWM
entirely, and used strict boolean MA comparisons. A SPY close 0.01% under the
21-EMA flipped a 20-pt signal off, so a flat tape with green QQQ/IWM could
still print a market-wide "downtrend" — the operator's "SPY downtrend
hallucination".

NOTE: v166 (SPY 0.25% tolerance) + v167 (composite SPY/QQQ/IWM) had already
shipped on 2026-05-27, but ONLY to `realtime_technical_service.py` (per-symbol
trend classifier) and `enhanced_scanner._update_market_context` (scanner ML
context). The **regime engine that drives trading decisions was never patched**
— this is that fix.

### Fix shipped (v19.34.176)
`backend/services/market_regime_engine.py`:
- `TrendSignalBlock` is now a **weighted composite of SPY/QQQ/IWM**
  (0.5 / 0.3 / 0.2, renormalized over whatever has ≥200 bars; SPY stays the
  anchor — if SPY data is missing the block returns neutral 50).
- New `_score_index()` scores each index independently; new `_band_points()`
  applies a **±0.25% tolerance band** (price within band = half credit /
  neutral instead of a hard 0/full flip) — matches v166.
- Surfaces `index_scores`, `indexes_used`, `blend_weights`, `divergence_flag`,
  and `tolerance_pct` in `trend_block.signals` for observability. Back-compat
  SPY MA fields retained.
- `_calculate_regime()` now fetches 200 bars for QQQ + IWM (was 50 for QQQ,
  none for IWM) and passes all three to the trend block.

### Files changed
- `backend/services/market_regime_engine.py`
- `backend/tests/test_regime_composite_trend_v19_34_176.py` (new, 8 tests passing)

### Verification
- 8/8 new unit tests pass (tolerance band, per-index scoring, blend,
  divergence, SPY-hallucination fix, SPY-only fallback, missing-SPY neutral).
- Backend boots clean; `/api/market-regime/current` responds (sandbox shows
  insufficient-data branch — no IB bars locally).
- ⚠️ OPERATOR LIVE-CHECK: on a day SPY is soft but QQQ/IWM green, confirm
  `signal_blocks.trend.signals.indexes_used = [spy, qqq, iwm]` and the regime
  no longer flips to CONFIRMED_DOWN on SPY alone.

---

## 2026-05-29 — v19.34.175 TQS/SMB UNIFICATION + 5-PILLAR UI DRILL-DOWN

### Why
TQS (Trade Quality Score) is now the single source of truth for a trade's
grade. SMB grade was being read by the position-size scaler even though SMB
is already 15% of the TQS Setup pillar (double-counting), AND the operator
UI showed confusing standalone SMB/"F" grade badges.

### CRITICAL latent bug found + fixed
Audit revealed `trading_bot_service._get_trade_alerts()` manually rebuilt the
alert dict that feeds `opportunity_evaluator.evaluate_opportunity()` and
**dropped every grade/quality field** (`tqs_grade`, `tqs_score`, `smb_grade`,
`tape_score`, `risk_reward`, `smb_score_total`, `trade_style`). Consequences in
production since v19.34.156:
  • Position sizing grade resolved to **D = 0.1×** on EVERY trade (grade was
    `None` → `_resolve_grade_multiplier(None)` → D). Operator confirmed NO
    `POSITION_SIZE_GRADE_*` env overrides on the DGX — so the bot has been
    sizing every trade at **10% of intended size**.
  • The post-gate TQS recalc ran on hardcoded defaults (smb_grade="B", tape=0,
    rr=2.0) instead of real alert values.

### Fixes shipped (operator chose option A — full TQS sizing)
- **Plumb real TQS data into the alert dict** (`trading_bot_service.py`
  `_get_trade_alerts`): tqs_score/grade/action/pillar_scores/pillar_grades/
  breakdown/weights + tape_score, smb_score_total, risk_reward, trade_style,
  and smb_grade (audit-only).
- **Rewire position sizing to TQS** (`opportunity_evaluator.py` ~L840):
  `alert_grade = _post_gate_tqs_grade → tqs_grade → trade_grade`. SMB no longer
  drives sizing. Multiplier table unchanged (A=1.0/B=0.7/C=0.3/D=0.1) → A-grade
  trades now size at full 1.0× (~10× larger than the broken 0.1×).
- **`unified_grade` field** added to `BotTrade` (= TQS grade), plus `tqs_grade`/
  `tqs_score`. `smb_grade` retained for audit only. Serialized via `to_dict()`,
  hydrated on restore via the dataclass allow-list.
- **5-pillar breakdown captured** at alert time (`enhanced_scanner.
  _enrich_alert_with_tqs`) + post-gate (`opportunity_evaluator`), stored in
  `entry_context.tqs.{pillar_scores,pillar_grades,breakdown,weights,
  unified_grade}`.
- **Frontend** (`OpenPositionsV5.jsx` + new `TqsPillarPanel.jsx`): SMB grade
  badges replaced with the unified TQS grade; standalone **F**/missing grade
  chips suppressed (confused operators). New expand-on-click 5-pillar drill-down
  (Setup/Technical/Fundamental/Context/Execution) showing per-pillar score,
  grade, weight, sub-component scores + ± factor bullets.
- **DB backfill** (`backend/scripts/backfill_v19_34_175_unified_grade.py`):
  idempotent, sets `unified_grade` on historical `bot_trades` from
  entry_context.tqs → score-derived grade → quality_grade → smb_grade. Supports
  `DRY_RUN=1`.

### Files changed
- `backend/services/trading_bot_service.py` (BotTrade fields + alert-dict plumbing)
- `backend/services/opportunity_evaluator.py` (sizing rewire + unified_grade + entry_context.tqs)
- `backend/services/enhanced_scanner.py` (LiveAlert pillar fields + capture)
- `frontend/src/components/sentcom/v5/OpenPositionsV5.jsx`
- `frontend/src/components/sentcom/v5/TqsPillarPanel.jsx` (new)
- `backend/scripts/backfill_v19_34_175_unified_grade.py` (new)
- `backend/tests/test_tqs_unification_v19_34_175.py` (new, 10 tests passing)

### Verification
- 10/10 unit tests pass. Backend compiles + `/api/tqs/*` endpoints return the
  expected 5-pillar breakdown. Frontend compiles clean. (No automated
  testing-agent — hardware-bound per AGENTS.md.)
- ⚠️ OPERATOR LIVE-CHECK NEEDED next session: confirm A-grade fills now size at
  full 1.0× (entry_context.multipliers.grade_scale = 1.0) and that the size
  jump is expected/acceptable.

---

## 2026-05-28 — v19.34.183/185/186 BBAI PHANTOM WHIPLASH FIX BUNDLE

### Investigation
After v181/v182 EOD fix, surfaced that ARMG and BBAI had `reconciled_external`
phantom trades on 2026-05-28. Initial hypothesis: stale GTC bracket legs from
prior sessions filling today. **Disproven** — `bot_orders` cross-session
check came back empty; IBKR statement showed both May 26 + May 27 BBAI
positions flattened cleanly.

Diagnostic scripts created (all read-only, surfaced via paste.rs):
- `/tmp/trace_orphan_origin.py` — classifies today's reconciled_* trades
  vs originating alerts; flagged 11/22 trades today with `alert_id=None`
  on `bot_trades` (separate v184 issue, deferred).
- `/tmp/verify_alert_persistence.py` — confirmed `live_alerts` IS the
  alert persistence collection (117K rows, 1989 today). Earlier
  hypothesis "alerts never persisted" was **wrong** — I was querying
  the wrong collection name. **Retracted.**
- `/tmp/bbai_origin_trace.py` — pulled full 7-day BBAI lifecycle.
- `/tmp/bbai_bracket_hunt.py` — auto-scanned every Mongo collection for
  BBAI rows, found bracket_lifecycle_events with smoking-gun error.

### Real Root Causes Found

**Cause 1 — Trade-ID Race**: Bot fires order → IB confirms fill → position
appears at IB. Reconciler runs (10-30s cadence) BEFORE the executor finishes
updating `_open_trades`. Sees IB position without matching internal record,
stamps `entered_by=reconciled_external`. Bot loses ownership of its own
trade. Evidence: `trade_audit_log` shows 25+ BBAI mean_reversion_short
intents today; `bot_trades` shows 0 as `bot_fired` and 3 as
`reconciled_external` with mangled share counts.

**Cause 2 — IB Error 110 (Variable Tick)**: Reconciler's orphan-stop math
in `position_reconciler.py:1310-1314` uses float arithmetic:
`stop_price = avg_cost - stop_distance`. For BBAI at $4.82 with 1.5%
stop, this produces $4.7477 — IB's tick grid for $1+ stocks requires
$0.01 increments, so IB returns Error 110, the `bracket_attach_governor`
permanently blocks the symbol for the day, and the phantom stays naked.
Evidence: 15+ consecutive `bracket_lifecycle_events` failures on BBAI
with `error=bracket_attach_blocked:permanent_block:ib_error_110_*`.

### Fixes Shipped

**v19.34.185 — Submit-Race Guard** (`position_reconciler.py:1259-1322`)
Before spawning a `reconciled_orphan` BotTrade for symbol X, scan
`bot._open_trades` for any trade matching X with `pre_submit_at`
within the last 60s. If found, refuse to adopt — log `submit_race_v19_34_185`
skip and let the next reconcile cycle find the trade properly
registered. Honors the v19.34.6 pre-submit stamping that was
previously ignored by the reconciler.

**v19.34.186 — Variable-Tick Rounding** (`position_reconciler.py:1377-1389`)
Added `_v186_tick_round()` after orphan-stop math. Uses Decimal +
ROUND_HALF_UP to snap stop_price + target_1 to the correct grid:
- Stock < $1.00 → $0.0001 (4 decimals)
- Stock >= $1.00 → $0.01 (2 decimals)

Both patches committed as `002b7345`. Deploy script at paste.rs/jQJ9k
(idempotent, auto-commits, auto-pushes).

**One-time data repair** (`/tmp/repair_phantom_v19_34_185.py`,
paste.rs/eNi97). Cross-references `trade_audit_log` planned trades
against `bot_trades` reconciled_external fills within ±120s and ±0.5%
price tolerance. For 2026-05-28: surfaced 6 candidates, repaired 1
(BBAI 277sh short → vwap_fade_short, audit_match=0434fb3e tight_match).
The other 5 left as-is (genuine external positions, share-count drift,
or partial-fill remnants — script conservatively requires strong evidence).

### Files Changed
- `backend/services/position_reconciler.py` (+80 lines)

### Verification Plan (2026-05-29 open)
1. 15:45 ET — EOD heartbeats fire (v181/v182 confirms)
2. Throughout session — No `submit_race_v19_34_185` adoptions of
   bot-fired trades; bot keeps ownership
3. Sub-$5 stocks — No more `ib_error_110` permanent blocks;
   brackets attach cleanly

### Still Open (Deferred to Future Sessions)
- v19.34.184 — `alert_id` stamping fix for `squeeze`, `vwap_bounce`,
  `gap_fade`, `daily_squeeze`, `pocket_pivot` paths. v19.34.36 wiring
  works for `mean_reversion_short` but bypasses these 5 setups.
  Today: 11/22 trades had `alert_id=None`.
- v19.34.187 — Defensive belt-and-suspenders cooldown
  (`_recent_executor_activity` dict) on the reconciler. Belt for v185
  if pre_submit_at isn't stamped on some new code path.
- v19.34.172 — Dual-shape timestamps (`ts` ISO + `ts_dt` BSON) on
  `bot_trades`, `alert_outcomes`, `shadow_decisions`,
  `bracket_lifecycle_events` to prevent silent 0-rows query bugs.
- v19.34.175 — TQS/SMB unification + 5-pillar UI drill-down panel
  (read-only with expand-on-click, hide SMB "F" badges).

---


## 2026-05-28 — v19.34.181 + v19.34.182 EOD AUTO-CLOSE RESTORED

### Trigger
EOD auto-close failed silently on 2026-05-28 — operator had to manually
flatten all positions in TWS at the close. The v169 heartbeat showed
0 entries, suggesting `check_eod_close()` was never reached. Initial
hypothesis (three early `continue`s in scan_loop: daily-loss / trading
hours / PAUSED) was wrong — diagnostic queries confirmed none had tripped.

### Real Root Cause
`/tmp/backend.log` showed 10× consecutive lines of:
```
⚠️ [TradingBot] _check_eod_close exceeded 5.0s budget — skipping this cycle
```

The `_EOD_WALL_S = 5.0` asyncio.wait_for timeout in `_scan_loop` was killing
`check_eod_close()` on every cycle. Reasons EOD needs > 5s:
- `check_position_memory_disagreement` (IB roundtrip)
- `_flatten_ghost_positions` sweep
- Parallel `asyncio.gather` of N IB close calls (~2–5s each)

TimeoutError → "skipping this cycle" → next scan → repeat. The cancellation
happened BEFORE reaching the heartbeat write at line 1209, explaining the
0-heartbeat post-mortem.

### Fixes
**v19.34.181** — Single-line bump in `services/trading_bot_service.py`:
```python
_EOD_WALL_S = 5.0  →  _EOD_WALL_S = 60.0
```
Also re-canonicalized `bot_config.eod_config` MongoDB document:
`{enabled: True, close_hour: 15, close_minute: 45}`.

**v19.34.182** — Belt + suspenders. Added dedicated `_eod_supervisor_loop()`
asyncio task spawned in `TradingBotService.start()`:
- Ticks every 15s, **independent** of `_scan_loop`.
- Calls `check_eod_close()`, `check_scalp_decay()`, `_check_eod_grading()`
  with **NO `asyncio.wait_for` wall** — EOD can take as long as it needs.
- Idempotent: scan_loop ALSO calls them (60s wall now); both paths safe
  to run concurrently via `_eod_close_executed_today` flag + grading
  per-day key.
- New 16:00 ET hard alarm: if any `close_at_eod=True` position is still
  open at 4:00 PM ET, fires a CRITICAL `sentcom_thoughts` row
  (`category="eod_post_close_alarm"`) + WS broadcast.
- Cancelled cleanly in `TradingBotService.stop()`.

### Verification
Backend restart confirmed:
```
🤖 [TradingBot] Scan loop started - interval: 30s
🛡️  [TradingBot] v19.34.182 EOD supervisor started (15s cadence, no wait_for wall)
```

### Files Changed
- `backend/services/trading_bot_service.py` (v181 sed + v182 patch)
- `bot_config.eod_config` MongoDB document (canonical 15:45)

### Operational Notes
- Per `AGENTS.md`, backend restart uses `./start_backend.sh --force` (not
  supervisorctl). The Windows `.bat` runs `git checkout -- .` on the DGX,
  so v182's deploy script auto-commits + pushes immediately.
- Diagnostic script saved at `/tmp/eod_diag.py` for future post-mortems.

---


## 2026-05-28 — v19.34.170 Timestamp normalization + Fundamentals reconnect

### Trigger
Two recurring stability issues identified in the v169 handoff:

1. **Timestamp type drift across DB collections** — `bot_trades`,
   `alert_outcomes`, `shadow_decisions` write ISO strings;
   `bracket_lifecycle_events` and `_persist_thought` writes use BSON
   datetimes. The v169 EOD heartbeat wrote `created_at` as an ISO
   string, which broke the `created_at` TTL index on `sentcom_thoughts`
   AND made the row invisible to `routers/diagnostics.py` queries that
   filter on `timestamp` (ISO). Cross-collection queries returned 0
   rows silently — a known cause of "phantom" debugging sessions.

2. **Fundamentals "Not connected to IB" log spam** —
   `TradeContextService._capture_fundamental_context` unconditionally
   called `ib_service.get_fundamentals(symbol)` which raises
   `ConnectionError` whenever the direct ib_insync worker is stale
   (most of the time on this DGX install, since live data uses the IB
   pusher RPC path). Each evaluated alert logged a WARN and left the
   `FundamentalContext` empty.

### Fix
- **`backend/utils/timestamps.py`** — new module exposing `now_iso`,
  `now_bson`, `parse_to_bson`, `parse_to_iso`, `stamps`, `epoch_ms`.
  Canonical convention going forward: new collections write BOTH a
  `ts` ISO string AND a `ts_dt` BSON datetime so either query shape
  succeeds. Existing collections keep their current shape but
  consumers use `parse_to_bson`/`parse_to_iso` to coerce input.
- **`services/position_manager.py` EOD heartbeat** — rewritten to the
  canonical `sentcom_thoughts` schema: `kind="system"`, `content`,
  ISO `timestamp` (so `routers/diagnostics.py` queries see it), BSON
  `created_at` (so the TTL index actually expires it after 7d). Keeps
  top-level `category="eod_heartbeat"` so the operator's existing
  `db.sentcom_thoughts.find({category:'eod_heartbeat'})` query shape
  from v169 still works.
- **`services/trade_context_service.py`** — gate the IB fundamentals
  call behind `ib_service.get_connection_status()` and fall back to
  the Finnhub-backed `FundamentalDataService` when the direct IB
  worker reports disconnected. Earnings proximity lookup is now
  independent of either upstream.

### Test
- `tests/test_v19_34_170_timestamps_and_fundamentals.py` — 12 tests:
  timestamp parse/round-trip, fundamentals fallback hits Finnhub when
  IB is down, no IB call when disconnected, IB path is preferred when
  connected, static guard against the EOD heartbeat regressing to ISO
  `created_at`. All 12 pass. Regression suite (v164/v165/v168.1/v169
  = 54 tests) all still green.

### Deployment notes
- No DB migration needed — change is forward-compatible.
- After the next DGX backend restart, new `sentcom_thoughts` rows for
  EOD heartbeats will have the new schema. Old v169-shape rows TTL out
  in 7d.

---


## 2026-05-28 — v19.34.169 Pre-market sizing+EOD observability

### Trigger
Operator report: small share sizes on POSITION-tier setups (e.g. ALAB
1 share, ASTS 3 shares); and EOD scheduler appeared silent yesterday,
requiring ~13 manual TWS closes. Diagnosed root causes:

1. **Sizing**: `rs_leader_break`, `accumulation_entry`, `power_trend_stack`,
   `stage_2_breakout` use 2.5-3.0× ATR multipliers. On high-priced
   volatile names this yields 12-14% raw stop distances, which
   combined with the fixed risk_per_trade budget collapsed share
   counts to 1-3. POSITION-tier setups are multi-day holds by design
   (`close_at_eod=False`); their stops were tuned for swing R:R, not
   intraday risk envelopes.

2. **EOD silence**: `_check_eod_close` IS wired into the scan loop
   (`trading_bot_service.py:3907`, with a wall-time budget) and
   `_eod_close_enabled=True` at init. But EOD state lives only
   in-memory on the `TradingBotService` instance — no DB
   audit trail. Yesterday's `/tmp/backend.log` was truncated by the
   morning restart, so we can't retrospectively prove what fired.
   The 11 filled positions all closed via `oca_closed_externally_v19_31`
   — the bot's catch-all when IB shows position vanished without
   bot-initiated close. That reason fires for BOTH IB OCA brackets
   AND operator-initiated TWS manual closes (the bot can't distinguish).

### Fix
- **`opportunity_evaluator.calculate_atr_based_stop`** — cap stop
  distance at 5% of entry for ATR multipliers ≥ 2.5 (INVESTMENT and
  POSITION horizons). Operator-tunable via env
  `MAX_STOP_PCT_INVESTMENT` / `MAX_STOP_PCT_POSITION`. Scalps and
  intraday setups unchanged. Cap NEVER widens an already-tight stop.
- **`position_manager.check_eod_close`** — write a `sentcom_thoughts`
  row (category=`eod_heartbeat`) once per minute inside the EOD
  window so the operator can SEE the scheduler firing from the UI
  even when no positions are eligible to close. Dedupes per HH:MM.
- **`start_backend.sh`** — archive `/tmp/backend.log` to
  `logs/backend_YYYYMMDD_HHMMSS.log` before each restart, with 30-day
  retention. Prevents future "where did yesterday's evidence go" gaps.

### Tests (`backend/tests/test_v19_34_169_stop_cap.py`)
- 8/8 passing: ALAB 5% cap, stage_2_breakout 5% cap (3.0× mult),
  accumulation_entry 5% cap (2.5× mult), intraday breakout NOT capped,
  9_ema_scalp NOT capped, env override (`MAX_STOP_PCT_POSITION=0.07`),
  already-tight stop preserved, short-side symmetry.

### Verified live on DGX
- POSITION-tier sizing: deployed via `backend/scripts/deploy_v19_34_169.py`.
  Restart confirmed; first qualifying trade will show stop_pct ≤ 5%.
- Log archive: `→ archived /tmp/backend.log → logs/backend_20260528_093341.log
  (702099 bytes)` on first restart.
- EOD heartbeat: deferred verification to today's 19:45-20:00 UTC
  window (operator to query `sentcom_thoughts` for category=eod_heartbeat).

### Known follow-ups
- EOD bug NOT confirmed-fixed yet — heartbeat is the diagnostic.
  Action item for tonight: query for `category=eod_heartbeat` after
  the close. If heartbeats fire but no closes go out for
  `close_at_eod=True` positions, the bug is downstream in the
  flatten path. If no heartbeats at all, the scan loop isn't reaching
  EOD code (timeout, wedged loop, etc.).
- `bot._eod_close_executed_today` flag is in-memory only — needs DB
  persistence so a mid-day crash doesn't repeat EOD.


## 2026-05-27 — v19.34.168.1 Composite regime history+stats routing fix

### Trigger
v168 added `/api/market-regime/history` + `/api/market-regime/stats`
endpoints as bare `@app.get(...)` decorators in `server.py`. Both
collided with the existing daily Engine A router (`routers/market_regime.py`
mounted at prefix `/api/market-regime`): `/history` was shadowed
(returned daily Engine A's `market_regime_state` rows instead of intraday
snapshots) and `/stats` returned 404.

### Fix
- Renamed the new intraday endpoints to live under the `composite/`
  namespace established by v167.1:
  - `GET /api/market-regime/composite/history` → reads `regime_snapshots`
  - `GET /api/market-regime/composite/stats` → % time-in-regime over N hours
- Both endpoints registered next to the working `/api/market-regime/composite`
  route at the end of `server.py` so binding is deterministic.
- Daily Engine A `/api/market-regime/history` still serves `market_regime_state`
  (no collision, verified via regression curl).
- `backend/services/regime_persistence_service.py` shipped with TTL=30d index,
  in-process change detection, history + stats query helpers.
- Idempotent deploy script `backend/scripts/deploy_v19_34_168_1.py`:
  strips any prior broken `@app.get("/api/market-regime/history")` /
  `/stats` decorators before injecting the new routes.

### Tests (`backend/tests/test_v19_34_168_1_endpoint_routing.py`)
- 8/8 passing: change-detection, divergence-flip persistence, history
  filter window, stats % calculation, empty-DB handling, and
  `server.py` namespace verification.

### Verified live on DGX
- `composite/history?hours=6` → `success:true, source:"regime_snapshots"`
- `composite/stats?hours=6` → `success:true, "no snapshots in window"`
  (correct — collection only populates on regime/agreement/divergence flips)
- `history?days=30` → still returns Engine A composite_score data (no regression)


## 2026-05-27 — v19.34.167 Composite SPY/QQQ/IWM market regime classifier

### Trigger
v166 fixed the SPY trend classifier but the SCANNER's regime gating
(`enhanced_scanner._update_market_context`) was still SPY-only — blind
to QQQ/IWM divergence. A clean uptrend in SPY+QQQ with IWM breaking
down would tag the market STRONG_UPTREND and let `9_ema_scalp` fire
into a small-cap-led reversal.

### Architecture decision
Audited the three existing regime layers (`MarketRegimeEngine` daily,
`enhanced_scanner._update_market_context` intraday, `realtime_technical_service.trend`
per-symbol kernel) — kept them separate (different timeframes) and
extended layer 2 to vote across the broad indexes using the layer 3
kernel as the per-index probe. No new infrastructure.

### Patch (`backend/services/enhanced_scanner.py`)
1. **`_update_market_context`** rewritten to `asyncio.gather` SPY+QQQ+IWM
   snapshots in parallel, then delegate to a pure classifier.
2. **`_classify_market_regime(spy, qqq, iwm)`** — new pure method:
   - VOLATILE if max daily_range_pct across valid indexes > 2.0
   - Unanimous (3/3) up + 3/3 above VWAP + EMA9 → STRONG_UPTREND
     (or MOMENTUM if SPY rsi > 60)
   - Unanimous (3/3) down + 3/3 not above VWAP → STRONG_DOWNTREND
   - Majority (2/3) up + 2/3 VWAP support → MOMENTUM (degraded)
   - Majority (2/3) down → FADE (degraded)
   - Mixed/no majority → RANGE_BOUND (or FADE if SPY quiet + extreme RSI)
3. **Single-index fallback** replays v166 logic verbatim if QQQ/IWM
   unavailable.
4. **`self._market_data`** new attribute exposing `indices_valid`,
   `index_agreement` (unanimous_up/down, majority_up/down, mixed),
   `divergence_flag`, `uptrend_votes`, `downtrend_votes`,
   `max_daily_range_pct`, and `per_index: {spy, qqq, iwm}` breakdown.
5. `self._spy_data` retained for backwards compat with downstream consumers.

### Tests — `backend/tests/test_market_regime_composite_v19_34_167.py`
14/14 passing on DGX:
- Unanimous up (clean / overbought)
- Unanimous down
- Small-cap divergence (SPY+QQQ up, IWM down) → MOMENTUM
- Tech divergence (majority down) → FADE
- 1-1-1 split → RANGE_BOUND
- VOLATILE override (IWM > 2% range)
- 2% boundary not VOLATILE (strict >)
- Single-index degraded mode (3 variants)
- Metadata structure sanity
- v166 audit case regression: must NOT classify STRONG_DOWNTREND

### Deploy
Single-line 12,904-char base64 paste (after chunked approach broke
when chat collapsed newlines). Pre/post SHA verified.

### Verification
- Pre: `73991b86facdc3e1...` → Post: `0bdbb7a97c6a78f7...` ✅
- New backend PID 3757239 serving on :8001 ✅
- Backup retained: `enhanced_scanner.py.pre_v167.bak`

### Watch next
- Scanner ticks emit new alerts with composite regime + divergence flag
- Setups that were silenced by false STRONG_DOWNTREND tags should
  start firing during clean uptrend / sideways regimes

---

## 2026-05-27 — v19.34.166 Trend classifier tolerance + macro-context veto

### Trigger
After v19.34.165 unlocked 5 momentum setups, the audit found that ~80% of
live alerts on a +0.48% SPY gap-up day were being tagged
`strong_downtrend` by `realtime_technical_service.get_technical_snapshot`.
SPY at 749.19 (EMA9=749.26, EMA20=749.65, EMA50=698.44, SMA200=698.44)
was classified "downtrend" because the original logic at L596-602 used
strict binary `>` vs EMA9/EMA20 — a 7-cent intraday print below EMA9
flipped the classification despite price sitting 7% above EMA50 and the
secular structure being a clean uptrend. The misclass poisoned every
setup gate that requires `trend == "uptrend"` (incl. `9_ema_scalp`,
dormant since 2026-04-07).

### Patch (`backend/services/realtime_technical_service.py` L593-643)
1. **Tolerance band — 0.25%** (`_TREND_TOLERANCE_PCT`). Distances within
   ±0.25% of an EMA count as "at" — neither above nor below — so noise-
   level prints don't flip uptrend↔downtrend tick-by-tick.
2. **Macro-context veto**. If price > EMA50 AND EMA50 > SMA200 (secular
   uptrend structure), the classifier may NEVER return "downtrend".

### Tests — `backend/tests/test_trend_classifier_v19_34_166.py`
9/9 passing.

### Verification
- pre `f38efa1ac07888a3...` → post `afba82a9db7bfa60...` ✅
- Live SPY trend went from "downtrend" → "sideways" at price=749.46,
  dist_from_ema9=-0.01%

---
