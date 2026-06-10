"""
v319c — GBM_FORCE_PROMOTE override pins (timeseries_gbm._force_promote_enabled).

Used to evict a KNOWN-INVALID active model (e.g. a leaky pre-fix model whose
inflated macro-F1 blocks an honest, legitimately-lower replacement). Bypasses
ONLY the relative-vs-active comparison; the absolute class-collapse gate stays.
"""
from services.ai_modules.timeseries_gbm import _force_promote_enabled


def test_disabled_by_default():
    assert _force_promote_enabled("gap_fill_5min", None) is False
    assert _force_promote_enabled("gap_fill_5min", "") is False
    assert _force_promote_enabled("gap_fill_5min", "   ") is False


def test_global_truthy_values_enable_all():
    for v in ("1", "true", "TRUE", "all", "ALL", "*", "yes", "on"):
        assert _force_promote_enabled("any_model_name", v) is True


def test_comma_list_matches_exact_names_only():
    env = "gap_fill_5min, gap_fill_15min"
    assert _force_promote_enabled("gap_fill_5min", env) is True
    assert _force_promote_enabled("gap_fill_15min", env) is True
    assert _force_promote_enabled("gap_fill_1min", env) is False
    assert _force_promote_enabled("vol_predictor_5min", env) is False


def test_single_name():
    assert _force_promote_enabled("gap_fill_15min", "gap_fill_15min") is True
    assert _force_promote_enabled("gap_fill_5min", "gap_fill_15min") is False


def test_no_substring_false_positive():
    # a list entry must match the full name, not a prefix/substring
    assert _force_promote_enabled("gap_fill_5min_extra", "gap_fill_5min") is False
