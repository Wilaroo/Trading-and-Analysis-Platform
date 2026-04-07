# SentCom AI Trading Platform - PRD

## Original Problem Statement
AI trading platform with 5-Phase Auto-Validation Pipeline, Data Inventory System, CNN chart detection, and maximum Interactive Brokers (IB) historical data collection. Optimizing the ML training pipeline performance over 177M MongoDB rows, resolving stale AI Training status, fixing UI desyncs, and utilizing hardware efficiently.

## Distributed Architecture
```
+----------------------------------+     +---------------------------+
|        DGX SPARK (Linux)         |     |   WINDOWS PC              |
|        IP: 192.168.50.2          |     |   IP: 192.168.50.1        |
|                                  |     |                           |
|  - FastAPI Backend (venv) :8001  |<--->|  - IB Gateway :4002       |
|  - MongoDB (Docker) :27017       | LAN |  - IB Data Pusher         |
|  - Ollama :11434                 |     |  - IB Historical Collector |
|  - Frontend React :3000          |     |  - Browser UI              |
|  - GPU: Blackwell GB10 128GB    |     |                           |
+----------------------------------+     +---------------------------+
```

## What's Been Implemented

### Session: April 7, 2026
- Created backend `.env` and frontend `.env` for DGX Spark (MongoDB local, IB Gateway remote)
- Fixed `asyncio.create_task` crash at module load (trading_bot._restore_state + simulation_engine.initialize moved to startup event)
- Fixed WebSocket startup modal blocking (made WS `required: false`)
- Fixed DynamicRiskPanel and SentCom null-check spam (silenced non-critical errors)
- Full MongoDB migration: Atlas → Spark local Docker (177,394,521 ib_historical_data rows + 93 collections)
- Optimized fill-gaps endpoint: replaced `distinct()` with aggregation pipeline for 177M+ row performance
- Fixed ib_historical_collector pacing bug (duplicate check waited 600s instead of 15s)
- Created `TradeCommand_Spark_AITraining.bat` for Windows-to-Spark distributed startup
- Created `DGX_SPARK_ENV_TEMPLATE.md` documentation
- Queued 13,555 chained gap-fill requests (9 gaps across 593 symbols)
- 4 turbo collectors running overnight to fill all data gaps

### Previous Sessions
- Fixed phantom `QUICK` symbol (Yahoo Finance validation)
- Fixed frontend aggressive polling during training mode
- Configured 10Gbps direct Ethernet link (Windows PC ↔ DGX Spark)
- Set up DGX Spark base dependencies (Docker, MongoDB, Node.js, Yarn, Ollama)

## Data Coverage (as of April 7, 2026)
- **Total bars**: 177,394,521
- **ADV symbols**: 9,187
- **Timeframes**: 1min, 5min, 15min, 30min, 1hour, 1day, 1week
- **Gaps being filled**: 9 gaps across 3 tiers (intraday, swing, investment)
- **Queue**: ~37K pending requests being processed by 4 turbo collectors

## Prioritized Backlog

### P0 - Critical
- [DONE] Get app running on DGX Spark
- [DONE] Migrate data from Atlas to local MongoDB
- [DONE] Fill data gaps via IB collectors
- [ ] Train all models on Blackwell GPU (after gaps filled)

### P1 - High
- [ ] Swap LightGBM to XGBoost GPU (or PyTorch) for ML Training
- [ ] Auto-Optimize AI Settings: Sweep confidence thresholds and lookback windows

### P2 - Medium
- [ ] Desktop notification system (training completion alerts)
- [ ] Gap Fill training phase wiring
- [ ] Smart Templates from AI performance data
- [ ] Model Health card UI element
- [ ] Resume Training feature (skip completed models on interrupt)

### Backlog
- [ ] Systematic migration to Motor (async PyMongo)
- [ ] Fix backend direct IB connection (currently only pusher works via LAN)

## Key Technical Notes
- **CRITICAL**: DO NOT run `apt install nvidia-*` or `dkms` on the DGX Spark
- **Virtual Environment**: All Python commands on Spark must use `source ~/venv/bin/activate`
- **nohup**: Always use `nohup` when starting backend/frontend on Spark via SSH
- **localhost quirk**: Use `192.168.50.2` (not `localhost`) for curl on the Spark
- **IB Client IDs**: Pusher=15, Collectors=16-19 (avoid conflicts with ID=1 used by backend)
- **emergentintegrations**: Not installed on Spark (skipped during setup)

## Key Files
- `backend/.env` - Spark environment config (gitignored)
- `frontend/.env` - Frontend config (gitignored)
- `documents/DGX_SPARK_ENV_TEMPLATE.md` - ENV reference
- `documents/TradeCommand_Spark_AITraining.bat` - Windows startup script
- `documents/scripts/ib_historical_collector.py` - Gap fill collector
- `documents/scripts/ib_data_pusher.py` - Live data pusher
- `backend/routers/ib_collector_router.py` - Collection endpoints (optimized)
- `backend/services/trading_bot_service.py` - Fixed startup crash
- `backend/server.py` - Fixed asyncio.create_task at module load
- `frontend/src/components/StartupModal.jsx` - Fixed WS blocking
- `frontend/src/components/DynamicRiskPanel.jsx` - Fixed null-check spam
- `frontend/src/components/SentCom.jsx` - Fixed null-check spam
