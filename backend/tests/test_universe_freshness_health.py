"""
Regression contract for `/api/ib-collector/universe-freshness-health` added 2026-04-24.

This is the user-facing "Am I ready to retrain?" rollup. It must stay
consistent with the STALE_DAYS logic used in gap-analysis/fill-gaps so
different dashboards don't disagree about what "fresh" means.
"""
from pathlib import Path
import re

ROUTER = Path(__file__).parent.parent / "routers" / "ib_collector_router.py"
SRC = ROUTER.read_text()


def test_endpoint_registered_and_named():
    assert '@router.get("/universe-freshness-health")' in SRC, (
        "The universe-freshness-health endpoint must be registered on the router."
    )
    assert "async def universe_freshness_health(" in SRC


def test_readiness_gate_uses_both_critical_and_pct():
    """Decision must AND the critical-symbol check with the overall pct threshold."""
    assert "ready = all_critical_fresh and overall_fresh_pct >= min_fresh_pct_to_retrain" in SRC, (
        "ready_to_retrain must require BOTH all critical symbols fresh AND "
        "overall fresh_pct above the configurable threshold."
    )


def test_stale_days_matches_other_endpoints():
    """All three endpoints (gap-analysis, fill-gaps, universe-freshness-health)
    must use identical staleness thresholds — drift between them = silent
    disagreement about what 'fresh' means."""
    # Every STALE_DAYS map in this file must have the same values.
    maps = re.findall(r"STALE_DAYS\s*=\s*\{([^}]+)\}", SRC, re.DOTALL)
    assert len(maps) >= 3, (
        f"Expected STALE_DAYS in ≥3 endpoints (gap-analysis, fill-gaps, "
        f"universe-freshness-health), found {len(maps)}"
    )
    # Parse each into a dict and verify all are identical
    parsed = []
    for block in maps:
        pairs = re.findall(r'"([^"]+)"\s*:\s*(\d+)', block)
        parsed.append({k: int(v) for k, v in pairs})
    for i in range(1, len(parsed)):
        assert parsed[i] == parsed[0], (
            f"STALE_DAYS map #{i+1} diverges from the first. "
            f"All endpoints must agree on staleness thresholds.\n"
            f"#1: {parsed[0]}\n#{i+1}: {parsed[i]}"
        )


def test_response_shape_has_key_fields():
    """Make sure the response includes the fields the UI / retrain gate need."""
    must_have = [
        "ready_to_retrain",
        "blocking_reasons",
        "overall",
        "critical_symbols",
        "by_tier",
        "oldest_10_daily",
        "freshest_10_daily",
        "last_successful_backfill",
        "queue_snapshot",
    ]
    for field in must_have:
        assert f'"{field}"' in SRC, (
            f"universe-freshness-health response must include '{field}'."
        )


def test_critical_symbols_defaults_include_major_etfs():
    """Default critical_symbols must include the major market ETFs that anchor
    training. If these are stale, SPY-based setups will overfit to old data."""
    # The default value is a comma-separated query param
    m = re.search(
        r'critical_symbols:\s*str\s*=\s*"([^"]+)"',
        SRC,
    )
    assert m is not None, "Default critical_symbols query param missing."
    defaults = [s.strip().upper() for s in m.group(1).split(",")]
    for must in ("SPY", "QQQ", "IWM", "AAPL", "MSFT"):
        assert must in defaults, (
            f"'{must}' must be in default critical_symbols list. "
            "It's an anchor for training and scanner universes."
        )
