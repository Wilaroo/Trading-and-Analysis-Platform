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

- **Current version**: v19.34.74 (2026-05-22, "AGENTS.md context-pack expansion")
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

## 12. App-wide startup flow — `.bat` orchestration (Windows side)

The DGX runs the brain; **Windows orchestrates the boot**. Everything
the operator clicks on is a `.bat` in `scripts/` (paths inside `.bat`
files use the Windows clone at
`C:\Users\13174\Trading-and-Analysis-Platform`). All `.bat` files SSH
into the DGX (`spark-1a60@192.168.50.2`) and call shell scripts on the
Linux side.

### `StartTrading.bat` — the canonical "go live" launcher
9 steps, all gated by a health probe. The operator runs this once per
trading day. Re-running is idempotent (kills + relaunches windows).

| Step | What it does | Side | Failure mode |
|---|---|---|---|
| **1. Spark connectivity** | `ping -n 1 -w 2000 192.168.50.2` | Windows | Aborts if Spark not reachable on 10 GbE LAN (192.168.50.0/24). |
| **2. Git pull** | `git pull origin main` on Windows, then `ssh spark "git checkout -- . && git stash drop && git pull origin main"` on Spark. The hard checkout discards any local crud the agent left on the DGX. | Both | Warns if SSH keys not set; user types password. |
| **2.5 Spark stop** | `bash scripts/spark_stop.sh` over SSH — kills any lingering uvicorn/yarn/mongo procs from the prior session. | Spark | Quiet (silent-fail if nothing running). |
| **3. Spark start** | `bash scripts/spark_start.sh` over SSH — re-launches `start_backend.sh --force`, mongo container, frontend (`yarn start` or static `serve build`), Ollama daemon, GPU workers. Then a Windows-side `curl /api/health` loop polls up to 20s for "backend is ready". | Spark | If `/api/health` never returns 200, the `.bat` continues with a `[WARN]` — operator must SSH in to debug. |
| **4. IB Gateway login** | If `ibgateway.exe` not running, start it; auto-type `IB_USERNAME` / `IB_PASSWORD` (paper: `paperesw100000`) via `WScript.SendKeys`. Then poll port `4002` (paper) or `4001` (live) up to 40s. Dismisses the IBKR "warning" popups. | Windows | Manual login required if VBS auto-type races the splash screen. |
| **5. IB pusher** | Kill any `[IB PUSHER]` cmd window, launch fresh: `python ib_data_pusher.py --cloud-url http://192.168.50.2:8001 --symbols VIX SPY QQQ IWM DIA --client-id 15`. Sets `IB_PUSHER_L1_AUTO_TOP_N=400` (the live-universe cap — was 60 pre-v19.34.52, caused 119 stale-bar symbols). | Windows | Pusher window is YELLOW; closing it kills live quotes. |
| **6. Turbo collectors** | 4 minimized `[COLLECTOR N] Turbo` windows, client IDs 16-19, staggered 2s apart. Run `ib_historical_collector.py --turbo` in idle-poll mode. Activate when the NIA "Fill Gaps" button enqueues work. | Windows | Collectors are RED; idle ≠ broken (they wake on queue). |
| **7. Browser** | Opens `http://192.168.50.2:3000` (the V5 React UI). | Windows | — |
| **8. Training monitor** | Opens BLUE SSH terminal running `bash documents/scripts/monitor_training.sh` — tails Spark's ML training pipeline. | Spark via SSH | Closes if SSH key auth missing. |
| **9. Health loop** | Continuous `cls` + curl probe loop hitting `/api/health`, `/api/startup-check`, `/api/focus-mode`, `/api/ib-collector/queue-progress`, `/api/ai-training/status`. Press any key to refresh. | Windows | Operator-facing dashboard; closing it does not kill services. |

