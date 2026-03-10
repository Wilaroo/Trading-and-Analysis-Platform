"""
Slow Learning Module - Phase 6

Backtesting engine, shadow mode, and strategy verification.
Runs offline analysis on historical data to validate strategies.
"""

from services.slow_learning.historical_data_service import (
    HistoricalDataService,
    get_historical_data_service,
    init_historical_data_service
)
from services.slow_learning.backtest_engine import (
    BacktestEngine,
    get_backtest_engine,
    init_backtest_engine
)
from services.slow_learning.shadow_mode_service import (
    ShadowModeService,
    get_shadow_mode_service,
    init_shadow_mode_service
)

__all__ = [
    "HistoricalDataService",
    "get_historical_data_service",
    "init_historical_data_service",
    "BacktestEngine",
    "get_backtest_engine", 
    "init_backtest_engine",
    "ShadowModeService",
    "get_shadow_mode_service",
    "init_shadow_mode_service"
]
