"""
Regression tests for `smart_levels_service`.

Tests the three computational primitives in isolation (volume profile,
swing pivots, floor pivots), the cluster-and-rank pass, and the
end-to-end `compute_smart_levels` + `compute_path_multiplier` API. No
Mongo / FastAPI dependencies — pure-Python tests.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from services import smart_levels_service as sls


# ─── Synthetic bar generator ────────────────────────────────────────────

def _bars(prices: list[float], volume: float = 100_000) -> list[dict]:
    """Build a list of OHLC=close bars with ascending dates."""
    out = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, p in enumerate(prices):
        out.append({
            "symbol": "TEST",
            "bar_size": "5 mins",
            "date": (base + timedelta(minutes=5 * i)).isoformat(),
            "open": p, "high": p, "low": p, "close": p, "volume": volume,
        })
    return out


# ─── _compute_volume_profile ────────────────────────────────────────────

def test_volume_profile_picks_dominant_price_as_poc():
    """A bar set with most volume at $100 should put POC near $100."""
    bars = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 100 bars at $100 with volume 1M, 10 bars at $110 with volume 100K
    for i in range(100):
        bars.append({
            "date": (base + timedelta(minutes=5 * i)).isoformat(),
            "open": 100, "high": 100.5, "low": 99.5, "close": 100, "volume": 1_000_000,
        })
    for i in range(100, 110):
        bars.append({
            "date": (base + timedelta(minutes=5 * i)).isoformat(),
            "open": 110, "high": 110.5, "low": 109.5, "close": 110, "volume": 100_000,
        })
    vp = sls._compute_volume_profile(bars, num_bins=64)
    assert vp["poc_price"] is not None
    assert 99 <= vp["poc_price"] <= 101


def test_volume_profile_returns_empty_when_all_volume_zero():
    bars = _bars([100, 101, 102, 103, 104], volume=0)
    vp = sls._compute_volume_profile(bars, num_bins=32)
    assert vp == {"poc_price": None, "hvn_prices": []}


# ─── _compute_swing_pivots ──────────────────────────────────────────────

def test_swing_pivots_detect_local_peaks_and_troughs():
    # Up-down-up pattern: the middle peak at index 5 should be detected.
    bars = _bars([100, 101, 102, 103, 104, 110, 104, 103, 102, 101, 100])
    highs, lows = sls._compute_swing_pivots(bars, k=2)
    # The 110 spike is a swing high
    assert any(abs(h - 110) < 1e-6 for h in highs)
    # 100 at edges is NOT a pivot (need ±k bars on both sides)


def test_swing_pivots_safe_on_short_series():
    bars = _bars([100, 101, 102])
    highs, lows = sls._compute_swing_pivots(bars, k=5)
    assert highs == [] and lows == []


# ─── _compute_floor_pivots ──────────────────────────────────────────────

def test_floor_pivots_match_canonical_formulas():
    # Yesterday: H=110, L=90, C=100
    fp = sls._compute_floor_pivots(110, 90, 100)
    assert abs(fp["pp"] - 100) < 1e-9
    assert abs(fp["r1"] - 110) < 1e-9   # 2*100 - 90
    assert abs(fp["s1"] -  90) < 1e-9   # 2*100 - 110
    assert abs(fp["r2"] - 120) < 1e-9   # PP + (H-L) = 100 + 20
    assert abs(fp["s2"] -  80) < 1e-9


# ─── compute_smart_levels (end-to-end with mock db) ─────────────────────

def _make_db_with_bars(bars_5min, bars_1day=None):
    db = MagicMock()
    coll = MagicMock()

    def find(query, projection):
        bs = query.get("bar_size")
        if bs == "5 mins":
            data = list(bars_5min)
        elif bs == "1 day":
            data = list(bars_1day or [])
        elif bs == "1 week":
            data = list(bars_1day or [])
        else:
            data = []
        cursor = MagicMock()
        # sort(...).limit(...) returns the data; no need for true sort
        # since helper feeds in ascending order and the loader reverses.
        cursor.sort.return_value.limit.return_value = list(reversed(data))
        return cursor

    coll.find.side_effect = find
    db.__getitem__.return_value = coll
    return db


def test_compute_smart_levels_returns_support_and_resistance():
    bars_5min = _bars([100, 100.5, 101, 100, 99, 98, 99, 100, 101, 102] * 10)
    bars_1day = _bars([99, 100, 101], volume=10_000_000)
    db = _make_db_with_bars(bars_5min, bars_1day)

    out = sls.compute_smart_levels(db, "TEST", "5min")
    assert "support" in out and "resistance" in out
    assert out["timeframe"] == "5min"
    assert out.get("error") is None
    # POC + at least one floor pivot should appear in sources
    assert out["sources"]["vp_poc"] is not None
    assert "pp" in out["sources"]["floor_pivots"]


def test_compute_smart_levels_unsupported_timeframe():
    db = _make_db_with_bars([])
    out = sls.compute_smart_levels(db, "TEST", "bogus")
    assert out["error"] == "unsupported timeframe 'bogus'"
    assert out["support"] == [] and out["resistance"] == []


def test_compute_smart_levels_insufficient_bars():
    bars = _bars([100, 101, 102])  # < 10 → bail
    db = _make_db_with_bars(bars, [])
    out = sls.compute_smart_levels(db, "TEST", "5min")
    assert out["error"] == "insufficient bars"


# ─── compute_path_multiplier ────────────────────────────────────────────

def test_path_multiplier_thick_hvn_in_stop_zone_downsizes():
    """Long entry at 100, stop at 95. If most volume traded between 95
    and 100, the stop zone is "fat" → multiplier 0.7."""
    bars = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 200 bars centered at $97 (well inside the [95, 100] path corridor)
    # with high volume — should make the path corridor look fat.
    for i in range(200):
        bars.append({
            "date": (base + timedelta(minutes=5 * i)).isoformat(),
            "open": 97, "high": 97.5, "low": 96.5, "close": 97, "volume": 1_000_000,
        })
    # A handful of bars at $105 with low volume
    for i in range(200, 220):
        bars.append({
            "date": (base + timedelta(minutes=5 * i)).isoformat(),
            "open": 105, "high": 106, "low": 104, "close": 105, "volume": 50_000,
        })
    db = _make_db_with_bars(bars)
    out = sls.compute_path_multiplier(db, "TEST", "5 mins", entry=100.0, stop=95.0, direction="long")
    assert out["multiplier"] == sls._PATH_MULT_FAT
    assert out["reason"] == "thick_hvn_in_stop_zone"


def test_path_multiplier_clean_lvn_full_size():
    """Long entry at 100, stop at 95. If almost no volume traded in
    [95, 100], the path is clean → full size 1.0."""
    bars = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # All volume at $80 and $120 — none in the [95, 100] corridor.
    for i in range(150):
        bars.append({
            "date": (base + timedelta(minutes=5 * i)).isoformat(),
            "open": 80, "high": 80.5, "low": 79.5, "close": 80, "volume": 1_000_000,
        })
    for i in range(150, 300):
        bars.append({
            "date": (base + timedelta(minutes=5 * i)).isoformat(),
            "open": 120, "high": 121, "low": 119, "close": 120, "volume": 1_000_000,
        })
    db = _make_db_with_bars(bars)
    out = sls.compute_path_multiplier(db, "TEST", "5 mins", entry=100.0, stop=95.0, direction="long")
    assert out["multiplier"] == sls._PATH_MULT_LEAN


def test_path_multiplier_invalid_inputs_default_to_one():
    db = _make_db_with_bars(_bars([100, 101, 102]))
    out = sls.compute_path_multiplier(db, "TEST", "5 mins", entry=100, stop=100, direction="long")
    assert out["multiplier"] == 1.0
    assert out["reason"] == "insufficient_data"


def test_path_multiplier_unknown_direction():
    db = _make_db_with_bars(_bars([100, 101, 102] * 30, volume=1_000_000))
    out = sls.compute_path_multiplier(db, "TEST", "5 mins", entry=100, stop=95, direction="diagonal")
    assert out["multiplier"] == 1.0
    assert out["reason"] == "unknown_direction"


# ─── compute_stop_guard ────────────────────────────────────────────────

def _build_db_with_smart_levels(monkeypatch, support_levels, resistance_levels):
    """Patch `compute_smart_levels` to return canned levels so we can
    test the snap logic without seeding a full bar profile."""
    canned = {
        "current_price": 100.0,
        "support":    support_levels,
        "resistance": resistance_levels,
        "sources": {},
        "timeframe": "5min",
    }
    monkeypatch.setattr(sls, "compute_smart_levels", lambda *_a, **_kw: canned)
    return MagicMock()


def test_stop_guard_widens_long_stop_to_just_below_nearby_support(monkeypatch):
    """Long stop at 95.10 with strong HVN at 95.00 → snap to 94.94."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[
            {"price": 95.00, "kind": "HVN", "strength": 0.8},
        ],
        resistance_levels=[],
    )
    out = sls.compute_stop_guard(
        db, "TEST", "5 mins",
        entry=100.0, proposed_stop=95.10, direction="long",
    )
    assert out["snapped"] is True
    assert out["reason"] == "snapped_below_support"
    assert out["level_kind"] == "HVN"
    assert out["stop"] < 95.00


