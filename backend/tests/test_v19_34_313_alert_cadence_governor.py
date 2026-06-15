"""v19.34.313 alert cadence governor -- unit tests."""
import importlib
import os


def _reload():
    import services.enhanced_scanner as es
    importlib.reload(es)
    return es


def test_cooldown_defaults():
    for k in ("SETUP_REFIRE_COOLDOWN_SCALP_S",
              "SETUP_REFIRE_COOLDOWN_INTRADAY_S",
              "SETUP_REFIRE_COOLDOWN_DAILY_S"):
        os.environ.pop(k, None)
    es = _reload()
    assert es._COOLDOWN_S_SCALP == 300
    assert es._COOLDOWN_S_INTRADAY == 1800
    assert es._COOLDOWN_S_DAILY == 86400


def test_cooldown_env_overrides():
    os.environ["SETUP_REFIRE_COOLDOWN_SCALP_S"] = "120"
    os.environ["SETUP_REFIRE_COOLDOWN_INTRADAY_S"] = "600"
    os.environ["SETUP_REFIRE_COOLDOWN_DAILY_S"] = "43200"
    try:
        es = _reload()
        assert es._COOLDOWN_S_SCALP == 120
        assert es._COOLDOWN_S_INTRADAY == 600
        assert es._COOLDOWN_S_DAILY == 43200
    finally:
        for k in ("SETUP_REFIRE_COOLDOWN_SCALP_S",
                  "SETUP_REFIRE_COOLDOWN_INTRADAY_S",
                  "SETUP_REFIRE_COOLDOWN_DAILY_S"):
            os.environ.pop(k, None)
        _reload()


def test_refire_cooldown_seconds_dispatch():
    from services.enhanced_scanner import refire_cooldown_seconds
    assert refire_cooldown_seconds("scalp") == 300
    assert refire_cooldown_seconds("intraday") == 1800
    assert refire_cooldown_seconds("multi_day") == 86400
    assert refire_cooldown_seconds("swing") == 86400
    assert refire_cooldown_seconds("position") == 86400
    assert refire_cooldown_seconds("investment") == 86400
    # Unknown / None / empty defaults to intraday cooldown
    assert refire_cooldown_seconds(None) == 1800
    assert refire_cooldown_seconds("") == 1800
    assert refire_cooldown_seconds("UNKNOWN_TIER") == 1800
    # Case-insensitive
    assert refire_cooldown_seconds("SCALP") == 300
    assert refire_cooldown_seconds("Swing") == 86400


def test_style_sets_membership():
    from services.enhanced_scanner import (
        SCALP_INTRADAY_STYLES, DAILY_TIER_STYLES
    )
    assert "scalp" in SCALP_INTRADAY_STYLES
    assert "intraday" in SCALP_INTRADAY_STYLES
    assert "multi_day" in DAILY_TIER_STYLES
    assert "swing" in DAILY_TIER_STYLES
    assert "position" in DAILY_TIER_STYLES
    assert "investment" in DAILY_TIER_STYLES
    # Mutually exclusive
    assert SCALP_INTRADAY_STYLES & DAILY_TIER_STYLES == set()


def test_eod_eviction_hour_constant():
    from services.enhanced_scanner import EOD_EVICTION_ET_HOUR
    assert EOD_EVICTION_ET_HOUR == 16
