"""
Tests for services/portfolio_allocator_service — HRP-based sizing multiplier.
"""
import numpy as np
import pytest

from services import portfolio_allocator_service as alloc


@pytest.fixture(autouse=True)
def _clear_fetcher():
    alloc.set_returns_fetcher(None)
    yield
    alloc.set_returns_fetcher(None)


def test_single_symbol_returns_neutral():
    mults = alloc.compute_hrp_multipliers(["AAPL"])
    assert mults == {"AAPL": 1.0}


def test_no_fetcher_returns_all_neutral():
    # 3 symbols but no fetcher registered → all neutral
    mults = alloc.compute_hrp_multipliers(["AAPL", "META", "SPY"])
    assert mults == {"AAPL": 1.0, "META": 1.0, "SPY": 1.0}


def test_fetcher_returning_none_for_all_is_neutral():
    alloc.set_returns_fetcher(lambda s: None)
    mults = alloc.compute_hrp_multipliers(["AAPL", "META"])
    assert mults == {"AAPL": 1.0, "META": 1.0}


def test_fetcher_with_too_few_observations_is_neutral():
    # Return only 5 points per symbol — below MIN_RETURN_OBSERVATIONS (10)
    alloc.set_returns_fetcher(lambda s: np.array([0.01, -0.02, 0.03, 0.0, 0.01]))
    mults = alloc.compute_hrp_multipliers(["AAPL", "META"])
    assert mults == {"AAPL": 1.0, "META": 1.0}


def test_two_uncorrelated_symbols_get_equal_weight():
    rng = np.random.default_rng(42)
    # AAPL: random walk; XLU: independent random walk
    returns = {
        "AAPL": rng.normal(0, 0.01, 60),
        "XLU": rng.normal(0, 0.01, 60),
    }
    alloc.set_returns_fetcher(lambda s: returns.get(s))
    mults = alloc.compute_hrp_multipliers(["AAPL", "XLU"])
    # Uncorrelated → equal weight → both multipliers ~1.0
    assert abs(mults["AAPL"] - 1.0) < 0.3
    assert abs(mults["XLU"] - 1.0) < 0.3


def test_highly_correlated_cluster_downweights_members():
    rng = np.random.default_rng(7)
    # Two tech stocks, near-identical; one diversifier
    base = rng.normal(0, 0.01, 80)
    returns = {
        "AAPL": base + rng.normal(0, 0.001, 80),   # ~99% corr with base
        "META": base + rng.normal(0, 0.001, 80),   # ~99% corr with base
        "XLU":  rng.normal(0, 0.01, 80),           # independent
    }
    alloc.set_returns_fetcher(lambda s: returns.get(s))
    mults = alloc.compute_hrp_multipliers(["AAPL", "META", "XLU"])
    # The correlated cluster should get smaller multipliers than the diversifier
    assert mults["XLU"] > mults["AAPL"]
    assert mults["XLU"] > mults["META"]
    # All within bounds
    for s, m in mults.items():
        assert alloc.MULTIPLIER_FLOOR <= m <= alloc.MULTIPLIER_CEILING, (s, m)


def test_multiplier_always_bounded():
    """Even extreme pathological inputs respect [floor, ceiling]."""
    rng = np.random.default_rng(0)
    n = 60
    # One perfect cluster of 10 near-duplicates + a lonely diversifier
    base = rng.normal(0, 0.01, n)
    symbols = [f"CLUSTER_{i}" for i in range(10)] + ["DIV"]
    returns = {s: base + rng.normal(0, 1e-5, n) for s in symbols[:-1]}
    returns["DIV"] = rng.normal(0, 0.01, n)
    alloc.set_returns_fetcher(lambda s: returns.get(s))
    mults = alloc.compute_hrp_multipliers(symbols)
    for s, m in mults.items():
        assert alloc.MULTIPLIER_FLOOR <= m <= alloc.MULTIPLIER_CEILING, (s, m)


def test_get_hrp_multiplier_single_peer_is_neutral():
    """Even with a fetcher, 1 symbol alone → 1.0 (no peers to relate to)."""
    alloc.set_returns_fetcher(lambda s: np.zeros(30))
    m = alloc.get_hrp_multiplier("AAPL", ["AAPL"])
    assert m == 1.0


def test_get_hrp_multiplier_returns_self_multiplier():
    rng = np.random.default_rng(1)
    returns = {
        "AAPL": rng.normal(0, 0.01, 40),
        "NVDA": rng.normal(0, 0.01, 40),
    }
    alloc.set_returns_fetcher(lambda s: returns.get(s))
    m = alloc.get_hrp_multiplier("AAPL", ["AAPL", "NVDA"])
    assert 0.4 <= m <= 1.4


def test_fetcher_exception_is_swallowed_neutral():
    def broken_fetcher(s):
        raise RuntimeError("network down")
    alloc.set_returns_fetcher(broken_fetcher)
    mults = alloc.compute_hrp_multipliers(["AAPL", "META"])
    assert mults == {"AAPL": 1.0, "META": 1.0}


def test_symbols_are_uppercased_and_deduped():
    rng = np.random.default_rng(2)
    returns = {
        "AAPL": rng.normal(0, 0.01, 30),
        "META": rng.normal(0, 0.01, 30),
    }
    alloc.set_returns_fetcher(lambda s: returns.get(s.upper()))
    mults = alloc.compute_hrp_multipliers(["aapl", "AAPL", "MEta"])
    # Should dedupe AAPL, uppercase everything
    assert set(mults.keys()) == {"AAPL", "META"}


def test_returns_aligned_to_shortest_common_length():
    """If one symbol has fewer data points, trim all to that length."""
    long = np.random.default_rng(3).normal(0, 0.01, 80)
    short = np.random.default_rng(4).normal(0, 0.01, 30)
    returns = {"AAPL": long, "META": short}
    alloc.set_returns_fetcher(lambda s: returns.get(s))
    # Should still produce multipliers, just aligned to len(30)
    mults = alloc.compute_hrp_multipliers(["AAPL", "META"])
    assert set(mults.keys()) == {"AAPL", "META"}
    for m in mults.values():
        assert alloc.MULTIPLIER_FLOOR <= m <= alloc.MULTIPLIER_CEILING


def test_set_and_get_fetcher_roundtrip():
    def fake(_s):
        return np.zeros(20)
    alloc.set_returns_fetcher(fake)
    assert alloc.get_returns_fetcher() is fake
    alloc.set_returns_fetcher(None)
    assert alloc.get_returns_fetcher() is None
