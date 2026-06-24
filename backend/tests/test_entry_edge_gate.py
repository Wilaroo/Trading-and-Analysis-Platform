"""Synthetic, DB-free proof of the LIVE Entry Edge gate: a known-BAD archetype
cell gets vetoed, a known-GOOD cell does not, and any garbage fails OPEN."""
import os
from datetime import datetime, timezone


class _FakeColl:
    def __init__(self, rows):
        self.rows = rows

    def find(self, q, proj=None):
        return iter(self.rows)


class _FakeDB:
    def __init__(self, rows):
        self._c = _FakeColl(rows)

    def __getitem__(self, name):
        return self._c


def _trade(setup, direction, tw, regime, realized_r):
    return {
        "status": "closed",
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "setup_type": setup,
        "direction": direction,
        "timeframe": "intraday",
        "tape_score": 5,
        "mfe_r": max(0.0, realized_r),
        "realized_pnl": realized_r * 100.0,
        "risk_amount": 100.0,
        "entry_context": {
            "time_window": tw,
            "market_regime": regime,
            "priority": "high",
            "regime_score": 55.0,
            "trigger_probability": 0.6,
            "technicals": {"rsi": 55.0},
        },
    }


def _build_book():
    rows = []
    # GOOD cell: squeeze|long|power_hour|risk_on → strongly +R
    for i in range(35):
        rows.append(_trade("squeeze", "long", "power_hour", "risk_on", 1.0 if i % 5 else 0.5))
    # BAD cell: squeeze|long|midday|risk_on → strongly -R
    for i in range(35):
        rows.append(_trade("squeeze", "long", "midday", "risk_on", -1.0 if i % 5 else -0.5))
    # filler spread so the distribution + 30th pctile cutoff are meaningful
    for i in range(40):
        rows.append(_trade("vwap_continuation", "long", "afternoon", "risk_on",
                           0.2 if i % 2 else -0.2))
    return rows


def run():
    os.environ["ENTRY_EDGE_VETO_TARGET"] = "realized_r"
    os.environ["ENTRY_EDGE_VETO_CLIP"] = "3"
    os.environ["ENTRY_EDGE_VETO_PCTILE"] = "30"
    os.environ["ENTRY_EDGE_VETO_MIN_TRADES"] = "60"

    import database
    from services.entry_edge_gate import _EntryEdgeGate

    db = _FakeDB(_build_book())
    database.get_database = lambda: db   # patch so evaluate() finds our fake book

    gate = _EntryEdgeGate()
    gate._ensure(db, force=True)
    st = gate.status()
    assert st["model_loaded"], "model should fit on 110 synthetic trades"
    assert st["threshold"] is not None
    print("FIT:", st["model_n"], "trades  threshold=%.4f" % st["threshold"],
          "skip_bottom=%d%%" % st["skip_bottom_pct"])

    bad = gate.evaluate(
        {"direction": "long", "timeframe": "intraday", "setup_type": "squeeze", "tape_score": 5},
        {"time_window": "midday", "market_regime": "risk_on", "priority": "high",
         "regime_score": 55.0, "trigger_probability": 0.6, "technicals": {"rsi": 55.0}},
    )
    good = gate.evaluate(
        {"direction": "long", "timeframe": "intraday", "setup_type": "squeeze", "tape_score": 5},
        {"time_window": "power_hour", "market_regime": "risk_on", "priority": "high",
         "regime_score": 55.0, "trigger_probability": 0.6, "technicals": {"rsi": 55.0}},
    )
    print("BAD  cell:", bad)
    print("GOOD cell:", good)
    assert bad["veto"] is True, "the proven-bad archetype must be vetoed"
    assert good["veto"] is False, "the proven-good archetype must pass"
    assert good["edge"] > bad["edge"], "good edge must exceed bad edge"

    # fail-open: no matchable cell (None direction) → never veto
    fo = gate.evaluate({"direction": None, "setup_type": None, "timeframe": None},
                       {"time_window": None, "market_regime": None})
    print("FAIL-OPEN (no cell):", fo)
    assert fo["veto"] is False, "un-scoreable candidate must fail open"

    print("\n✅ ALL GATE ASSERTIONS PASSED — bad vetoed, good kept, fail-open safe")


if __name__ == "__main__":
    run()