def test_stop_guard_does_not_widen_when_stop_is_clear_of_levels(monkeypatch):
    """Long stop at 95 with nearest support at 90 → leaves stop alone."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[{"price": 90.00, "kind": "HVN", "strength": 0.9}],
        resistance_levels=[],
    )
    out = sls.compute_stop_guard(
        db, "TEST", "5 mins",
        entry=100.0, proposed_stop=95.0, direction="long",
    )
    assert out["snapped"] is False
    assert out["stop"] == 95.0


def test_stop_guard_caps_widening_to_max_widen_pct(monkeypatch):
    """If snapping would push stop > +40% of original distance, refuse
    to snap (preserves sizing risk math)."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[
            # entry=100, proposed_stop=99 (1pt distance). Level at 98.6
            # ⇒ new_distance ≈ 1.4, +40% boundary = 1.40 — sits AT cap.
            # So make level 98.4 so widen_pct = 0.6 (60%) and breaches.
            {"price": 98.40, "kind": "HVN", "strength": 0.8},
        ],
        resistance_levels=[],
    )
    out = sls.compute_stop_guard(
        db, "TEST", "5 mins",
        entry=100.0, proposed_stop=99.0, direction="long",
    )
    assert out["snapped"] is False
    assert out["reason"] == "would_exceed_max_widen"
    assert out["stop"] == 99.0