### Other `.bat` files (purpose only — code in `scripts/`)
| File | When | What |
|---|---|---|
| `StartCollection.bat` | Off-hours data backfill | Pauses live trading; dedicates all bandwidth to historical pulls. |
| `PostRestartAuto.bat` | 2:15 AM ET nightly (after IB's daily 2:00 AM restart) | Re-logs into IB Gateway, restarts pusher, resumes any pending collection queue. |
| `NightlyAuto.bat` | Cron (Task Scheduler) | Runs `StartTrading.bat` → waits for health → triggers nightly Smart-Backfill cycle → exits. |
| `WeekendAuto.bat` | Saturday 8 AM | Full batch: backfill + ML training + simulations. Hands-off. |
| `SetupScheduledTasks.bat` | One-time (operator) | Registers `TradeCommand_Weekend` and `TradeCommand_Nightly` in Windows Task Scheduler. |
| `Diagnostics.bat` | On demand | Read-only health audit: local Ollama, DGX backend, Mongo, IB Gateway port, pusher heartbeat, collector status. |

### Spark-side scripts (`scripts/spark_*.sh`)
| File | Purpose |
|---|---|
| `spark_start.sh` | Boot Mongo (Docker) → Ollama daemon → `start_backend.sh --force` → frontend (`serve -s build`). Idempotent. |
| `spark_stop.sh` | Reverse of start. Used by `StartTrading.bat` step 2.5. |
| `start_backend.sh --force` | Direct backend launcher; `--force` overrides the v19.30.11 skip-if-healthy guard so the agent can always restart cleanly. |

### Network topology
```
+----------------------------+        10 GbE LAN        +-------------------------+
| WINDOWS PC (192.168.50.1) | <---------------------> | DGX SPARK (192.168.50.2)|
|  IB Gateway   :4002       |                          | FastAPI       :8001    |
|  IB Pusher    (id 15)     |  data push (HTTP POST)  | React build    :3000    |
|  Collectors 1-4 (16-19)   | ----------------------> | MongoDB       :27017   |
|  Pusher RPC   :8765       | <---------------------- | Ollama         :11434  |
+----------------------------+   resubscribe / kill    +-------------------------+
```
Pusher RPC `192.168.50.1:8765` is how the DGX tells Windows "I need a
new symbol subscribed" or "kill subscription for SYM" — used by
`ib_pusher_rpc.py` and the stale-quote watchdog (pending v19.34.74+).

### `/app` vs operator's GitHub — drift risk
This sandbox (`/app`) is **disconnected from the user's private
GitHub** (no `git remote` configured here, repo private). The contract
is: **`/app` and the DGX repo are kept in sync via `paste.rs` patches**;
GitHub is the operator's responsibility (`git push` from the DGX after
they `git apply` a patch). If the sandbox is older than DGX (operator
hot-fixed live), an unsuspecting agent could overwrite their fix.
**Mitigation**: when starting a session, ask the operator to paste the
output of `git log --oneline -5` on the DGX before generating patches.

---

## 13. Glossary — terms-of-art used in code & logs

