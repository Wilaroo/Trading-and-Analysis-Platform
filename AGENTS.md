# AGENTS.md — TradeCommand / SentCom

> **READ FIRST.** This is the navigation contract for any coding agent
> (Emergent E1, Claude Code, Cursor, Copilot, etc.) working on this
> repository. It tells you **where things live**, **what NOT to touch**,
> and **which traps have already burned us**. Update this file when you
> learn new conventions — it's version-controlled and repo-scoped.

---

## 1. What this app is (one paragraph)

**SentCom** is a self-improving AI trading bot running natively on a
physical NVIDIA DGX Spark (Linux) with FastAPI backend + React frontend
+ MongoDB. It connects to **Interactive Brokers** via a **Windows PC**
running `ib_data_pusher.py` (data) and `ib_async` (order execution). The
DGX runs the brains; Windows runs the broker socket. The two boxes talk
over LAN: DGX `:8001` (FastAPI) ↔ Windows `192.168.50.1:8765` (pusher
RPC) and `:4002` (IB Gateway paper) or `:4001` (live).

**Strict IB-only data pipeline.** Alpaca / TwelveData / Yahoo are
removed from the critical path to eliminate train/serve data skew.

---

## 2. Deployment model — read before changing ANY infra

### Two-machine architecture
- **DGX Spark (Linux)**: `~/Trading-and-Analysis-Platform` — runs
  `python server.py` (FastAPI :8001) under `.venv` python3.12, serves
  the React build static, persists state to local MongoDB.
- **Windows PC**: same repo path; runs IB Gateway + `ib_data_pusher.py`
  (level 1+2 quotes, executions). The `.bat` files in `scripts/` start
  it and pull GitHub.

### The deploy contract (NEVER VIOLATE)
1. **NO Emergent "Save to Github" UI button.** `/app` (this fork) is
   disconnected from the user's GitHub repo. Instruct the user to
   `git add/commit/push` directly from the DGX terminal.
2. **Patch deployment uses `paste.rs`.** Reason: the DGX terminal
   corrupts bash heredocs / multi-line string replacements. Generate a
   `.patch` file locally → upload via `curl --data-binary
   @file https://paste.rs/` → give user a one-liner
   `curl -o /tmp/x.patch <url> && git apply --check && git apply`.
3. **Frontend changes require `cd frontend && yarn build`** before they
   appear (FastAPI serves the static build, not dev-server).
4. **Backend restart**: `./start_backend.sh --force` (the `--force` is
   critical — without it, the script's v19.30.11 skip-restart-if-healthy
   guard refuses to restart a healthy backend).
5. **Python on DGX is `/usr/bin/python3.12` via `.venv/bin/python`**.
   `python` alone is NOT installed. `python3` exists but is a
   different (system) interpreter that doesn't have the venv deps.

### Testing constraints
- **Standard automated testing agents WILL FAIL** here because they
  lack access to the physical DGX hardware + Windows IB Gateway
  bindings. **DO NOT call `testing_agent_v3_fork`** for this codebase.
- Use **pytest** in `/app/backend/tests/`, **curl** for API checks,
  **screenshot tool** for frontend verification, and **manual python
  snippets** via `execute_bash`.
- DGX env has pytest installed in `.venv`, NOT in system python3 or
  python3.12. If the user runs pytest and gets `No module named pytest`,
  they need to either `source .venv/bin/activate` first or install via
  `--break-system-packages` (one-time).

---

## 3. Code navigation map — "where does X live?"

