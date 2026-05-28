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