| Term | Meaning |
|---|---|
| **Bracket / OCA bracket** | Three-leg parent+stop+target order. "One-Cancels-All": filling/canceling one child cancels the sibling. Stored as `bot_orders` with shared `oca_group`. |
| **Naked sweep** | Periodic check (`_naked_position_sweep`, ~60s) that re-attaches a bracket to any IB position that has no protective stop. Triggered by partial fills or operator manual closes. |
| **Naked sibling guard** (v19.34.73) | Inside naked-sweep: before re-issuing a bracket, dedupe against any *open* sibling brackets on the same `(symbol, direction)` to avoid stacking PT/SL legs. |
| **Orphan** | An IB position with no matching `_open_trades` entry (e.g., manually entered, or bot state was wiped). The orphan-reconciler decides to adopt it (`entered_by="reconciled_external"`) or eject it. |
| **Phantom** | An `_open_trades` entry with no matching IB position. Typically a stale `reconciled_excess_*` record left after a drift resolve. Purged at boot by the v19.34.73 phantom-sibling purge. |
| **Drift** | Mismatch between bot's tracked qty and IB's actual position qty. *Excess drift* = IB has more shares than bot tracks; *short drift* = bot tracks more than IB shows. Logged to `share_drift_events`. |
| **Reconciled excess** | A synthetic trade spawned by `position_reconciler` when IB has more shares than tracked. Notes: `"v19.34.15b: spawned to claim excess..."`. Owned but never bot-fired. |
| **Bracket-stacking** | IB has N×K target orders for N shares — multiple PT legs at different prices. One fills → siblings flip the position direction. Audited via `GET /api/trading-bot/bracket-stacking-audit`. |
| **Sym-dir-cap** | The "1 trade per (symbol, direction)" guard inside `opportunity_evaluator.py`. Iterates `_open_trades.values()`; latches onto whatever it finds first (so phantoms can block new entries). |
| **Direction-stability gate** | 30s cooldown after a position closes before a new entry on the same `(symbol, direction)` is allowed. Prevents flip-flop on stale fills. |
| **TQS** | Trade Quality Score — composite signal grading (`smart_filter.py`). Ranges A+ / A / B / C / fail. Used to gate auto-execute (default: A+ + A fire instantly). |
| **SMB grade** | Bellafiore-style trade grading. Imported into `smb_unified_scoring.py`. Currently *not timeframe-aware* — known bug, see ROADMAP. |
| **Carry-forward alert** | An alert that fires intraday but the trade window expires (EOD / cooldown / scan miss). Re-evaluated on next session boot. Stored in `carry_forward_alerts`. |
| **Confidence gate** | Probabilistic acceptance threshold; gates an alert based on the model's calibration history (`confidence_gate_log`). |
| **Kill switch** | Daily-loss cap. v19.34.123 made it continuous (15s loop on `bot_trades` realized PnL + `_open_trades` unrealized). Pre-v123, only checked inside scan loop. |
| **Focus mode** | Operator-set scanner targeting state: `auto`, `manual <symbols>`, `off`. Stored in `bot_state.focus_mode`. |
| **NIA** | "Network Intelligence Agent" page — the data-collection control center (Fill Gaps, train, etc.). |
| **Stocks in play** | Daily curated universe of high-volume / catalyst-driven symbols. Refreshed pre-open. Stored in `stocks_in_play`. |
| **Setup vs Trade** | Bellafiore two-layer model. *Setup* = daily-bar context ("Gap & Go", "Range Break", …). *Trade* = intraday entry pattern ("9-EMA Scalp", "VWAP Continuation", …). Matrix in `market_setup_classifier.py`. See §16. |
| **paste.rs** | Plaintext pastebin used as patch-deploy channel because DGX terminal eats bash heredocs. |
| **Pipeline tail** | `bash scripts/tail_pipeline.sh` — color-coded real-time view of `/tmp/backend.log` filtered by stage. |
| **Spark** | The NVIDIA DGX Spark workstation (Blackwell GB10, 128 GB unified memory). |

---

## 14. MongoDB schema cheat-sheet

> Database: `tradecommand` (set via `DB_NAME` env). **Always exclude
> `_id`** in projections: `db.<coll>.find({}, {"_id": 0})`. The
> codebase touches **~165 collections** — this table covers the ones
> agents actually need to know about.

### Core trading state (HOT — touched every minute)
| Collection | Owns | TTL | Key fields |
|---|---|---|---|
| `bot_trades` | **Canonical execution history**. Every trade ever fired. Read on boot via `_restore_state` to repopulate `_open_trades`. | — | `trade_id`, `symbol`, `side`, `shares`, `entry_price`, `entered_by` (`bot_fired` / `reconciled_external` / `reconciled_excess_v19_34_15b` / `manual`), `status` (`open` / `closed`), `notes`, `entry_time_ms`, `pnl` |
| `bracket_lifecycle_events` | Audit log of every bracket event (submit / fill / cancel / reissue) | **7d** | `trade_id`, `event` (`bracket_submitted` / `child_filled` / `cancel_ack` / …), `oca_group`, `order_id`, `ts_ms` |
| `share_drift_events` | Each drift detection + resolution | — | `symbol`, `direction`, `bot_qty`, `ib_qty`, `delta`, `resolution` (`spawned_excess` / `adopted_orphan` / `purged_phantom` / `noop`), `ts` |
| `bot_state` | Single-row machine state | — | `mode` (`autonomous` / `paused` / `manual`), `focus_mode`, `started_at_ms` |
| `bot_orders` | All IB order submissions (parent + bracket children) | — | `order_id`, `oca_group`, `trade_id`, `symbol`, `action`, `order_type`, `status` |
| `daily_stats` | Per-trading-day aggregate | — | `date`, `gross_pnl`, `net_pnl`, `trade_count`, `win_count`, `kill_switch_state` |
| `order_queue` | Outgoing IB requests in flight | — | `request_id`, `payload`, `status`, `attempts` |
| `kill_switch_history` | Each kill-switch trip + reset | — | `triggered_at`, `reason`, `pnl_at_trip`, `reset_at` |
| `state_integrity_events` | Watchdog detections (mismatched OCA groups, etc.) | — | `event`, `severity`, `payload`, `ts` |

