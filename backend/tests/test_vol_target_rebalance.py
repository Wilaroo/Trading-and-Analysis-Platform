"""
Regression test for v19.34.312 volatility-target rebalance.

Old target compared 20-bar trailing vol to fh-bar forward vol (length
mismatch → ~85% HIGH_VOL → model collapse). New target uses equal-length
fh-return windows → balanced (~50/50) and single/batch must agree exactly.
"""
import numpy as np
import pytest

from services.ai_modules.volatility_model import (
    compute_vol_target, compute_vol_targets_batch,
)


def _garch_series(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    vol = 0.01
    rets = []
    for _ in range(n):
        vol = 0.9 * vol + 0.1 * 0.01 + 0.05 * abs(rng.standard_normal()) * 0.01
        rets.append(rng.standard_normal() * vol)
    return 100 * np.exp(np.cumsum(rets))


@pytest.mark.parametrize("fh", [4, 12, 26])
def test_target_is_balanced(fh):
    closes = _garch_series()
    b = compute_vol_targets_batch(closes, fh, start_idx=50)
    valid = b[b >= 0]
    assert len(valid) > 1000
    frac = valid.mean()
    # Must be far from the old ~0.85 collapse; allow a fair band.
    assert 0.35 <= frac <= 0.65, f"fh={fh} HIGH_VOL frac={frac:.3f} not balanced"


@pytest.mark.parametrize("fh", [4, 12, 26])
def test_single_batch_consistency(fh):
    closes = _garch_series(seed=1)
    b = compute_vol_targets_batch(closes, fh, start_idx=50)
    mismatch = 0
    for i in range(50, 50 + len(b)):
        bv = b[i - 50]
        if bv < 0:
            continue
        s = compute_vol_target(closes, fh, i)
        if s is None or int(s) != int(bv):
            mismatch += 1
    assert mismatch == 0, f"fh={fh}: {mismatch} single/batch mismatches"
