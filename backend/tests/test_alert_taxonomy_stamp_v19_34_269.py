"""m3 — LiveAlert stamps canonical_setup / strategy_family / exit_archetype
from the SSOT on construction (additive write-path tags)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.enhanced_scanner import LiveAlert, AlertPriority  # noqa: E402


def _mk(setup_type, direction="long", **kw):
    base = dict(
        id="t", symbol="AAPL", setup_type=setup_type, strategy_name="s",
        direction=direction, priority=AlertPriority.MEDIUM, current_price=100.0,
        trigger_price=100.0, stop_loss=99.0, target=102.0, risk_reward=2.0,
        trigger_probability=0.6, win_probability=0.55, minutes_to_trigger=0,
        headline="x", reasoning=[], time_window="rth", market_regime="neutral",
    )
    base.update(kw)
    return LiveAlert(**base)


class TestAlertTaxonomyStamp:
    def test_variant_collapses_to_canonical(self):
        a = _mk("vwap_fade_short", "short")
        assert a.canonical_setup == "vwap_fade"
        assert a.strategy_family == "reversion"
        assert a.exit_archetype == "target"

    def test_momentum_runner(self):
        a = _mk("squeeze")
        assert a.canonical_setup == "squeeze"
        assert a.strategy_family == "breakout"
        assert a.exit_archetype == "runner"

    def test_confirmed_variant(self):
        a = _mk("breakout_confirmed")
        assert a.canonical_setup == "breakout"
        assert a.strategy_family == "breakout"

    def test_runner_reversal_exception(self):
        a = _mk("bouncy_ball", "short")
        assert a.canonical_setup == "bouncy_ball"
        assert a.strategy_family == "reversal"
        assert a.exit_archetype == "runner"

    def test_fields_serialized_in_to_dict(self):
        d = _mk("squeeze").to_dict()
        for k in ("canonical_setup", "strategy_family", "exit_archetype"):
            assert k in d and d[k]
