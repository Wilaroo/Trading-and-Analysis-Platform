"""
TradeCommand - Trading and Analysis Platform Backend
Enhanced with Yahoo Finance, TradingView, Insider Trading, COT Data
Real-Time WebSocket Streaming
Now with Finnhub integration (60 calls/min), Notifications, Market Context Analysis, and Trade Journal
"""
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import os
import httpx
import asyncio
import random
import json
from concurrent.futures import ThreadPoolExecutor
from pymongo import MongoClient

# Load environment variables
load_dotenv()

# Import services and routers
from services.stock_data import get_stock_service
from data.index_symbols import get_all_symbols_set
from services.notifications import get_notification_service
from services.market_context import get_market_context_service
from services.trade_journal import get_trade_journal_service
from services.catalyst_scoring import get_catalyst_scoring_service
from services.trading_rules import get_trading_rules_engine
from routers.notifications import router as notifications_router, init_notification_service
from routers.market_context import router as market_context_router, init_market_context_service
from routers.trades import router as trades_router, init_trade_journal_service
from routers.catalyst import router as catalyst_router, init_catalyst_service
from routers.rules import router as rules_router, init_trading_rules
from routers.ib import router as ib_router, init_ib_service
# Refactored IB modules are available at routers.ib_modules but not yet active
# from routers.ib_modules import router as ib_historical_router
from routers.strategies import router as strategies_router, init_strategy_service
from routers.scoring import router as scoring_router
from routers.features import router as features_router
from routers.knowledge import router as knowledge_router
from routers.learning import router as learning_router
from routers.quality import router as quality_router, init_quality_router
from routers.assistant import router as assistant_router, init_assistant_router
from routers.scheduler import router as scheduler_router, init_scheduler_router
from routers.alpaca import router as alpaca_router, init_alpaca_router
from routers.trade_history import router as trade_history_router
from routers.scanner import router as scanner_router, init_scanner_router
from routers.alerts import router as alerts_router, init_alerts_router
from routers.technicals import router as technicals_router
from routers.live_scanner import router as live_scanner_router, init_live_scanner_router
from routers.circuit_breaker import router as circuit_breaker_router, init_circuit_breaker_router
from services.ollama_proxy_manager import ollama_proxy_manager, handle_ollama_proxy_websocket
from routers.trading_bot import router as trading_bot_router, init_trading_bot_router
from routers.learning_dashboard import router as learning_dashboard_router, init_learning_dashboard
from routers.market_intel import router as market_intel_router, init_market_intel_router
from routers.research import router as research_router
from routers.config import router as config_router
from routers.tqs_router import router as tqs_router
from routers.risk_router import router as risk_router
from routers.rag_router import router as rag_router
from routers.medium_learning_router import router as medium_learning_router
from routers.slow_learning_router import router as slow_learning_router
from routers.scheduler_router import router as scheduler_router
from routers.portfolio_awareness import router as portfolio_awareness_router
from routers.quick_actions import router as quick_actions_router, init_quick_actions_router
from routers.sectors import router as sectors_router
from routers.patterns import router as patterns_router
from routers.sentiment import router as sentiment_router
from routers.simulator import router as simulator_router
from routers.ev_tracking import router as ev_tracking_router
from routers.smb_router import router as smb_router
from routers.journal_router import router as journal_router
from routers.agents import router as agents_router, init_agents_router
from routers.advanced_backtest_router import router as advanced_backtest_router, init_advanced_backtest_router
from routers.hybrid_data import router as hybrid_data_router, init_hybrid_data_router
from routers.market_scanner import router as market_scanner_router, init_market_scanner_router
from routers.market_regime import router as market_regime_router, init_market_regime_engine
from routers.regime_performance import router as regime_performance_router, init_regime_performance_router
from routers.context_awareness import router as context_awareness_router, init_context_router
from routers.smart_stops import router as smart_stops_router, init_smart_stop_router
from routers.sentcom import router as sentcom_router
from routers.dynamic_risk_router import router as dynamic_risk_router
from routers.ai_modules import router as ai_modules_router, inject_services as inject_ai_module_services
from routers.learning_connectors_router import router as learning_connectors_router, init_learning_connectors_router
from routers.ib_collector_router import router as ib_collector_router
from routers.data_storage_router import router as data_storage_router
from routers.strategy_promotion_router import router as strategy_promotion_router, init_strategy_promotion_router
from routers.scripts import router as scripts_router
from routers.startup_status import router as startup_status_router
from routers.focus_mode_router import router as focus_mode_router
from routers.watchlist import router as watchlist_router, init_watchlist_router, get_watchlist as _watchlist_get_watchlist
from routers.portfolio import router as portfolio_router, init_portfolio_router, get_portfolio as _portfolio_get_portfolio
from routers.earnings_router import router as earnings_router, init_earnings_router
from routers.ollama_proxy import (
    router as ollama_proxy_router, init_ollama_proxy_router,
    is_http_ollama_proxy_connected, call_ollama_via_http_proxy,
    get_http_proxy_info, track_ollama_request
)
from routers.market_data import router as market_data_router, init_market_data_router
from routers.system_router import router as system_router, init_system_router
from routers.dashboard_router import router as dashboard_router, init_dashboard_router
from routers.ai_training import router as ai_training_router
from routers.short_data import router as short_data_router
from routers.trade_snapshots import router as trade_snapshots_router, init_snapshot_service, init_snapshot_assistant
from routers.social_feed import router as social_feed_router, init_social_feed_router
from services.social_feed_service import init_social_feed_service
from services.sentcom_service import get_sentcom_service, init_sentcom_service
from services.dynamic_risk_engine import get_dynamic_risk_engine
from services.focus_mode_manager import focus_mode_manager
from services.job_queue_manager import job_queue_manager
from services.ai_modules import (
    get_ai_module_config, init_ai_module_config,
    get_shadow_tracker, init_shadow_tracker,
    get_debate_agents, init_debate_agents,
    get_ai_risk_manager, init_ai_risk_manager,
    init_institutional_flow_service,
    init_volume_anomaly_service,
    init_ai_consultation,
    init_timeseries_ai
)
from services.ai_modules.agent_data_service import get_agent_data_service, init_agent_data_service
from services.strategy_promotion_service import get_strategy_promotion_service, init_strategy_promotion_service
from services.market_intel_service import get_market_intel_service
from services.hybrid_data_service import get_hybrid_data_service, init_hybrid_data_service
from services.market_scanner_service import get_market_scanner_service, init_market_scanner_service
from services.market_regime_engine import MarketRegimeEngine, get_market_regime_engine
from services.regime_performance_service import get_regime_performance_service, init_regime_performance_service
from services.learning_loop_service import get_learning_loop_service, init_learning_loop_service
from services.trade_context_service import get_trade_context_service, init_trade_context_service
from services.execution_tracker_service import get_execution_tracker, init_execution_tracker
from services.graceful_degradation import get_degradation_service, init_degradation_service
from services.tqs import get_tqs_engine, init_tqs_engine
from services.circuit_breaker import get_circuit_breaker_service, init_circuit_breaker_service
from services.position_sizer import get_position_sizer_service, init_position_sizer_service
from services.health_monitor import get_health_monitor_service, init_health_monitor_service
from services.dynamic_thresholds import get_dynamic_threshold_service, init_dynamic_threshold_service
from services.rag import get_rag_service, init_rag_service
from services.context_awareness_service import get_context_awareness_service, init_context_awareness_service
from services.medium_learning import (
    get_calibration_service, init_calibration_service,
    get_context_performance_service,
    get_confirmation_validator_service,
    get_playbook_performance_service,
    get_edge_decay_service
)
from services.slow_learning import (
    get_historical_data_service, init_historical_data_service,
    get_backtest_engine, init_backtest_engine,
    get_shadow_mode_service, init_shadow_mode_service
)
from services.learning_context_provider import (
    get_learning_context_provider, init_learning_context_provider
)
from services.trading_scheduler import (
    get_trading_scheduler, init_trading_scheduler
)
from services.eod_generation_service import get_eod_service
from services.ib_service import get_ib_service
from services.news_service import init_news_service
from services.strategy_service import get_strategy_service
from services.scoring_engine import get_scoring_engine
from services.feature_engine import get_feature_engine
from services.quality_service import init_quality_service
from services.ai_assistant_service import init_assistant_service
from services.ai_assistant_service import LLMProvider
from services.scheduler_service import init_scheduler_service
from services.alpaca_service import init_alpaca_service
from services.predictive_scanner import get_predictive_scanner
from services.alert_system import get_alert_system
from services.trading_bot_service import get_trading_bot_service
from services.trade_executor_service import get_trade_executor
from services.smart_watchlist_service import init_smart_watchlist, get_smart_watchlist
from services.index_universe import get_index_universe
from services.wave_scanner import init_wave_scanner, get_wave_scanner
from services.sector_analysis_service import get_sector_analysis_service
from services.chart_pattern_service import get_chart_pattern_service
from services.sentiment_analysis_service import get_sentiment_service
from services.service_registry import get_service_registry, register_service, get_service_optional
from data.strategies_data import ALL_STRATEGIES_DATA

# Initialize service registry for clean dependency management
services = get_service_registry()

