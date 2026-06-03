"""
v19.34.247 — EOD-aware thresholds (two related fixes).

(1) FALSE "IB PUSHER DEAD" banner near EOD
    The hard 30s dead threshold tripped during the natural EOD push
    slowdown (thin ticks into the bell + the serialized 15:45 flatten
    loop lagging the push-data handler). `_resolve_pusher_dead_threshold`
    relaxes the threshold (default 120s) inside the 15:40-16:05 ET window.

(2) STALE "EOD fires at 3:55pm" gate text
    The no-new-entries gate hardcoded HARD_CUT=15:55 / SOFT_CUT=15:45 and
    emitted "past 3:55pm ET" stream text — but the EOD-flatten loop moved
    to 15:45 ET in v19.34.154. `_eod_cut_times` re-pins the HARD cut to the
    bot's ACTUAL flatten time and builds all operator-facing strings from
    it, so no fresh entry is opened after the flatten loop starts and the
    banner never goes stale.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.opportunity_evaluator import _eod_cut_times, _eod_fmt12  # noqa: E402
from routers.ib import _resolve_pusher_dead_threshold  # noqa: E402


# ── (2) EOD cut-time resolver ───────────────────────────────────────
def test_hard_cut_pinned_to_flatten_time_1545():
    cuts = _eod_cut_times(15, 45, grace_min=10)
    assert cuts["hard_cut"] == 15 * 60 + 45      # no fresh entry once flatten starts
    assert cuts["soft_cut"] == 15 * 60 + 35      # 10-min warn window before
    assert cuts["hard_str"] == "3:45pm"          # never the stale 3:55
    assert cuts["soft_str"] == "3:35pm"
    assert cuts["hard_hhmm"] == "15:45"


def test_half_day_cut_1255():
    cuts = _eod_cut_times(12, 55, grace_min=10)
    assert cuts["hard_cut"] == 12 * 60 + 55
    assert cuts["hard_str"] == "12:55pm"
    assert cuts["soft_str"] == "12:45pm"


def test_grace_is_configurable():
    cuts = _eod_cut_times(15, 45, grace_min=20)
    assert cuts["soft_cut"] == 15 * 60 + 25
    assert cuts["soft_str"] == "3:25pm"


def test_fmt12_edges():
    assert _eod_fmt12(15, 45) == "3:45pm"
    assert _eod_fmt12(12, 0) == "12:00pm"
    assert _eod_fmt12(16, 5) == "4:05pm"


# ── (1) Pusher-dead threshold resolver ──────────────────────────────
def _clear_env():
    for k in (
        "PUSHER_DEAD_THRESHOLD_S", "PUSHER_DEAD_EOD_THRESHOLD_S",
        "PUSHER_DEAD_EOD_WINDOW_START_MIN", "PUSHER_DEAD_EOD_WINDOW_END_MIN",
    ):
        os.environ.pop(k, None)


def test_normal_threshold_midday():
    _clear_env()
    thr, in_eod = _resolve_pusher_dead_threshold(11 * 60)  # 11:00 ET
    assert thr == 30
    assert in_eod is False


def test_relaxed_threshold_in_eod_window():
    _clear_env()
    # 15:50 ET — inside the relax window, mid 15:45 flatten slowdown.
    thr, in_eod = _resolve_pusher_dead_threshold(15 * 60 + 50)
    assert thr == 120
    assert in_eod is True


def test_window_boundaries():
    _clear_env()
    assert _resolve_pusher_dead_threshold(15 * 60 + 40)[1] is True   # start inclusive
    assert _resolve_pusher_dead_threshold(16 * 60 + 5)[1] is False   # end exclusive
    assert _resolve_pusher_dead_threshold(15 * 60 + 39)[1] is False  # just before


def test_clock_unavailable_uses_normal():
    _clear_env()
    thr, in_eod = _resolve_pusher_dead_threshold(None)
    assert thr == 30
    assert in_eod is False


def test_env_overrides_respected():
    _clear_env()
    os.environ["PUSHER_DEAD_THRESHOLD_S"] = "45"
    os.environ["PUSHER_DEAD_EOD_THRESHOLD_S"] = "180"
    try:
        assert _resolve_pusher_dead_threshold(11 * 60)[0] == 45
        assert _resolve_pusher_dead_threshold(15 * 60 + 50)[0] == 180
    finally:
        _clear_env()