### Scanner / signals
| Collection | Owns |
|---|---|
| `live_alerts` | Currently-active intraday alerts |
| `alerts` | All historical alerts (post-fire dedupe collapsed) |
| `live_scanner_alerts` | Raw scanner emissions before dedupe |
| `predictive_alerts` | Pre-fire ML predictions for outcome |
| `alert_outcomes` | Realized outcome (win/loss/skip) per alert |
| `carry_forward_alerts` | Alerts surviving session boundary |
| `forming_setups` | Daily setups still building intraday |
| `rejection_events` | Why an alert was filtered out |
| `confidence_gate_log` | Each gate decision (allow / block / calibrate) |
| `gate_decisions` / `gate_calibration` | Same theme, longer history |
| `stocks_in_play` | Daily curated universe |
| `symbol_universe` | All tradeable symbols (master list) |
| `us_symbols` | Equity reference data |
| `ticker_scores` | Per-symbol composite score cache |

### Market & sentiment
| Collection | Owns |
|---|---|
| `news_articles` / `news_sentiment` | Catalyst news + scored sentiment |
| `catalysts` / `catalyst_templates` | Earnings, FDA, M&A flags |
| `market_intel_reports` | Daily macro intel digests |
| `market_regime_state` / `_history` / `_ftd` / `_snapshots` | Regime classifier outputs (FTD = follow-through-day) |
| `cot_data` | CFTC Commitment of Traders weekly |
| `insider_trades` / `institutional_ownership` | Form 4 / 13F |
| `finra_short_interest` | Bi-monthly short interest |
| `earnings_calendar` / `earnings` / `earnings_scores` | Earnings calendar + ER-quality scores |
| `social_feed_analyses` / `social_feed_config` | StockTwits / Reddit feed signals |

### Bars & quotes
| Collection | Owns |
|---|---|
| `historical_bars` / `ib_historical_data` | Daily/intraday OHLCV |
| `live_bar_cache` | In-progress current-minute bar |
| `ib_live_snapshot` | Last L1 quote per symbol |
| `bar_poll_log` | Pusher RPC poll heartbeats |
| `data_inventory` | What we have / are missing |
| `ib_data_summary` | Per-symbol completeness summary |
| `ib_collection_jobs` / `historical_data_requests` | Backfill queue |
| `ib_smart_backfill_history` | Smart-backfill audit |
| `ib_executions` | Raw IB exec reports |
| `ib_short_data` | Short borrow / locate data |

### ML / training
| Collection | Owns |
|---|---|
| `timeseries_models` / `cnn_models` / `dl_models` / `setup_type_models` | Active model registry |
| `setup_type_models_backup` | Pre-promotion snapshot |
| `model_baselines` / `model_validations` / `model_training_history` | Training history & checkpoints |
| `training_history` / `training_pipeline_status` / `training_pipeline_result` / `training_runs_archive` | Pipeline runs |
| `ai_accuracy_tracking` | Per-prediction accuracy log |
| `feature_cache` | Pre-computed feature vectors |
| `learning_stats` | Aggregate ML KPIs |
| `shadow_decisions` / `shadow_module_performance` / `shadow_module_weights` / `shadow_filters` / `shadow_signals` | Shadow-mode A/B testing |
| `tuning_history` / `tuning_recommendations` / `calibration_log` / `calibration_history` / `calibration_config` | Hyperparam / calibration tracker |
| `regime_performance` / `regime_trade_log` | Per-regime backtests |
| `score_history` / `quality_metrics` | TQS scoring telemetry |
| `multiplier_threshold_history` | Threshold-tuning history |

