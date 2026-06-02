"""
v19.34.228 — TQS grade calibration tests.

Validates the percentile-rank grading + absolute-floor (hybrid) demotion +
static-band fallback. Reference cache is injected directly so no DB is needed.
"""
import time

import pytest

from services.tqs import grade_calibration as gc


def _inject_reference(scores):
    """Pre-fill the cache so calibrate_grade uses it (no DB refresh)."""
    gc._cache.sorted_scores = sorted(float(s) for s in scores)
    gc._cache.n = len(scores)
    gc._cache.fetched_at = time.time()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Deterministic defaults; calibration enabled; tiny min-sample for tests.
    for k in list(gc.os.environ):
        if k.startswith("TQS_CAL_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TQS_CAL_MIN_SAMPLE", "10")
    monkeypatch.setenv("TQS_CAL_TTL_SEC", "9999")
    yield
    gc._cache.sorted_scores = []
    gc._cache.n = 0
    gc._cache.fetched_at = 0.0


def test_percentile_spread_produces_all_grades():
    # uniform 48..67 reference (matches the real compressed band). n=1000.
    # cuts A>=90,B>=70,C>=35,D>=10 ⇒ A:s>=65, B:61-64, C:54-60, D:49-53, F:48
    ref = list(range(48, 68)) * 50  # n=1000
    _inject_reference(ref)
    assert gc.calibrate_grade(67) == "A"   # rank 100, >= floor 60
    assert gc.calibrate_grade(64) == "B"   # rank 85, >= floor 57
    assert gc.calibrate_grade(56) == "C"   # rank 45
    assert gc.calibrate_grade(48) == "F"   # rank 5


def test_absolute_floor_demotes_high_rank_low_score():
    # Reference where the TOP decile is still absolutely mediocre (<=56),
    # so percentile says A but the floor (60) must demote it.
    ref = [50] * 900 + [55, 56] * 50  # n=1000, top values ~55-56
    _inject_reference(ref)
    # 56 is top-rank here but well below floor A=60 and B=57 → demote to C
    g = gc.calibrate_grade(56)
    assert g in ("C", "D"), g  # NOT A or B
    assert g != "A"


def test_floor_allows_when_score_high_enough():
    ref = list(range(48, 68)) * 50
    _inject_reference(ref)
    # 65 is top-decile rank (>=90) AND above floor A(60) → should be A
    assert gc.calibrate_grade(65) == "A"


def test_static_fallback_when_reference_too_small(monkeypatch):
    monkeypatch.setenv("TQS_CAL_MIN_SAMPLE", "10000")  # force "too small"
    _inject_reference(list(range(48, 68)) * 50)  # n=1000 < 10000
    # falls back to static bands: 56 → C+ (>=55)
    assert gc.calibrate_grade(56) == "C+"
    # 90 → A on static bands
    assert gc.calibrate_grade(90) == "A"


def test_disabled_uses_static(monkeypatch):
    monkeypatch.setenv("TQS_CAL_ENABLED", "false")
    _inject_reference(list(range(48, 68)) * 50)
    # static bands: 66 >= 65 → "B"; 56 -> "C+"
    assert gc.calibrate_grade(66) == "B"
    assert gc.calibrate_grade(56) == "C+"


def test_monotonic_non_decreasing():
    """Higher raw score must never produce a worse grade (safety invariant)."""
    _inject_reference(list(range(48, 68)) * 50)
    order = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4}
    last = -1
    for s in range(48, 68):
        g = gc.calibrate_grade(s)
        assert order[g] >= last, f"grade dropped at score {s}: {g}"
        last = order[g]


def test_bad_input_is_F():
    _inject_reference(list(range(48, 68)) * 50)
    assert gc.calibrate_grade(None) == "F"
    assert gc.calibrate_grade("x") == "F"
