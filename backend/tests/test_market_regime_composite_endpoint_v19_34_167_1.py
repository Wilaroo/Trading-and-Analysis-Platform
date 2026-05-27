"""v19.34.167.1 — verify composite endpoint registered + returns shape."""
import sys
from pathlib import Path
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

def test_endpoint_is_registered():
    """The route must exist on the FastAPI app."""
    from server import app
    paths = [r.path for r in app.routes]
    assert "/api/market-regime/composite" in paths, (
        f"endpoint not registered. Routes containing 'market-regime': "
        f"{[p for p in paths if 'market-regime' in p]}"
    )

def test_endpoint_returns_dict_with_expected_keys():
    """Even when scanner not initialized, endpoint must return a dict
    with the expected top-level keys (success bool, regime str, metadata dict)."""
    import asyncio
    from server import get_market_regime_composite
    result = asyncio.run(get_market_regime_composite())
    assert isinstance(result, dict)
    assert "success" in result
    assert "regime" in result
    assert "metadata" in result
    assert isinstance(result["metadata"], dict)
