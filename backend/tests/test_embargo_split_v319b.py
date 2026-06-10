"""
v319b — train/val EMBARGO gap pins (timeseries_gbm._embargo_size).

The GBM train/val split was a plain time-ordered cut with NO embargo: the last
`forecast_horizon` training samples have forward label windows that overlap the
start of validation → mild optimistic bias. _embargo_size sizes the purge gap.
"""
import os

from services.ai_modules.timeseries_gbm import _embargo_size


def test_default_embargo_equals_horizon():
    # large train block → embargo == horizon (not clamped)
    assert _embargo_size(split_idx=10_000, forecast_horizon=45) == 45
    assert _embargo_size(split_idx=10_000, forecast_horizon=9) == 9
    assert _embargo_size(split_idx=10_000, forecast_horizon=3) == 3


def test_env_override_takes_precedence():
    assert _embargo_size(10_000, 5, env_override="20") == 20
    assert _embargo_size(10_000, 5, env_override="0") == 0


def test_invalid_env_falls_back_to_horizon():
    assert _embargo_size(10_000, 7, env_override="garbage") == 7
    assert _embargo_size(10_000, 7, env_override="   ") == 7
    assert _embargo_size(10_000, 7, env_override=None) == 7


def test_clamped_to_25pct_of_train_block():
    # horizon huge vs a small train block → capped at 25%
    assert _embargo_size(split_idx=100, forecast_horizon=90) == 25
    assert _embargo_size(split_idx=40, forecast_horizon=1000) == 10


def test_tiny_split_returns_zero():
    assert _embargo_size(split_idx=1, forecast_horizon=5) == 0
    assert _embargo_size(split_idx=0, forecast_horizon=5) == 0


def test_negative_horizon_is_floored_to_zero():
    assert _embargo_size(10_000, -5) == 0


def test_train_block_stays_non_empty():
    # whatever the inputs, train_end = split_idx - embargo must be >= 1
    for si in (2, 5, 50, 500, 5000):
        for fh in (0, 1, 3, 9, 45, 100, 100000):
            emb = _embargo_size(si, fh)
            assert 0 <= emb < si, (si, fh, emb)
            assert si - emb >= 1
