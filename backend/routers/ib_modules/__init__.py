"""
IB Router Package

This package contains the refactored Interactive Brokers API endpoints,
split into logical domain-specific modules for better maintainability.

Modules:
- historical_data: Historical data collection, storage, and index optimization
- (more modules will be added as refactoring continues)
"""
from fastapi import APIRouter
from .historical_data import router as historical_data_router

# Main router that combines all sub-routers
# Note: The prefix is NOT set here - it will be set in server.py
# This allows flexibility in how the routes are mounted
router = APIRouter()

# Include all sub-routers
router.include_router(historical_data_router)

# Export for convenience
__all__ = [
    "router",
    "historical_data_router",
]
