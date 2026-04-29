# Spark + Windows Environment Access — operator hand-off card

**This file is read by every forked agent first. Keep it concise and current.**

## Machines & responsibilities

| Machine | Role |
|---|---|
| **DGX Spark** (Linux) — `spark-1a60@spark-0323` | Backend FastAPI + Frontend React + MongoDB + AI/GPU |
| **Windows PC** | IB Gateway + Data Pusher (port 8765) + 4 Turbo Collectors |

## Access surface — Spark

| What | Path / Value |
|---|---|
| Repo root | `/home/spark-1a60/Trading-and-Analysis-Platform/` |
| Backend code | `/home/spark-1a60/Trading-and-Analysis-Platform/backend/` |
| Frontend code | `/home/spark-1a60/Trading-and-Analysis-Platform/frontend/` |
| Python venv | `/home/spark-1a60/Trading-and-Analysis-Platform/.venv/bin/python` |
| Backend run cmd | `python server.py` (raw process, no supervisor/systemd) |
| Backend cwd at runtime | `/home/spark-1a60/Trading-and-Analysis-Platform/backend` |
| Backend port | `localhost:8001` |
| Frontend port | `localhost:3000` |
| Backend env file | `~/Trading-and-Analysis-Platform/backend/.env` (contains `MONGO_URL`, `DB_NAME`) |
| `mongosh` | **NOT installed** — use the venv python + pymongo for mongo queries |
| Backend logs | NOT under `/var/log/supervisor/` — bare process. Need to check stdout/stderr or instrument |
| Sudo | Operator has had password trouble — **avoid sudo** when possible |

## Restart workflow — IMPORTANT

Operator runs a `.bat` file on Windows that:
1. Performs `git pull` on **both** Windows + Spark
2. Restarts the bare `python server.py` process on Spark
3. Restarts IB pusher + collectors on Windows

**Never instruct operator to run `sudo supervisorctl restart` — it doesn't exist.** Always tell them to "save+pull+restart via your .bat".

## Mongo query template (Python via venv)

```bash
~/Trading-and-Analysis-Platform/.venv/bin/python -c "
import os
from pathlib import Path
env_path = Path.home() / 'Trading-and-Analysis-Platform/backend/.env'
for line in env_path.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('='); os.environ.setdefault(k.strip(), v.strip().strip('\"').strip(\"'\"))
from pymongo import MongoClient
db = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]

# YOUR QUERY HERE
print(db['bot_trades'].count_documents({}))
"
```

## Key collections (as of 2026-04-29)

| Collection | Rows | Notes |
|---|---|---|
| `ib_historical_data` | **206,499,976** | bar_sizes: `1 day` (13.6M), `1 hour`, `1 min`, `5 mins`, `15 mins`, `30 mins`, `1 week` |
| `bot_trades` | 6,850 | **LAST TRADE: 2026-04-16** — 13-day silent regression |
| `symbol_adv_cache` | 9,412 | Field is `avg_dollar_volume` (NOT `adv_dollars` — common gotcha) |
| `sentcom_thoughts` | 110+ | rejection narratives + filter thoughts. `kind: 'rejection'`, `action_type: rejection_*` |
| `live_alerts` | active | priority/tape/auto_eligible flags; current_price/trigger_price/stop_loss/target |
| `bot_state` | 1 | `mode: autonomous`, `running: true`, `risk_params`, `enabled_setups` |
| `historical_data_requests` | 337,727 | IB backfill queue |
| `daily_stats`, `daily_report_cards` | 38, 21 | per-day P&L tracking |
| `regime_trade_log` | 82 | regime tagged trades |
| `simulated_trades` | 117 | sim phase trades |
| `live_bar_cache` | 31 | active intraday bar cache |
| `ai_module_config` | small | shadow_mode flags per module — operator's projection returned empty (4 modules visible via API: debate_agents, ai_risk_manager, institutional_flow, timeseries_ai) |
| `ai_module_decisions`, `module_decisions`, `shadow_decisions` | varies | shadow tracker outputs |

## Bot state snapshot (2026-04-29)

```
mode:                autonomous
running:             true
account:             DUM61566S (IB demo / paper)
starting_capital:    $1,069,671.46 (synced to live IB equity)
max_open_positions:  7
max_risk_per_trade:  $2,500
max_position_pct:    50%
min_risk_reward:     2.5
enabled_setups:      44 (all in `live` phase per /api/strategy-promotion/phases)
ai_modules:          4 registered, all shadow_mode=true
                     (debate_agents, ai_risk_manager, institutional_flow, timeseries_ai)
```

## Critical issue under investigation (April 29-30, 2026)

