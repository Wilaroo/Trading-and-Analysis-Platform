"""setup_ev report — aggregation + verdict tests (fake-db, no Mongo)."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.setup_ev import generate_setup_ev_report, _winsor_mean, _verdict  # noqa: E402


class _FakeCol:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *_a, **_k):
        return iter(self._docs)


class _FakeDB:
    def __init__(self, docs):
        self._c = _FakeCol(docs)

    def __getitem__(self, _name):
        return self._c


def _trade(setup, direction, pnl, risk=100.0):
    return {
        "setup_type": setup, "status": "closed", "direction": direction,
        "realized_pnl": pnl, "risk_amount": risk,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }


def test_winsor_and_verdict_units():
    assert _verdict(-0.2, 20) == "bleeding"
    assert _verdict(0.0, 20) == "marginal"
    assert _verdict(0.3, 20) == "healthy"
    assert _verdict(-0.5, 4) == "thin"
    # winsor clamps a fat outlier (n>=10)
    rs = [0.1] * 11 + [50.0]
    assert _winsor_mean(rs) < 5.0


def test_bleeder_surfaces_first_and_dir_split():
    docs = []
    # bull_flag swing: 12 trades, strongly negative (bleeder)
    for _ in range(12):
        docs.append(_trade("bull_flag", "long", -30))
    # vwap_bounce swing: 12 trades, positive (healthy)
    for _ in range(12):
        docs.append(_trade("vwap_bounce", "long", +40))
    # squeeze swing: short branch negative, long positive
    for _ in range(11):
        docs.append(_trade("squeeze", "long", +20))
    for _ in range(11):
        docs.append(_trade("squeeze", "short", -25))

    rep = generate_setup_ev_report(_FakeDB(docs), days=30, horizon=None, min_n=1)
    rows = rep["setups"]
    assert rows, "expected setup rows"
    # worst total_r first
    assert rows[0]["setup_type"] == "bull_flag"
    assert rows[0]["verdict"] == "bleeding"
    # healthy one present
    vb = next(r for r in rows if r["setup_type"] == "vwap_bounce")
    assert vb["verdict"] == "healthy"
    # direction split captured for squeeze
    sq = next(r for r in rows if r["setup_type"] == "squeeze")
    assert sq["by_direction"]["short"]["avg_r"] < 0 < sq["by_direction"]["long"]["avg_r"]
    assert "bull_flag" in rep["headline"]


if __name__ == "__main__":
    test_winsor_and_verdict_units()
    test_bleeder_surfaces_first_and_dir_split()
    print("PASS: setup_ev report tests")