### Operator / UI / journal
| Collection | Owns |
|---|---|
| `playbooks` / `playbook_trades` / `playbook_performance` / `pending_playbooks` | Bellafiore playbook entries |
| `game_plans` | Pre-open game plans |
| `weekend_briefings` / `weekly_intelligence_reports` | Saturday review |
| `trade_journal` (rendered) ← `trade_snapshots` / `trade_outcomes` / `trade_ideas` / `trade_drops` | Per-trade lifecycle store |
| `watchlists` / `smart_watchlist` | Operator watchlists |
| `trade_templates` / `trader_profile` | Personal config |
| `notifications` / `assistant_conversations` / `assistant_patterns` | Chat / nudge system |
| `sentcom_chat_history` / `sentcom_chat_sessions` / `sentcom_context_archive` / `sentcom_memory` / `sentcom_thoughts` | LLM operator-chat backend |
| `tradersync_imports` | TraderSync CSV ingest |

### Misc / infra
| Collection | Owns |
|---|---|
| `pusher_health_history` / `pusher_heartbeat` / `pusher_config_cache` / `pusher_rotation_log` | Windows pusher health |
| `memory_watchdog` | Memory-leak detector |
| `task_heartbeats` | Async-loop liveness |
| `eod_generation_log` | EOD report build trail |
| `friday_close_snapshots` / `daily_report_cards` | EOD artifacts |
| `dlq_purge_log` | Dead-letter queue purges |
| `bot_events` | Generic event audit |
| `bot_trades_reset_log` | Manual `bot_trades` truncations |
| `system_settings` | Misc key-value config |
| `tavily_credit_usage` | External API credit meter |

---

## 15. Worker-loop catalog — what runs in the background

These are all `asyncio.create_task(...)` loops spawned during
`TradingBotService.start()` (see `trading_bot_service.py` ~L2070-3700).
Cadence is in seconds. **If you add a new loop, add an entry here.**

| Loop | Spawn line | Cadence | Owner method | What it does |
|---|---|---|---|---|
| Scan loop | ~L2075 | scan-tick | `_scan_loop()` | Master signal-evaluation loop — pulls quotes, evaluates alerts, fires entries when guards clear. |
| Kill-switch monitor | ~L2088 | **15 s** | `_kill_switch_monitor_loop()` | Continuous realized + unrealized PnL check against the daily-loss cap (v19.34.123). |
| Startup orphan guard | ~L2132 | once (15 s delay) | `_startup_orphan_guard()` | Boot-time scan of IB positions vs `_open_trades` → adopt / eject. |
| Phantom sibling purge | ~L2230 | once (20 s delay) | `_startup_phantom_sibling_purge()` | Boot-time dedupe of `(symbol, direction)` siblings; loser entries removed (v19.34.73). |
| Orphan-GTC startup audit | ~L2456 | once | `_startup_orphan_gtc_audit()` | Sweep IB GTC orders for any without a matching trade. |
| Orphan-GTC periodic | ~L2588 | **60 s** | `_periodic_orphan_gtc_audit()` | Continuous version of above. |
| Bracket-state reconcile | ~L2672 | **30 s** | `_periodic_bracket_state_reconcile()` | Compares OCA child states against IB; heals desyncs. |
| Startup auto-reconcile | ~L2827 | once (60 s after boot) | `_startup_auto_reconcile()` | Full drift resolve after the 30 s direction-stability gate clears. |
| Realized-PnL autosync | ~L2946 | **45 s** | `_realized_pnl_autosync_loop()` | Syncs `bot_trades.pnl` from IB executions. |
| Mid-bar tick lifecycle | ~L3075 | **30 s** | `_midbar_tick_lifecycle_loop()` | Tick→bar persister maintenance. |
| Boot zombie sweep | ~L3204 | once (45 s delay) | `_boot_zombie_sweep()` | Removes `_open_trades` entries that match neither IB nor recent fills. |
| Pending reaper | ~L3275 | **45 s** | `_stale_pending_reaper_loop()` | Cancels IB orders stuck in `Pending Submit` > N min. |
| EOD policy migration | ~L3339 | once | `_eod_policy_migration()` | One-shot config upgrade at first boot. |
| Share-drift loop | ~L3465 | **60 s** | `_share_drift_loop()` | Detects + logs IB-vs-bot share count drift; emits `share_drift_events`. |
| Orphan reconcile loop | ~L3579 | **60 s** | `_orphan_reconcile_loop()` | Continuous orphan adoption / ejection (fixed v19.34.22 to skip `reconciled_excess_*`). |
| Manage-open-trades | (in `position_manager.py`) | scan-tick | `manage_open_trades()` | Per-trade stop / target / scale-out logic; naked sweep ride-along. |

