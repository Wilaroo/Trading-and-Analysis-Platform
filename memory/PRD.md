# TradeCommand / SentCom — Product Requirements

## Original problem statement
AI trading platform running across DGX Spark (Linux) + Windows PC (IB Gateway). Goal: stable massive training pipeline, real-time responsive UI, SentCom chat aware of live portfolio status without hanging the backend, and a bot that can go live for automated trading with accurate dashboards.

## Architecture
- **DGX Spark (Linux, 192.168.50.2)**: Backend FastAPI :8001, Chat :8002, MongoDB :27017, Frontend React :3000, Ollama :11434, worker, Blackwell GPU
- **Windows PC (192.168.50.1)**: IB Gateway :4002, IB Data Pusher (client 15), 4 Turbo Collectors (clients 16–19)
- Orders flow: Spark backend `/api/ib/orders/queue` → Mongo `order_queue` → Windows pusher polls `/api/ib/orders/pending` → submits to IB → reports via `/api/ib/orders/result`
- Position/quotes flow: IB Gateway → pusher → `POST /api/ib/push-data` → in-memory `_pushed_ib_data` (+ Mongo snapshot for chat_server)

## Completed in this session (2026-04-20)
### XGBoost & setup models rewired to triple-barrier labels (P0) — DONE
- `_extract_symbol_worker` (Phase 1 generic directional, `timeseries_gbm.py`) now produces
  triple-barrier 3-class labels (0=DOWN/SL-hit, 1=FLAT/time-exit, 2=UP/PT-hit) instead of
  binary `future > current`. Feature cache key bumped to `_tb3c` to invalidate stale entries.
- `_extract_setup_long_worker` (Phase 2) and `_extract_setup_short_worker` (Phase 2.5) switched
  from noise-band 3-class to triple-barrier 3-class. Shorts use negated-series trick so the
  lower barrier == PT for a short.
- Phase 7 regime-conditional models switched from binary `future_ret > 0` to triple-barrier
  3-class; `train_from_features(num_classes=3)`.
- Phase 8 ensemble meta-learner switched from ±0.3% threshold 3-class to triple-barrier
  (using ATR-scaled barriers with `max_bars = anchor_fh`).
- `TimeSeriesGBM.train()` and `train_vectorized()` now delegate to
  `train_from_features(num_classes=3)` — single canonical training path.
- `TimeSeriesGBM.predict()` handles 3-class softmax output (shape (1,3)) → `{down, flat, up}`.
- Persistence: `_save_model()` writes `num_classes` and `label_scheme`
  (`triple_barrier_3class` or `binary`); `_load_model()` restores `_num_classes`.
- `get_setup_models_status()` now returns `label_scheme` per profile from DB so UI can
  distinguish freshly-trained triple-barrier models from legacy binary models.
- NIA `SetupModelsPanel` shows a green **Triple-Barrier** badge for new models and a red
  **Legacy binary** warning for models that need retraining.

### Test coverage
- `backend/tests/test_triple_barrier_labeler.py` (8 tests, unchanged).
- NEW: `backend/tests/test_timeseries_gbm_triple_barrier.py` (3 tests):
  - `_extract_symbol_worker` returns int64 3-class targets.
  - End-to-end train_from_features(num_classes=3) + XGBoost softprob predict returns (N,3).
  - `get_model_info`/`get_status` surface `num_classes` and `label_scheme`.
- All 11 tests pass (`PYTHONPATH=backend python -m pytest backend/tests/…`).

### Downstream consumers — verified wired to new scheme (no code changes needed):
- `predict_for_setup` (timeseries_service.py): already handles 3-class softprob output →
  returns `{direction: up/down/flat, probability_up/down/flat, confidence, num_classes}`.
- `confidence_gate.py`: consumes via `_get_live_prediction` → `predict_for_setup` (up/down/flat),
  plus `_get_tft_signal`, `_get_cnn_lstm_signal`, `_get_cnn_signal`, `_get_vae_regime_signal`
  which already return 3-class direction strings.
- TFT + CNN-LSTM `predict()`: direction_map {0:down, 1:flat, 2:up} — matches triple-barrier
  class indices (fixed earlier this session).
