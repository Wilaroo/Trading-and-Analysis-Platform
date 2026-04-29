# TradeCommand / SentCom — Product Requirements

> Lean, static spec. Dated work history lives in `CHANGELOG.md`.
> Open priorities and backlog live in `ROADMAP.md`.
>
> **Rules for the agent (keep these docs alive):**
>   - Ship something → prepend a `## YYYY-MM-DD — <title> — SHIPPED`
>     section to **CHANGELOG.md** (Why / Scope / Verification).
>   - Priority shifts → reorder **ROADMAP.md**; promoted item moves up,
>     completed item is removed and recorded in CHANGELOG.
>   - Architecture / API contract / hardware topology changes → edit
>     **PRD.md** (this file).
>   - Never silently drop history; never let `🔴 Now / Near-term` go
>     stale across more than one task.

## Original problem statement
AI trading platform running across DGX Spark (Linux) + Windows PC (IB Gateway). Goal: stable massive training pipeline, real-time responsive UI, SentCom chat aware of live portfolio status without hanging the backend, and a bot that can go live for automated trading with accurate dashboards.


## Architecture
- **DGX Spark (Linux, 192.168.50.2)**: Backend FastAPI :8001, Chat :8002, MongoDB :27017, Frontend React :3000, Ollama :11434, worker, Blackwell GPU
- **Windows PC (192.168.50.1)**: IB Gateway :4002, IB Data Pusher (client 15), 4 Turbo Collectors (clients 16–19)
- Orders flow: Spark backend `/api/ib/orders/queue` → Mongo `order_queue` → Windows pusher polls `/api/ib/orders/pending` → submits to IB → reports via `/api/ib/orders/result`
- Position/quotes flow: IB Gateway → pusher → `POST /api/ib/push-data` → in-memory `_pushed_ib_data` (+ Mongo snapshot for chat_server)




