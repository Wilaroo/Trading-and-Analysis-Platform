"""Tests for hrp_allocator — HRP + NCO portfolio allocation.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_hrp_allocator.py -v
"""
import numpy as np
import pytest

from services.ai_modules.hrp_allocator import (
    correlation_distance, quasi_diagonal, recursive_bisection,
    hrp_weights_from_returns, hrp_weights, nco_weights,
)

scipy = pytest.importorskip("scipy")


def test_correlation_distance_shape():
    corr = np.array([[1.0, 0.8, -0.1],
                     [0.8, 1.0, 0.2],
                     [-0.1, 0.2, 1.0]])
    d = correlation_distance(corr)
    # Condensed form length = n*(n-1)/2
    assert d.shape == (3,)
    # Highly correlated pair has LOW distance
    assert d[0] < d[1]   # (0,1) pair is 0.8-corr → smaller dist than (0,2)


def test_hrp_weights_sum_to_one():
    rng = np.random.default_rng(0)
    n = 5
    T = 500
    R = rng.normal(0, 0.01, (T, n))
    names = ["A", "B", "C", "D", "E"]
    w = hrp_weights_from_returns(R, asset_names=names)
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert all(ww >= 0 for ww in w.values())


def test_hrp_gives_less_weight_to_redundant_assets():
    """
    If 3 assets are highly correlated and 2 are uncorrelated, the uncorrelated
    pair should collectively get meaningful allocation (diversification).
    """
    rng = np.random.default_rng(1)
    T = 1000
    # 3 correlated assets (all follow same drift + indep noise)
    common = rng.normal(0, 0.01, T)
    a = common + rng.normal(0, 0.003, T)
    b = common + rng.normal(0, 0.003, T)
    c = common + rng.normal(0, 0.003, T)
    # 2 independent assets
    d = rng.normal(0, 0.01, T)
    e = rng.normal(0, 0.01, T)
    R = np.column_stack([a, b, c, d, e])
    names = ["A", "B", "C", "D", "E"]
    w = hrp_weights_from_returns(R, asset_names=names)

    corr_bucket = w["A"] + w["B"] + w["C"]
    uncorr_bucket = w["D"] + w["E"]
    # Uncorrelated assets should collectively have non-trivial share
    # (not dominated by the correlated cluster)
    assert uncorr_bucket > 0.25


def test_hrp_single_asset_returns_full_weight():
    w = hrp_weights_from_returns(np.array([[0.01], [0.02], [-0.01]]), ["ONLY"])
    assert w == {"ONLY": 1.0}


def test_hrp_weights_empty_candidates():
    w = hrp_weights([], np.zeros((10, 5)), {})
    assert w == {}


def test_hrp_weights_via_candidates():
    rng = np.random.default_rng(2)
    R = rng.normal(0, 0.01, (300, 4))
    col_map = {"AAPL": 0, "META": 1, "SPY": 2, "XOM": 3}
    candidates = [
        {"symbol": "AAPL", "direction": "long"},
        {"symbol": "META", "direction": "long"},
        {"symbol": "SPY", "direction": "short"},
    ]
    w = hrp_weights(candidates, R, col_map)
    assert set(w.keys()) == {"AAPL", "META", "SPY"}
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_nco_weights_sum_to_one():
    rng = np.random.default_rng(3)
    n = 6
    R = rng.normal(0, 0.01, (500, n))
    names = [f"S{i}" for i in range(n)]
    w = nco_weights(R, asset_names=names, max_clusters=3)
    assert abs(sum(w.values()) - 1.0) < 0.01   # small floating-point tolerance
    assert len(w) == n


def test_quasi_diagonal_reorders_assets():
    # Build a tiny linkage tree manually
    rng = np.random.default_rng(4)
    R = rng.normal(0, 0.01, (200, 4))
    cov = np.cov(R.T)
    sigma = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sigma, sigma)
    np.fill_diagonal(corr, 1.0)
    from scipy.cluster.hierarchy import linkage
    dist = correlation_distance(corr)
    link = linkage(dist, method="single")
    order = quasi_diagonal(link)
    assert sorted(order) == [0, 1, 2, 3]


def test_recursive_bisection_weights_normalized():
    rng = np.random.default_rng(5)
    n = 4
    R = rng.normal(0, 0.01, (300, n))
    cov = np.cov(R.T)
    order = list(range(n))
    w = recursive_bisection(cov, order)
    assert abs(w.sum() - 1.0) < 1e-6
    assert (w >= 0).all()
