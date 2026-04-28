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
- `GET /api/assistant/coach/morning-briefing` — coach prompt only (not position source)
- `GET /api/ai-modules/validation/summary` — promotion-rate dashboard
- `POST /api/ib/push-data` — receive pusher snapshot
- `GET /api/ib/orders/pending` — pusher polls this
- `POST /api/ib/orders/claim/{id}`, `POST /api/ib/orders/result` — claim/complete hooks pusher should use but may not
- `POST /api/ai-modules/shadow/track-outcomes?drain=true&batch_size=50` — drain shadow-decision backlog (added 2026-04-29). Yields to event loop between batches.


## Key files
- `backend/routers/portfolio.py` — portfolio endpoint + new flatten-paper
- `backend/routers/ib.py` — push-data + order queue glue
- `backend/services/order_queue_service.py` — Mongo-backed queue with auto-expire
- `frontend/src/components/MorningBriefingModal.jsx` — briefing UI + Flatten button
- `backend/services/ai_modules/post_training_validator.py` — 9 fail-closed gates
- `backend/scripts/revalidate_all.py` — Phase 13 revalidation script
- `backend/services/smart_levels_service.py` — `compute_smart_levels`, `compute_stop_guard`, `compute_target_snap`, `compute_trailing_stop_snap` (added 2026-04-29 — liquidity-aware trail)
- `backend/services/stop_manager.py` — `set_db(db)` injection enables HVN-anchored breakeven + trail (2026-04-29)


## Hardware runtime notes
- Can't test this codebase in the Emergent container (no IB, no pusher, no GPU). All verification is curl/python on the user's Spark. Testing agents unavailable for integration flows.
- Code changes reach Spark via "Save to Github" → `git pull` on both Windows and Spark.
- Backend restart: `pkill -f "python server.py" && cd backend && nohup python server.py > /tmp/backend.log 2>&1 &` (Spark uses `.venv`, not supervisor)


