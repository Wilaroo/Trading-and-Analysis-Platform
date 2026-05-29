"""
v19.34.180 regression — POST /risk-params must persist MONGO_WINS fields
synchronously so the operator's API change is not silently reverted by the
state-integrity watchdog (observed 2026-05-29: max_open_positions=25 -> 10).

Pure-logic guard (no IB/GPU/live DB per DGX constraint): validates the
field-filter that decides which updated risk params get written straight to
bot_state, and that the critical fields are classified MONGO_WINS.
"""
from services.state_integrity_service import MONGO_WINS_FIELDS, MEMORY_WINS_FIELDS


def _mongo_persist_dict(kwargs, risk_obj):
    """Mirror of trading_bot_service.update_risk_params v19.34.180 filter."""
    return {
        f"risk_params.{k}": getattr(risk_obj, k)
        for k in kwargs
        if k in MONGO_WINS_FIELDS and hasattr(risk_obj, k)
    }


class _RP:
    max_open_positions = 25
    max_position_pct = 20.0
    min_risk_reward = 1.7
    starting_capital = 200000.0
    setup_min_rr = {"squeeze": 1.3}


def test_max_open_positions_is_mongo_wins():
    assert "max_open_positions" in MONGO_WINS_FIELDS


def test_persist_dict_includes_mongo_wins_fields():
    out = _mongo_persist_dict({"max_open_positions": 25}, _RP())
    assert out == {"risk_params.max_open_positions": 25}


def test_persist_dict_excludes_memory_wins_fields():
    # starting_capital + setup_min_rr are MEMORY_WINS — must NOT be force-written.
    out = _mongo_persist_dict(
        {"starting_capital": 200000.0, "setup_min_rr": {"squeeze": 1.3}}, _RP()
    )
    assert out == {}
    assert "starting_capital" in MEMORY_WINS_FIELDS
    assert "setup_min_rr" in MEMORY_WINS_FIELDS


def test_persist_dict_mixed_update_filters_correctly():
    out = _mongo_persist_dict(
        {"max_open_positions": 25, "min_risk_reward": 1.7, "starting_capital": 1.0},
        _RP(),
    )
    assert out == {
        "risk_params.max_open_positions": 25,
        "risk_params.min_risk_reward": 1.7,
    }