def test_stop_guard_filters_weak_levels(monkeypatch):
    """A level with strength < 0.5 should not trigger a snap even if
    it sits in the buffer zone."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[{"price": 95.00, "kind": "HVN", "strength": 0.30}],
        resistance_levels=[],
    )
    out = sls.compute_stop_guard(
        db, "TEST", "5 mins",
        entry=100.0, proposed_stop=95.10, direction="long",
    )
    assert out["snapped"] is False


def test_stop_guard_widens_short_stop_to_just_above_nearby_resistance(monkeypatch):
    """Short stop at 104.90 with strong R1 at 105.00 → snap above."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[],
        resistance_levels=[{"price": 105.00, "kind": "R1", "strength": 0.7}],
    )
    out = sls.compute_stop_guard(
        db, "TEST", "5 mins",
        entry=100.0, proposed_stop=104.90, direction="short",
    )
    assert out["snapped"] is True
    assert out["reason"] == "snapped_above_resistance"
    assert out["stop"] > 105.00


def test_stop_guard_invalid_inputs():
    out = sls.compute_stop_guard(MagicMock(), "TEST", "5 mins",
                                 entry=100, proposed_stop=100, direction="long")
    assert out["snapped"] is False
    assert out["reason"] == "invalid_inputs"


def test_stop_guard_unknown_direction(monkeypatch):
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[{"price": 95.00, "kind": "HVN", "strength": 0.9}],
        resistance_levels=[],
    )
    out = sls.compute_stop_guard(
        db, "TEST", "5 mins",
        entry=100.0, proposed_stop=95.10, direction="diagonal",
    )
    assert out["snapped"] is False
    assert out["reason"] == "unknown_direction"


# ─── compute_target_snap ───────────────────────────────────────────────

