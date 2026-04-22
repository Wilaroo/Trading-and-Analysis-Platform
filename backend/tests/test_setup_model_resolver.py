"""
Unit tests for _resolve_setup_model_key — the routing layer that maps
scanner-emitted setup_type strings to the best matching trained-model key.

Context
-------
After Phase 13 revalidation (2026-04-23), three SHORT models promoted with
real edge: SHORT_SCALP (417 trades, 53% WR, 1.52 Sharpe), SHORT_VWAP
(525 trades, 54.3% WR, 1.76 Sharpe), SHORT_REVERSAL (459 trades, 53.4% WR,
1.94 Sharpe). But scanner alerts arrive with names like `rubber_band_scalp_short`
or `vwap_reclaim_short`, which never matched those trained models before this
fix — the bot was ignoring real edge.

This resolver bridges scanner namespace → training namespace so the 3 promoted
shorts are actually reachable from the live trading path.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_setup_model_resolver.py -v
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ai_modules.timeseries_service import TimeSeriesAIService  # noqa: E402


resolve = TimeSeriesAIService._resolve_setup_model_key


# Representative set of loaded models — what the DB typically has on Spark
AVAILABLE = {
    "SCALP", "VWAP", "REVERSAL", "BREAKOUT", "ORB", "RANGE",
    "MEAN_REVERSION", "MOMENTUM", "TREND",
    "SHORT_SCALP", "SHORT_VWAP", "SHORT_REVERSAL",
    "SHORT_ORB", "SHORT_BREAKDOWN", "SHORT_GAP_FADE",
    "SHORT_RANGE", "SHORT_MEAN_REVERSION", "SHORT_MOMENTUM", "SHORT_TREND",
}


def test_exact_match_wins():
    assert resolve("SCALP", AVAILABLE) == "SCALP"
    assert resolve("SHORT_VWAP", AVAILABLE) == "SHORT_VWAP"
    assert resolve("scalp", AVAILABLE) == "SCALP"   # case normalized


def test_legacy_vwap_bounce_routes_to_vwap():
    assert resolve("VWAP_BOUNCE", AVAILABLE) == "VWAP"
    assert resolve("VWAP_FADE", AVAILABLE) == "VWAP"


def test_scanner_short_scalp_variants_route_to_SHORT_SCALP():
    # The promoted SHORT_SCALP model must catch these
    cases = [
        "rubber_band_scalp_short",
        "spencer_scalp_short",
        "abc_scalp_short",
        "9_ema_scalp_short",
    ]
    for raw in cases:
        resolved = resolve(raw, AVAILABLE)
        assert resolved == "SHORT_SCALP", f"{raw} → {resolved}"


def test_scanner_short_vwap_variants_route_to_SHORT_VWAP():
    cases = [
        "vwap_reclaim_short",
        "vwap_fade_short",
        "vwap_bounce_short",
    ]
    for raw in cases:
        resolved = resolve(raw, AVAILABLE)
        assert resolved == "SHORT_VWAP", f"{raw} → {resolved}"


def test_scanner_short_reversal_variants_route_to_SHORT_REVERSAL():
    cases = [
        "reversal_short",
        "opening_drive_reversal_short",
        "halfback_reversal_short",
    ]
    for raw in cases:
        resolved = resolve(raw, AVAILABLE)
        assert resolved == "SHORT_REVERSAL", f"{raw} → {resolved}"


def test_long_side_variants_strip_suffix():
    # Long-side gets base lookup
    assert resolve("rubber_band_scalp_long", AVAILABLE) == "SCALP"
    assert resolve("vwap_reclaim_long", AVAILABLE) == "VWAP"
    assert resolve("reversal_long", AVAILABLE) == "REVERSAL"


def test_unknown_setup_returns_raw_for_general_fallback():
    # predict_for_setup will fall back to the general model when no match
    assert resolve("totally_unknown_setup_type", AVAILABLE) == "TOTALLY_UNKNOWN_SETUP_TYPE"


def test_no_short_models_available_falls_to_base():
    # If only long models are loaded, short alerts should strip suffix and
    # look up base (better than nothing).
    only_long = {"SCALP", "VWAP", "REVERSAL"}
    assert resolve("rubber_band_scalp_short", only_long) == "SCALP"
    assert resolve("vwap_reclaim_short", only_long) == "VWAP"


def test_empty_setup_type_passthrough():
    assert resolve("", AVAILABLE) == ""
    assert resolve(None, AVAILABLE) is None


def test_preserves_existing_vwap_fade_semantics():
    # Even when we pass a short-side VWAP_FADE variant, routing still works
    assert resolve("VWAP_FADE_SHORT", AVAILABLE) == "SHORT_VWAP"