## Key API surface
- `GET /api/portfolio` — IB pushed positions + manual fallback; quote_ready guard
- `POST /api/portfolio/flatten-paper?confirm=FLATTEN` — flatten paper account, 120s cooldown
- `GET /api/assistant/coach/morning-briefing` — Setup-landscape + multi-index-regime grounded morning briefing in 1st-person voice (2026-04-30 v4)
- `GET /api/assistant/coach/eod-briefing` — retrospective EOD coaching (2026-04-29 v3)
- `GET /api/assistant/coach/weekend-prep-briefing` — Sunday-night prep (2026-04-29 v3)
- `GET /api/scanner/setup-landscape?context=morning|midday|eod|weekend` — universe-wide Bellafiore-Setup snapshot + 1st-person narrative (now leads with multi-index regime line + cites yesterday's grade — 2026-04-30 v4)
- `GET /api/scanner/landscape-receipts?days=7&context=morning` — recent graded landscape predictions (closes the AI feedback loop — 2026-04-30 v4)
- `POST /api/scanner/landscape-grade?trading_day=YYYY-MM-DD` — manual trigger of EOD grading job (2026-04-30 v4)
- `GET /api/scanner/setup-trade-matrix` — full Trade × Setup matrix + classifier stats (2026-04-29 v2)
- `GET /api/scanner/sector-regime` — per-sector regime snapshot (11 SPDR ETFs + SPY benchmark, soft-gate ML feature — 2026-04-30 v6)
- `POST /api/scanner/backfill-sector-tags` — populate `symbol_adv_cache.sector` from the static GICS map (idempotent — 2026-04-30 v6)
- `GET /api/scanner/in-play-config` — current in-play scoring thresholds (single source of truth shared by scanner + AI assistant — 2026-04-30 v7)
- `PUT /api/scanner/in-play-config` — runtime threshold tuning, persists to `bot_state.in_play_config` (`{"strict_gate": true}` opts into hard gating — 2026-04-30 v7)
- `GET /api/diagnostic/trade-funnel?date=YYYY-MM-DD` — walks the alert→bot→execution chain and pinpoints the first dead stage (2026-04-30 v8)
- `GET /api/scanner/setup-coverage` — orphan/silent/active/time-filtered diagnostic
- `GET /api/scanner/detector-stats` — per-detector evals + hits (cumulative + cycle)
- `GET /api/ai-modules/validation/summary` — promotion-rate dashboard
- `POST /api/ib/push-data` — receive pusher snapshot
- `GET /api/ib/orders/pending` — pusher polls this
- `POST /api/ib/orders/claim/{id}`, `POST /api/ib/orders/result` — claim/complete hooks pusher should use but may not
- `POST /api/ai-modules/shadow/track-outcomes?drain=true&batch_size=50` — drain shadow-decision backlog (added 2026-04-29). Yields to event loop between batches.


## Pipeline architecture (Bellafiore + ML hybrid)

### Conceptual hierarchy (operator mental model + UI)
`Market Regime (SPY/QQQ/IWM/DIA) → Sector Regime → Daily Setup → Time/In-play → Trade`

### Runtime architecture (decided 2026-04-29 evening, locked 2026-04-30)
**Hard gates only in 3 places** to avoid compounding rejection rate
that would starve the ML pipeline of training data:
  1. **Time-window** (`_is_setup_valid_now` in `enhanced_scanner.py`) — opening_drive can't fire midday
  2. **In-Play / Universe** — ADV ≥ $2M/day floor (FAIL CLOSED on unknown ADV) + RVOL ≥ 0.8 floor + tier-based scan frequency. **Unified richer in-play score** (RVOL/Gap/ATR/Spread/Catalyst — `services/in_play_service.py`, shipped 2026-04-30 v7) is **stamped on every alert** as metadata; promotes to a hard gate only when `bot_state.in_play_config.strict_gate=true`.
  3. **Confidence gate** — predicted_R + win_prob threshold

**Everything else flows in as features** to the per-Trade ML models:
  - **Multi-index regime tag** (`MultiIndexRegimeClassifier` —
    shipped 2026-04-30) — composite SPY/QQQ/IWM/DIA label, 8 active
    buckets + UNKNOWN; one-hot encoded into `regime_label_*` features.
  - **Sector regime tag** (`SectorRegimeClassifier` — shipped
    2026-04-30) — 11 SPDR sector ETFs + SPY benchmark → 5 active
    buckets + UNKNOWN; per-symbol resolution via static GICS map
    in `SectorTagService`; one-hot encoded into `sector_label_*`
    features. Training uses `SectorRegimeHistoricalProvider` with
    per-(etf, date) caching.
  - Daily Setup tag (`MarketSetupClassifier` — shipped 2026-04-29 v2;
    one-hot encoded into `setup_label_*` features 2026-04-30)
  - Setup × Trade matrix context (`is_countertrend`, `out_of_context_warning`, `experimental` — shipped 2026-04-29 v2)
  - Setup landscape (`SetupLandscapeService` — shipped 2026-04-29 v3;
    extended with regime line 2026-04-30)
  - Numerical regime features (24 floats — `regime_features.py`,
    SPY/QQQ/IWM trend/RSI/momentum/breadth/correlations/rotations)

`STRATEGY_REGIME_PREFERENCES` in `enhanced_scanner.py` is METADATA
ONLY — explicitly NOT a hard-gate enforcement (re-documented
2026-04-30 to close the next-session-plan item #6). It documents the
operator's mental model of which trades thrive in which regimes; the
actual learning happens via the one-hot features above.

The matrix in `services/market_setup_classifier.py::TRADE_SETUP_MATRIX`
is the operator's source of truth for which Trade fits which Setup;
`/app/memory/SETUPS_AND_TRADES.md` is the human-readable mirror.


## Key files
- `backend/routers/portfolio.py` — portfolio endpoint + flatten-paper
- `backend/routers/ib.py` — push-data + order queue glue
- `backend/routers/scanner.py` — `/setup-coverage`, `/setup-trade-matrix`, `/setup-landscape`, `/detector-stats`
- `backend/routers/assistant.py` — `/coach/morning-briefing`, `/coach/eod-briefing`, `/coach/weekend-prep-briefing`
- `backend/services/order_queue_service.py` — Mongo-backed queue with auto-expire
- `backend/services/enhanced_scanner.py` — 38 trade detectors, scanner loop, `_apply_setup_context` matrix gate + multi-index regime stamping (2026-04-30), `LiveAlert` dataclass with context fields (`market_setup`, `is_countertrend`, `out_of_context_warning`, `experimental`, `multi_index_regime`)
- `backend/services/market_setup_classifier.py` — `MarketSetup` enum (7 + NEUTRAL), `MarketSetupClassifier` (daily-bar driven), `TRADE_SETUP_MATRIX`, `TRADE_ALIASES`, `EXPERIMENTAL_TRADES`, `lookup_trade_context()`, `_sync_classify_window()` for training-time per-bar labels (2026-04-30)
- `backend/services/in_play_service.py` — **NEW 2026-04-30** — unified in-play scorer used by both the live scanner (`score_from_snapshot`) and the AI assistant (`score_from_market_data`); runtime-tunable thresholds persisted to `bot_state.in_play_config`; SOFT mode by default (stamps `LiveAlert.in_play_score/reasons/disqualifiers` only), STRICT mode rejects alerts when `is_in_play=False`
- `backend/services/multi_index_regime_classifier.py` — **NEW 2026-04-30** — `MultiIndexRegime` enum (9 buckets), `MultiIndexRegimeClassifier` reads ~25 daily bars per index (SPY/QQQ/IWM/DIA), 5-min market-wide cache, `derive_regime_label_from_features()` for training
- `backend/services/sector_tag_service.py` — **NEW 2026-04-30** — static GICS-aligned `STATIC_SECTOR_MAP` (~340 most-liquid stocks) + ETF self-mapping; `tag_symbol`, `tag_many`, `coverage`, `backfill_symbol_adv_cache` (idempotent)
- `backend/services/sector_regime_classifier.py` — **NEW 2026-04-30** — `SectorRegime` enum (6 buckets: STRONG/ROTATING_IN/NEUTRAL/ROTATING_OUT/WEAK/UNKNOWN), `SectorRegimeClassifier` reads 11 SPDR ETFs + SPY (5-min market-wide cache), `SectorRegimeHistoricalProvider` for training-time per-sample sector regime lookup with per-(etf,date) caching
- `backend/services/ai_modules/composite_label_features.py` — **NEW 2026-04-30** — one-hot helpers: `SETUP_LABEL_FEATURE_NAMES` (7), `REGIME_LABEL_FEATURE_NAMES` (8), `SECTOR_LABEL_FEATURE_NAMES` (5), `ALL_LABEL_FEATURE_NAMES` (20), `build_label_features(market_setup, multi_index_regime, sector_regime)`
- `backend/scripts/backfill_sector_tags.py` — **NEW 2026-04-30** — one-shot CLI for sector backfill
- `backend/services/setup_landscape_service.py` — `SetupLandscapeService` with 4 narrative voices (morning/midday/eod/weekend), 1st-person voice rules, 60s cache, **regime line preface (2026-04-30)** + `LandscapeSnapshot.multi_index_regime/regime_confidence/regime_reasoning` + **auto-records snapshot to `landscape_predictions` (2026-04-30) + cites yesterday's grade in morning narrative**
- `backend/services/landscape_grading_service.py` — **NEW 2026-04-30** — `LandscapeGradingService` records every snapshot's prediction to `landscape_predictions`, grades EOD by joining to `alert_outcomes` (A/B/C/D/F per Bellafiore Setup family), `get_recent_grades` powers the morning briefing's "Quick receipt — yesterday I predicted ..." citation. **`get_weekly_summary` (2026-04-30 v5)** rolls up the past 7 days of grades for the Sunday weekend voice ("Last week's record — 3A · 1B · 1C — strong directional read")
- `backend/services/ai_assistant_service.py` — `get_coaching_alert()` injects landscape narrative + voice rules + multi-index regime fields into AI prompts and payload (2026-04-30)
- `backend/services/ai_modules/timeseries_service.py` — training (`_train_single_setup_profile`) + prediction (`predict_for_setup`) plumbed with the 15 categorical label features (2026-04-30)
- `frontend/src/components/MorningBriefingModal.jsx` — briefing UI + Flatten button
- `backend/services/ai_modules/post_training_validator.py` — 9 fail-closed gates
- `backend/scripts/revalidate_all.py` — Phase 13 revalidation script
- `backend/services/smart_levels_service.py` — `compute_smart_levels`, `compute_stop_guard`, `compute_target_snap`, `compute_trailing_stop_snap` (added 2026-04-29 — liquidity-aware trail)
- `backend/services/stop_manager.py` — `set_db(db)` injection enables HVN-anchored breakeven + trail (2026-04-29). **Realtime stop-guard re-check (2026-04-30 v11)**: `_periodic_resnap_check` runs after every `update_trailing_stop` call (60s per-trade throttle), re-snaps to fresher HVN levels in `breakeven`/`trailing` modes, ratchet-only.
- `backend/services/sector_tag_service.py` — `tag_symbol_async` (2026-04-30 v11) full fallback chain: STATIC_MAP → `symbol_adv_cache.sector` → Finnhub `stock/profile2` industry → `_industry_to_etf` mapper → persist back to Mongo. `_PRIORITY_OVERRIDES` resolves conflicts (Biotech > Tech, REIT > Industrial, Renewable > Energy); `_EXPLICIT_NONE` blocklist returns UNKNOWN for cryptocurrency / SPAC / trust / fund.
- `frontend/src/components/sentcom/v5/ShadowVsRealTile.jsx` — **NEW 2026-04-30 v11** — V5 status-strip tile, reads `/api/ai-modules/shadow/stats` + `/api/trading-bot/stats/performance` every 60s, renders side-by-side win-rate + divergence signal (`shadow ahead` / `shadow behind` / `in sync` per ±5pp).
- `app/memory/SETUPS_AND_TRADES.md` — canonical doc for the 7 Setups + 22 Trades + matrix + aliases


## Hardware runtime notes
- Can't test this codebase in the Emergent container (no IB, no pusher, no GPU). All verification is curl/python on the user's Spark. Testing agents unavailable for integration flows.
- Code changes reach Spark via "Save to Github" → `git pull` on both Windows and Spark.
- Backend restart: `pkill -f "python server.py" && cd backend && nohup python server.py > /tmp/backend.log 2>&1 &` (Spark uses `.venv`, not supervisor)