> ⚠️ **Boot order matters.** Multiple loops sleep at start to let
> `_restore_state` + the orphan guard finish. Don't shorten those
> delays without re-validating the b415ed5f phantom race (see §6).

External (non-bot) workers:
- **Scheduler service** (`scheduler_service.py`) — APScheduler-style
  cron tasks (EOD report build, weekly briefings, nightly backfill).
- **Pusher RPC poller** (Windows side) — `ib_data_pusher.py` keeps
  L1 / L2 subscriptions; reconnects on socket drop.
- **Tick-to-bar persister** (`tick_to_bar_persister.py`) — async
  consumer rolling ticks into `live_bar_cache` → `historical_bars`.

---

## 16. Strategy / setup taxonomy

> Canonical source: `backend/services/market_setup_classifier.py`
> (`TRADE_SETUP_MATRIX`, `TRADE_ALIASES`, `EXPERIMENTAL_TRADES`) and
> `/app/memory/SETUPS_AND_TRADES.md` (auto-generatable, hand-mirrored
> for now). Inventory list: `/app/memory/setup_inventory_master_list.txt`.

### Two-layer Bellafiore model
- **Setup** — daily-bar context. Classified **once per scan cycle**,
  5-min cache, per symbol.
- **Trade** — intraday entry. Detected **each scan tick** from
  `TechnicalSnapshot`.

### The 7 Setups
| Setup | Detection signal |
|---|---|
| `gap_and_go` | abs(gap) ≥ 1.5 % + ≥ 2× avg vol + tight prior consolidation |
| `range_break` | 10-day range < 12 % + decisive close outside range + vol ≥ 1.5× avg |
| `day_2` | Day 1 range ≥ 1× ATR(14), close ≥ 80 % up day's range, Day 2 opens ≤ 3 % from Day 1 close |
| `gap_down_into_support` | gap ≤ −1 % AND gap-low within 1× ATR of 20-day low |
| `gap_up_into_resistance` | gap ≥ +1 % AND gap-high within 1× ATR of 20-day high |
| `overextension` | 4+ consecutive same-color candles AND > 1.5× ATR from 20-EMA AND RSI extreme |
| `volatility_in_range` | 15-day ATR ≥ 1.5 % AND price within range AND ≥ 3 touches each band |
| `neutral` (fallback) | top setup scored < 0.5 confidence; trades fire uncontested |

### Matrix-gated Trades (22)
🟢 with-trend · 🔴 countertrend · — out-of-context (alert tagged
`out_of_context_warning=True`, priority downgraded one notch).

| Trade (`setup_type`) | Gap&Go | RangeBrk | Day 2 | GapDn↘Sup | GapUp↗Res | Overext | VolRng |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `the_3_30_trade` | 🟢 | — | — | — | — | — | — |
| `second_chance` | 🟢 | 🟢 | — | — | — | — | — |
| `hitchhiker` | 🟢 | 🟢 | — | — | — | — | — |
| `9_ema_scalp` | 🟢 | 🟢 | — | — | — | — | — |
| `vwap_continuation` | 🟢 | 🟢 | — | — | — | — | — |
| `gap_give_go` | 🟢 | 🟢 | — | — | — | — | — |
| `first_vwap_pullback` | 🟢 | 🟢 | — | — | — | — | — |
| `big_dog` | 🟢 | 🟢 | — | — | — | — | — |
| `bouncy_ball` | 🟢 | 🟢 | — | — | — | 🔴 | — |
| `premarket_high_break` | 🟢 | 🟢 | 🟢 | — | — | — | — |
| `back_through_open` | 🟢 | 🟢 | 🟢 | 🔴 | 🔴 | — | — |
| `range_break` | 🟢 | 🟢 | 🟢 | 🔴 | 🔴 | 🔴 | — |
| `hod_breakout` | 🟢 | 🟢 | 🟢 | — | — | — | — |
| `spencer_scalp` | — | 🟢 | 🟢 | — | — | — | — |
| `first_move_up` | — | 🟢 | 🟢 | — | 🔴 | 🔴 | 🔴 |
| `first_move_down` | — | 🟢 | 🟢 | 🔴 | — | 🔴 | 🔴 |
| `bella_fade` | — | 🟢 | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| `fashionably_late` | — | — | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| `backside` | — | — | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| `rubber_band` | — | — | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| `off_sides` | — | — | — | 🔴 | 🔴 | 🔴 | 🔴 |