**Bot has not created a single `bot_trade` since 2026-04-16 (13-day silent regression).**

- Hard gates work: alerts → priority → tape_confirmed → auto_eligible flow correctly (validated 2026-04-29)
- Confidence gate evaluates and approves (today_evaluated: 84, today_go: 32, today_skip: 31)
- BUT zero rows land in `bot_trades` collection
- **Forensic instrumentation shipped 2026-04-30 v12** — every silent exit between AI gate and `bot_trades.insert_one()` now records to `trade_drops` collection. `GET /api/diagnostic/trade-drops?minutes=60` aggregates by gate.
- **Likeliest root cause identified**: `trade_execution.execute_trade` broker-reject + exception branches were orphaning REJECTED trades in process memory (no `_save_trade()` call). Patched in v12.

### 🎯 Operator action plan (after pull + restart on Spark)

```bash
# After 5-10 min of RTH scanning
curl -s http://localhost:8001/api/diagnostic/trade-drops?minutes=60 | python3 -m json.tool
# Read `first_killing_gate` — names the suspect.
# Possible gates: account_guard, broker_rejected, safety_guardrail,
# safety_guardrail_crash, no_trade_executor, pre_exec_guardrail_veto,
# strategy_paper_phase, strategy_simulation_phase, execution_exception
```

If `first_killing_gate=account_guard`: rotate `IB_ACCOUNT_PAPER` in
backend/.env to include the pusher's reported `DUM61566S` alias.

If `first_killing_gate=broker_rejected`: read the `reason` field in
the `recent[]` array — IB-side error (margin, no buying power, etc).

REJECTED trades now appear in `bot_trades` (orphan bug fixed in v12)
so post-mortem queries against the collection will see attempts that
were silently dropping for 13 days.

See `/app/memory/CHANGELOG.md` v12 entry for the full detail.

## Key endpoints (use external `localhost:8001` from Spark CLI)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/diagnostic/rth-readiness` | 9-check pre-flight (single curl) |
| GET | `/api/diagnostic/trade-funnel` | Stage-by-stage execution flow with kill_check |
| GET | `/api/diagnostic/trade-drops?minutes=N&gate=X` | **NEW 2026-04-30 v12** — silent execution-drop forensics. `first_killing_gate` names the suspect; `recent[]` lists last 25 with context. |
| GET | `/api/trading-bot/status` | Bot mode, daily_stats, risk_params, account.equity |
| POST | `/api/trading-bot/refresh-account` | Force-pull IB equity → starting_capital |
| GET | `/api/scanner/setup-landscape` | Daily Bellafiore Setup classification + multi-index regime |
| GET | `/api/scanner/setup-trade-matrix` | Allowed Trade × Setup grid |
| GET | `/api/trading-bot/rejection-analytics?days=1&min_count=1` | Why trades got killed |
| GET | `/api/ai-modules/config` | All 4 AI module enabled/shadow flags |
| GET | `/api/ai-training/confidence-gate/stats` | today_evaluated/go/skip rates |
| GET | `/api/ai-training/confidence-gate/calibration` | auto-tuned threshold overrides |
| GET | `/api/strategy-promotion/phases` | per-strategy phase (paper/sim/live/demoted/disabled) |
| GET | `/api/ib/pusher-health` | Windows-side IB pusher status |
| GET | `/api/ib/pushed-data` | Last pushed quote/account/positions snapshot |

## jq + envelope-shape gotchas

Many endpoints wrap responses in `{success, count, items}` style envelopes. If a jq pipeline says `Cannot index string with string "X"`, the array you want is probably under `.alerts`, `.trades`, `.configs`, `.thoughts`, `.checks`, etc. **Don't trust raw `.[]` iteration on these endpoints.**

Common templates that work:
```bash
# Generic envelope unwrap
curl -s URL | jq '(.alerts // .trades // .configs // .data // .) | ...'

# Multi-field summary without iteration ambiguity
curl -s URL | jq '{a: .field_a, b: .field_b, count: (.items | length)}'
```

## Async/sync cursor gotcha (fixed 2026-04-29)

The bot's `db` handle on Spark is **sync PyMongo**, not motor. Code paths using `await cursor.to_list(length=N)` throw TypeError silently. Fix template:

```python
import asyncio as _asyncio
cursor = db['col'].find({...}).sort(...).limit(N)
to_list = getattr(cursor, "to_list", None)
if to_list is not None and _asyncio.iscoroutinefunction(to_list):
    rows = await cursor.to_list(length=N)
else:
    rows = list(cursor)
```

Search the codebase for `await cursor.to_list` periodically — there's still 1 known case in `job_queue_manager.py:91` as of 2026-04-29.
