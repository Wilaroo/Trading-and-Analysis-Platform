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
