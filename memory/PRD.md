# TradeCommand / SentCom — Product Requirements

## Original problem statement
AI trading platform running across DGX Spark (Linux) + Windows PC (IB Gateway). Goal: stable massive training pipeline, real-time responsive UI, SentCom chat aware of live portfolio status without hanging the backend, and a bot that can go live for automated trading with accurate dashboards.

## Architecture
- **DGX Spark (Linux, 192.168.50.2)**: Backend FastAPI :8001, Chat :8002, MongoDB :27017, Frontend React :3000, Ollama :11434, worker, Blackwell GPU
- **Windows PC (192.168.50.1)**: IB Gateway :4002, IB Data Pusher (client 15), 4 Turbo Collectors (clients 16–19)
- Orders flow: Spark backend `/api/ib/orders/queue` → Mongo `order_queue` → Windows pusher polls `/api/ib/orders/pending` → submits to IB → reports via `/api/ib/orders/result`
- Position/quotes flow: IB Gateway → pusher → `POST /api/ib/push-data` → in-memory `_pushed_ib_data` (+ Mongo snapshot for chat_server)

## Completed in this session (2026-04-20)
### P0 Morning Briefing bogus-position bug — RESOLVED
- Root-caused: `MorningBriefingModal.jsx` calls `/api/portfolio`, which pulls IB-pushed positions. When marketPrice=0 on restart, `gain_loss = 0 − cost_basis` produced fake -$1.2M.
- Fix: `backend/routers/portfolio.py` — added `quote_ready` flag per position and `quotes_ready` in summary; trusts IB's `unrealizedPNL` until live quote arrives; filters zero-share rows.
- Fix: `frontend/src/components/MorningBriefingModal.jsx` — shows amber "awaiting quotes" badge instead of fake PnL.

### New `POST /api/portfolio/flatten-paper` endpoint
- 4 guard rails: `confirm=FLATTEN` token, paper-account-only (code starts with 'D'), 120s cooldown, pre-flight cancel of stale `flatten_*` orders.
- UI button in MorningBriefingModal with JS confirm dialog.

### Cleared 19 stale IB paper-account bagholds
Via flatten endpoint + manual TC2000/TWS cleanup.

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
