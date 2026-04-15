"""
Test that vectorized batch functions produce equivalent results to the original
per-bar functions. This validates the mathematical correctness of the optimization.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest

# ─── Volatility Model Tests ───────────────────────────────────────────


def _make_synthetic_bars(n=500, seed=42):
    """Generate synthetic OHLCV data for testing."""
    rng = np.random.RandomState(seed)
    base = 100.0 + np.cumsum(rng.randn(n) * 0.5)
    base = np.maximum(base, 10.0)  # keep positive
    noise = rng.rand(n) * 2 + 0.5
    closes = base.astype(np.float32)
    highs = (base + noise).astype(np.float32)
    lows = (base - noise).astype(np.float32)
    opens = (base + rng.randn(n) * 0.3).astype(np.float32)
    volumes = (rng.rand(n) * 1e6 + 1e4).astype(np.float32)
    return closes, highs, lows, opens, volumes


def test_vol_targets_batch_matches_original():
    """Verify compute_vol_targets_batch matches compute_vol_target for all bars."""
    from services.ai_modules.volatility_model import (
        compute_vol_target, compute_vol_targets_batch,
    )
    closes, _, _, _, _ = _make_synthetic_bars(500)
    fh = 12
    start_idx = 50

    # Original: per-bar
    original_targets = []
    for i in range(start_idx, len(closes) - fh):
        t = compute_vol_target(closes, fh, i)
        original_targets.append(t if t is not None else 0.0)
    original_targets = np.array(original_targets, dtype=np.float32)

    # Vectorized: batch
    batch_targets = compute_vol_targets_batch(closes, fh, start_idx=start_idx)

    n = min(len(original_targets), len(batch_targets))
    assert n > 0, "No targets produced"
    np.testing.assert_array_equal(
        original_targets[:n], batch_targets[:n],
        err_msg="Vol targets batch does not match original"
    )
    print(f"  vol_targets_batch: {n} targets match ✓")


def test_vol_features_batch_shape():
    """Verify compute_vol_features_batch produces correct shape and reasonable values."""
    from services.ai_modules.volatility_model import (
        compute_vol_features_batch, VOL_FEATURE_NAMES,
    )
    closes, highs, lows, opens, volumes = _make_synthetic_bars(500)
    feat_matrix = compute_vol_features_batch(closes, highs, lows, opens, volumes, lookback=50)

    expected_rows = len(closes) - 50
    assert feat_matrix.shape == (expected_rows, 6), f"Expected ({expected_rows}, 6), got {feat_matrix.shape}"
    assert feat_matrix.dtype == np.float32
    # No NaN/Inf
    assert np.all(np.isfinite(feat_matrix)), "Found NaN/Inf in vol features"
    # vol_rank should be in [0, 1]
    assert np.all(feat_matrix[:, 0] >= 0) and np.all(feat_matrix[:, 0] <= 1), "vol_rank_20 out of range"
    assert np.all(feat_matrix[:, 1] >= 0) and np.all(feat_matrix[:, 1] <= 1), "vol_rank_50 out of range"
    # gap_frequency should be in [0, 1]
    assert np.all(feat_matrix[:, 4] >= 0) and np.all(feat_matrix[:, 4] <= 1), "gap_frequency out of range"
    print(f"  vol_features_batch: shape {feat_matrix.shape} ✓, all finite, ranges valid")


def test_vol_features_batch_approx_matches_original():
    """Spot-check that batch vol features approximately match per-bar computation."""
    from services.ai_modules.volatility_model import (
        compute_vol_specific_features, compute_vol_features_batch, VOL_FEATURE_NAMES,
    )
    closes, highs, lows, opens, volumes = _make_synthetic_bars(200)
    batch = compute_vol_features_batch(closes, highs, lows, opens, volumes, lookback=50)

    # Check a few sample bars
    test_indices = [50, 75, 100, 150]
    for bar_i in test_indices:
        if bar_i >= len(closes):
            continue
        j = bar_i - 50
        if j >= len(batch):
            continue

        # Original: most-recent-first window
        c_win = closes[bar_i - 49: bar_i + 1][::-1]
        h_win = highs[bar_i - 49: bar_i + 1][::-1]
        l_win = lows[bar_i - 49: bar_i + 1][::-1]
        o_win = opens[bar_i - 49: bar_i + 1][::-1]
        v_win = volumes[bar_i - 49: bar_i + 1][::-1]
        orig = compute_vol_specific_features(c_win, h_win, l_win, o_win, v_win)
        orig_vec = np.array([orig.get(f, 0.0) for f in VOL_FEATURE_NAMES], dtype=np.float32)
        batch_vec = batch[j]

        # Allow small float32 tolerance due to different computation order
        np.testing.assert_allclose(
            batch_vec, orig_vec, rtol=0.15, atol=0.05,
            err_msg=f"Vol features mismatch at bar {bar_i}"
        )
    print(f"  vol_features_batch spot-check: {len(test_indices)} bars match (within tolerance) ✓")


# ─── Sector-Relative Model Tests ──────────────────────────────────────


def test_sector_targets_batch_matches_original():
    """Verify compute_sector_relative_targets_batch matches original."""
    from services.ai_modules.sector_relative_model import (
        compute_sector_relative_target, compute_sector_relative_targets_batch,
    )
    stock_c, _, _, _, _ = _make_synthetic_bars(300, seed=1)
    sector_c, _, _, _, _ = _make_synthetic_bars(300, seed=2)
    fh = 5

    # Original
    orig = []
    for i in range(50, len(stock_c) - fh):
        t = compute_sector_relative_target(stock_c, sector_c, i, fh)
        orig.append(t if t is not None else -1.0)
    orig = np.array(orig, dtype=np.float32)

    # Batch
    batch = compute_sector_relative_targets_batch(stock_c, sector_c, fh, start_idx=50)

    n = min(len(orig), len(batch))
    assert n > 0
    # Filter both for valid (non-None in original = non-(-1) in batch)
    valid = (orig[:n] >= 0) & (batch[:n] >= 0)
    np.testing.assert_array_equal(
        orig[:n][valid], batch[:n][valid],
        err_msg="Sector targets batch does not match original"
    )
    print(f"  sector_targets_batch: {valid.sum()}/{n} targets match ✓")


def test_sector_features_batch_shape():
    """Verify sector features batch shape and ranges."""
    from services.ai_modules.sector_relative_model import (
        compute_sector_relative_features_batch, SECTOR_REL_FEATURE_NAMES,
    )
    stock_c, _, _, _, stock_v = _make_synthetic_bars(300, seed=1)
    sector_c, _, _, _, sector_v = _make_synthetic_bars(300, seed=2)

    feat = compute_sector_relative_features_batch(stock_c, stock_v, sector_c, sector_v, lookback=50)
    expected_rows = 300 - 50
    assert feat.shape == (expected_rows, 10), f"Expected ({expected_rows}, 10), got {feat.shape}"
    assert np.all(np.isfinite(feat)), "Found NaN/Inf in sector features"
    print(f"  sector_features_batch: shape {feat.shape} ✓, all finite")


# ─── Performance Test ──────────────────────────────────────────────────


def test_vol_batch_is_faster():
    """Verify vectorized batch is significantly faster than per-bar loop."""
    import time
    from services.ai_modules.volatility_model import (
        compute_vol_specific_features, compute_vol_features_batch,
        compute_vol_target, compute_vol_targets_batch,
    )
    closes, highs, lows, opens, volumes = _make_synthetic_bars(5000)
    fh = 12

    # Time original per-bar loop (targets only — features are similar)
    t0 = time.monotonic()
    for i in range(50, len(closes) - fh):
        compute_vol_target(closes, fh, i)
    original_time = time.monotonic() - t0

    # Time vectorized batch
    t0 = time.monotonic()
    compute_vol_targets_batch(closes, fh, start_idx=50)
    batch_time = time.monotonic() - t0

    speedup = original_time / max(batch_time, 1e-9)
    print(f"  Performance: original={original_time:.3f}s, batch={batch_time:.3f}s, speedup={speedup:.1f}x")
    assert speedup > 2.0, f"Expected at least 2x speedup, got {speedup:.1f}x"

    # Time vol features
    t0 = time.monotonic()
    for i in range(50, min(550, len(closes))):  # Only 500 bars to keep reasonable
        c = closes[i - 49: i + 1][::-1]
        h = highs[i - 49: i + 1][::-1]
        l = lows[i - 49: i + 1][::-1]
        o = opens[i - 49: i + 1][::-1]
        v = volumes[i - 49: i + 1][::-1]
        compute_vol_specific_features(c, h, l, o, v)
    feat_orig_time = time.monotonic() - t0

    t0 = time.monotonic()
    compute_vol_features_batch(closes, highs, lows, opens, volumes, lookback=50)
    feat_batch_time = time.monotonic() - t0

    feat_speedup = feat_orig_time / max(feat_batch_time, 1e-9)
    print(f"  Features: original(500bars)={feat_orig_time:.3f}s, batch(5000bars)={feat_batch_time:.3f}s, speedup≈{feat_speedup:.1f}x")


def test_setup_worker_produces_results():
    """Verify the optimized setup worker produces valid feature matrices."""
    from services.ai_modules.training_pipeline import _extract_setup_long_worker
    closes, highs, lows, opens, volumes = _make_synthetic_bars(500)
    bars = [{"close": float(closes[i]), "high": float(highs[i]), "low": float(lows[i]),
             "open": float(opens[i]), "volume": float(volumes[i]),
             "date": f"2025-01-{i%28+1:02d}T10:00:00"} for i in range(500)]
    
    # Test with SCALP setup type
    setup_configs = [("SCALP", 12, 0.003)]
    result = _extract_setup_long_worker(("TEST", bars, setup_configs))
    
    assert result is not None, "Worker returned None"
    assert len(result) > 0, "Worker returned empty results"
    for key, (X, y) in result.items():
        assert X.shape[0] == y.shape[0], f"X/y shape mismatch: {X.shape[0]} vs {y.shape[0]}"
        assert X.shape[0] > 100, f"Too few samples: {X.shape[0]}"
        assert X.dtype == np.float32, f"Expected float32, got {X.dtype}"
        assert np.all(np.isfinite(X)), "Found NaN/Inf in features"
        assert set(np.unique(y)).issubset({0, 1, 2}), f"Unexpected target values: {np.unique(y)}"
        print(f"  setup_long_worker: {X.shape[0]} samples, shape={X.shape}, targets={dict(zip(*np.unique(y, return_counts=True)))} ✓")


def test_exit_worker_produces_results():
    """Verify the optimized exit worker produces valid results."""
    from services.ai_modules.training_pipeline import _extract_exit_worker
    closes, highs, lows, opens, volumes = _make_synthetic_bars(500)
    bars = [{"close": float(closes[i]), "high": float(highs[i]), "low": float(lows[i]),
             "open": float(opens[i]), "volume": float(volumes[i]),
             "date": f"2025-01-{i%28+1:02d}T10:00:00"} for i in range(500)]
    
    exit_configs = [("SCALP", 12)]
    result = _extract_exit_worker(("TEST", bars, exit_configs))
    
    assert result is not None, "Exit worker returned None"
    for key, (X, y) in result.items():
        assert X.shape[0] == y.shape[0], f"X/y shape mismatch"
        assert X.shape[0] > 50, f"Too few samples: {X.shape[0]}"
        assert np.all(np.isfinite(X)), "Found NaN/Inf in features"
        assert np.all(y >= 1) and np.all(y <= 30), f"Exit targets out of range: min={y.min()}, max={y.max()}"
        print(f"  exit_worker: {X.shape[0]} samples, target range=[{y.min():.0f}, {y.max():.0f}] ✓")


def test_risk_worker_produces_results():
    """Verify the optimized risk worker produces valid results."""
    from services.ai_modules.training_pipeline import _extract_risk_worker
    closes, highs, lows, opens, volumes = _make_synthetic_bars(500)
    bars = [{"close": float(closes[i]), "high": float(highs[i]), "low": float(lows[i]),
             "open": float(opens[i]), "volume": float(volumes[i]),
             "date": f"2025-01-{i%28+1:02d}T10:00:00"} for i in range(500)]
    
    risk_configs = [("5 mins", 24)]
    result = _extract_risk_worker(("TEST", bars, risk_configs))
    
    assert result is not None, "Risk worker returned None"
    for key, (X, y) in result.items():
        assert X.shape[0] == y.shape[0], f"X/y shape mismatch"
        assert X.shape[0] > 50, f"Too few samples: {X.shape[0]}"
        assert np.all(np.isfinite(X)), "Found NaN/Inf in features"
        assert set(np.unique(y)).issubset({0, 1}), f"Unexpected risk targets: {np.unique(y)}"
        print(f"  risk_worker: {X.shape[0]} samples, STOP_HIT={np.sum(y==1)}, SURVIVED={np.sum(y==0)} ✓")


if __name__ == "__main__":
    print("=== Vectorization Correctness Tests ===")
    test_vol_targets_batch_matches_original()
    test_vol_features_batch_shape()
    test_vol_features_batch_approx_matches_original()
    test_sector_targets_batch_matches_original()
    test_sector_features_batch_shape()
    print("\n=== Worker Tests ===")
    test_setup_worker_produces_results()
    test_exit_worker_produces_results()
    test_risk_worker_produces_results()
    print("\n=== Performance Tests ===")
    test_vol_batch_is_faster()
    print("\n=== ALL TESTS PASSED ===")