- Scanner / Trading Bot / Learning Loop / Trade Journal / NIA / SentCom Chat: consume
  `direction` as semantic string ("up"/"down"/"flat" for prediction, "long"/"short" for trade
  side). No changes needed — prediction interface unchanged.

### Retrain plan (USER — run on Spark once Phase 13 revalidation finishes)
1. Stop the current bot and revalidation script.
2. Clear the NVMe feature cache so `_tb3c` keys rebuild:
   `mongo tradecommand --eval 'db.feature_cache.deleteMany({})'`
3. Kick off a full retrain (Phase 1 → Phase 8): `python backend/scripts/local_train.py`
   (or the worker job if available). This will produce triple-barrier models that
   overwrite the old binary/noise-band models in `timeseries_models` collection (protected
   by the best-model promotion gate — new model must beat accuracy of current active).
4. After training, rerun `python backend/scripts/revalidate_all.py` to validate the new
   models against the fail-closed gates.
5. Retrain DL models (TFT, CNN-LSTM, VAE) via the Phase 11 job so their metadata matches
   (`regime_diversity`, `win_auc`).
6. Verify the NIA page shows green **Triple-Barrier** badges on every trained profile,
   and that 0-trade filter rate drops below 100% on sample symbols.


### P0 Morning Briefing bogus-position bug — RESOLVED
- Root-caused: `MorningBriefingModal.jsx` calls `/api/portfolio`, which pulls IB-pushed positions. When marketPrice=0 on restart, `gain_loss = 0 − cost_basis` produced fake -$1.2M.
- Fix: `backend/routers/portfolio.py` — added `quote_ready` flag per position and `quotes_ready` in summary; trusts IB's `unrealizedPNL` until live quote arrives; filters zero-share rows.
- Fix: `frontend/src/components/MorningBriefingModal.jsx` — shows amber "awaiting quotes" badge instead of fake PnL. Flatten button removed (wrong place for destructive admin action).

### New `POST /api/portfolio/flatten-paper` endpoint
- Guard rails: `confirm=FLATTEN` token, paper-account-only (code starts with 'D'), 120s cooldown, pre-flight cancel of stale `flatten_*` orders, pusher-freshness check (refuses if last_update >30s old).

### IB Pusher double-execution bug — FIXED
- Root cause: TWS mid-session auto-upgrade + fixed pusher clientId=15 → IB replayed stale session state as new orders, causing 2×-3× fills per flatten order.
- `documents/scripts/ib_data_pusher.py` — added `_recently_submitted` in-memory idempotency cache stamping each `order_id → (timestamp, ib_order_id)` immediately after `placeOrder()`. Any duplicate poll of same order_id is blocked + reported rejected within 10 min.
- `documents/scripts/StartTradeCommand.bat` — pusher clientId now randomized 20–69 per startup so stale TWS sessions can't replay.

### 🚨 Credential leak — FIXED
- Paper password was hardcoded in `.bat` and committed to GitHub. Moved to local-only `.ib_secret`, `.gitignore` updated, `README_SECRETS.md` added.
- User rotated paper password + created `.ib_secret` on Windows.

### Validator fail-open paths — LAYER 1 FIXED, LAYER 2 IDENTIFIED AND FIXED
- **Layer 1 (earlier session)**: `Insufficient trades → promoting by default` → replaced with 9 fail-closed gates (n≥30, Sharpe≥0.5, edge≥5pp, MC P(profit)≥55%, etc.)
- **Layer 2 (today, 2026-04-20)**: when a failing model had no prior baseline to roll back to, validator silently flipped `decision["promote"] = True` and saved the broken model as baseline. Now rejects outright and does NOT write a baseline; trading bot reads baselines as the live-trading gate, so rejected models cannot leak into prod.
- `backend/scripts/revalidate_all.py` — fixed dict-vs-string bug in SETUP_TRAINING_PROFILES iteration.

### Phase 13 revalidation — RUNNING
- Launched against 20 unique setup types (best bar_size each, from 34 trained pairs).
- Uses fixed fail-closed validator + new layer-2 fix.
- ETA ~60-90 min. First run pending verification.

