"""DB-free end-to-end check of the OOS PROMOTE backtest: with cleanly separated
archetype cells, the OOS GO bucket is positive and STAND-DOWN is negative."""
from datetime import datetime, timezone


class _Coll:
    def __init__(self, rows):
        self.rows = rows

    def find(self, q=None, proj=None):
        return [dict(r) for r in self.rows]

    def find_one(self, q=None, proj=None, sort=None):
        return None


class _DB:
    def __init__(self, rows):
        self._c = _Coll(rows)

    def __getitem__(self, name):
        return self._c


def _t(setup, direction, tw, regime, r):
    now = datetime.now(timezone.utc).isoformat()
    return {"status": "closed", "closed_at": now, "setup_type": setup,
            "direction": direction, "timeframe": "intraday", "tape_score": 5,
            "mfe_r": max(0.0, r), "realized_pnl": r * 100.0, "risk_amount": 100.0,
            "entry_context": {"time_window": tw, "market_regime": regime,
                              "priority": "high", "regime_score": 55.0,
                              "trigger_probability": 0.6, "technicals": {"rsi": 55.0}}}


def run():
    rows = []
    for i in range(60):                       # GOOD cell → strongly +R
        rows.append(_t("squeeze", "long", "power_hour", "risk_on", 1.0 if i % 6 else 0.4))
    for i in range(60):                       # BAD cell → strongly -R
        rows.append(_t("squeeze", "long", "midday", "risk_on", -1.0 if i % 6 else -0.4))
    for i in range(60):                       # NEUTRAL cell → ~0
        rows.append(_t("vwap_continuation", "long", "afternoon", "risk_on",
                       0.2 if i % 2 else -0.2))

    from services.entry_edge_promote import generate_report
    rep = generate_report(_DB(rows), days=120, k_folds=5)
    import json
    print(json.dumps({k: rep[k] for k in ("n_used", "oos", "verdict")}, indent=2, default=str))

    assert rep["n_used"] == 180
    oos = rep["oos"]
    assert oos["go_only"]["n"] > 0, "some trades must clear GO"
    assert oos["go_only"]["avg_r"] > 0, "OOS GO bucket should be positive"
    assert oos["stand_down"]["avg_r"] < 0, "OOS STAND-DOWN bucket should be negative"
    assert oos["go_only"]["avg_r"] > oos["baseline_all"]["avg_r"], "GO beats baseline"
    print("\n✅ OOS PROMOTE backtest OK — GO positive, stand-down negative, beats baseline")


if __name__ == "__main__":
    run()
