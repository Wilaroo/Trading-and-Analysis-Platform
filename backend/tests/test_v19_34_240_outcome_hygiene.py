"""
v19.34.240 — trade-outcome hygiene tests.

Covers the pure classifier + excursion floor + the edge-ranker read-side
defenses (genuine filter via constructor + absurd-R drop). These are the
logic-bearing pieces; the pnl_compute wiring is a thin application of them.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.trade_outcome_hygiene import (  # noqa: E402
    classify_close, is_genuine_close, excursion_floor,
)
from services.gameplan_edge_ranker import GamePlanEdgeRanker  # noqa: E402


# ── classifier: genuine cases ──────────────────────────────────────────────
def test_genuine_target_hit():
    g, tag = classify_close("target_hit", entry_price=100, exit_price=108,
                            net_pnl=800, hold_seconds=7200)
    assert g is True and tag == "genuine"


def test_genuine_stop_after_real_hold():
    g, _ = classify_close("stop_loss", entry_price=100, exit_price=95,
                          net_pnl=-500, hold_seconds=3600)
    assert g is True


def test_genuine_eod_close():
    assert is_genuine_close("eod_auto_close", entry_price=50, exit_price=51,
                            net_pnl=100, hold_seconds=20000) is True


# ── classifier: artifact cases ─────────────────────────────────────────────
def test_phantom_sweep_is_artifact():
    g, tag = classify_close("wrong_direction_phantom_swept_v19_29",
                            entry_price=48.7, exit_price=50.9, net_pnl=20006,
                            hold_seconds=60)
    assert g is False and tag.startswith("artifact_reason")


def test_operator_flatten_is_artifact():
    g, tag = classify_close("operator_external_flatten", entry_price=143.15,
                            exit_price=143.15, net_pnl=22903, hold_seconds=60)
    assert g is False


def test_instant_external_unwind_is_artifact():
    g, tag = classify_close("oca_closed_externally_v19_31", entry_price=48.95,
                            exit_price=49.0, net_pnl=-2, hold_seconds=60)
    assert g is False and tag == "instant_external_unwind"


def test_oca_external_with_real_hold_is_genuine():
    # Same reason but held 6.3h -> a real managed exit, NOT an instant unwind.
    g, _ = classify_close("oca_closed_externally_v19_31", entry_price=50.42,
                          exit_price=49.08, net_pnl=379, hold_seconds=22800)
    assert g is True


def test_corrupt_pnl_attribution_is_artifact():
    g, tag = classify_close("manual", entry_price=143.15, exit_price=143.15,
                            net_pnl=22903, hold_seconds=300)
    assert g is False and tag == "corrupt_pnl_attribution"


def test_reconciled_entered_by_is_artifact():
    g, tag = classify_close("stop_loss", entered_by="reconciled_external",
                            entry_price=100, exit_price=99, net_pnl=-100,
                            hold_seconds=300)
    assert g is False and tag.startswith("non_bot_entry")


# ── excursion floor ────────────────────────────────────────────────────────
def test_excursion_floor_long_winner():
    mfe, mae = excursion_floor("long", entry_price=100, exit_price=104, stop_price=98)
    assert mfe == 2.0 and mae == 0.0


def test_excursion_floor_long_loser():
    mfe, mae = excursion_floor("long", entry_price=100, exit_price=98, stop_price=98)
    assert mfe == 0.0 and mae == -1.0


def test_excursion_floor_short_winner():
    mfe, mae = excursion_floor("short", entry_price=100, exit_price=96, stop_price=102)
    assert mfe == 2.0 and mae == 0.0


def test_excursion_floor_no_stop_uses_2pct():
    mfe, _ = excursion_floor("long", entry_price=100, exit_price=102, stop_price=0)
    assert abs(mfe - 1.0) < 1e-9  # 2 / (100*0.02)


# ── edge ranker read-side defenses ─────────────────────────────────────────
def _mk(setup, outcome, r, direction="long"):
    return {"setup_type": setup, "outcome": outcome, "actual_r": r,
            "direction": direction, "context": {"market_regime": "neutral"}}


def test_ranker_drops_absurd_r_rows():
    good = [_mk("squeeze", "won", 2.0) for _ in range(6)]
    poison = [_mk("squeeze", "won", 25.0) for _ in range(6)]  # corrupt inflated R (>cap)
    r_clean = GamePlanEdgeRanker(good)
    r_poison = GamePlanEdgeRanker(good + poison)
    # absurd rows are skipped, so the L1 bucket aggregate matches the clean set
    b_clean = r_clean._b.get(("L1", "squeeze", "long"))
    b_poison = r_poison._b.get(("L1", "squeeze", "long"))
    assert b_clean["win_r_sum"] == b_poison["win_r_sum"]
    assert b_clean["wins"] == b_poison["wins"] == 6


def test_ranker_keeps_normal_r():
    rk = GamePlanEdgeRanker([_mk("orb", "won", 3.5), _mk("orb", "lost", -1.0)])
    b = rk._b.get(("L1", "orb", "long"))
    assert b["wins"] == 1 and b["losses"] == 1