### Aliases (operator-merged)
`puppy_dog` → `big_dog` · `tidal_wave` → `bouncy_ball` ·
`vwap_bounce` → `first_vwap_pullback`

### Experimental (matrix bypass, `experimental=True` tag)
`vwap_fade`, `abc_scalp`, `breakout`, `gap_fade`, `chart_pattern`,
`squeeze`, `mean_reversion`, `relative_strength`,
`volume_capitulation`, `approaching_hod`, `approaching_range_break`,
`range_break_confirmed`.

### Gating policy (current = soft mode, picked 2026-04-29)
- 🟢 with-trend → no-op
- 🔴 countertrend → tag `is_countertrend=True`, priority unchanged
- — out-of-context → `out_of_context_warning=True`, priority −1, reason
  bullet appended

After 2 weeks of live data, flip to **strict mode** (out-of-context
alerts blocked entirely).

### Live API
```
GET /api/scanner/setup-trade-matrix
```
Returns full matrix + live classifier stats so the UI can render the
daily-Setup heat-grid.

### Known bugs in scoring (open)
- **Scalp SMB grade**: scoring is not timeframe-aware — scalps get
  full-day SMB B grades that don't reflect intraday context. Tracked
  in ROADMAP P2.
- **AI rejection prompt staleness**: the LLM rejection narrator still
  believes `squeeze` is scalp-only despite intraday promotion.

---

## 17. Frontend page map (V5 production)

> V5 uses **tab-switching** (not React Router) — `activeTab` state in
> `App.js` toggles `display: block/none` between mounted pages. See
> `App.js` ~L452 (`renderPage`). The `Command Center` + `NIA` pages
> are *always mounted* (kept hot for fast switching).

### Top-level tabs / pages (`frontend/src/pages/`)
| Tab key | File | Backend it talks to |
|---|---|---|
| `command-center` | `CommandCenterPage.jsx` | `/api/dashboard/*`, `/api/trading-bot/*`, `/api/live/*`, ws `/ws` |
| `nia` | `NIA…` (data control) | `/api/ib-collector/*`, `/api/ai-training/*` |
| `chart` | `ChartsPage.js` | `/api/market-data/*`, `/api/technicals/*` |
| `trade-journal` | `TradeJournalPage.js` | `/api/trade-history/*`, `/api/trade-snapshots/*` |
| `dashboard` | `DashboardPage.js` | `/api/dashboard/*` |
| `scanner` | `ScannerPage.js` | `/api/scanner/*`, `/api/live-scanner/*` |
| `strategies` | `StrategiesPage.js` | `/api/strategies/*`, `/api/strategy-promotion/*` |
| `watchlist` | `WatchlistPage.js` | `/api/watchlist/*` |
| `portfolio` | `PortfolioPage.js` | `/api/portfolio/*`, `/api/risk/*` |
| `fundamentals` | `FundamentalsPage.js` | `/api/research/*`, `/api/earnings/*` |
| `insider` | `InsiderTradingPage.js` | `/api/market-intel/*` |
| `cot` | `COTDataPage.js` | `/api/market-intel/cot` |
| `alerts` | `AlertsPage.js` | `/api/alerts/*`, `/api/notifications/*` |
| `earnings-calendar` | `EarningsCalendarPage.js` | `/api/earnings/calendar` |
| `market-context` | `MarketContextPage.js` | `/api/market-context/*`, `/api/market-regime/*` |
| `trade-opportunities` | `TradeOpportunitiesPage.js` | `/api/scanner/setup-trade-matrix`, `/api/trades/*` |
| `trading-rules` | `TradingRulesPage.js` | `/api/rules/*` |
| `glossary` | `GlossaryPage.js` | `/api/help/glossary` |
| `settings` | `SettingsPage.js` | `/api/config/*` |
| `diagnostics` | `DiagnosticsPage.jsx` | `/api/trading-bot/diag/*`, `/api/diagnostic/*` |

