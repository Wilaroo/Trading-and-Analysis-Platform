"""n-aware significance gate for tqs_integrity anti_predictive flag.

Regression: the probe used to flag `anti_predictive` purely on |corr| < -0.05,
ignoring sample size — so it screamed on statistical noise (scalp pillars at
n~123 with |corr|<0.09, well below the 2/sqrt(n) ≈ 0.18 floor). The gate must
require the negative correlation to ALSO clear the noise floor.
"""
from services.tqs_integrity import _sig_threshold, _is_significant, _anti_predictive


def test_sig_threshold_shrinks_with_n():
    # 2/sqrt(n): smaller samples need a bigger |corr| to be believed.
    assert _sig_threshold(100) == round(2.0 / 10.0, 3)   # 0.2
    assert _sig_threshold(400) == round(2.0 / 20.0, 3)   # 0.1
    assert _sig_threshold(4) is None                     # too few to judge


def test_noise_below_floor_is_not_anti_predictive():
    # n=123, corr=-0.08 -> threshold ≈ 0.180 -> NOT significant -> NOT flagged.
    assert _is_significant(-0.08, 123) is False
    assert _anti_predictive(-0.08, 123) is False


def test_strong_negative_on_large_n_is_anti_predictive():
    # n=400, corr=-0.30 -> threshold 0.10 -> significant -> flagged.
    assert _is_significant(-0.30, 400) is True
    assert _anti_predictive(-0.30, 400) is True


def test_positive_corr_never_anti_predictive():
    assert _anti_predictive(0.30, 400) is False


def test_significant_but_tiny_negative_not_flagged():
    # Clears the floor in magnitude but is barely-negative (> -0.05) -> not anti.
    assert _anti_predictive(-0.04, 10000) is False


def test_none_corr_is_safe():
    assert _is_significant(None, 100) is False
    assert _anti_predictive(None, 100) is False
