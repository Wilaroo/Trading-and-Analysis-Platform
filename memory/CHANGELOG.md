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