## Active P0 Blockers
### 🟢 Pusher double-execution bug — FIXED (pending verification on Windows)
- **Root cause**: TWS mid-session auto-upgrade caused the pusher's IB client connection (fixed clientId=15) to reconnect with stale session state. Previously-submitted MKT orders got replayed by TWS as if new, causing 2×-3× execution for each flatten order.
- **Fixes applied (2026-04-20)**:
  1. `ib_data_pusher.py` — `_recently_submitted` in-memory cache stamps each `order_id → (timestamp, ib_order_id)` immediately after `placeOrder()`. Any duplicate poll of same order_id is blocked + reported rejected within 10-min window.
  2. `StartTradeCommand.bat` — pusher clientId now randomized 20–69 each startup (`set /a IB_PUSHER_CLIENT_ID=%RANDOM% %% 50 + 20`). TWS can't replay a clientId it's never seen.
  3. `routers/portfolio.py` flatten endpoint — refuses to fire if pusher snapshot > 30s old (prevents flattening against stale positions).
  4. Pre-flight cancel of prior `flatten_*` orders (already done in first pass).
- **Verification plan for next session**: re-enable TWS API, restart pusher with new fixes, queue a single test order, confirm IB shows exactly one fill.

### 🚨 Security — paper password was committed to git
- `StartTradeCommand.bat` had `set IB_PASSWORD=Socr1025!@!?` hardcoded (line 30, pre-fix).
- **Fixed**: password moved to local `.ib_secret` file loaded via `call "%REPO_DIR%\.ib_secret"`. `.gitignore` updated to cover `*.secret`. `documents/scripts/README_SECRETS.md` explains setup.
- **User action required**: rotate the paper password in IB Account Management, then create `.ib_secret` on the Windows PC with the new password.

## P1 Outstanding
- Phase 13 revalidation: `backend/scripts/revalidate_all.py` against the fixed fail-closed validator (was next after Morning Briefing)
- Phase 6 Distributed PC Worker: offload CNN/DL training to Windows PC over LAN
- Rebuild TFT / CNN-LSTM with triple-barrier targets (binary up/down → majority-class collapse)
- Wire FinBERT into confidence gate as Layer 12
- Wire confidence gate into live validation

## P2 / Backlog
- Motor async MongoDB driver migration (replace sync PyMongo in hot paths)
- Per-signal weight optimizer for gate auto-tuning
- Earnings calendar + news feed in Chat
- Sparkline (12-wk promotion rate) on ValidationSummaryCard
- `server.py` breakup → `routers/` + `models/` + `tests/`

## Key API surface
- `GET /api/portfolio` — IB pushed positions + manual fallback; quote_ready guard
- `POST /api/portfolio/flatten-paper?confirm=FLATTEN` — flatten paper account, 120s cooldown
- `GET /api/assistant/coach/morning-briefing` — coach prompt only (not position source)
- `GET /api/ai-modules/validation/summary` — promotion-rate dashboard
- `POST /api/ib/push-data` — receive pusher snapshot
- `GET /api/ib/orders/pending` — pusher polls this
- `POST /api/ib/orders/claim/{id}`, `POST /api/ib/orders/result` — claim/complete hooks pusher should use but may not

## Key files
- `backend/routers/portfolio.py` — portfolio endpoint + new flatten-paper
- `backend/routers/ib.py` — push-data + order queue glue
- `backend/services/order_queue_service.py` — Mongo-backed queue with auto-expire
- `frontend/src/components/MorningBriefingModal.jsx` — briefing UI + Flatten button
- `backend/services/ai_modules/post_training_validator.py` — 9 fail-closed gates
- `backend/scripts/revalidate_all.py` — Phase 13 revalidation script

## Hardware runtime notes
- Can't test this codebase in the Emergent container (no IB, no pusher, no GPU). All verification is curl/python on the user's Spark. Testing agents unavailable for integration flows.
- Code changes reach Spark via "Save to Github" → `git pull` on both Windows and Spark.
- Backend restart: `pkill -f "python server.py" && cd backend && nohup python server.py > /tmp/backend.log 2>&1 &` (Spark uses `.venv`, not supervisor)