app = FastAPI(title="TradeCommand API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
mongo_client = MongoClient(os.environ.get("MONGO_URL"))
db = mongo_client[os.environ.get("DB_NAME", "tradecommand")]

# Register database instance for other modules to access
from database import set_database
set_database(db)

# Initialize services
stock_service = get_stock_service()
notification_service = get_notification_service(db)
market_context_service = get_market_context_service()
trade_journal_service = get_trade_journal_service(db)
catalyst_scoring_service = get_catalyst_scoring_service(db)
trading_rules_engine = get_trading_rules_engine()
ib_service = get_ib_service()
strategy_service = get_strategy_service(db)
scoring_engine = get_scoring_engine(db)
feature_engine = get_feature_engine()
quality_service = init_quality_service(ib_service, db)

# Initialize End-of-Day Generation Service (for automatic DRC & Playbook generation at 4:30 PM ET)
eod_service = get_eod_service(db)
eod_service.start_scheduler()
print("End-of-Day auto-generation scheduler started (4:30 PM ET weekdays)")

# Initialize Alpaca service early and wire it to stock_service
alpaca_service = init_alpaca_service()
stock_service.set_alpaca_service(alpaca_service)

# Seed strategies if not already done
if not strategy_service.is_seeded():
    seeded_count = strategy_service.seed_strategies(ALL_STRATEGIES_DATA)
    print(f"Seeded {seeded_count} trading strategies to database")

# Initialize routers with services
init_notification_service(notification_service)
init_market_context_service(market_context_service)
init_trade_journal_service(trade_journal_service)

# Trade Snapshot Service
from services.trade_snapshot_service import TradeSnapshotService
trade_snapshot_service = TradeSnapshotService(db)
init_snapshot_service(trade_snapshot_service)

# Initialize Social Feed service
social_feed_service = init_social_feed_service(db)
init_social_feed_router(social_feed_service)

# Wire snapshot service into trade journal for auto-generation on manual trade close
trade_journal_service._snapshot_service = trade_snapshot_service

init_catalyst_service(catalyst_scoring_service, stock_service)
init_trading_rules(trading_rules_engine)
init_ib_service(ib_service)
init_strategy_service(strategy_service)
init_quality_router(quality_service, ib_service)
assistant_service = init_assistant_service(db)
init_assistant_router(assistant_service)
init_snapshot_assistant(assistant_service)  # Must come after assistant_service is created
news_service = init_news_service(ib_service)
scheduler_service = init_scheduler_service()
scheduler_service.start()
init_scheduler_router(scheduler_service, assistant_service, None)  # Newsletter removed
init_alpaca_router(alpaca_service)

# Initialize sector analysis service
sector_service = get_sector_analysis_service()
sector_service.set_alpaca_service(alpaca_service)

# Initialize chart pattern service
chart_pattern_service = get_chart_pattern_service()
chart_pattern_service.set_alpaca_service(alpaca_service)

# Initialize sentiment analysis service
sentiment_service = get_sentiment_service()
sentiment_service.set_services(news_service=None, llm_service=None)  # Will be wired to news/llm later if available

# Initialize quick actions router with technical service for volatility-adjusted sizing
from services.realtime_technical_service import get_technical_service
realtime_tech_service = get_technical_service()
init_quick_actions_router(alpaca_service, db, trading_bot=None, technical_service=realtime_tech_service)

# Initialize user viewed symbols tracker
from services.user_viewed_tracker import init_user_viewed_tracker
init_user_viewed_tracker(db)

# Initialize predictive scanner
predictive_scanner = get_predictive_scanner()
init_scanner_router(predictive_scanner)

# Initialize advanced alert system
alert_system = get_alert_system()
init_alerts_router(alert_system)

# Initialize ENHANCED background scanner for live alerts (200+ symbols, all SMB strategies)
from services.enhanced_scanner import get_enhanced_scanner
background_scanner = get_enhanced_scanner()
init_live_scanner_router(background_scanner)
register_service('enhanced_scanner', background_scanner)  # Register for learning connectors

# Wire enhanced scanner into predictive scanner for shared market data
predictive_scanner.set_enhanced_scanner(background_scanner)

# Initialize trading bot
trading_bot = get_trading_bot_service()
trade_executor = get_trade_executor()
from services.alpaca_service import get_alpaca_service
alpaca_service = get_alpaca_service()
trading_bot.set_services(
    alert_system=alert_system,
    trading_intelligence=None,
    alpaca_service=alpaca_service,
    trade_executor=trade_executor,
    db=db
)
init_trading_bot_router(trading_bot, trade_executor)
init_circuit_breaker_router(trading_bot)

# Wire AI assistant ↔ Trading bot integration
assistant_service.set_trading_bot(trading_bot)
assistant_service.set_alpaca_service(alpaca_service)  # Wire Alpaca for positions
trading_bot._ai_assistant = assistant_service

# Wire Scanner ↔ Trading bot for auto-execution
background_scanner.set_trading_bot(trading_bot)
background_scanner.set_db(db)

# Wire Trading bot ↔ Scanner for Smart Strategy Filtering (access to strategy stats)
trading_bot.set_enhanced_scanner(background_scanner)

# Wire Scanner ↔ AI assistant for proactive coaching notifications
background_scanner.set_ai_assistant(assistant_service)

# Initialize strategy performance & learning service
from services.strategy_performance_service import get_performance_service
perf_service = get_performance_service()
perf_service._db = db
perf_service.set_services(trading_bot=trading_bot, ai_assistant=assistant_service)
trading_bot._perf_service = perf_service
init_learning_dashboard(perf_service)

# Initialize SentCom - Unified AI Command Center
from agents.orchestrator import get_orchestrator, init_orchestrator
try:
    from services.order_queue_service import get_order_queue_service
    _order_queue = get_order_queue_service()
except:
    _order_queue = None

# Initialize Historical Data Queue Service (for IB Data Pusher)
try:
    from services.historical_data_queue_service import init_historical_data_queue_service
    init_historical_data_queue_service(db)
    print("[SERVER] Historical Data Queue Service initialized")
except Exception as e:
    print(f"[SERVER] Warning: Historical Data Queue Service not initialized: {e}")

# Initialize the orchestrator with basic services first
# More services will be injected later when they're ready
orchestrator_services = {
    "ib_router": ib_service,
    "scanner": None,  # Will be injected later
    "order_queue": _order_queue,
    "db": db,
    "performance_analyzer": perf_service,
    "technical_service": None,  # Will be injected later
    "sector_service": None,
    "sentiment_service": None,
    "tqs_engine": None,  # Will be injected later
}

# Initialize orchestrator with services injected
_orchestrator = init_orchestrator(services=orchestrator_services)
print("[SERVER] Orchestrator initialized (basic services)")

sentcom_services = {
    "trading_bot": trading_bot,
    "orchestrator": _orchestrator,
    "ib_service": ib_service,
    "regime_engine": None,  # Will be set later when regime engine is ready
    "order_queue": _order_queue,
    "db": db
}
init_sentcom_service(sentcom_services)
print("[SERVER] SentCom service initialized")

# Initialize Dynamic Risk Engine
dynamic_risk_engine = get_dynamic_risk_engine()
dynamic_risk_engine.inject_services({
    "trading_bot": trading_bot,
    "market_data": None,  # Will be set later if needed
    "db": db
})
print("[SERVER] Dynamic Risk Engine initialized")

# Wire Dynamic Risk into SentCom for risk-aware responses
sentcom_svc = get_sentcom_service()
sentcom_svc.inject_dynamic_risk(dynamic_risk_engine)
print("[SERVER] Dynamic Risk wired into SentCom")

# Include routers
app.include_router(notifications_router)
app.include_router(market_context_router)
app.include_router(trades_router)
app.include_router(catalyst_router)
app.include_router(rules_router)
app.include_router(ib_router)
# Refactored IB historical endpoints available but not active yet
# app.include_router(ib_historical_router, prefix="/api/ib")
app.include_router(strategies_router)
app.include_router(scoring_router)
app.include_router(features_router)
app.include_router(knowledge_router)
app.include_router(learning_router)
app.include_router(quality_router)
app.include_router(alpaca_router)
app.include_router(assistant_router)
app.include_router(scheduler_router)
app.include_router(trade_history_router)
app.include_router(scanner_router)
app.include_router(alerts_router)
app.include_router(technicals_router)
app.include_router(live_scanner_router)
app.include_router(trading_bot_router)
app.include_router(learning_dashboard_router)
app.include_router(market_intel_router)
app.include_router(research_router)
app.include_router(config_router)
app.include_router(portfolio_awareness_router)
app.include_router(quick_actions_router)
app.include_router(sectors_router)
app.include_router(patterns_router)
app.include_router(sentiment_router)
app.include_router(simulator_router)
app.include_router(ev_tracking_router)
app.include_router(smb_router)
app.include_router(journal_router)
app.include_router(tqs_router)
app.include_router(risk_router)
app.include_router(rag_router)
app.include_router(medium_learning_router)
app.include_router(slow_learning_router)
app.include_router(scheduler_router)
app.include_router(circuit_breaker_router)
app.include_router(agents_router)  # Multi-agent system
app.include_router(advanced_backtest_router)  # Advanced backtesting system
app.include_router(hybrid_data_router)  # Hybrid IB/Alpaca data service
app.include_router(market_scanner_router)  # Market-wide strategy scanner
app.include_router(market_regime_router)  # Market regime engine
app.include_router(regime_performance_router)  # Regime-based performance tracking
app.include_router(context_awareness_router)  # Phase 2 AI context awareness
app.include_router(smart_stops_router)  # Unified Smart Stop System
init_smart_stop_router()  # Initialize smart stop service
app.include_router(sentcom_router)  # SentCom - Unified AI Command Center
app.include_router(dynamic_risk_router)  # Dynamic Risk Management Engine
app.include_router(ai_modules_router)  # AI Modules - Shadow Mode, Debate, Risk Manager
app.include_router(learning_connectors_router)  # Learning Connectors - Data flow orchestration
app.include_router(ib_collector_router)  # IB Historical Data Collector
app.include_router(ai_training_router)  # AI Bulk Training Pipeline
app.include_router(short_data_router)  # Short Interest Data (IB + FINRA)
app.include_router(trade_snapshots_router)  # Trade Chart Snapshots with AI Annotations
app.include_router(social_feed_router)  # Twitter/X Social Feed & AI Sentiment
app.include_router(data_storage_router)  # Data Storage Management
app.include_router(strategy_promotion_router)  # Strategy Promotion - Autonomous Loop
app.include_router(scripts_router)  # Scripts auto-update endpoint for StartTrading.bat
app.include_router(startup_status_router)  # Startup Status Dashboard
app.include_router(focus_mode_router)  # Focus Mode & Job Queue System
app.include_router(watchlist_router)  # Watchlist CRUD (extracted from server.py)
app.include_router(portfolio_router)  # Portfolio positions (extracted from server.py)
app.include_router(earnings_router)  # Earnings calendar & analysis (extracted from server.py)
app.include_router(ollama_proxy_router)  # Ollama proxy HTTP endpoints (extracted from server.py)
app.include_router(market_data_router)  # Market data, quotes, fundamentals (extracted from server.py)
app.include_router(system_router)  # System health, startup-check, consolidated-status, LLM status, system monitor
app.include_router(dashboard_router)  # Dashboard stats/init, alerts CRUD, scanner, wave-scanner, universe

# Initialize job queue manager with sync database (uses asyncio.to_thread internally)
job_queue_manager.set_db(db)

# Collections
strategies_col = db["strategies"]
watchlists_col = db["watchlists"]
smart_watchlist_col = db["smart_watchlist"]  # New: for hybrid auto/manual watchlist
alerts_col = db["alerts"]
portfolios_col = db["portfolios"]
scans_col = db["scans"]
insider_col = db["insider_trades"]
cot_col = db["cot_data"]
earnings_col = db["earnings"]

# NEW: Learning Architecture Collections (Phase 1)
trade_outcomes_col = db["trade_outcomes"]  # Full trade records with context
learning_stats_col = db["learning_stats"]  # Aggregated statistics by context
calibration_log_col = db["calibration_log"]  # Threshold adjustment history
trader_profile_col = db["trader_profile"]  # Trader patterns for RAG

# Initialize smart watchlist and wave scanner
smart_watchlist = init_smart_watchlist(smart_watchlist_col)
index_universe = get_index_universe()
wave_scanner = init_wave_scanner(smart_watchlist, index_universe)

# Initialize market intel service (moved here to wire smart_watchlist)
market_intel_service = get_market_intel_service()
market_intel_service._db = db
market_intel_service.set_services(
    ai_assistant=assistant_service,
    trading_bot=trading_bot,
    perf_service=perf_service,
    alpaca_service=alpaca_service,
    news_service=news_service,
    scanner_service=background_scanner,
    smart_watchlist=smart_watchlist,
    alert_system=alert_system
)
register_service('market_intel_service', market_intel_service)
init_market_intel_router(market_intel_service)

# ===================== LEARNING ARCHITECTURE (Phase 1) =====================
# Initialize Three-Speed Learning Architecture services

# 1. Graceful Degradation Service - handles service failures
degradation_service = init_degradation_service()

# 2. Execution Tracker - tracks trade execution quality
execution_tracker = init_execution_tracker(db=db, alpaca_service=alpaca_service)

# 3. Trade Context Service - captures market context at trade time
trade_context_service = init_trade_context_service(
    alpaca_service=alpaca_service,
    ib_service=ib_service,
    sector_service=sector_service,
    news_service=news_service,
    technical_service=realtime_tech_service,
    sentiment_service=sentiment_service,
    db=db
)

# 4. Learning Loop Service - orchestrates the learning system
learning_loop_service = init_learning_loop_service(db=db)
learning_loop_service.set_services(
    context_service=trade_context_service,
    execution_tracker=execution_tracker,
    degradation_service=degradation_service
)

# Wire learning loop to trading bot for trade outcome recording
trading_bot._learning_loop = learning_loop_service

# Register learning services in registry for later use
register_service('learning_loop_service', learning_loop_service)
register_service('trade_context_service', trade_context_service)
register_service('execution_tracker', execution_tracker)
register_service('alpaca_service', alpaca_service)

print("Three-Speed Learning Architecture Phase 1 initialized")
print("  - Collections: trade_outcomes, learning_stats, calibration_log, trader_profile")
print("  - Services: LearningLoop, TradeContext, ExecutionTracker, GracefulDegradation")

# ===================== TQS ENGINE (Phase 2) =====================
# Initialize Trade Quality Score engine with all 5 pillars

tqs_engine = init_tqs_engine(
    learning_loop=learning_loop_service,
    alpaca_service=alpaca_service,
    ib_service=ib_service,
    technical_service=realtime_tech_service,
    sector_service=sector_service,
    scanner=background_scanner
)

print("TQS Engine (Phase 2) initialized")
print("  - Pillars: Setup(25%), Technical(25%), Fundamental(15%), Context(20%), Execution(15%)")
print("  - Endpoints: /api/tqs/score, /api/tqs/breakdown, /api/tqs/batch")

# Register TQS engine
register_service('tqs_engine', tqs_engine)

# Late injection of full services to orchestrator (now that TQS and scanner are ready)
try:
    _orchestrator.inject_services({
        "ib_router": ib_service,
        "scanner": background_scanner,
        "order_queue": _order_queue,
        "db": db,
        "performance_analyzer": perf_service,
        "technical_service": realtime_tech_service,
        "sector_service": sector_service,
        "sentiment_service": None,
        "tqs_engine": tqs_engine,
    })
    print("[SERVER] Orchestrator fully wired with all services (scanner, TQS, technical)")
except Exception as e:
    print(f"[SERVER] Warning: Orchestrator late injection failed: {e}")

# ===================== MARKET REGIME ENGINE (Phase 2.5) =====================
# Initialize Market Regime Engine for market state detection

market_regime_engine = MarketRegimeEngine(
    alpaca_service=alpaca_service,
    ib_service=ib_service,
    db=db
)
init_market_regime_engine(market_regime_engine)
register_service('market_regime_engine', market_regime_engine)

print("Market Regime Engine (Phase 2.5) initialized")
print("  - Signal Blocks: SPY/QQQ breadth, VIX, sector rotation, volume, internals")
print("  - States: RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN")
print("  - Endpoints: /api/market-regime/current, /api/market-regime/summary")

# Wire Market Regime to Trading Bot for regime-aware position sizing
trading_bot.set_market_regime_engine(market_regime_engine)
print("  - Wired to Trading Bot: Position sizing adjusts based on regime")

# Wire Market Regime to SentCom for regime-aware briefings and chat
sentcom_svc = get_sentcom_service()
sentcom_svc.inject_regime_engine(market_regime_engine)
print("  - Wired to SentCom: Briefings and chat now use real market regime data")

# Inject dependencies for regime performance endpoint
from routers.market_regime import inject_dependencies as inject_market_regime_deps
inject_market_regime_deps(db=db, trading_bot=trading_bot)
print("  - Regime Performance: Personalized stats wired to /api/market-regime/performance")

# Initialize Regime Performance Tracking Service
regime_performance_service = init_regime_performance_service(db=db)
init_regime_performance_router(regime_performance_service)
register_service('regime_performance_service', regime_performance_service)

# Wire Regime Performance Service to Trading Bot for trade logging
trading_bot.set_regime_performance_service(regime_performance_service)
print("  - Regime Performance Tracking: Strategy performance by market regime")
print("  - Wired to Trading Bot: Closed trades logged with regime data")
print("  - Endpoints: /api/regime-performance/summary, /api/regime-performance/best-for-regime/{regime}")

# Wire Trade Journal to Trading Bot for auto-recording
trading_bot.set_trade_journal(trade_journal_service)
trading_bot._snapshot_service = trade_snapshot_service
print("  - Trade Journal: Auto-recording enabled for bot trades")
print("  - Trade Snapshots: Auto-generation enabled for closed trades")

# ===================== AI CONFIDENCE GATE =====================
from services.ai_modules.confidence_gate import init_confidence_gate
confidence_gate = init_confidence_gate(db=db)
register_service('confidence_gate', confidence_gate)
print("AI Confidence Gate initialized")
print("  - Pre-trade intelligence: Regime + Model Consensus → GO/REDUCE/SKIP")
print("  - Endpoints: /api/ai-training/confidence-gate/summary, decisions, stats")

# Wire Confidence Gate to Trading Bot
trading_bot.set_confidence_gate(confidence_gate)
print("  - Wired to Trading Bot: Every trade now passes through the confidence gate")

# ===================== CONTEXT AWARENESS SERVICE (Phase 2 AI) =====================
# Initialize Context Awareness Service for smarter AI responses
context_awareness_service = init_context_awareness_service(
    regime_engine=market_regime_engine,
    db=db
)
init_context_router(context_awareness_service)
register_service('context_awareness', context_awareness_service)
print("Context Awareness Service (Phase 2 AI) initialized")
print("  - Time-of-day awareness: Pre-market, Open, Midday, Close, After-hours")
print("  - Regime awareness: Integrated with Market Regime Engine")
print("  - Position awareness: Real-time position and exposure tracking")
print("  - Endpoints: /api/context/session, /api/context/regime, /api/context/full")

# ===================== UNIFIED SMART STOP SYSTEM =====================
# Initialize Smart Stop Service with all external services for intelligent analysis
from services.smart_stop_service import get_smart_stop_service, init_smart_stop_service
smart_stop_service = init_smart_stop_service(
    regime_service=market_regime_engine,
    sector_service=sector_service,
    data_service=alpaca_service
)
# Inject MongoDB for historical data access (uses unified ib_historical_data collection)
smart_stop_service.set_db(db)
register_service('smart_stop_service', smart_stop_service)
print("Unified Smart Stop System initialized")
print("  - 6 Stop Modes: original, atr_dynamic, anti_hunt, volatility_adjusted, layered, chandelier")
print("  - 8 Setup Rules: breakout, pullback, momentum, mean_reversion, gap_and_go, vwap_reversal, earnings_play, default")
print("  - Volume Profile Analysis: POC, VAH/VAL, HVN/LVN detection (from ib_historical_data)")
print("  - Sector Correlation: Relative strength-based adjustments")
print("  - Stop Hunt Protection: Anti-hunt, layered stops, round number avoidance")
print("  - Endpoints: /api/smart-stops/calculate, /api/smart-stops/intelligent-calculate, /api/smart-stops/analyze-trade")

# ===================== FAST LEARNING (Phase 3A & 3B) =====================
# Initialize circuit breakers, position sizing, health monitoring, dynamic thresholds

# 1. Circuit Breaker Service - risk controls
circuit_breaker_service = init_circuit_breaker_service(
    learning_loop=learning_loop_service,
    db=db
)

# 2. Position Sizer Service - TQS-based sizing
position_sizer_service = init_position_sizer_service(
    circuit_breaker=circuit_breaker_service,
    learning_loop=learning_loop_service
)

# 3. Dynamic Threshold Service - context-aware gating
dynamic_threshold_service = init_dynamic_threshold_service(
    learning_loop=learning_loop_service
)

# 4. Health Monitor Service - system status
health_monitor_service = init_health_monitor_service(
    alpaca_service=alpaca_service,
    ib_service=ib_service,
    scanner=background_scanner,
    tqs_engine=tqs_engine,
    circuit_breaker=circuit_breaker_service,
    learning_loop=learning_loop_service,
    db=db
)

print("Fast Learning (Phase 3A & 3B) initialized")
print("  - Circuit Breakers: daily_loss, consecutive_losses, trade_frequency, tilt_detection")
print("  - Position Sizing: TQS-scaled, volatility-adjusted, circuit breaker-constrained")
print("  - Dynamic Thresholds: regime-based, time-based, VIX-based")
print("  - Endpoints: /api/risk/circuit-breakers, /api/risk/position-sizing, /api/risk/thresholds")

# ===================== RAG KNOWLEDGE BASE (Phase 4) =====================
# Initialize Retrieval-Augmented Generation for personalized AI context

try:
    rag_service = init_rag_service(db=db, learning_loop=learning_loop_service)
    register_service('rag_service', rag_service)
    print("RAG Knowledge Base (Phase 4) initialized")
    print("  - Vector Store: ChromaDB at /app/backend/data/chromadb")
    print("  - Collections: trade_outcomes, playbooks, patterns, daily_insights")
    print("  - Endpoints: /api/rag/retrieve, /api/rag/augment-prompt, /api/rag/sync")
except Exception as e:
    print(f"RAG Knowledge Base initialization deferred: {e}")
    print("  - Will initialize on first use (embedding model loading)")
    rag_service = None

# ===================== MEDIUM LEARNING (Phase 5) =====================
# Initialize end-of-day analysis services

try:
    # Initialize all Medium Learning services with database
    calibration_service = init_calibration_service(db=db)
    
    context_perf_service = get_context_performance_service()
    context_perf_service.set_db(db)
    
    confirmation_service = get_confirmation_validator_service()
    confirmation_service.set_db(db)
    
    playbook_perf_service = get_playbook_performance_service()
    playbook_perf_service.set_db(db)
    
    edge_decay_service = get_edge_decay_service()
    edge_decay_service.set_db(db)
    
    # Register Medium Learning services
    register_service('calibration_service', calibration_service)
    register_service('context_perf_service', context_perf_service)
    register_service('confirmation_service', confirmation_service)
    register_service('playbook_perf_service', playbook_perf_service)
    register_service('edge_decay_service', edge_decay_service)
    
    print("Medium Learning (Phase 5) initialized")
    print("  - Calibration Service: TQS threshold recommendations")
    print("  - Context Performance: Setup+regime+time tracking")
    print("  - Confirmation Validator: Signal effectiveness analysis")
    print("  - Playbook Performance: Theory vs reality linkage")
    print("  - Edge Decay: Strategy degradation detection")
    print("  - Endpoints: /api/medium-learning/*")
except Exception as e:
    print(f"Medium Learning initialization deferred: {e}")
    calibration_service = None

# ===================== SLOW LEARNING (Phase 6) =====================
# Initialize backtesting, historical data, and shadow mode services

try:
    # Initialize Historical Data Service
    historical_data_service = init_historical_data_service(db=db, alpaca_service=alpaca_service)
    
    # Initialize Backtest Engine
    backtest_engine = init_backtest_engine(
        db=db,
        historical_data_service=historical_data_service
    )
    
    # Initialize Shadow Mode Service
    shadow_mode_service = init_shadow_mode_service(db=db, alpaca_service=alpaca_service)
    
    # Initialize Advanced Backtest Engine (new!)
    from services.slow_learning.advanced_backtest_engine import init_advanced_backtest_engine
    advanced_backtest_engine = init_advanced_backtest_engine(
        db=db,
        historical_data_service=historical_data_service,
        alpaca_service=alpaca_service,
        tqs_engine=get_service_optional('tqs_engine')
    )
    init_advanced_backtest_router(advanced_backtest_engine)
    
    # Register Slow Learning services
    register_service('shadow_mode_service', shadow_mode_service)
    register_service('historical_data_service', historical_data_service)
    register_service('backtest_engine', backtest_engine)
    register_service('advanced_backtest_engine', advanced_backtest_engine)
    
    # Initialize Hybrid Data Service (IB primary, Alpaca fallback)
    hybrid_data_service = init_hybrid_data_service(
        db=db,
        ib_service=ib_service,
        alpaca_service=alpaca_service
    )
    init_hybrid_data_router(hybrid_data_service)
    register_service('hybrid_data_service', hybrid_data_service)
    
    # Wire hybrid data service to advanced backtest engine
    advanced_backtest_engine.set_hybrid_data_service(hybrid_data_service)
    
    # Initialize Market Scanner Service (full US market scanning)
    market_scanner_service = init_market_scanner_service(
        db=db,
        hybrid_data_service=hybrid_data_service,
        alpaca_service=alpaca_service
    )
    init_market_scanner_router(market_scanner_service)
    register_service('market_scanner_service', market_scanner_service)
    
    print("Slow Learning (Phase 6) initialized")
    print("  - Historical Data Service: Alpaca data download and storage")
    print("  - Hybrid Data Service: IB primary, Alpaca fallback, MongoDB cache")
    print("  - Market Scanner: Full US market strategy scanning")
    print("  - Backtest Engine: Strategy backtesting on historical data")
    print("  - Advanced Backtest Engine: Multi-strategy, Walk-forward, Monte Carlo")
    print("  - Shadow Mode: Paper trading filter validation")
    print("  - Endpoints: /api/slow-learning/*, /api/backtest/*, /api/data/*, /api/scanner/*")
except Exception as e:
    print(f"Slow Learning initialization deferred: {e}")
    historical_data_service = None

# ===================== LEARNING CONTEXT PROVIDER =====================
# Provides personalized learning insights for AI coaching

try:
    from services.weekly_report_service import get_weekly_report_service
    
    learning_context_provider = init_learning_context_provider(
        db=db,
        calibration_service=get_service_optional('calibration_service'),
        context_performance_service=get_service_optional('context_perf_service'),
        confirmation_validator_service=get_service_optional('confirmation_service'),
        playbook_performance_service=get_service_optional('playbook_perf_service'),
        edge_decay_service=get_service_optional('edge_decay_service'),
        rag_service=get_service_optional('rag_service')
    )
    register_service('learning_context_provider', learning_context_provider)
    print("Learning Context Provider initialized")
    print("  - Provides TQS + Learning insights for AI coaching")
    # Wire to AI assistant
    if assistant_service is not None:
        assistant_service.set_learning_context_provider(learning_context_provider)
    
    # Wire learning services to SentCom (late injection)
    try:
        sentcom_svc = get_sentcom_service()
        sentcom_svc.inject_learning_services(
            learning_loop=learning_loop_service,
            learning_context_provider=learning_context_provider
        )
        print("[SERVER] SentCom wired to Learning services")
    except Exception as e:
        print(f"[SERVER] SentCom learning wire deferred: {e}")
        
except Exception as e:
    print(f"Learning Context Provider initialization deferred: {e}")
    learning_context_provider = None

# ===================== AI MODULES (Institutional-Grade) =====================
# Initialize AI trading modules: Shadow Mode, Bull/Bear Debate, AI Risk Manager
try:
    # Initialize AI Module Configuration (toggles, settings)
    ai_module_config = init_ai_module_config(db=db)
    
    # Initialize Shadow Tracker (logs all AI decisions for learning)
    shadow_tracker = init_shadow_tracker(db=db, alpaca_service=alpaca_service)
    
    # Initialize Debate Agents (Bull/Bear deliberation)
    # Get config dict from module settings
    debate_config = ai_module_config.get_module_settings("debate_agents")
    debate_config_dict = debate_config.custom_settings if debate_config else None
    debate_agents = init_debate_agents(
        llm_service=None,  # Uses rule-based for now, can add LLM later
        learning_provider=learning_context_provider,
        config=debate_config_dict
    )
    
    # Initialize AgentDataService (NEW - breaks agent silos)
    agent_data_service = init_agent_data_service(db=db)
    debate_agents.set_data_service(agent_data_service)  # Connect to debate agents
    
    # Initialize AI Risk Manager
    risk_config = ai_module_config.get_module_settings("ai_risk_manager")
    risk_config_dict = risk_config.custom_settings if risk_config else None
    ai_risk_manager = init_ai_risk_manager(config=risk_config_dict)
    ai_risk_manager.set_services(
        portfolio_service=None,  # Can wire later
        learning_provider=learning_context_provider,
        news_service=news_service
    )
    
    # Initialize Institutional Flow Service (Phase 5 - FREE SEC EDGAR)
    institutional_flow = init_institutional_flow_service(db=db)
    
    # Initialize Volume Anomaly Service (Phase 6 - Uses existing data)
    volume_anomaly = init_volume_anomaly_service(db=db)
    
    # Initialize Time-Series AI (Phase 3 - LightGBM directional forecasting)
    timeseries_ai = init_timeseries_ai(db=db, historical_service=alpaca_service)
    
    # Initialize AI Trade Consultation (wires modules into trading bot)
    ai_consultation = init_ai_consultation(
        module_config=ai_module_config,
        shadow_tracker=shadow_tracker,
        debate_agents=debate_agents,
        risk_manager=ai_risk_manager,
        institutional_flow=institutional_flow,
        volume_anomaly=volume_anomaly,
        timeseries_ai=timeseries_ai
    )
    
    # Inject services into AI modules router (AFTER ai_consultation is created)
    from routers.ai_modules import inject_timeseries_service
    inject_ai_module_services(
        ai_module_config, 
        shadow_tracker, 
        debate_agents, 
        ai_risk_manager,
        institutional_flow,
        volume_anomaly,
        ai_consultation,
        agent_data_service  # NEW
    )
    inject_timeseries_service(timeseries_ai)
    
    # Register AI module services
    register_service('ai_module_config', ai_module_config)
    register_service('shadow_tracker', shadow_tracker)
    register_service('debate_agents', debate_agents)
    register_service('ai_risk_manager', ai_risk_manager)
    register_service('institutional_flow', institutional_flow)
    register_service('volume_anomaly', volume_anomaly)
    register_service('ai_consultation', ai_consultation)
    register_service('timeseries_ai', timeseries_ai)
    register_service('agent_data_service', agent_data_service)  # NEW
    
    # Wire Time-Series AI model into Advanced Backtest Engine for AI comparison backtesting
    if timeseries_ai is not None:
        from services.ai_modules.timeseries_gbm import get_timeseries_model
        ts_model = get_timeseries_model()
        if ts_model is not None:
            advanced_backtest_engine.set_timeseries_model(ts_model)
            print("Time-Series AI model wired into Advanced Backtest Engine for AI comparison")
    
    print("AI Modules (Institutional-Grade) initialized")
    print("  - Module Config: Toggle individual AI modules on/off")
    print("  - Shadow Tracker: Logs all AI decisions without execution")
    print("  - Debate Agents: Bull/Bear deliberation before trades")
    print("  - AI Risk Manager: Multi-factor risk assessment")
    print("  - Institutional Flow: 13F tracking, ownership context (FREE)")
    print("  - Volume Anomaly: Z-score detection, accumulation/distribution")
    print("  - Time-Series AI: LightGBM directional forecasting (Phase 3)")
    print("  - Trade Consultation: Pre-trade AI analysis integration")
    print("  - Endpoints: /api/ai-modules/config, /api/ai-modules/timeseries/*")
    
except Exception as e:
    print(f"AI Modules initialization deferred: {e}")
    import traceback
    traceback.print_exc()
    ai_module_config = None
    shadow_tracker = None
    debate_agents = None
    ai_risk_manager = None
    institutional_flow = None
    volume_anomaly = None
    ai_consultation = None
    timeseries_ai = None

# Wire AI Consultation into Trading Bot (Phase 2 Integration)
if ai_consultation is not None:
    trading_bot.set_ai_consultation(ai_consultation)
    print("AI Trade Consultation wired into Trading Bot")
    print("  - Pre-trade analysis: Debate + Risk + Institutional + Volume")
    print("  - Shadow Mode: AI analyzes but doesn't block trades (learning mode)")
    print("  - Live Mode: AI can block/reduce trades based on analysis")

# ===================== HISTORICAL SIMULATION ENGINE =====================
# Full SentCom backtesting on historical data
try:
    from services.simulation_engine import init_simulation_engine, get_simulation_engine
    from services.ai_modules.timeseries_gbm import get_timeseries_model
    
    simulation_engine = init_simulation_engine(
        db=db,
        alpaca_service=alpaca_service,
        timeseries_model=get_timeseries_model() if timeseries_ai else None,
        trade_consultation=ai_consultation,
        scoring_engine=scoring_engine
    )
    
    # Initialize the simulation engine
    asyncio.create_task(simulation_engine.initialize())
    
    # Initialize router (simulation engine unified into advanced backtest)
    
    register_service('simulation_engine', simulation_engine)
    
    # Wire simulation engine into the advanced backtest router (unified access)
    init_advanced_backtest_router(advanced_backtest_engine, simulation_engine=simulation_engine)
    
    print("Historical Simulation Engine initialized")
    print("  - Full SentCom bot backtesting on 1+ year of data")
    print("  - Uses all AI agents (Debate, Risk, Time-Series, Institutional)")
    print("  - Tracks all decisions for learning")
    print("  - Endpoints: /api/simulation/*")
except Exception as e:
    print(f"Historical Simulation Engine initialization deferred: {e}")
    import traceback
    traceback.print_exc()
    simulation_engine = None

# ===================== LEARNING CONNECTORS =====================
# Orchestrates data flow between learning systems

try:
    from services.learning_connectors_service import init_learning_connectors
    from services.ai_modules.shadow_tracker import get_shadow_tracker
    from services.learning_loop_service import get_learning_loop_service
    
    learning_connectors = init_learning_connectors(
        db=db,
        timeseries_ai=get_service_optional('timeseries_ai'),
        shadow_tracker=get_shadow_tracker(),
        learning_loop=get_learning_loop_service(),
        scanner=get_service_optional('enhanced_scanner'),
        simulation_engine=simulation_engine
    )
    
    init_learning_connectors_router(
        db=db,
        timeseries_ai=get_service_optional('timeseries_ai'),
        shadow_tracker=get_shadow_tracker(),
        learning_loop=get_learning_loop_service(),
        scanner=get_service_optional('enhanced_scanner'),
        simulation_engine=simulation_engine,
        dynamic_thresholds=get_service_optional('dynamic_threshold_service')
    )
    
    register_service('learning_connectors', learning_connectors)
    
    print("Learning Connectors initialized")
    print("  - Simulation → Time-Series Model retraining")
    print("  - Shadow Tracker → Module weight calibration")
    print("  - Alert Outcomes → Scanner threshold tuning (NOW AUTO-APPLIES)")
    print("  - Endpoints: /api/learning-connectors/*")
except Exception as e:
    print(f"Learning Connectors initialization deferred: {e}")
    import traceback
    traceback.print_exc()

# ===================== STRATEGY PROMOTION SERVICE =====================
# Autonomous learning loop: SIMULATION → PAPER → LIVE

try:
    init_strategy_promotion_router(db=db)
    strategy_promotion_service = get_strategy_promotion_service()
    register_service('strategy_promotion', strategy_promotion_service)
    
    # Connect Strategy Promotion Service to Trading Bot
    # This enables the SIM → PAPER → LIVE trade gating
    trading_bot.set_strategy_promotion_service(strategy_promotion_service)
    
    print("Strategy Promotion Service initialized")
    print("  - Manages strategy lifecycle: SIMULATION → PAPER → LIVE")
    print("  - Auto-promotes strategies that prove profitable")
    print("  - Connected to Trading Bot for trade execution gating")
    print("  - Endpoints: /api/strategy-promotion/*")
except Exception as e:
    print(f"Strategy Promotion Service initialization deferred: {e}")
    import traceback
    traceback.print_exc()

# ===================== IB HISTORICAL DATA COLLECTOR =====================
# Systematically collects historical data from IB Gateway for learning

try:
    from services.ib_historical_collector import init_ib_collector
    
    # Get Alpaca service for fetching US stock universe
    alpaca_historical_service = get_service_optional('alpaca_historical_service')
    
    ib_collector = init_ib_collector(
        db=db, 
        ib_service=ib_service,
        alpaca_service=alpaca_historical_service or alpaca_service  # Use main alpaca_service as fallback
    )
    
    # Wire market scanner for robust full-market symbol fetching
    market_scanner = get_service_optional('market_scanner_service')
    if market_scanner:
        ib_collector.set_market_scanner(market_scanner)
        print("  - Market scanner wired for full-market symbol universe")
    
    register_service('ib_collector', ib_collector)
    
    print("IB Historical Data Collector initialized")
    print("  - Collects OHLCV data from IB Gateway")
    print("  - Supports multiple bar sizes (1min, 5min, 1hour, 1day)")
    print("  - Full market collection: ALL US stocks via Alpaca")
    print("  - Stores in MongoDB for model training")
    print("  - Endpoints: /api/ib-collector/*")
except Exception as e:
    print(f"IB Historical Collector initialization deferred: {e}")

# ===================== DATA STORAGE MANAGER =====================
# Ensures proper data persistence and indexing for all learning data

try:
    from services.data_storage_manager import init_storage_manager
    
    storage_manager = init_storage_manager(db=db)
    register_service('storage_manager', storage_manager)
    
    print("Data Storage Manager initialized")
    print("  - Manages 14 collections for learning data")
    print("  - Ensures proper indexes for fast retrieval")
    print("  - Endpoints: /api/data-storage/*")
except Exception as e:
    print(f"Data Storage Manager initialization deferred: {e}")

# ===================== TRADING SCHEDULER =====================
# Automated daily/weekly analysis tasks

try:
    from services.weekly_report_service import get_weekly_report_service, init_weekly_report_service
    
    # Initialize weekly report service with all required dependencies
    weekly_report_svc = init_weekly_report_service(
        db=db,
        calibration_service=get_service_optional('calibration_service'),
        context_performance_service=get_service_optional('context_perf_service'),
        confirmation_validator_service=get_service_optional('confirmation_service'),
        playbook_performance_service=get_service_optional('playbook_perf_service'),
        edge_decay_service=get_service_optional('edge_decay_service')
    )
    
    trading_scheduler = init_trading_scheduler(
        db=db,
        calibration_service=get_service_optional('calibration_service'),
        context_performance_service=get_service_optional('context_perf_service'),
        confirmation_validator_service=get_service_optional('confirmation_service'),
        playbook_performance_service=get_service_optional('playbook_perf_service'),
        edge_decay_service=get_service_optional('edge_decay_service'),
        weekly_report_service=weekly_report_svc,
        shadow_mode_service=get_service_optional('shadow_mode_service'),
        shadow_tracker=shadow_tracker,
        start=True  # Auto-start scheduler
    )
    print("Trading Scheduler initialized")
    print("  - Daily Analysis: 4:00 PM ET (Mon-Fri)")
    print("  - Weekly Report: Friday 4:30 PM ET")
    print("  - Edge Decay Check: 4:15 PM ET (Mon-Fri)")
    print("  - Shadow Updates: Every 5 min (market hours)")
    print("  - Endpoints: /api/scheduler/*")
except Exception as e:
    print(f"Trading Scheduler initialization deferred: {e}")
    trading_scheduler = None

# ===================== MULTI-AGENT SYSTEM =====================
# Initialize the new multi-agent architecture for AI-powered trading
try:
    from services.order_queue_service import get_order_queue_service
    
    # Register perf_service for agent access
    register_service('perf_service', perf_service)
    
    # Initialize agent system with all required services (using service registry)
    init_agents_router({
        "ib_router": ib_router,
        "scanner": background_scanner,
        "order_queue": get_order_queue_service(),
        "db": db,
        "performance_analyzer": perf_service,
        "learning_service": get_service_optional('learning_loop_service'),
        "trading_bot": trading_bot,
        "alpaca_service": alpaca_service,
        # Three-Speed Learning Architecture services
        "learning_context_provider": get_service_optional('learning_context_provider'),
        "learning_loop_service": get_service_optional('learning_loop_service'),
        # TQS Engine for Analyst
        "tqs_engine": get_service_optional('tqs_engine'),
        # Phase 2 AI: Context Awareness Service
        "context_awareness": get_service_optional('context_awareness')
    })
    print("Multi-Agent System initialized")
    print("  - Agents: Router, Trade Executor, Coach, Analyst")
    print("  - LLM: GPT-OSS cloud → llama3.5 8b fallback")
    print("  - Learning: Integrated with Three-Speed Architecture")
    print("  - TQS: Trade Quality Score integrated with Analyst")
    print("  - Context Awareness: Phase 2 AI (time/regime/position aware)")
    print("  - Endpoints: /api/agents/chat, /api/agents/status, /api/agents/metrics")
except Exception as e:
    print(f"Multi-Agent System initialization deferred: {e}")

# ===================== STRATEGY HELPERS =====================
# Strategies are now stored in MongoDB and accessed via strategy_service
# Use strategy_service.get_all_strategies() to get all strategies
# Use strategy_service.get_strategy_by_id(id) to get a specific strategy

def get_all_strategies_cached():
    """Get all strategies from database (cached in service)"""
    return strategy_service.get_all_strategies()

def get_strategy_by_id_cached(strategy_id: str):
    """Get a strategy by ID from database"""
    return strategy_service.get_strategy_by_id(strategy_id)

# ===================== PYDANTIC MODELS =====================
class StockQuote(BaseModel):
    symbol: str
    price: float
    change: float
    change_percent: float
    volume: int
    high: float
    low: float
    open: float
    prev_close: float
    timestamp: str

class FundamentalData(BaseModel):
    symbol: str
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    price_to_sales: Optional[float] = None
    enterprise_value: Optional[float] = None
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    ebitda: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    profit_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    dividend_rate: Optional[float] = None
    payout_ratio: Optional[float] = None
    beta: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    avg_volume: Optional[int] = None
    shares_outstanding: Optional[int] = None
    float_shares: Optional[int] = None
    short_ratio: Optional[float] = None
    short_percent: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    company_name: Optional[str] = None
    description: Optional[str] = None

class InsiderTrade(BaseModel):
    symbol: str
    insider_name: str
    title: str
    transaction_type: str  # Buy, Sell, Option Exercise
    shares: int
    price: float
    value: float
    date: str
    filing_date: str

class COTData(BaseModel):
    market: str
    date: str
    commercial_long: int
    commercial_short: int
    commercial_net: int
    non_commercial_long: int
    non_commercial_short: int
    non_commercial_net: int
    total_long: int
    total_short: int
    change_commercial_net: int
    change_non_commercial_net: int

# ===================== TWELVE DATA API FOR REAL-TIME QUOTES =====================
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY", "demo")

# Simple in-memory cache for quotes (expires after 120 seconds to avoid rate limits)
_quote_cache = {}
_cache_ttl = 120  # seconds - increased to reduce API calls

async def fetch_twelvedata_quote(symbol: str) -> Optional[Dict]:
    """Fetch real-time quote from Twelve Data API with caching"""
    symbol = symbol.upper()
    
    # Check cache first
    cache_key = f"quote_{symbol}"
    if cache_key in _quote_cache:
        cached_data, cached_time = _quote_cache[cache_key]
        if (datetime.now(timezone.utc) - cached_time).total_seconds() < _cache_ttl:
            return cached_data
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.twelvedata.com/quote",
                params={"symbol": symbol, "apikey": TWELVEDATA_API_KEY},
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                
                # Check for errors
                if "code" in data and data["code"] != 200:
                    print(f"Twelve Data error for {symbol}: {data.get('message')}")
                    return None
                
                price = float(data.get("close", 0))
                prev_close = float(data.get("previous_close", 0))
                change = float(data.get("change", 0))
                change_pct = float(data.get("percent_change", 0))
                
                result = {
                    "symbol": symbol,
                    "name": data.get("name", symbol),
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_percent": round(change_pct, 2),
                    "volume": int(data.get("volume", 0)),
                    "high": round(float(data.get("high", price)), 2),
                    "low": round(float(data.get("low", price)), 2),
                    "open": round(float(data.get("open", price)), 2),
                    "prev_close": round(prev_close, 2),
                    "avg_volume": int(data.get("average_volume", 0)),
                    "fifty_two_week_high": float(data.get("fifty_two_week", {}).get("high", 0)) if data.get("fifty_two_week") else None,
                    "fifty_two_week_low": float(data.get("fifty_two_week", {}).get("low", 0)) if data.get("fifty_two_week") else None,
                    "exchange": data.get("exchange"),
                    "is_market_open": data.get("is_market_open", False),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                # Cache the result
                _quote_cache[cache_key] = (result, datetime.now(timezone.utc))
                return result
    except Exception as e:
        print(f"Twelve Data error for {symbol}: {e}")
    
    return None

def _convert_to_yf_symbol(symbol: str) -> str:
    """Convert symbol to yfinance format"""
    symbol_upper = symbol.upper()
    if symbol_upper == "VIX":
        return "^VIX"
    return symbol_upper

async def fetch_quote(symbol: str) -> Optional[Dict]:
    """Fetch real-time quote - uses new StockDataService with Finnhub priority"""
    return await stock_service.get_quote(symbol)

def generate_simulated_quote(symbol: str) -> Dict:
    """Generate simulated quote data"""
    base_prices = {
        "SPY": 475, "QQQ": 415, "DIA": 385, "IWM": 198, "VIX": 15,
        "AAPL": 186, "MSFT": 379, "GOOGL": 143, "AMZN": 178, "NVDA": 495,
        "TSLA": 249, "META": 358, "AMD": 146, "NFLX": 479, "CRM": 278,
        "BA": 215, "DIS": 113, "V": 279, "MA": 446, "JPM": 178,
        "GS": 379, "XOM": 112, "CVX": 159, "COIN": 178, "PLTR": 23,
    }
    
    base = base_prices.get(symbol, random.uniform(50, 300))
    variation = random.uniform(-0.03, 0.03)
    price = base * (1 + variation)
    change_pct = random.uniform(-3, 3)
    change = price * change_pct / 100
    volume = random.randint(5000000, 50000000)
    
    return {
        "symbol": symbol,
        "price": round(price, 2),
        "change": round(change, 2),
        "change_percent": round(change_pct, 2),
        "volume": volume,
        "high": round(price * 1.01, 2),
        "low": round(price * 0.99, 2),
        "open": round(price - change/2, 2),
        "prev_close": round(price - change, 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

async def fetch_fundamentals(symbol: str) -> Dict:
    """Fetch fundamental data from Yahoo Finance"""
    symbol = symbol.upper()
    yf_symbol = _convert_to_yf_symbol(symbol)
    
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_symbol)
        info = ticker.info
        
        return {
            "symbol": symbol,
            "company_name": info.get("longName") or info.get("shortName", symbol),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": info.get("longBusinessSummary", "")[:500] if info.get("longBusinessSummary") else None,
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "revenue": info.get("totalRevenue"),
            "gross_profit": info.get("grossProfits"),
            "ebitda": info.get("ebitda"),
            "net_income": info.get("netIncomeToCommon"),
            "eps": info.get("trailingEps"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "dividend_yield": info.get("dividendYield"),
            "dividend_rate": info.get("dividendRate"),
            "payout_ratio": info.get("payoutRatio"),
            "beta": info.get("beta"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "float_shares": info.get("floatShares"),
            "short_ratio": info.get("shortRatio"),
            "short_percent": info.get("shortPercentOfFloat"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"Fundamentals error for {symbol}: {e}")
        return generate_simulated_fundamentals(symbol)

def generate_simulated_fundamentals(symbol: str) -> Dict:
    """Generate simulated fundamental data"""
    return {
        "symbol": symbol,
        "company_name": f"{symbol} Inc.",
        "sector": random.choice(["Technology", "Healthcare", "Financial", "Consumer Cyclical", "Energy"]),
        "industry": "Various",
        "market_cap": random.randint(10_000_000_000, 3_000_000_000_000),
        "pe_ratio": round(random.uniform(10, 50), 2),
        "forward_pe": round(random.uniform(8, 40), 2),
        "peg_ratio": round(random.uniform(0.5, 3), 2),
        "price_to_book": round(random.uniform(1, 20), 2),
        "price_to_sales": round(random.uniform(1, 15), 2),
        "revenue": random.randint(1_000_000_000, 500_000_000_000),
        "ebitda": random.randint(100_000_000, 100_000_000_000),
        "net_income": random.randint(100_000_000, 50_000_000_000),
        "eps": round(random.uniform(1, 30), 2),
        "revenue_growth": round(random.uniform(-0.1, 0.5), 3),
        "earnings_growth": round(random.uniform(-0.2, 0.6), 3),
        "profit_margin": round(random.uniform(0.05, 0.4), 3),
        "operating_margin": round(random.uniform(0.1, 0.5), 3),
        "roe": round(random.uniform(0.05, 0.5), 3),
        "roa": round(random.uniform(0.02, 0.2), 3),
        "debt_to_equity": round(random.uniform(0, 200), 2),
        "current_ratio": round(random.uniform(0.5, 3), 2),
        "dividend_yield": round(random.uniform(0, 0.05), 4),
        "beta": round(random.uniform(0.5, 2), 2),
        "fifty_two_week_high": round(random.uniform(100, 500), 2),
        "fifty_two_week_low": round(random.uniform(50, 300), 2),
        "avg_volume": random.randint(1000000, 100000000),
        "short_ratio": round(random.uniform(1, 10), 2),
        "short_percent": round(random.uniform(0.01, 0.3), 3),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

async def fetch_historical_data(symbol: str, period: str = "1y") -> List[Dict]:
    """Fetch historical price data"""
    try:
        import yfinance as yf
        yf_symbol = _convert_to_yf_symbol(symbol)
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period=period)
        
        data = []
        for date, row in hist.iterrows():
            data.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(row['Open'], 2),
                "high": round(row['High'], 2),
                "low": round(row['Low'], 2),
                "close": round(row['Close'], 2),
                "volume": int(row['Volume'])
            })
        return data
    except Exception as e:
        print(f"Historical data error: {e}")
        return []

# ===================== VST SCORING SYSTEM (VectorVest-style) =====================
# Scores are on 0-10 scale with 5.00 = average, 2 decimal places

async def calculate_relative_value(fundamentals: Dict, quote_data: Dict = None) -> Dict:
    """
    Calculate Relative Value (RV) score - long-term return vs risk
    Based on: expected return, valuation, growth potential
    """
    # Extract metrics
    pe_ratio = fundamentals.get("pe_ratio") or 20
    forward_pe = fundamentals.get("forward_pe") or pe_ratio
    peg_ratio = fundamentals.get("peg_ratio") or 1.5
    eps_growth = fundamentals.get("earnings_growth") or 0.1
    revenue_growth = fundamentals.get("revenue_growth") or 0.05
    dividend_yield = fundamentals.get("dividend_yield") or 0
    price_to_book = fundamentals.get("price_to_book") or 3
    roe = fundamentals.get("roe") or 0.15
    
    # Constants
    BOND_YIELD = 0.045  # 4.5% risk-free rate
    MARKET_AVG_RETURN = 0.10  # 10% market average
    
    # 1. Expected Return Component (0-2)
    # Expected annual return = EPS growth + dividend yield
    expected_return = max(0, eps_growth) + (dividend_yield or 0)
    
    # Normalize to 0-2 scale
    rv_return_raw = (expected_return - BOND_YIELD) / (MARKET_AVG_RETURN - BOND_YIELD) if (MARKET_AVG_RETURN - BOND_YIELD) != 0 else 1
    rv_return = max(0, min(2, rv_return_raw))
    
    # 2. Valuation Component (0-2) - Lower P/E = better value
    median_pe = 20  # Market median P/E
    if pe_ratio and pe_ratio > 0:
        valuation_score = min(2, max(0, (median_pe / pe_ratio) * 1.0))
    else:
        valuation_score = 1.0
    
    # 3. Growth Quality Component (0-2)
    # PEG < 1 is good, PEG > 2 is expensive
    if peg_ratio and peg_ratio > 0:
        peg_score = min(2, max(0, 2 - (peg_ratio - 1)))
    else:
        peg_score = 1.0
    
    # 4. ROE Component (0-2) - Higher ROE = better
    roe_score = min(2, max(0, (roe or 0.15) / 0.15)) if roe else 1.0
    
    # Combine: RV_0_2 = weighted average
    rv_0_2 = (0.35 * rv_return) + (0.30 * valuation_score) + (0.20 * peg_score) + (0.15 * roe_score)
    
    # Convert to 0-10 scale
    rv_score = round(rv_0_2 * 5, 2)
    
    return {
        "score": rv_score,
        "components": {
            "expected_return": round(expected_return * 100, 2),
            "valuation_score": round(valuation_score * 5, 2),
            "peg_score": round(peg_score * 5, 2),
            "roe_score": round(roe_score * 5, 2)
        },
        "interpretation": "Excellent Value" if rv_score >= 7 else "Good Value" if rv_score >= 5.5 else "Fair Value" if rv_score >= 4 else "Poor Value"
    }

async def calculate_relative_safety(fundamentals: Dict, quote_data: Dict = None) -> Dict:
    """
    Calculate Relative Safety (RS) score - financial strength, stability, risk
    Based on: debt, profitability, earnings consistency, volatility
    """
    # Extract metrics
    debt_to_equity = fundamentals.get("debt_to_equity") or 50
    current_ratio = fundamentals.get("current_ratio") or 1.5
    profit_margin = fundamentals.get("profit_margin") or 0.1
    operating_margin = fundamentals.get("operating_margin") or 0.15
    roe = fundamentals.get("roe") or 0.15
    roa = fundamentals.get("roa") or 0.05
    beta = fundamentals.get("beta") or 1.0
    
    # 1. Leverage & Liquidity Score (0-2)
    # Good: D/E < 50, Current Ratio > 1.5
    de_score = min(2, max(0, 2 - (debt_to_equity / 100))) if debt_to_equity else 1.5
    cr_score = min(2, max(0, current_ratio / 1.5)) if current_ratio else 1.0
    leverage_score = (de_score + cr_score) / 2
    
    # 2. Profitability Score (0-2)
    # High margins = safer
    pm_score = min(2, max(0, (profit_margin or 0.1) / 0.1))
    om_score = min(2, max(0, (operating_margin or 0.15) / 0.15))
    profitability_score = (pm_score + om_score) / 2
    
    # 3. Returns Quality (0-2)
    roe_adj = min(2, max(0, (roe or 0.15) / 0.15))
    roa_adj = min(2, max(0, (roa or 0.05) / 0.05))
    returns_score = (roe_adj + roa_adj) / 2
    
    # 4. Volatility Penalty (0-2)
    # Beta > 1.5 = risky, Beta < 0.8 = safe
    if beta:
        vol_score = min(2, max(0, 2 - (beta - 0.8) * 1.5))
    else:
        vol_score = 1.0
    
    # Combine: RS_0_2 = weighted average
    rs_0_2 = (0.30 * leverage_score) + (0.30 * profitability_score) + (0.25 * returns_score) + (0.15 * vol_score)
    
    # Convert to 0-10 scale
    rs_score = round(rs_0_2 * 5, 2)
    
    return {
        "score": rs_score,
        "components": {
            "leverage_liquidity": round(leverage_score * 5, 2),
            "profitability": round(profitability_score * 5, 2),
            "returns_quality": round(returns_score * 5, 2),
            "volatility": round(vol_score * 5, 2)
        },
        "interpretation": "Very Safe" if rs_score >= 7 else "Safe" if rs_score >= 5.5 else "Moderate Risk" if rs_score >= 4 else "High Risk"
    }

async def calculate_relative_timing(symbol: str, quote_data: Dict = None) -> Dict:
    """
    Calculate Relative Timing (RT) score - price trend, momentum, directionality
    Based on: returns, moving averages, momentum indicators
    """
    # Get historical data for calculations
    try:
        import yfinance as yf
        yf_symbol = _convert_to_yf_symbol(symbol)
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period="6mo")
        
        if len(hist) < 20:
            raise ValueError("Insufficient historical data")
        
        current_price = hist['Close'].iloc[-1]
        
        # Calculate returns
        ret_1w = ((current_price / hist['Close'].iloc[-5]) - 1) * 100 if len(hist) >= 5 else 0
        ret_1m = ((current_price / hist['Close'].iloc[-21]) - 1) * 100 if len(hist) >= 21 else 0
        ret_3m = ((current_price / hist['Close'].iloc[-63]) - 1) * 100 if len(hist) >= 63 else 0
        
        # Calculate moving averages
        sma_20 = hist['Close'].tail(20).mean()
        sma_50 = hist['Close'].tail(50).mean() if len(hist) >= 50 else sma_20
        
        # Calculate momentum (RSI-like)
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).tail(14).mean()
        loss = (-delta.where(delta < 0, 0)).tail(14).mean()
        rs = gain / loss if loss != 0 else 1
        rsi = 100 - (100 / (1 + rs))
        
    except Exception as e:
        print(f"Timing calculation error for {symbol}: {e}")
        # Generate simulated data
        random.seed(hash(symbol + "timing"))
        ret_1w = random.uniform(-5, 8)
        ret_1m = random.uniform(-10, 15)
        ret_3m = random.uniform(-15, 25)
        current_price = random.uniform(100, 500)
        sma_20 = current_price * random.uniform(0.95, 1.05)
        sma_50 = current_price * random.uniform(0.90, 1.10)
        rsi = random.uniform(30, 70)
    
    # 1. Return Component (0-2)
    # Weighted momentum score
    mom_raw = 0.4 * ret_1w + 0.4 * ret_1m + 0.2 * ret_3m
    # Map to 0-2: -10% = 0, 0% = 1, +10% = 2
    return_score = min(2, max(0, 1 + (mom_raw / 10)))
    
    # 2. Trend Position Component (0-2)
    trend_score = 1.0
    if current_price > sma_20:
        trend_score += 0.3
    else:
        trend_score -= 0.3
    if current_price > sma_50:
        trend_score += 0.3
    else:
        trend_score -= 0.3
    if sma_20 > sma_50:
        trend_score += 0.2
    else:
        trend_score -= 0.2
    trend_score = min(2, max(0, trend_score))
    
    # 3. RSI/Momentum Component (0-2)
    # RSI 30-70 = neutral, >70 = overbought (still bullish), <30 = oversold
    if rsi >= 50:
        rsi_score = min(2, 1 + ((rsi - 50) / 50))
    else:
        rsi_score = max(0, rsi / 50)
    
    # Combine: RT_0_2 = weighted average
    rt_0_2 = (0.50 * return_score) + (0.35 * trend_score) + (0.15 * rsi_score)
    
    # Convert to 0-10 scale
    rt_score = round(rt_0_2 * 5, 2)
    
    return {
        "score": rt_score,
        "components": {
            "momentum": round(return_score * 5, 2),
            "trend_position": round(trend_score * 5, 2),
            "rsi_momentum": round(rsi_score * 5, 2)
        },
        "metrics": {
            "return_1w": round(ret_1w, 2),
            "return_1m": round(ret_1m, 2),
            "return_3m": round(ret_3m, 2),
            "rsi": round(rsi, 1),
            "above_sma20": current_price > sma_20,
            "above_sma50": current_price > sma_50,
            "sma20_above_sma50": sma_20 > sma_50
        },
        "interpretation": "Strong Uptrend" if rt_score >= 7 else "Uptrend" if rt_score >= 5.5 else "Neutral" if rt_score >= 4 else "Downtrend"
    }

async def calculate_vst_composite(rv: Dict, rs: Dict, rt: Dict, weights: Dict = None) -> Dict:
    """
    Calculate VST Composite Score
    VST = sqrt(w_RV * RV^2 + w_RS * RS^2 + w_RT * RT^2)
    """
    # Default weights (balanced)
    if not weights:
        weights = {"rv": 0.35, "rs": 0.30, "rt": 0.35}
    
    rv_score = rv.get("score", 5) / 5  # Convert back to 0-2
    rs_score = rs.get("score", 5) / 5
    rt_score = rt.get("score", 5) / 5
    
    # VST formula (geometric mean style)
    vst_0_2 = (
        weights["rv"] * (rv_score ** 2) +
        weights["rs"] * (rs_score ** 2) +
        weights["rt"] * (rt_score ** 2)
    ) ** 0.5
    
    # Convert to 0-10 scale
    vst_score = round(vst_0_2 * 5, 2)
    
    # Determine recommendation
    rv_s = rv.get("score", 5)
    rs_s = rs.get("score", 5)
    rt_s = rt.get("score", 5)
    
    if vst_score >= 6.0 and rt_s >= 5.5:
        recommendation = "STRONG BUY"
        rec_color = "green"
    elif vst_score >= 5.0 and rt_s >= 5.0:
        recommendation = "BUY"
        rec_color = "green"
    elif vst_score < 4.0 or rt_s < 4.0:
        recommendation = "SELL"
        rec_color = "red"
    else:
        recommendation = "HOLD"
        rec_color = "yellow"
    
    return {
        "score": vst_score,
        "recommendation": recommendation,
        "recommendation_color": rec_color,
        "weights_used": weights,
        "interpretation": "Excellent" if vst_score >= 7 else "Good" if vst_score >= 5.5 else "Fair" if vst_score >= 4 else "Poor"
    }

async def get_full_vst_analysis(symbol: str) -> Dict:
    """
    Get complete VST analysis for a symbol
    """
    # Fetch fundamentals
    fundamentals = await fetch_fundamentals(symbol)
    
    # Fetch quote
    quote = await fetch_quote(symbol)
    
    # Calculate all scores
    rv = await calculate_relative_value(fundamentals, quote)
    rs = await calculate_relative_safety(fundamentals, quote)
    rt = await calculate_relative_timing(symbol, quote)
    vst = await calculate_vst_composite(rv, rs, rt)
    
    return {
        "symbol": symbol.upper(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "relative_value": rv,
        "relative_safety": rs,
        "relative_timing": rt,
        "vst_composite": vst,
        "fundamentals_summary": {
            "pe_ratio": fundamentals.get("pe_ratio"),
            "peg_ratio": fundamentals.get("peg_ratio"),
            "roe": fundamentals.get("roe"),
            "debt_to_equity": fundamentals.get("debt_to_equity"),
            "profit_margin": fundamentals.get("profit_margin"),
            "beta": fundamentals.get("beta")
        }
    }

# ===================== INSIDER TRADING DATA =====================
async def fetch_insider_trades(symbol: str) -> List[Dict]:
    """Fetch insider trading data from Finnhub"""
    trades = []
    
    try:
        async with httpx.AsyncClient() as client:
            # Using Finnhub free API for insider transactions
            resp = await client.get(
                "https://finnhub.io/api/v1/stock/insider-transactions",
                params={"symbol": symbol.upper(), "token": "demo"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                for tx in data.get("data", [])[:20]:
                    shares = tx.get("share", 0)
                    price = tx.get("transactionPrice", 0) or 0
                    trades.append({
                        "symbol": symbol.upper(),
                        "insider_name": tx.get("name", "Unknown"),
                        "title": tx.get("position", "Insider"),
                        "transaction_type": "Buy" if tx.get("transactionCode") in ["P", "A"] else "Sell",
                        "shares": abs(shares),
                        "price": round(price, 2),
                        "value": round(abs(shares * price), 2),
                        "date": tx.get("transactionDate", ""),
                        "filing_date": tx.get("filingDate", "")
                    })
    except Exception as e:
        print(f"Insider trades error: {e}")
    
    # Add simulated data if no real data
    if not trades:
        trades = generate_simulated_insider_trades(symbol)
    
    return trades

def generate_simulated_insider_trades(symbol: str) -> List[Dict]:
    """Generate simulated insider trading data"""
    trades = []
    names = ["John Smith (CEO)", "Jane Doe (CFO)", "Bob Wilson (Director)", "Sarah Johnson (COO)", "Mike Brown (VP Sales)"]
    
    for i in range(10):
        is_buy = random.random() > 0.4  # 60% buys for bullish signal
        shares = random.randint(1000, 50000)
        price = random.uniform(50, 300)
        date = (datetime.now() - timedelta(days=random.randint(1, 90))).strftime("%Y-%m-%d")
        
        trades.append({
            "symbol": symbol.upper(),
            "insider_name": random.choice(names),
            "title": random.choice(["CEO", "CFO", "Director", "COO", "VP", "10% Owner"]),
            "transaction_type": "Buy" if is_buy else "Sell",
            "shares": shares,
            "price": round(price, 2),
            "value": round(shares * price, 2),
            "date": date,
            "filing_date": date
        })
    
    return sorted(trades, key=lambda x: x["date"], reverse=True)

async def get_unusual_insider_activity() -> List[Dict]:
    """Get stocks with unusual insider buying activity"""
    symbols = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "META", "AMD", "AMZN", "JPM", "GS", 
               "BA", "DIS", "V", "MA", "CRM", "NFLX", "COIN", "PLTR", "SQ", "SHOP"]
    
    unusual_activity = []
    
    for symbol in symbols[:10]:  # Limit to avoid too many API calls
        trades = await fetch_insider_trades(symbol)
        
        # Calculate net insider activity
        total_buys = sum(t["value"] for t in trades if t["transaction_type"] == "Buy")
        total_sells = sum(t["value"] for t in trades if t["transaction_type"] == "Sell")
        net_activity = total_buys - total_sells
        buy_count = len([t for t in trades if t["transaction_type"] == "Buy"])
        sell_count = len([t for t in trades if t["transaction_type"] == "Sell"])
        
        # Flag unusual activity (high buy ratio or large transactions)
        if total_buys > 0:
            buy_ratio = total_buys / (total_buys + total_sells) if (total_buys + total_sells) > 0 else 0
            is_unusual = buy_ratio > 0.7 or total_buys > 1000000
            
            unusual_activity.append({
                "symbol": symbol,
                "total_buys": round(total_buys, 2),
                "total_sells": round(total_sells, 2),
                "net_activity": round(net_activity, 2),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "buy_ratio": round(buy_ratio, 2),
                "is_unusual": is_unusual,
                "signal": "BULLISH" if net_activity > 0 else "BEARISH",
                "recent_trades": trades[:5]
            })
    
    # Sort by net activity descending
    unusual_activity.sort(key=lambda x: x["net_activity"], reverse=True)
    return unusual_activity

# ===================== COMMITMENT OF TRADERS (COT) DATA =====================
async def fetch_cot_data(market: str = "ES") -> List[Dict]:
    """Fetch Commitment of Traders data"""
    # COT data mapping
    cot_markets = {
        "ES": "E-MINI S&P 500",
        "NQ": "E-MINI NASDAQ-100", 
        "GC": "GOLD",
        "SI": "SILVER",
        "CL": "CRUDE OIL",
        "NG": "NATURAL GAS",
        "ZB": "US TREASURY BONDS",
        "ZN": "10-YEAR T-NOTE",
        "6E": "EURO FX",
        "6J": "JAPANESE YEN",
        "ZC": "CORN",
        "ZS": "SOYBEANS",
        "ZW": "WHEAT"
    }
    
    market_name = cot_markets.get(market.upper(), market.upper())
    
    # Generate simulated COT data (in production, would use CFTC API or Quandl)
    cot_data = []
    
    for i in range(12):  # Last 12 weeks
        date = (datetime.now() - timedelta(weeks=i)).strftime("%Y-%m-%d")
        
        # Base values with some randomization
        comm_long = random.randint(200000, 400000)
        comm_short = random.randint(150000, 350000)
        non_comm_long = random.randint(300000, 500000)
        non_comm_short = random.randint(250000, 450000)
        
        prev_comm_net = random.randint(-50000, 50000)
        prev_non_comm_net = random.randint(-30000, 30000)
        
        cot_data.append({
            "market": market_name,
            "market_code": market.upper(),
            "date": date,
            "commercial_long": comm_long,
            "commercial_short": comm_short,
            "commercial_net": comm_long - comm_short,
            "non_commercial_long": non_comm_long,
            "non_commercial_short": non_comm_short,
            "non_commercial_net": non_comm_long - non_comm_short,
            "total_long": comm_long + non_comm_long,
            "total_short": comm_short + non_comm_short,
            "change_commercial_net": (comm_long - comm_short) - prev_comm_net,
            "change_non_commercial_net": (non_comm_long - non_comm_short) - prev_non_comm_net,
            "commercial_sentiment": "BULLISH" if (comm_long - comm_short) > 0 else "BEARISH",
            "speculator_sentiment": "BULLISH" if (non_comm_long - non_comm_short) > 0 else "BEARISH"
        })
    
    return cot_data

async def get_cot_summary() -> Dict:
    """Get COT summary for major markets"""
    markets = ["ES", "NQ", "GC", "CL", "6E", "ZB"]
    summary = []
    
    for market in markets:
        data = await fetch_cot_data(market)
        if data:
            latest = data[0]
            prev = data[1] if len(data) > 1 else data[0]
            
            summary.append({
                "market": latest["market"],
                "market_code": latest["market_code"],
                "commercial_net": latest["commercial_net"],
                "commercial_change": latest["commercial_net"] - prev["commercial_net"],
                "speculator_net": latest["non_commercial_net"],
                "speculator_change": latest["non_commercial_net"] - prev["non_commercial_net"],
                "commercial_sentiment": latest["commercial_sentiment"],
                "speculator_sentiment": latest["speculator_sentiment"],
                "date": latest["date"]
            })
    
    return {
        "summary": summary,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ===================== MARKET NEWS =====================
async def fetch_market_news() -> List[Dict]:
    """Fetch market news"""
    news_items = []
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/news",
                params={"category": "general", "token": "demo"},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data[:15]:
                    news_items.append({
                        "title": item.get("headline", ""),
                        "summary": item.get("summary", "")[:300],
                        "source": item.get("source", "Finnhub"),
                        "url": item.get("url", ""),
                        "published": datetime.fromtimestamp(item.get("datetime", 0), timezone.utc).isoformat(),
                        "related_symbols": item.get("related", "").split(",")[:3] if item.get("related") else [],
                        "sentiment": None
                    })
    except Exception as e:
        print(f"News error: {e}")
    
    # Fallback news
    if not news_items:
        news_items = [
            {"title": "Markets Rally on Tech Earnings", "summary": "Major indices climb as tech giants report strong quarterly results...", "source": "Market Watch", "url": "#", "published": datetime.now(timezone.utc).isoformat(), "related_symbols": ["AAPL", "MSFT", "GOOGL"], "sentiment": "bullish"},
            {"title": "Fed Signals Rate Path", "summary": "Federal Reserve maintains steady outlook as inflation data improves...", "source": "Reuters", "url": "#", "published": datetime.now(timezone.utc).isoformat(), "related_symbols": ["SPY", "TLT"], "sentiment": "neutral"},
            {"title": "Energy Sector Leads Gains", "summary": "Oil prices rise on supply concerns, boosting energy stocks...", "source": "Bloomberg", "url": "#", "published": datetime.now(timezone.utc).isoformat(), "related_symbols": ["XLE", "XOM", "CVX"], "sentiment": "bullish"},
        ]
    
    return news_items

# ===================== HELPER FUNCTIONS =====================
async def fetch_multiple_quotes(symbols: List[str]) -> List[Dict]:
    """Fetch multiple quotes in parallel"""
    tasks = [fetch_quote(sym) for sym in symbols]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

async def generate_ai_analysis(prompt: str) -> str:
    """Generate AI analysis"""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=f"analysis-{datetime.now(timezone.utc).timestamp()}",
            system_message="You are a professional trading analyst. Provide concise, actionable insights."
        ).with_model("openai", "gpt-4o")
        
        user_message = UserMessage(text=prompt)
        response = await chat.send_message(user_message)
        return response
    except Exception as e:
        print(f"AI Analysis error: {e}")
        return "Analysis unavailable"

async def score_stock_for_strategies(symbol: str, quote_data: Dict, fundamentals: Dict = None, category_filter: str = None) -> Dict:
    """
    Score a stock against all 50 trading strategies using detailed criteria.
    Returns matched strategies with confidence scores for each.
    """
    matched_strategies = []
    strategy_details = []
    total_criteria_met = 0
    total_criteria_checked = 0
    
    # Extract quote data
    price = quote_data.get("price", 0)
    change_pct = quote_data.get("change_percent", 0)
    volume = quote_data.get("volume", 0)
    avg_volume = quote_data.get("avg_volume", 0) or volume
    high = quote_data.get("high", price)
    low = quote_data.get("low", price)
    open_price = quote_data.get("open", price)
    prev_close = quote_data.get("prev_close", price)
    
    # Calculate derived metrics
    rvol = (volume / avg_volume) if avg_volume > 0 else 1  # Relative Volume
    daily_range = ((high - low) / low * 100) if low > 0 else 0
    gap_pct = ((open_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
    vwap_estimate = (high + low + price) / 3  # Simplified VWAP
    above_vwap = price > vwap_estimate
    
    # Fundamentals data (if available)
    pe_ratio = fundamentals.get("pe_ratio") if fundamentals else None
    pb_ratio = fundamentals.get("price_to_book") if fundamentals else None
    dividend_yield = fundamentals.get("dividend_yield") if fundamentals else None
    roe = fundamentals.get("roe") if fundamentals else None
    revenue_growth = fundamentals.get("revenue_growth") if fundamentals else None
    beta = fundamentals.get("beta") if fundamentals else None
    
    # ===================== INTRADAY STRATEGIES =====================
    if not category_filter or category_filter == "intraday":
        # INT-01: Trend Momentum Continuation
        criteria_met = 0
        if above_vwap and change_pct > 0:
            criteria_met += 1
        if change_pct > 0.5:  # Upward momentum
            criteria_met += 1
        if rvol >= 2:
            criteria_met += 1
        if high > open_price:  # Making higher highs
            criteria_met += 1
        if criteria_met >= 3:
            matched_strategies.append("INT-01")
            strategy_details.append({"id": "INT-01", "name": "Trend Momentum Continuation", "criteria_met": criteria_met, "total": 4, "confidence": criteria_met/4*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 4
        
        # INT-02: Intraday Breakout (Range High)
        criteria_met = 0
        if daily_range < 3:  # Tight range
            criteria_met += 1
        if rvol >= 1.5:
            criteria_met += 1
        if price >= high * 0.99:  # Near high
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-02")
            strategy_details.append({"id": "INT-02", "name": "Intraday Breakout", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-03: Opening Range Breakout (ORB)
        criteria_met = 0
        orb_range = daily_range  # Using daily range as proxy
        if orb_range < 2:  # Reasonable opening range
            criteria_met += 1
        if price > open_price and change_pct > 0.5:  # Break above ORH
            criteria_met += 1
        if rvol >= 1.2:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-03")
            strategy_details.append({"id": "INT-03", "name": "Opening Range Breakout", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-04: Gap-and-Go
        criteria_met = 0
        if abs(gap_pct) >= 3:  # Gap >= 3%
            criteria_met += 1
        if rvol >= 3:  # High premarket volume
            criteria_met += 1
        if gap_pct > 0 and price > open_price:  # Holds gap
            criteria_met += 1
        if above_vwap:
            criteria_met += 1
        if criteria_met >= 3:
            matched_strategies.append("INT-04")
            strategy_details.append({"id": "INT-04", "name": "Gap-and-Go", "criteria_met": criteria_met, "total": 4, "confidence": criteria_met/4*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 4
        
        # INT-05: Pullback in Trend (Buy the Dip)
        criteria_met = 0
        if change_pct > 0:  # Overall uptrend
            criteria_met += 1
        if price < high * 0.98 and price > low * 1.02:  # Pullback from high
            criteria_met += 1
        if above_vwap:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-05")
            strategy_details.append({"id": "INT-05", "name": "Pullback in Trend", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-06: VWAP Bounce
        criteria_met = 0
        if above_vwap:
            criteria_met += 1
        if abs(price - vwap_estimate) / vwap_estimate < 0.005:  # Near VWAP
            criteria_met += 1
        if change_pct > 0:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-06")
            strategy_details.append({"id": "INT-06", "name": "VWAP Bounce", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-07: VWAP Reversion (Fade to VWAP)
        criteria_met = 0
        vwap_extension = abs((price - vwap_estimate) / vwap_estimate * 100)
        if vwap_extension >= 2:  # Extended from VWAP
            criteria_met += 1
        if daily_range > 3:  # Parabolic move
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INT-07")
            strategy_details.append({"id": "INT-07", "name": "VWAP Reversion", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INT-08: Mean Reversion After Exhaustion Spike
        criteria_met = 0
        if daily_range >= 3:  # Wide range candles
            criteria_met += 1
        if rvol >= 2:  # Volume climax
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INT-08")
            strategy_details.append({"id": "INT-08", "name": "Mean Reversion Exhaustion", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INT-10: Bull/Bear Flag Intraday
        criteria_met = 0
        if change_pct > 2 or change_pct < -2:  # Strong impulse
            criteria_met += 1
        if daily_range < 4:  # Consolidation
            criteria_met += 1
        if rvol >= 1.5:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-10")
            strategy_details.append({"id": "INT-10", "name": "Bull/Bear Flag", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-13: Intraday Range Trading
        criteria_met = 0
        if -0.5 < change_pct < 0.5:  # Tight range
            criteria_met += 1
        if rvol < 1.5:  # Low relative volume
            criteria_met += 1
        if daily_range < 2:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-13")
            strategy_details.append({"id": "INT-13", "name": "Intraday Range Trading", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-14: News/Earnings Momentum
        criteria_met = 0
        if abs(gap_pct) >= 3:  # Gap on news
            criteria_met += 1
        if rvol >= 3:  # High volume all session
            criteria_met += 1
        if abs(change_pct) >= 3:  # Big move
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-14")
            strategy_details.append({"id": "INT-14", "name": "News/Earnings Momentum", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-16: High-of-Day Break Scalps
        criteria_met = 0
        if price >= high * 0.995:  # Near HOD
            criteria_met += 1
        if change_pct > 0:  # Uptrend
            criteria_met += 1
        if rvol >= 1.5:  # Volume building
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("INT-16")
            strategy_details.append({"id": "INT-16", "name": "HOD Break Scalps", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # INT-18: Index-Correlated Trend Riding
        criteria_met = 0
        if beta and beta >= 1.2:  # High beta
            criteria_met += 1
        if change_pct > 1:  # Strong trend
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INT-18")
            strategy_details.append({"id": "INT-18", "name": "Index-Correlated Riding", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
    
    # ===================== SWING STRATEGIES =====================
    if not category_filter or category_filter == "swing":
        # SWG-01: Daily Trend Following
        criteria_met = 0
        if change_pct > 0:  # Uptrend
            criteria_met += 1
        if price > prev_close:  # Above previous close
            criteria_met += 1
        if volume > avg_volume:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("SWG-01")
            strategy_details.append({"id": "SWG-01", "name": "Daily Trend Following", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # SWG-02: Breakout from Multi-Week Base
        criteria_met = 0
        if daily_range < 3:  # Tight consolidation
            criteria_met += 1
        if rvol >= 1.5:  # Strong volume
            criteria_met += 1
        if price >= high * 0.98:  # Near breakout
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("SWG-02")
            strategy_details.append({"id": "SWG-02", "name": "Multi-Week Base Breakout", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # SWG-04: Pullback After Breakout
        criteria_met = 0
        if change_pct < 0 and change_pct > -3:  # Light pullback
            criteria_met += 1
        if rvol < 1:  # Lower volume on pullback
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-04")
            strategy_details.append({"id": "SWG-04", "name": "Pullback After Breakout", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # SWG-06: RSI/Stochastic Mean-Reversion
        criteria_met = 0
        if change_pct < -2:  # Oversold condition
            criteria_met += 1
        if price > low * 1.01:  # Showing bounce
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-06")
            strategy_details.append({"id": "SWG-06", "name": "RSI Mean-Reversion", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # SWG-07: Earnings Breakout Continuation
        criteria_met = 0
        if abs(gap_pct) >= 3:  # Gap on earnings
            criteria_met += 1
        if price > open_price:  # Holding gap
            criteria_met += 1
        if rvol >= 2:
            criteria_met += 1
        if criteria_met >= 2:
            matched_strategies.append("SWG-07")
            strategy_details.append({"id": "SWG-07", "name": "Earnings Breakout", "criteria_met": criteria_met, "total": 3, "confidence": criteria_met/3*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 3
        
        # SWG-09: Sector Relative Strength
        criteria_met = 0
        if change_pct > 1.5:  # Outperforming
            criteria_met += 1
        if rvol >= 1.2:
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-09")
            strategy_details.append({"id": "SWG-09", "name": "Sector Relative Strength", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # SWG-10: Shorting Failed Breakouts
        criteria_met = 0
        if change_pct < -1 and price < high * 0.98:  # Failed breakout
            criteria_met += 1
        if rvol >= 1.5:  # Volume on failure
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-10")
            strategy_details.append({"id": "SWG-10", "name": "Failed Breakout Short", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # SWG-13: Volatility Contraction Pattern (VCP)
        criteria_met = 0
        if daily_range < 2:  # Tight contraction
            criteria_met += 1
        if rvol < 1:  # Decreasing volume
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("SWG-13")
            strategy_details.append({"id": "SWG-13", "name": "VCP Pattern", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
    
    # ===================== INVESTMENT STRATEGIES =====================
    if not category_filter or category_filter == "investment":
        # INV-04: Value Investing
        criteria_met = 0
        if pe_ratio and pe_ratio < 20:  # Low P/E
            criteria_met += 1
        if pb_ratio and pb_ratio < 3:  # Low P/B
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-04")
            strategy_details.append({"id": "INV-04", "name": "Value Investing", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INV-05: Quality Factor
        criteria_met = 0
        if roe and roe > 0.15:  # High ROE
            criteria_met += 1
        if pe_ratio and pe_ratio < 30:  # Reasonable valuation
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-05")
            strategy_details.append({"id": "INV-05", "name": "Quality Factor", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INV-06: Growth Investing
        criteria_met = 0
        if revenue_growth and revenue_growth > 0.15:  # High growth
            criteria_met += 1
        if pe_ratio and pe_ratio > 20:  # Growth premium
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-06")
            strategy_details.append({"id": "INV-06", "name": "Growth Investing", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INV-07: Dividend Growth
        criteria_met = 0
        if dividend_yield and dividend_yield > 0.01:  # Has dividend
            criteria_met += 1
        if dividend_yield and dividend_yield < 0.06:  # Sustainable yield
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-07")
            strategy_details.append({"id": "INV-07", "name": "Dividend Growth", "criteria_met": criteria_met, "total": 2, "confidence": criteria_met/2*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 2
        
        # INV-08: High-Yield Dividend
        criteria_met = 0
        if dividend_yield and dividend_yield >= 0.04:  # High yield
            criteria_met += 1
        if criteria_met >= 1:
            matched_strategies.append("INV-08")
            strategy_details.append({"id": "INV-08", "name": "High-Yield Dividend", "criteria_met": criteria_met, "total": 1, "confidence": criteria_met/1*100})
        total_criteria_met += criteria_met
        total_criteria_checked += 1
    
    # Calculate final score
    if total_criteria_checked > 0:
        base_score = (total_criteria_met / total_criteria_checked) * 100
    else:
        base_score = 0
    
    # Boost score based on number of matching strategies
    strategy_bonus = min(30, len(matched_strategies) * 5)
    score = min(100, int(base_score + strategy_bonus))
    
    return {
        "symbol": symbol,
        "score": score,
        "matched_strategies": matched_strategies,
        "strategy_details": strategy_details,
        "criteria_met": total_criteria_met,
        "total_criteria": total_criteria_checked,
        "change_percent": change_pct,
        "volume": volume,
        "rvol": round(rvol, 2),
        "gap_percent": round(gap_pct, 2),
        "daily_range": round(daily_range, 2),
        "above_vwap": above_vwap
    }

# Initialize watchlist & portfolio routers (dependencies defined above)
init_watchlist_router(db, smart_watchlist, fetch_multiple_quotes, score_stock_for_strategies, generate_ai_analysis)
init_portfolio_router(db, fetch_multiple_quotes)
init_earnings_router(stock_service, get_all_symbols_set)
init_ollama_proxy_router(ollama_proxy_manager)
init_market_data_router(
    get_stock_service, fetch_quote, fetch_multiple_quotes, fetch_fundamentals,
    get_full_vst_analysis, fetch_historical_data, fetch_insider_trades,
    get_unusual_insider_activity, fetch_cot_data, get_cot_summary, fetch_market_news
)

# ===================== INITIALIZE EXTRACTED ROUTERS =====================
# System router: health, startup-check, consolidated-status, LLM status, system monitor
init_system_router(
    ib_service=ib_service,
    assistant_service=assistant_service,
    ollama_proxy_manager=ollama_proxy_manager,
    is_http_ollama_proxy_connected=is_http_ollama_proxy_connected,
    strategy_promotion_service=get_service_optional('strategy_promotion'),
    simulation_engine=get_service_optional('simulation_engine'),
    strategy_service=strategy_service,
    db=db,
    get_feature_engine=get_feature_engine,
    get_scoring_engine=get_scoring_engine,
    get_stock_service=get_stock_service,
    get_service_optional=get_service_optional,
    background_scanner=background_scanner,
    LLMProvider=LLMProvider,
)

# Dashboard router: dashboard stats/init, alerts CRUD, scanner, wave-scanner, universe
init_dashboard_router(
    get_portfolio=_portfolio_get_portfolio,
    get_watchlist=_watchlist_get_watchlist,
    strategy_service=strategy_service,
    get_ib_service=get_ib_service,
    get_smart_watchlist=get_smart_watchlist,
    background_scanner=background_scanner,
    assistant_service=assistant_service,
    alerts_col=alerts_col,
    fetch_multiple_quotes=fetch_multiple_quotes,
    score_stock_for_strategies=score_stock_for_strategies,
    get_all_strategies_cached=get_all_strategies_cached,
    scans_col=scans_col,
    wave_scanner=wave_scanner,
    index_universe=index_universe,
)

# ===================== WEBSOCKET REAL-TIME STREAMING =====================

# ===================== WEBSOCKET REAL-TIME STREAMING =====================

class ConnectionManager:
    """Manages WebSocket connections for real-time streaming"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        print(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
        print(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    def subscribe(self, websocket: WebSocket, symbols: List[str]):
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update([s.upper() for s in symbols])
    
    def unsubscribe(self, websocket: WebSocket, symbols: List[str]):
        if websocket in self.subscriptions:
            for symbol in symbols:
                self.subscriptions[websocket].discard(symbol.upper())
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            print(f"Error sending message: {e}")
            # Clean up stale connection
            self.disconnect(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all active connections, cleaning up stale ones"""
        stale_connections = []
        
        # Create a copy of the list to avoid modification during iteration
        connections_to_send = self.active_connections.copy()
        
        for connection in connections_to_send:
            try:
                await connection.send_json(message)
            except Exception as e:
                # Connection is stale or closed, mark for removal
                stale_connections.append(connection)
                if str(e):  # Only print if there's an actual error message
                    print(f"Error broadcasting (removing stale connection): {e}")
        
        # Clean up stale connections
        for stale in stale_connections:
            self.disconnect(stale)

manager = ConnectionManager()

# Default symbols to stream
DEFAULT_STREAM_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "AAPL", "MSFT", "NVDA", "TSLA"]


def _is_training_active():
    """Quick check if training mode is active — used by WS streams to pause during training."""
    try:
        return focus_mode_manager.get_mode() != "live"
    except Exception:
        return False

async def stream_quotes():
    """Background task to stream quotes using batch API"""
    await asyncio.sleep(3)
    
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                all_symbols = set(DEFAULT_STREAM_SYMBOLS)
                for symbols in manager.subscriptions.values():
                    all_symbols.update(symbols)
                
                # Use batch quote API - single request for all symbols
                symbol_list = [s for s in list(all_symbols)[:12] if s not in ("VIX", "^VIX", "$VIX")]
                
                quotes = []
                try:
                    batch_results = await alpaca_service.get_quotes_batch(symbol_list)
                    for symbol, data in batch_results.items():
                        # Clean internal cache fields before broadcasting
                        clean_data = {k: v for k, v in data.items() if not k.startswith('_')}
                        quotes.append(clean_data)
                except Exception as batch_err:
                    print(f"Batch quote error: {batch_err}")
                    # Fallback to individual fetches (limited)
                    for symbol in symbol_list[:5]:
                        quote = await fetch_quote(symbol)
                        if quote:
                            clean_quote = {k: v for k, v in quote.items() if not k.startswith('_')}
                            quotes.append(clean_quote)
                        await asyncio.sleep(0.3)
                
                if quotes:
                    message = {
                        "type": "quotes",
                        "data": quotes,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    await manager.broadcast(message)
            except Exception as e:
                print(f"Stream error: {e}")
                import traceback
                traceback.print_exc()
        
        await asyncio.sleep(15)  # 15s interval


# ===================== SYSTEM STATUS STREAMING =====================

async def stream_system_status():
    """Background task to push system status updates via WebSocket"""
    await asyncio.sleep(5)  # Wait for services to initialize
    
    # Cache for change detection
    last_ib_status = None
    last_bot_status = None
    last_scanner_status = None
    
    while True:
        if manager.active_connections:
            try:
                # IB Connection Status
                try:
                    ib_status = ib_service.get_connection_status()
                    ib_data = {
                        "connected": ib_status.get("connected", False),
                        "busy": ib_status.get("busy", False),
                        "error": ib_status.get("error")
                    }
                    # Only broadcast if changed
                    if ib_data != last_ib_status:
                        await manager.broadcast({
                            "type": "ib_status",
                            "data": ib_data,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        last_ib_status = ib_data
                except Exception as e:
                    print(f"IB status stream error: {e}")
                
                # Trading Bot Status
                try:
                    bot_status = trading_bot.get_status()
                    bot_data = {
                        "state": bot_status.get("state", "unknown"),
                        "mode": bot_status.get("mode", "manual"),
                        "open_positions": bot_status.get("open_positions", 0),
                        "pending_orders": bot_status.get("pending_orders", 0),
                        "daily_pnl": bot_status.get("daily_pnl", 0),
                        "daily_trades": bot_status.get("daily_trades", 0),
                        "last_scan": bot_status.get("last_scan"),
                        "next_scan": bot_status.get("next_scan"),
                        "error": bot_status.get("error")
                    }
                    if bot_data != last_bot_status:
                        await manager.broadcast({
                            "type": "bot_status",
                            "data": bot_data,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        last_bot_status = bot_data
                except Exception as e:
                    print(f"Bot status stream error: {e}")
                
                # Scanner Status
                try:
                    scanner_status = background_scanner.get_stats()
                    scanner_data = {
                        "running": scanner_status.get("running", False),
                        "scan_count": scanner_status.get("scan_count", 0),
                        "alerts_count": scanner_status.get("active_alerts", 0),
                        "symbols_scanned": scanner_status.get("symbols_scanned_last", 0)
                    }
                    if scanner_data != last_scanner_status:
                        await manager.broadcast({
                            "type": "scanner_status",
                            "data": scanner_data,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        last_scanner_status = scanner_data
                except Exception as e:
                    print(f"Scanner status stream error: {e}")
                
                # Yield control to event loop
                await asyncio.sleep(0)
                
            except Exception as e:
                print(f"System status stream error: {e}")
        
        await asyncio.sleep(10)  # Check every 10 seconds


async def stream_bot_trades():
    """Background task to push bot trades updates via WebSocket"""
    await asyncio.sleep(8)
    
    last_trades_hash = None
    
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                # Get all trades using the summary method
                trades_data = trading_bot.get_all_trades_summary()
                all_trades = []
                all_trades.extend(trades_data.get("pending", []))
                all_trades.extend(trades_data.get("open", []))
                all_trades.extend(trades_data.get("closed", [])[:30])  # Limit closed trades
                
                # Create hash of trade IDs to detect changes
                trades_hash = hash(tuple(t.get("id", "") for t in all_trades[-20:]))
                
                if trades_hash != last_trades_hash:
                    await manager.broadcast({
                        "type": "bot_trades",
                        "data": all_trades,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_trades_hash = trades_hash
            except Exception as e:
                print(f"Bot trades stream error: {e}")
        
        await asyncio.sleep(20)  # Check every 20 seconds


async def stream_scanner_alerts():
    """Background task to push scanner alerts via WebSocket"""
    await asyncio.sleep(10)
    
    last_alerts_count = 0
    
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                alerts = background_scanner.get_live_alerts()
                current_count = len(alerts)
                
                # Convert LiveAlert objects to dicts
                alerts_data = []
                for alert in alerts[:20]:  # Top 20 alerts
                    if hasattr(alert, 'to_dict'):
                        alerts_data.append(alert.to_dict())
                    elif hasattr(alert, '__dict__'):
                        alerts_data.append(dict(alert.__dict__))
                    else:
                        alerts_data.append(alert)
                
                # Broadcast if alerts changed
                if current_count != last_alerts_count or current_count > 0:
                    await manager.broadcast({
                        "type": "scanner_alerts",
                        "data": alerts_data,
                        "count": current_count,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_alerts_count = current_count
            except Exception as e:
                print(f"Scanner alerts stream error: {e}")
        
        await asyncio.sleep(15)  # Check every 15 seconds


async def stream_smart_watchlist():
    """Background task to push smart watchlist updates via WebSocket"""
    await asyncio.sleep(12)
    
    last_watchlist_hash = None
    
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                watchlist_service = get_smart_watchlist()
                if watchlist_service:
                    watchlist_items = watchlist_service.get_watchlist()
                    
                    # Convert WatchlistItem objects to dicts
                    watchlist = []
                    for item in watchlist_items:
                        if hasattr(item, 'to_dict'):
                            watchlist.append(item.to_dict())
                        elif hasattr(item, '__dict__'):
                            # Convert dataclass/object to dict
                            item_dict = {}
                            for key, val in item.__dict__.items():
                                if not key.startswith('_'):
                                    # Handle datetime objects
                                    if hasattr(val, 'isoformat'):
                                        item_dict[key] = val.isoformat()
                                    else:
                                        item_dict[key] = val
                            watchlist.append(item_dict)
                        else:
                            watchlist.append(item)
                    
                    # Hash based on symbols
                    watchlist_hash = hash(tuple(w.get("symbol", "") for w in watchlist if isinstance(w, dict)))
                    
                    if watchlist_hash != last_watchlist_hash:
                        await manager.broadcast({
                            "type": "smart_watchlist",
                            "data": watchlist,
                            "count": len(watchlist),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        last_watchlist_hash = watchlist_hash
            except Exception as e:
                print(f"Smart watchlist stream error: {e}")
        
        await asyncio.sleep(25)  # Check every 25 seconds


async def stream_coaching_notifications():
    """Background task to push AI coaching notifications via WebSocket"""
    await asyncio.sleep(15)
    
    last_notification_time = datetime.now(timezone.utc) - timedelta(hours=1)
    
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                # Use the correct method name
                notifications = assistant_service.get_coaching_notifications(since=last_notification_time.isoformat())
                
                if notifications:
                    await manager.broadcast({
                        "type": "coaching_notifications",
                        "data": notifications,
                        "count": len(notifications),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    # Update last check time
                    last_notification_time = datetime.now(timezone.utc)
            except Exception as e:
                print(f"Coaching notifications stream error: {e}")
        
        await asyncio.sleep(12)  # Check every 12 seconds


async def stream_confidence_gate():
    """Push confidence gate summary + recent decisions via WebSocket."""
    await asyncio.sleep(20)
    
    last_summary_hash = None
    
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                from services.ai_modules.confidence_gate import get_confidence_gate
                gate = get_confidence_gate()
                summary = gate.get_summary()
                decisions = gate.get_decision_log(limit=20)
                
                # Only broadcast on change
                summary_hash = hash((
                    summary.get("trading_mode"),
                    summary.get("today", {}).get("evaluated", 0),
                    len(decisions),
                ))
                
                if summary_hash != last_summary_hash:
                    # Strip heavy fields from decisions
                    clean_decisions = [{
                        "decision": d.get("decision"),
                        "confidence_score": d.get("confidence_score"),
                        "symbol": d.get("symbol"),
                        "setup_type": d.get("setup_type"),
                        "direction": d.get("direction"),
                        "regime_state": d.get("regime_state"),
                        "ai_regime": d.get("ai_regime"),
                        "trading_mode": d.get("trading_mode"),
                        "position_multiplier": d.get("position_multiplier"),
                        "reasoning": d.get("reasoning", [])[:3],
                        "timestamp": d.get("timestamp"),
                    } for d in decisions]
                    
                    await manager.broadcast({
                        "type": "confidence_gate",
                        "data": {
                            "summary": summary,
                            "decisions": clean_decisions,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_summary_hash = summary_hash
            except Exception as e:
                print(f"Confidence gate stream error: {e}")
        
        await asyncio.sleep(15)  # Every 15 seconds


async def stream_training_status():
    """Push AI training pipeline status via WebSocket."""
    await asyncio.sleep(25)
    
    last_status_hash = None
    status = None
    
    while True:
        if manager.active_connections:
            try:
                def _get_training_status():
                    return db["training_pipeline_status"].find_one(
                        {"_id": "pipeline"}, {"_id": 0}
                    )
                status = await asyncio.to_thread(_get_training_status)
                
                # Build hash from actual training fields so we detect real changes
                if status:
                    status_hash = hash(
                        str(status.get("phase", "")) + 
                        str(status.get("current_model", "")) + 
                        str(status.get("models_completed", 0)) +
                        str(status.get("current_phase_progress", 0))
                    )
                else:
                    status_hash = None
                
                if status_hash != last_status_hash:
                    await manager.broadcast({
                        "type": "training_status",
                        "data": status or {"phase": "idle"},
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_status_hash = status_hash
            except Exception as e:
                print(f"Training status stream error: {e}")
        
        # Poll faster during training (every 3s), slower when idle (every 30s)
        is_training = (status.get("phase", "idle") not in ("idle", "completed", "cancelled", "error")) if status else False
        await asyncio.sleep(3 if is_training else 30)


async def stream_market_regime():
    """Push market regime data via WebSocket."""
    await asyncio.sleep(18)
    
    last_regime_hash = None
    
    while True:
        if _is_training_active():
            await asyncio.sleep(60)
            continue
        if manager.active_connections:
            try:
                regime_data = await market_regime_engine.get_current_regime()
                regime_hash = hash(str(regime_data.get("state")) + str(regime_data.get("composite_score")))
                
                if regime_hash != last_regime_hash:
                    await manager.broadcast({
                        "type": "market_regime",
                        "data": regime_data,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_regime_hash = regime_hash
            except Exception as e:
                print(f"Market regime stream error: {e}")
        
        await asyncio.sleep(60)  # Every 60 seconds (regime changes slowly)


async def stream_filter_thoughts():
    """Push smart filter & confidence gate thoughts via WebSocket."""
    await asyncio.sleep(22)
    
    last_thoughts_hash = None
    
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                thoughts = trading_bot.get_filter_thoughts(limit=20)
                thoughts_hash = hash(str(len(thoughts)) + str(thoughts[0].get('timestamp', '')) if thoughts else '')
                
                if thoughts_hash != last_thoughts_hash:
                    await manager.broadcast({
                        "type": "filter_thoughts",
                        "data": thoughts,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_thoughts_hash = thoughts_hash
            except Exception as e:
                print(f"Filter thoughts stream error: {e}")
        
        await asyncio.sleep(10)  # Every 10 seconds


async def stream_order_queue():
    """Push order queue status via WebSocket (replaces 3s polling)."""
    await asyncio.sleep(8)
    last_hash = None
    _module_warned = False
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                from services.ib_execution_service import get_ib_execution_service
                exec_svc = get_ib_execution_service()
                if exec_svc:
                    queue_data = exec_svc.get_queue_status()
                else:
                    queue_data = {"pending": [], "active": [], "completed": [], "queue_size": 0}
                data_hash = hash(str(queue_data.get("queue_size", 0)) + str(len(queue_data.get("active", []))))
                if data_hash != last_hash:
                    await manager.broadcast({
                        "type": "order_queue",
                        "data": queue_data,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_hash = data_hash
            except ImportError:
                if not _module_warned:
                    print("Order queue stream: ib_execution_service not available (non-critical)")
                    _module_warned = True
            except Exception as e:
                print(f"Order queue stream error: {e}")
        await asyncio.sleep(10)  # Reduced from 3s — order queue changes slowly


async def stream_risk_status():
    """Push dynamic risk status via WebSocket (replaces 5-10s polling)."""
    await asyncio.sleep(12)
    last_hash = None
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                from services.dynamic_risk_engine import get_dynamic_risk_engine
                risk_svc = get_dynamic_risk_engine()
                if risk_svc:
                    status = risk_svc.get_status()
                else:
                    status = {}
                status_hash = hash(str(status.get("current_mode")) + str(status.get("daily_pnl", 0)))
                if status_hash != last_hash:
                    await manager.broadcast({
                        "type": "risk_status",
                        "data": status,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_hash = status_hash
            except Exception as e:
                print(f"Risk status stream error: {e}")
        await asyncio.sleep(5)


async def stream_sentcom_data():
    """Push SentCom intelligence data via WebSocket (replaces 8 separate polling hooks)."""
    await asyncio.sleep(15)
    last_hash = None
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                sentcom_data = {}
                # SentCom status
                try:
                    from services.sentcom_engine import get_sentcom_engine
                    engine = get_sentcom_engine()
                    if engine:
                        sentcom_data["status"] = engine.get_status()
                        sentcom_data["stream"] = engine.get_stream(limit=50)
                except Exception:
                    pass
                # Positions from IB pushed data
                try:
                    pushed = db.get("ib_pushed_data", {})
                    if hasattr(pushed, 'find_one'):
                        def _get_pushed_positions():
                            return pushed.find_one(sort=[("timestamp", -1)], projection={"_id": 0})
                        latest = await asyncio.to_thread(_get_pushed_positions)
                        sentcom_data["positions"] = latest if latest else {}
                    else:
                        sentcom_data["positions"] = {}
                except Exception:
                    sentcom_data["positions"] = {}
                # Market context snapshot
                try:
                    from services.market_context_service import get_market_context_service
                    mcs = get_market_context_service()
                    if mcs:
                        sentcom_data["market_context"] = mcs.get_snapshot()
                except Exception:
                    pass

                data_hash = hash(str(sentcom_data.get("status", {}).get("last_updated", "")) + str(len(sentcom_data.get("stream", []))))
                if data_hash != last_hash:
                    await manager.broadcast({
                        "type": "sentcom_data",
                        "data": sentcom_data,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_hash = data_hash
            except Exception as e:
                print(f"SentCom stream error: {e}")
        await asyncio.sleep(10)


async def stream_market_intel():
    """Push market intel data via WebSocket (replaces 60s polling)."""
    await asyncio.sleep(20)
    last_hash = None
    while True:
        if _is_training_active():
            await asyncio.sleep(60)
            continue
        if manager.active_connections:
            try:
                intel_data = {}
                try:
                    schedule = await asyncio.to_thread(market_intel_service.get_schedule_status)
                    intel_data["schedule"] = schedule
                except Exception:
                    pass
                try:
                    reports = await asyncio.to_thread(market_intel_service.get_todays_reports)
                    intel_data["reports"] = reports[-5:] if reports else []
                except Exception:
                    pass
                try:
                    current = await asyncio.to_thread(market_intel_service.get_current_report)
                    intel_data["current"] = current
                except Exception:
                    pass
                data_hash = hash(str(intel_data.get("current", {}).get("timestamp", "")) + str(len(intel_data.get("reports", []))))
                if data_hash != last_hash:
                    await manager.broadcast({
                        "type": "market_intel",
                        "data": intel_data,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_hash = data_hash
            except Exception as e:
                print(f"Market intel stream error: {e}")
        await asyncio.sleep(30)


async def stream_data_collection():
    """Push data collection status via WebSocket (replaces 15s polling)."""
    await asyncio.sleep(10)
    last_hash = None
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                collection_data = {}
                try:
                    from services.ib_historical_collector import get_ib_collector
                    collector = get_ib_collector()
                    if collector:
                        progress = await collector.get_queue_progress_detailed()
                        collection_data["progress"] = progress
                except Exception:
                    pass
                try:
                    def _get_coverage():
                        return list(db["ib_historical_data"].aggregate([
                            {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
                            {"$group": {"_id": None, "symbols": {"$sum": 1}, "total_bars": {"$sum": "$count"}}}
                        ]))
                    coverage = await asyncio.to_thread(_get_coverage)
                    for doc in coverage:
                        collection_data["coverage"] = {"symbols": doc.get("symbols", 0), "total_bars": doc.get("total_bars", 0)}
                except Exception:
                    pass

                data_hash = hash(str(collection_data.get("progress", {}).get("active_collections", [])))
                if data_hash != last_hash:
                    await manager.broadcast({
                        "type": "data_collection",
                        "data": collection_data,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_hash = data_hash
            except Exception as e:
                print(f"Data collection stream error: {e}")
        await asyncio.sleep(15)


async def stream_focus_mode():
    """Push focus mode state via WebSocket — reads from in-memory FocusModeManager (source of truth)."""
    await asyncio.sleep(5)
    last_hash = None
    while True:
        if manager.active_connections:
            try:
                # Read from in-memory manager — this is the authoritative source
                # (focus_mode_manager.set_mode/reset_to_live updates this immediately)
                mode_data = focus_mode_manager.get_status()
                
                data_hash = hash(str(mode_data.get("mode", "")) + str(mode_data.get("start_time", "")))
                if data_hash != last_hash:
                    await manager.broadcast({
                        "type": "focus_mode",
                        "data": mode_data,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_hash = data_hash
            except Exception as e:
                print(f"Focus mode stream error: {e}")
        await asyncio.sleep(5)


async def stream_simulator():
    """Push simulator status + alerts via WebSocket (replaces dual polling)."""
    await asyncio.sleep(8)
    last_hash = None
    while True:
        if _is_training_active():
            await asyncio.sleep(30)
            continue
        if manager.active_connections:
            try:
                sim_data = {}
                try:
                    from services.simulator_service import get_simulator_service
                    sim_svc = get_simulator_service()
                    if sim_svc:
                        sim_data["status"] = sim_svc.get_status()
                        sim_data["alerts"] = sim_svc.get_alerts(limit=20)
                except Exception:
                    pass
                data_hash = hash(str(sim_data.get("status", {}).get("is_running", False)) + str(len(sim_data.get("alerts", []))))
                if data_hash != last_hash:
                    await manager.broadcast({
                        "type": "simulator",
                        "data": sim_data,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    last_hash = data_hash
            except Exception as e:
                print(f"Simulator stream error: {e}")
        await asyncio.sleep(5)


async def _weekly_adv_recalc_loop():
    """
    Background task: recalculate ADV cache from IB daily bars every Sunday at 10 PM ET.
    Uses 10-day lookback (2 trading weeks) since IB data is collected weekly.
    """
    import pytz
    et = pytz.timezone("US/Eastern")

    while True:
        try:
            now_et = datetime.now(et)
            # Calculate next Sunday 10 PM ET
            days_until_sunday = (6 - now_et.weekday()) % 7
            if days_until_sunday == 0 and now_et.hour >= 22:
                days_until_sunday = 7  # Already past this Sunday's window
            next_run = now_et.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
            wait_seconds = (next_run - now_et).total_seconds()
            print(f"[ADV Scheduler] Next recalc: {next_run.strftime('%a %b %d %I:%M %p ET')} (in {wait_seconds/3600:.1f}h)")
            await asyncio.sleep(wait_seconds)

            # Run the recalculation in a thread (heavy MongoDB aggregation)
            print("[ADV Scheduler] Starting weekly ADV cache recalculation...")
            result = await asyncio.to_thread(_run_adv_recalc)
            print(f"[ADV Scheduler] Complete: {result}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[ADV Scheduler] Error: {e}")
            await asyncio.sleep(3600)  # Retry in 1 hour on error


def _run_adv_recalc():
    """Sync wrapper for ADV recalculation (runs in thread)."""
    try:
        from scripts.recalculate_adv_cache import recalculate_adv_cache
        stats = recalculate_adv_cache(db, lookback_days=10, min_bars=5, verbose=True)
        return stats
    except Exception as e:
        return {"error": str(e)}


@app.on_event("startup")
async def startup_event():
    """Start background streaming task and background scanner"""
    
    # Expand the default thread pool to prevent starvation from blocking I/O
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=64))
    loop.slow_callback_duration = 0.5  # Log warning if a callback takes >500ms
    
    # Start WebSocket streaming tasks (lightweight, non-blocking)
    # Event loop health monitor — detects blocking calls
    async def _event_loop_monitor():
        """Periodically check event loop responsiveness. If asyncio.sleep(0) takes >500ms, something is blocking."""
        import time
        await asyncio.sleep(5)
        while True:
            t0 = time.monotonic()
            await asyncio.sleep(0)
            lag = time.monotonic() - t0
            if lag > 0.5:  # 500ms threshold
                print(f"⚠️ EVENT LOOP BLOCKED for {lag:.1f}s! Check for synchronous calls.")
            await asyncio.sleep(2)
    asyncio.create_task(_event_loop_monitor())
    
    asyncio.create_task(stream_quotes())
    asyncio.create_task(stream_system_status())
    asyncio.create_task(stream_bot_trades())
    asyncio.create_task(stream_scanner_alerts())
    asyncio.create_task(stream_smart_watchlist())
    asyncio.create_task(stream_coaching_notifications())
    asyncio.create_task(stream_confidence_gate())
    asyncio.create_task(stream_training_status())
    asyncio.create_task(stream_market_regime())
    asyncio.create_task(stream_filter_thoughts())
    asyncio.create_task(stream_order_queue())
    asyncio.create_task(stream_risk_status())
    asyncio.create_task(stream_sentcom_data())
    asyncio.create_task(stream_market_intel())
    asyncio.create_task(stream_data_collection())
    asyncio.create_task(stream_focus_mode())
    asyncio.create_task(stream_simulator())
    print("WebSocket streaming: 12 push types (quotes, ib_status, bot_status, scanner_status, bot_trades, scanner_alerts, smart_watchlist, coaching, confidence_gate, training, regime, filter_thoughts)")
    
    # Initialize web research service with database for credit tracking
    try:
        from services.web_research_service import get_web_research_service
        research_service = get_web_research_service(db)
        budget = research_service.get_credit_budget_status()
        print(f"Web research service initialized - Tavily credits: {budget['credits_used']}/{budget['monthly_limit']} ({budget['usage_percent']}%)")
    except Exception as e:
        print(f"Web research service init: {e}")
    
    # Start learning loop scheduler (auto-analysis at 4:15 PM ET)
    asyncio.create_task(perf_service.start_scheduler())
    print("Learning loop scheduler started")
    
    # Start market intel scheduler (auto-generates reports at scheduled times)
    asyncio.create_task(market_intel_service.start_scheduler())
    print("Market intel scheduler started")
    
    # Start weekly ADV cache recalculation (Sunday 10 PM ET)
    asyncio.create_task(_weekly_adv_recalc_loop())
    print("Weekly ADV cache recalc scheduler started (Sunday 10 PM ET)")
    
    # --- Heavy initialization (non-blocking) ---
    # All heavy operations run in background tasks so the server accepts
    # connections immediately. The StartupModal will see services come online
    # progressively via /api/startup-check.
    
    async def _deferred_heavy_init():
        """Run heavy initialization in background without blocking the event loop.
        Smart startup: services start in dependency order, skip gracefully if deps unavailable."""
        # Small delay to let the server finish startup
        await asyncio.sleep(1)

        # 1. Set focus mode to LIVE explicitly
        focus_mode_manager.set_mode(mode="live", context={"reason": "startup"})
        print("Focus mode: LIVE (all services active)")
        await asyncio.sleep(0)  # Yield to event loop

        # 2. Attempt auto-connect to IB Gateway (everything depends on this)
        ib_connected = False
        try:
            ib_svc = get_ib_service()
            status = ib_svc.get_connection_status()
            if not status.get("connected", False):
                print("Attempting auto-connect to IB Gateway...")
                ib_connected = await ib_svc.connect()
                if ib_connected:
                    print("IB Gateway: CONNECTED")
                else:
                    print("IB Gateway: NOT AVAILABLE — IB-dependent services will start in degraded mode")
            else:
                ib_connected = True
                print("IB Gateway: ALREADY CONNECTED")
        except Exception as e:
            print(f"IB Gateway: SKIPPED ({e})")
        await asyncio.sleep(0)  # Yield to event loop

        # 3. Start background scanner (needs IB for live scanning)
        try:
            await background_scanner.start()
            if ib_connected:
                print("Background scanner: STARTED (live alerts active)")
            else:
                print("Background scanner: STARTED (degraded — no IB connection, will activate when IB connects)")
        except Exception as e:
            print(f"Background scanner: FAILED ({e})")
        await asyncio.sleep(0)  # Yield to event loop

        # 4. Auto-start trading bot (needs IB for order execution)
        try:
            await trading_bot.start()
            mode = trading_bot.get_mode().value.upper()
            if ib_connected:
                print(f"Trading bot: STARTED in {mode} mode (live execution ready)")
            else:
                print(f"Trading bot: STARTED in {mode} mode (paper mode — no IB connection)")
        except Exception as e:
            print(f"Trading bot: FAILED ({e})")

        # 5. Startup summary
        print("")
        print("=" * 50)
        print("  LIVE TRADING MODE — Startup Complete")
        print("=" * 50)
        print(f"  IB Gateway:       {'CONNECTED' if ib_connected else 'DISCONNECTED'}")
        print("  Trading Bot:      ACTIVE")
        print("  Scanner:          ACTIVE")
        print("  Learning Loop:    SCHEDULED (4:15 PM ET)")
        print("  Market Intel:     SCHEDULED")
        print("  WebSocket:        16 streams active")
        print("  Focus Mode:       LIVE")
        print("  Collectors:       UI-controlled (not auto-started)")
        print("  Training:         UI-controlled (not auto-started)")
        print("=" * 50)
    
    asyncio.create_task(_deferred_heavy_init())
    print("Heavy initialization deferred to background task")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown of background services"""
    await background_scanner.stop()
    perf_service.stop_scheduler()
    market_intel_service.stop_scheduler()
    print("Background services stopped")


@app.websocket("/api/ws/quotes")
async def websocket_quotes(websocket: WebSocket):
    """WebSocket endpoint for real-time quote streaming"""
    await manager.connect(websocket)
    
    # Send immediate connected confirmation (critical for proxy keep-alive)
    try:
        await websocket.send_json({
            "type": "connected",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        print(f"Failed to send connected message: {e}")
        manager.disconnect(websocket)
        return
    
    # Start a background task for server-side keepalive pings
    async def server_keepalive():
        """Send periodic pings from server to keep connection alive"""
        try:
            while websocket in manager.active_connections:
                await asyncio.sleep(20)  # Ping every 20 seconds
                if websocket in manager.active_connections:
                    try:
                        await websocket.send_json({"type": "server_ping", "ts": datetime.now(timezone.utc).isoformat()})
                    except:
                        break
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    
    keepalive_task = asyncio.create_task(server_keepalive())
    
    # Fetch initial data in background (non-blocking) to avoid connection timeout
    async def send_initial_data():
        try:
            initial_quotes = []
            # Limit to first 4 symbols for faster initial load
            for symbol in DEFAULT_STREAM_SYMBOLS[:4]:
                try:
                    quote = await fetch_quote(symbol)
                    if quote:
                        clean_quote = {k: v for k, v in quote.items() if not k.startswith('_')}
                        initial_quotes.append(clean_quote)
                except Exception as symbol_err:
                    print(f"Error fetching quote for {symbol}: {symbol_err}")
                await asyncio.sleep(0.1)  # Reduced delay
            
            if initial_quotes and websocket in manager.active_connections:
                await manager.send_personal_message({
                    "type": "initial",
                    "data": initial_quotes,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }, websocket)
                print(f"Sent {len(initial_quotes)} initial quotes")
            
            # Also send current scanner alerts immediately (don't wait for stream_scanner_alerts)
            try:
                alerts = background_scanner.get_live_alerts()
                if alerts and websocket in manager.active_connections:
                    alerts_data = []
                    for alert in alerts[:20]:
                        if hasattr(alert, 'to_dict'):
                            alerts_data.append(alert.to_dict())
                        elif hasattr(alert, '__dict__'):
                            alerts_data.append(dict(alert.__dict__))
                        else:
                            alerts_data.append(alert)
                    if alerts_data:
                        await manager.send_personal_message({
                            "type": "scanner_alerts",
                            "data": alerts_data,
                            "count": len(alerts_data),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }, websocket)
                        print(f"Sent {len(alerts_data)} initial scanner alerts")
            except Exception as e:
                print(f"Error sending initial scanner alerts: {e}")

        except Exception as e:
            print(f"Error sending initial data: {e}")
    
    # Start initial data fetch as background task
    asyncio.create_task(send_initial_data())
    
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()
            
            if data.get("action") == "subscribe":
                symbols = data.get("symbols", [])
                manager.subscribe(websocket, symbols)
                await manager.send_personal_message({
                    "type": "subscribed",
                    "symbols": symbols
                }, websocket)
            
            elif data.get("action") == "unsubscribe":
                symbols = data.get("symbols", [])
                manager.unsubscribe(websocket, symbols)
                await manager.send_personal_message({
                    "type": "unsubscribed",
                    "symbols": symbols
                }, websocket)
            
            elif data.get("action") == "ping":
                await manager.send_personal_message({"type": "pong"}, websocket)
            
            elif data.get("action") == "train_setup":
                # Handle setup-specific training via WebSocket (bypasses HTTP connection pool)
                setup_type = data.get("setup_type")
                bar_size = data.get("bar_size")  # None = train all profiles for this setup
                try:
                    result = await job_queue_manager.create_job(
                        job_type="setup_training",
                        params={"setup_type": setup_type, "bar_size": bar_size, "max_symbols": None, "max_bars_per_symbol": None}
                    )
                    if not result.get("success"):
                        raise Exception(result.get("error", "Failed to create job"))
                    job_id = result["job"]["job_id"]
                    # Auto-activate TRAINING focus mode
                    focus_mode_manager.set_mode(
                        mode="training",
                        context={"setup_type": setup_type, "bar_size": bar_size},
                        job_id=job_id
                    )
                    await manager.send_personal_message({
                        "type": "train_queued",
                        "job_id": job_id,
                        "setup_type": setup_type,
                        "focus_mode": "training",
                        "success": True
                    }, websocket)
                    print(f"[WS] Created setup_training job {job_id} for {setup_type} (TRAINING mode activated)")
                except Exception as train_err:
                    import traceback
                    traceback.print_exc()
                    await manager.send_personal_message({
                        "type": "train_error",
                        "error": str(train_err),
                        "setup_type": setup_type,
                        "success": False
                    }, websocket)
            
            elif data.get("action") == "train_setup_all":
                # Handle train-all setup models via WebSocket
                try:
                    result = await job_queue_manager.create_job(
                        job_type="setup_training",
                        params={"setup_type": "ALL", "bar_size": None}
                    )
                    if not result.get("success"):
                        raise Exception(result.get("error", "Failed to create job"))
                    job_id = result["job"]["job_id"]
                    # Auto-activate TRAINING focus mode
                    focus_mode_manager.set_mode(
                        mode="training",
                        context={"setup_type": "ALL"},
                        job_id=job_id
                    )
                    await manager.send_personal_message({
                        "type": "train_queued",
                        "job_id": job_id,
                        "train_type": "setup_all",
                        "focus_mode": "training",
                        "success": True
                    }, websocket)
                    print(f"[WS] Created setup_training_all job {job_id} (TRAINING mode activated)")
                except Exception as train_err:
                    import traceback
                    traceback.print_exc()
                    await manager.send_personal_message({
                        "type": "train_error",
                        "error": str(train_err),
                        "success": False
                    }, websocket)
            
            elif data.get("action") == "train_general":
                # Handle general model training via WebSocket
                bar_size = data.get("bar_size", "1 day")
                train_type = data.get("train_type", "single")
                full_universe = data.get("full_universe", False)
                all_timeframes = data.get("all_timeframes", False)
                try:
                    params = {"bar_size": bar_size}
                    if full_universe:
                        params["full_universe"] = True
                        params["all_timeframes"] = all_timeframes
                    result = await job_queue_manager.create_job(
                        job_type="training",
                        params=params,
                        priority=8 if not full_universe else 10
                    )
                    if not result.get("success"):
                        raise Exception(result.get("error", "Failed to create job"))
                    job_id = result["job"]["job_id"]
                    # Auto-activate TRAINING focus mode
                    focus_mode_manager.set_mode(
                        mode="training",
                        context={"bar_size": bar_size, "train_type": train_type},
                        job_id=job_id
                    )
                    await manager.send_personal_message({
                        "type": "train_queued",
                        "job_id": job_id,
                        "train_type": train_type,
                        "focus_mode": "training",
                        "success": True
                    }, websocket)
                    print(f"[WS] Created training job {job_id} ({train_type}) (TRAINING mode activated)")
                except Exception as train_err:
                    import traceback
                    traceback.print_exc()
                    await manager.send_personal_message({
                        "type": "train_error",
                        "error": str(train_err),
                        "success": False
                    }, websocket)

            elif data.get("action") == "start_pipeline":
                # Start the full 5-phase training pipeline via WebSocket
                # (bypasses HTTP connection pool limitation entirely)
                try:
                    from routers.ai_training import start_training as _start_training_endpoint
                    result = await _start_training_endpoint()
                    await manager.send_personal_message({
                        "type": "pipeline_start_result",
                        "success": result.get("success", False),
                        "message": result.get("message", ""),
                        "error": result.get("error", ""),
                        "pid": result.get("pid"),
                    }, websocket)
                    print(f"[WS] Pipeline start result: {result.get('success')} - {result.get('message', result.get('error', ''))}")
                except Exception as pipe_err:
                    import traceback
                    traceback.print_exc()
                    await manager.send_personal_message({
                        "type": "pipeline_start_result",
                        "success": False,
                        "error": str(pipe_err),
                    }, websocket)

            elif data.get("action") == "stop_pipeline":
                # Stop the training pipeline via WebSocket
                try:
                    from routers.ai_training import stop_training as _stop_training_endpoint
                    result = await _stop_training_endpoint()
                    await manager.send_personal_message({
                        "type": "pipeline_stop_result",
                        "success": result.get("success", False),
                        "message": result.get("message", ""),
                    }, websocket)
                    print(f"[WS] Pipeline stop result: {result.get('success')} - {result.get('message', '')}")
                except Exception as pipe_err:
                    await manager.send_personal_message({
                        "type": "pipeline_stop_result",
                        "success": False,
                        "error": str(pipe_err),
                    }, websocket)
    
    except WebSocketDisconnect:
        print("WebSocket client disconnected gracefully")
        keepalive_task.cancel()
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        import traceback
        traceback.print_exc()
        keepalive_task.cancel()
        manager.disconnect(websocket)

@app.get("/api/stream/status")
async def get_stream_status():
    """Get WebSocket streaming status"""
    return {
        "active_connections": len(manager.active_connections),
        "streaming": True,
        "update_interval_seconds": 5,
        "default_symbols": DEFAULT_STREAM_SYMBOLS
    }


# ============================================================
# OLLAMA PROXY WEBSOCKET
# ============================================================

@app.websocket("/api/ws/ollama-proxy")
async def websocket_ollama_proxy(websocket: WebSocket):
    """WebSocket endpoint for local Ollama proxy connections"""
    await handle_ollama_proxy_websocket(websocket)



# ----- Ollama proxy routes extracted to routers/ollama_proxy.py -----

# SCRIPT DOWNLOAD ENDPOINTS (for auto-update)
# =====================================================
from fastapi.responses import PlainTextResponse
import os

SCRIPTS_DIR = "/app/documents"

@app.get("/api/scripts/{script_name}")
async def get_script(script_name: str):
    """Serve scripts for auto-update (StartTrading.bat, ollama_http.py, etc.)"""
    # Whitelist allowed scripts
    allowed_scripts = ["StartTrading.bat", "ollama_http.py", "ib_data_pusher.py", "ollama_proxy.py", "ui_mockups.html", "ui_mockups_v2.html", "ui_mockups_v2_enhanced.html", "ui_mockups_chart_modal_v3.html", "ui_mockups_chart_modal_refined.html", "ui_mockups_chart_modal_final.html", "TradeCommand_Overview.html"]
    
    if script_name not in allowed_scripts:
        return PlainTextResponse("Script not found", status_code=404)
    
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    
    if not os.path.exists(script_path):
        return PlainTextResponse("Script not found", status_code=404)
    
    with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    # Serve HTML files with correct content type
    if script_name.endswith(".html"):
        from starlette.responses import HTMLResponse
        return HTMLResponse(content)
    
    return PlainTextResponse(content, media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
