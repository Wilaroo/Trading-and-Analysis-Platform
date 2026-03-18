"""
pytest configuration for SentCom backend tests

Note: For full integration tests, use the live API via curl or requests.
These tests use direct endpoint testing without importing the full server.
"""
import pytest
import requests
import os


@pytest.fixture(scope="session")
def api_base_url():
    """Get the API base URL - use local backend for testing"""
    return "http://localhost:8001"


@pytest.fixture(scope="session")
def api_client(api_base_url):
    """Create a requests session for API calls"""
    session = requests.Session()
    session.base_url = api_base_url
    return session


@pytest.fixture
def mock_ib_connected():
    """Mock IB connection status as connected"""
    return {"connected": True, "pusher_active": True}


@pytest.fixture
def mock_ib_disconnected():
    """Mock IB connection status as disconnected"""
    return {"connected": False, "pusher_active": False}


@pytest.fixture
def sample_position():
    """Sample position data for testing"""
    return {
        "symbol": "AAPL",
        "quantity": 100,
        "avg_cost": 150.00,
        "current_price": 155.00,
        "unrealized_pnl": 500.00,
        "unrealized_pnl_percent": 3.33
    }


@pytest.fixture
def sample_quote():
    """Sample quote data for testing"""
    return {
        "symbol": "AAPL",
        "price": 155.00,
        "bid": 154.95,
        "ask": 155.05,
        "volume": 1000000,
        "change_percent": 1.5
    }


@pytest.fixture
def sample_historical_bar():
    """Sample historical bar data for testing"""
    return {
        "symbol": "AAPL",
        "date": "2026-03-18",
        "open": 150.00,
        "high": 156.00,
        "low": 149.50,
        "close": 155.00,
        "volume": 5000000,
        "bar_size": "1 day"
    }