def test_target_snap_pulls_long_target_below_nearby_resistance(monkeypatch):
    """Long entry 100, target 102.50, R1 at 102.40 → snap to 102.34."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[],
        resistance_levels=[
            {"price": 102.40, "kind": "R1", "strength": 0.7},
        ],
    )
    out = sls.compute_target_snap(
        db, "TEST", "5 mins",
        entry=100.0, proposed_targets=[102.50], direction="long",
    )
    assert out["any_snapped"] is True
    assert out["targets"][0] < 102.40
    d0 = out["details"][0]
    assert d0["snapped"] is True and d0["level_kind"] == "R1"


def test_target_snap_extends_long_target_when_resistance_just_above(monkeypatch):
    """Long entry 100, target 102.00, HVN at 102.30 (just above) →
    extend target to 102.24 (just before HVN)."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[],
        resistance_levels=[{"price": 102.30, "kind": "HVN", "strength": 0.8}],
    )
    out = sls.compute_target_snap(
        db, "TEST", "5 mins",
        entry=100.0, proposed_targets=[102.00], direction="long",
    )
    assert out["any_snapped"] is True
    # Should be EXTENDED (further from entry, i.e. > 102.00) and just below 102.30
    assert out["targets"][0] > 102.00
    assert out["targets"][0] < 102.30


def test_target_snap_leaves_targets_alone_when_no_levels_nearby(monkeypatch):
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[],
        resistance_levels=[{"price": 110.00, "kind": "HVN", "strength": 0.8}],
    )
    out = sls.compute_target_snap(
        db, "TEST", "5 mins",
        entry=100.0, proposed_targets=[101.50, 102.50, 104.00], direction="long",
    )
    assert out["any_snapped"] is False
    assert out["targets"] == [101.50, 102.50, 104.00]


def test_target_snap_dedupes_collapsed_targets(monkeypatch):
    """If two pre-snap targets get pulled onto the same resistance,
    the second is nudged ε past the first to preserve TP1<TP2 ordering."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[],
        resistance_levels=[{"price": 102.00, "kind": "R1", "strength": 0.8}],
    )
    out = sls.compute_target_snap(
        db, "TEST", "5 mins",
        entry=100.0, proposed_targets=[102.10, 102.20], direction="long",
    )
    assert out["targets"][0] != out["targets"][1]
    assert out["targets"][0] < out["targets"][1]
    # Second target gets `deduped` flag in its detail
    assert out["details"][1].get("deduped") is True


def test_target_snap_filters_weak_levels(monkeypatch):
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[],
        resistance_levels=[{"price": 102.40, "kind": "SWING_HIGH", "strength": 0.30}],
    )
    out = sls.compute_target_snap(
        db, "TEST", "5 mins",
        entry=100.0, proposed_targets=[102.50], direction="long",
    )
    assert out["any_snapped"] is False


def test_target_snap_caps_excessive_pull(monkeypatch):
    """Snap shouldn't tighten target by more than 30% of original
    distance even when a strong level sits in the buffer."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        # Original: entry=100, target=110 (10 distance). Resistance at
        # 100.50 → would tighten to 100.44, which is -95% (way past
        # the 30% pull cap). Must refuse.
        support_levels=[],
        resistance_levels=[{"price": 100.50, "kind": "HVN", "strength": 0.9}],
    )
    out = sls.compute_target_snap(
        db, "TEST", "5 mins",
        entry=100.0, proposed_targets=[110.0], direction="long",
    )
    assert out["any_snapped"] is False
    assert out["details"][0]["reason"] in {"would_exceed_target_caps", "no_nearby_level"}


def test_target_snap_pulls_short_target_above_nearby_support(monkeypatch):
    """Short entry 100, target 97.50, S1 at 97.60 → snap above 97.60."""
    db = _build_db_with_smart_levels(
        monkeypatch,
        support_levels=[{"price": 97.60, "kind": "S1", "strength": 0.7}],
        resistance_levels=[],
    )
    out = sls.compute_target_snap(
        db, "TEST", "5 mins",
        entry=100.0, proposed_targets=[97.50], direction="short",
    )
    assert out["any_snapped"] is True
    assert out["targets"][0] > 97.60
    assert out["details"][0]["level_kind"] == "S1"


def test_target_snap_empty_targets_returns_empty():
    out = sls.compute_target_snap(
        MagicMock(), "TEST", "5 mins",
        entry=100.0, proposed_targets=[], direction="long",
    )
    assert out == {"targets": [], "details": [], "any_snapped": False}
