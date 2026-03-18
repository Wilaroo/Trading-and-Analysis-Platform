"""
IB Router Package

This package contains the refactored Interactive Brokers API endpoints,
split into logical domain-specific modules for better maintainability.

Modules:
- historical_data: Historical data collection, storage, and index optimization
- collection_mode: Collection mode tracking and priority collection system
- news: News-related functionality including IB news providers
- alerts: Price alerts and enhanced alerts functionality
"""
from fastapi import APIRouter
from .historical_data import router as historical_data_router
from .collection_mode import router as collection_mode_router
from .news import router as news_router, init_news_services
from .alerts import router as alerts_router, init_alert_services

# Main router that combines all sub-routers
# Note: The prefix is NOT set here - it will be set in server.py
# This allows flexibility in how the routes are mounted
router = APIRouter()

# Include all sub-routers
router.include_router(historical_data_router)
router.include_router(collection_mode_router)
router.include_router(news_router)
router.include_router(alerts_router)


def init_services(ib_service=None, news_service=None, alpaca_service=None):
    """Initialize services for all sub-routers that need them"""
    if ib_service or news_service:
        init_news_services(ib_service, news_service)
    if ib_service or alpaca_service:
        init_alert_services(ib_service, alpaca_service)


# Export for convenience
__all__ = [
    "router",
    "historical_data_router",
    "collection_mode_router", 
    "news_router",
    "alerts_router",
    "init_services",
    "init_news_services",
    "init_alert_services",
]