### 🔑 The five files you'll touch most
| File | Lines | What it owns |
|---|---|---|
| `backend/services/trading_bot_service.py` | ~5,300 | **Core state owner.** `TradingBotService._open_trades` dict (keyed by `trade_id`, NOT symbol — see §6), `_closed_trades` list, `_daily_stats`, `start()` boot sequence, `_naked_position_sweep`, `close_trade`, `close_trade_custom`. Also holds all the periodic worker tasks (drift loop, bracket-state reconciler, naked-sweep, etc.). |
| `backend/services/position_manager.py` | ~2,700 | **Close/EOD orchestrator.** `close_trade` (the bot's safety-critical 100%-MKT close path used by EOD + stop-loss + scale-out), `close_trade_custom` (v19.34.72 operator panel path), `check_eod_close`, `manage_open_trades`, `_clamp_shares_to_ib_position`, quote-staleness recovery (`_stale_resub_set`). |
| `backend/services/trade_executor_service.py` | ~2,500 | **IB submission layer.** `close_position`, `close_position_custom`, `_cancel_ib_bracket_orders` (the v19.34.64 OCA-race guard — see §6), `submit_with_bracket`, executor mode handling (LIVE / PAPER / SIMULATED). |
| `backend/services/ib_direct_service.py` | ~2,200 | **Raw IB socket.** `ensure_connected`, `place_close_market`, `place_close_limit` (v19.34.72), `cancel_order`, `wait_for_orders_terminal`, `submit_bracket_order_oca`. Wraps `ib_async`. |
| `backend/routers/trading_bot.py` | ~8,800 | **REST API surface.** Every `/api/trading-bot/*` endpoint. Includes diagnostics (`/diag/symbol-state`), close (`/trades/{id}/close`), force-reconcile-down, share-drift-status, etc. |

### Supporting services you'll need to know about
| File | What it does | When to touch |
|---|---|---|
| `backend/services/position_reconciler.py` | Drift detection between IB and `_open_trades`. Spawns `reconciled_excess_*` synthetic trades when IB has more shares than tracked. | Drift / phantom / orphan issues |
| `backend/services/opportunity_evaluator.py` | The "sym-dir-cap" guard (v19.34.123). Decides if a new alert is allowed to enter given current `_open_trades`. **Iterates `_open_trades.values()`** — if a phantom is in there, this guard locks onto it as canonical. | Bot refuses new entries on a symbol |
| `backend/services/scanner_service.py` / `market_scanner_service.py` | Universe scanning + signal emission | Scanner false negatives / missing alerts |
| `backend/services/smart_filter.py` | TQS scoring of alerts | Setup grading questions |
| `backend/services/stop_manager.py` | Trailing stops + retune logic | Stop-loss bugs |
| `backend/services/alert_system.py` | Alert deduplication + lifecycle | "Dedup" / "identical active alert" issues |
| `backend/services/eod_generation_service.py` | EOD reports | NOT to be confused with EOD close (that's in `position_manager.py`) |
| `backend/services/ib_pusher_rpc.py` | RPC client → Windows pusher (`192.168.50.1:8765`) for subscribe/unsubscribe | Quote-staleness / pusher health |

### Frontend map
- `frontend/src/components/sentcom/v5/` — current production UI (V5).
  Key files: `OpenPositionsV5.jsx`, `CloseTradeModal.jsx`,
  `PositionThoughtsInline.jsx`, `BracketHistoryPanel.jsx`,
  `BootReconcilePill.jsx`, `DriftGuardPill.jsx`,
  `DeepFeedV5.jsx` (bot thoughts feed), `EodCountdownBannerV5.jsx`.
- `frontend/src/components/ui/` — shadcn primitives (button, dialog,
  card, etc.). Use these for new UI; don't rebuild.
- `frontend/src/pages/V6LayoutPreview.jsx` — the planned V6 refactor
  (not live yet — V5 is production).
- API calls always use `process.env.REACT_APP_BACKEND_URL` (frontend
  env). Never hardcode URLs.

### Scripts you'll find useful
- `start_backend.sh` — backend launcher (handles port-bind, venv,
  health-check). Use `--force` to override skip-if-healthy guard.
- `scripts/tail_pipeline.sh` — **NEW (v19.34.73)** real-time pipeline
  viewer. Tails `/tmp/backend.log`, color-codes events by stage.
  Launch: `bash scripts/tail_pipeline.sh` or `tmux` split.
- `scripts/post_backfill_audit.sh` — diagnostic check after backfill.
- `scripts/eod_postmortem.py` — EOD trade-by-trade review.
- `scripts/diagnose_ib_pusher.py` — Windows-side IB pusher health.

---

## 4. Memory & docs convention

`/app/memory/` is the source of truth for product/state:
- **`PRD.md`** — original problem statement, user personas, core
  requirements. Static — only update for major direction changes.
- **`CHANGELOG.md`** — append-only log of what was implemented,
  newest-first. Every shipped version gets an entry. Currently ~25k
  lines — break into year-files when it hits 30k.
- **`ROADMAP.md`** — prioritized backlog (P0 / P1 / P2 / P3). Top
  section = "Next session" items. Move items to CHANGELOG when shipped.
- **Specialized runbooks** in `/app/memory/`:
  `PRE_OPEN_CHECKLIST.md`, `IB_DIRECT_MIGRATION_PLAN.md`,
  `V6_POSITION_HEALTH_CONSOLE_SPEC.md`, etc.

**When finishing a task**: always update PRD.md OR CHANGELOG.md (newer
items go to CHANGELOG, structural changes to PRD).

---

## 5. Versioning convention — the `v19.34.XX` system

Every safety-critical patch gets a version tag. Patches are referenced
in:
- **Code comments**: `# v19.34.73 — bumped wait 4s → 8s`
- **Log lines**: `[v19.34.73 cancel-retry] %s — retrying...`
- **OCA group names**: `ADOPT-OCA-ADI-b415ed5f-1ba867` (the prefix
  encodes the path — `ADOPT-` = orphan-adoption, `OCA-` = bracket)
- **Database notes**: `notes: "v19.34.15b: spawned to claim excess..."`

**When adding a new patch:**
1. Increment from the latest version in `CHANGELOG.md` (currently
   v19.34.73 as of 2026-05-21).
2. Use `v19.34.XX` (or `v19.34.XXA`, `XXB`, `XXC` for sub-patches in
   the same release).
3. Tag EVERY new code path with the version comment so the next agent
   can grep for it.

---

## 6. Traps that have burned us — read these BEFORE you code

### 🔥 `_open_trades` is keyed by `trade_id`, NOT by symbol
**Past bug (v19.34.73)**: `/diag/symbol-state` used `ot.get(sym) or []`
assuming symbol-keyed. Always returned `[]`. Operator saw "phantom"
state corruption when state was actually fine.

**Correct pattern**:
```python
rows = [t for t in self._open_trades.values()
        if str(getattr(t, "symbol", "") or "").upper() == sym]
```

### 🔥 Multiple trades can exist for the same (symbol, direction)
**Past bug (the b415ed5f incident, 2026-05-21)**: An orphan-adopted
phantom (44sh, `entered_by="reconciled_external"`) co-existed in
`_open_trades` with the real bot_fired canonical (134sh). The
sym-dir-cap guard latched onto the older phantom and refused all new
entries; the naked-sweep reissued brackets for BOTH every 60s, with
the phantom's submissions bouncing off IB with Error 200 35+ times.

**Always**: when iterating per-symbol, build a sibling map by `(symbol,
direction)` and score canonicals. `entered_by="bot_fired"` always beats
`reconciled_*`; tie-break on `remaining_shares`. The v19.34.73 boot
phantom-purge runs this score and removes losers.

### 🔥 The `close_trade` path is SAFETY-CRITICAL — do not modify it directly
**Why**: It's called by EOD close, stop-loss triggers, scale-out engine.
A bug here = unprotected positions or double-fills.

**Pattern**: When adding new close behaviors (e.g., the v19.34.72
operator panel with partial/limit support), create a **sibling**
function like `close_trade_custom` and a **sibling** executor like
`close_position_custom`. Leave `close_trade` / `close_position`
untouched.

### 🔥 The OCA-race guard (v19.34.64) and its 8s timeout (v19.34.73)
**Why it exists**: A 2026-05-20 incident where the bot sent a MKT close
during the 50-200ms window where a bracket child cancel was still
propagating. The child filled AND the close filled → position flipped
direction at IB.

**Rule**: **NEVER** send a closing order at IB without first calling
`_cancel_ib_bracket_orders(trade)` and checking that:
- `result["filled"]` is empty (bracket child filled during cancel-wait
  = position already exited)
- `result["timeout"]` is empty (couldn't confirm terminal status)

The wait is **8s primary + 5s retry** (v19.34.73). Don't shorten without
proving median IB cancel ack time has dropped below 2s p99.

### 🔥 `_cancel_ib_bracket_orders` pre-filter (v19.34.70A)
The function pre-filters the order list against IB's live cache. Orders
NOT in the cache are pre-loaded into `result["unknown"]`. **When merging
results from the wait loop, use `extend` not `=`** or you'll erase the
pre-filter signal and re-introduce the v19.34.70A bug.

### 🔥 `_open_trades` dict has trades that aren't in MongoDB persistence
On boot, `_restore_state` loads from `bot_trades` collection, but the
position-reconciler also spawns trades in-memory (e.g.,
`reconciled_excess_*`). When persisting, ALWAYS go through
`bot._save_trade(trade)` — direct Mongo writes will miss serialization
helpers.

### 🔥 MongoDB `_id` is NEVER JSON-serializable
Every read from MongoDB MUST exclude `_id`:
```python
db.bot_trades.find({}, {"_id": 0})
```
And NEVER reuse a dict that was just `insert_one()`'d — pymongo mutates
the input by adding `_id`.

### 🔥 `datetime.utcnow()` is deprecated
Use `datetime.now(timezone.utc)`. The codebase has fully migrated.

### 🔥 The 4.9-hour stale quote problem
**Symptom**: `manage: SKIP stop-check for SYM — quote is 17795s old`.
**Cause**: The pusher dropped the subscription silently. The
`_stale_resub_set` trigger fires but the Windows-side pusher
subscribe_symbols handler doesn't always recover.
**Status**: Known issue. v19.34.74+ should add a real watchdog.
**Workaround**: Manual restart of Windows pusher.

### 🔥 Bracket-leg stacking (GM/LIN pattern)
**Symptom**: Bot=N sh, IB pending_target_qty=N×K (multiple PT orders
at different prices for same shares). If one fills, the others remain
working → position flips direction.
**Audit**: `GET /api/trading-bot/bracket-stacking-audit` (read-only).
**Auto-cancel endpoint pending v19.34.74+.**

---

## 7. Common operations — copy-paste-ready

### Check bot's view of a position
```bash
curl -s "http://localhost:8001/api/trading-bot/diag/symbol-state?symbol=ADI" | python3 -m json.tool
```

### Force-reconcile a symbol (dry-run)
```bash
curl -sS -X POST http://localhost:8001/api/trading-bot/force-reconcile-down \
  -H "Content-Type: application/json" -d '{"symbol":"ADI"}' | python3 -m json.tool
```

### List all open trades
```bash
curl -s http://localhost:8001/api/trading-bot/trades/open | python3 -c "
import sys, json
d = json.load(sys.stdin)
items = d if isinstance(d, list) else next((v for v in d.values() if isinstance(v, list)), [])
for p in items: print(f\"{p['symbol']:<6} {p.get('side','?'):<5} {p.get('shares',0):>6}  entered_by={p.get('entered_by','?')}\")
"
```

### Tail real-time pipeline (NEW v19.34.73)
```bash
bash scripts/tail_pipeline.sh           # color-coded full pipeline
bash scripts/tail_pipeline.sh --scan    # scanner-only
bash scripts/tail_pipeline.sh --errors  # errors-only
bash scripts/tail_pipeline.sh --trades  # fills + closes only
```

### Build + deploy a patch (full DGX flow)
```bash
# On dev machine:
cd /app && git diff --cached > /tmp/v19_34_XX.patch
curl -sS --data-binary @/tmp/v19_34_XX.patch https://paste.rs/
# → returns URL like https://paste.rs/AbCdE

# On DGX (operator):
curl -sS -o /tmp/v19_34_XX.patch https://paste.rs/AbCdE && \
  git apply --check /tmp/v19_34_XX.patch && \
  git apply /tmp/v19_34_XX.patch && \
  ./start_backend.sh --force
```

### Run the test suite
```bash
cd /app/backend && python -m pytest tests/ -q
# DGX: source .venv/bin/activate first if pytest missing
```

---

## 8. What NOT to do

- ❌ **Don't run `testing_agent_v3_fork`** — needs hardware bindings
  the test container can't reach.
- ❌ **Don't `apt install` or `pip install` system-wide** — use the venv
  at `.venv/`.
- ❌ **Don't rewrite `server.py`** without a plan. It's a monolith but
  active refactoring is on the roadmap (v19.34.74+).
- ❌ **Don't change `MONGO_URL`, `DB_NAME`, or `REACT_APP_BACKEND_URL`**
  in .env files. They're production config.
- ❌ **Don't add Alpaca / TwelveData / Yahoo to data hot path.** Strict
  IB-only is a deliberate architectural decision (train/serve skew).
- ❌ **Don't use `python3` on DGX for backend work** — use
  `/usr/bin/python3.12` or `.venv/bin/python`. They have different
  packages installed.
- ❌ **Don't add emojis to code unless requested.** Logs OK (we use
  🛑 ✅ 🔁 ⏭️ 🧹 for visual scanning).

---

## 9. Frontend conventions

- **Components**: Named exports for components, default exports for
  pages. Use the shadcn primitives in `frontend/src/components/ui/`.
- **API calls**: `${process.env.REACT_APP_BACKEND_URL}/api/...` —
  always via that env var.
- **Test IDs**: Every interactive element MUST have a `data-testid`
  attribute. Kebab-case, descriptive. Example:
  `data-testid="close-trade-confirm-btn"`.
- **State management**: Mostly local component state + `useState`. No
  Redux/Zustand. SWR-style polling for backend data via custom hooks.
- **Styling**: TailwindCSS + dark theme (`bg-zinc-950`, `border-zinc-800`,
  `text-zinc-100`). Color accents are cyan (info), emerald (success),
  rose (action/danger), amber (warning).
- **Position direction colors**: emerald = long, rose = short.

---

## 10. Active version & known-good state

- **Current version**: v19.34.73 (2026-05-21, "Close-path hardening")
- **Last green test run**: 94/94 across v19.34.69 → v19.34.73
- **Known issues**: see ROADMAP.md "Tomorrow's session" section
- **EOD close**: known-fixed in v19.34.73 (was failing silently in v19.34.72
  due to 4s cancel-wait timeout under load)

---

## 11. When you're stuck

1. Grep for the version tag of the most recent related patch:
   `grep -rn "v19.34" /app/backend/services/ | grep -i "<keyword>"`
2. Check `CHANGELOG.md` — search for the symptom keyword.
3. Check `/tmp/backend.log` — `grep -iE "(v19|error|exception|close)"`.
4. Use the diag endpoints listed in §7.
5. **Don't guess** — call `troubleshoot_agent` (read-only RCA) before
   making changes if it's been >1 attempt to fix.

---

*Last updated: 2026-05-21 (v19.34.73 ship). Update this file whenever
you learn a new convention or trap.*