V6 mockup pages exist (`V6LayoutPreview.jsx`, `V6BrainstormPreview.jsx`,
`V6NextMockup.jsx`, `V6ConceptsExplained.jsx`, `AuraMockupPreview.jsx`)
— **not wired into production** as of v19.34.74.

### Key components inside `components/sentcom/v5/` (73 files)
These are the heart of the V5 trading UI. Grouped by purpose:

**Position & trade management**
- `OpenPositionsV5.jsx` — the open-positions table; hosts close-buttons (v19.34.72 close modal trigger).
- `CloseTradeModal.jsx` — operator close panel (partial / market / limit OCA closing).
- `ClosedTodayDrilldown.jsx` — closed-trades panel.
- `BracketHistoryPanel.jsx` — per-trade OCA lifecycle viewer.
- `PositionThoughtsInline.jsx` — bot's per-trade reasoning sidebar.
- `OpenPositionsLegend.jsx` — color-coding legend.

**Health / safety pills (status bar)**
- `BootReconcilePill.jsx` — last boot reconcile result.
- `DriftGuardPill.jsx` — current drift status.
- `BracketReaperPill.jsx` — pending-reaper status.
- `CancelQueueSelfHealPill.jsx` — IB cancel queue health.
- `CpuReliefBadge.jsx` / `DeadLetterBadge.jsx` / `LiveDataChip.jsx` / `HealthChip.jsx` — system-health micro-indicators.
- `LLMRulesPill.jsx` / `OrderPoliciesHelpPill.jsx` — policy pills with tooltips.
- `MarketStateBanner.jsx` / `EodCountdownBannerV5.jsx` / `EodPreviewBanner.jsx` / `DayRollupBannerV5.jsx` — banner strip.

**Bot reasoning feed**
- `DeepFeedV5.jsx` — main thoughts stream (the operator's "TV").
- `BriefingsV5.jsx` / `BriefingsCompactStrip.jsx` — pre-open briefings.
- `AIDecisionAuditCard.jsx` — per-decision audit pop-out.
- `GamePlanStockCard.jsx` / `CarouselCountdownChip.jsx` — pre-open game plan.

**ML / training surfaces**
- `LastTrainingRunCard.jsx` / `LastTrophyRunCard.jsx` / `LastRunsTimeline.jsx` — recent ML runs.
- `MLFeatureAuditPanel.jsx` — feature-pipeline audit.
- `BackfillReadinessCard.jsx` / `CanonicalUniverseCard.jsx` — data-readiness gates.
- `AutonomyReadinessCard.jsx` / `AutonomyVerdictChip.jsx` — green-light meter.

**Diagnostics**
- `FreshnessInspector.jsx` — quote-staleness drill-down.
- `ConnectivityCheck.jsx` — IB / pusher / DGX health.
- `CommandPalette.jsx` — `Ctrl+K` operator action menu.
- `PipelineStageDrilldown.jsx` — pipeline tail UI counterpart.
- `CostBasisSyncTile.jsx` — IB cost-basis sync state.

**Layout helpers**
- `DrawerSplitHandle.jsx` — resizable panel splitter.
- `PanelErrorBoundary.jsx` — wraps each panel.

> If you build a new pill/card, **always add a `data-testid`**
> (kebab-case) and follow the dark-zinc + emerald/rose/cyan/amber
> palette (see §9).

---

*Last updated: 2026-05-22 (v19.34.74 ship — `.bat` flow + sections
12-17 context pack). Update this file whenever you learn a new
convention or trap.*
