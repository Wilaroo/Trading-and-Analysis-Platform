"""
test_strategy_stats_audit_v291.py — guards the win-rate/EV TRUST audit endpoint.

Replays the scanner's win-rate decision per setup with a fake scanner + in-memory
mongo, locking the four verdicts (NO-DATA->0% / GRACE / REAL-LOW / REAL-OK), the
base-setup canonicalization, and the summary aggregation.
"""
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.enhanced_scanner as es  # noqa: E402
from routers import scanner as scanner_router  # noqa: E402
from routers.scanner import _canon_setup_base  # noqa: E402


@dataclass
class _Stats:
    alerts_triggered: int = 0
    alerts_won: int = 0
    alerts_lost: int = 0
    win_rate: float = 0.0
    expected_value_r: float = 0.0
    profit_factor: float = 0.0


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeCollection:
    def __init__(self, rows):
        self._rows = rows

    def find(self, query, projection=None):
        return _FakeCursor([r for r in self._rows if self._match(r, query)])

    @staticmethod
    def _match(row, query):
        for k, v in query.items():
            if isinstance(v, dict) and "$gte" in v:
                if str(row.get(k, "")) < v["$gte"]:
                    return False
            elif row.get(k) != v:
                return False
        return True


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def __getitem__(self, name):
        return _FakeCollection(self._rows if name == "live_alerts" else [])


class _FakeScanner:
    def __init__(self, rows, stats):
        self.db = _FakeDB(rows)
        self._strategy_stats = stats
        self._win_rate_grace_min_trades = 20
        self._auto_execute_min_win_rate = 0.55


def _alert(setup, days_ago=1):
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {"setup_type": setup, "created_at": ts.strftime("%Y-%m-%d") + "T12:00:00+00:00"}


def _run(scanner, monkeypatch, days=30):
    monkeypatch.setattr(es, "get_enhanced_scanner", lambda: scanner)
    return scanner_router.get_strategy_stats_audit(days=days)


class TestCanon:
    def test_strips_long_short(self):
        assert _canon_setup_base("vwap_fade_long") == "vwap_fade"
        assert _canon_setup_base("vwap_fade_short") == "vwap_fade"
        assert _canon_setup_base("squeeze") == "squeeze"


class TestAuditVerdicts:
    def test_unregistered_is_no_data(self, monkeypatch):
        sc = _FakeScanner([_alert("accumulation_entry")] * 3, stats={})
        out = _run(sc, monkeypatch)
        row = out["setups"][0]
        assert row["setup_base"] == "accumulation_entry"
        assert row["registered"] is False
        assert row["effective_win_rate"] == 0.0
        assert row["verdict"].startswith("NO-DATA")

    def test_grace_when_thin(self, monkeypatch):
        stats = {"orb": _Stats(alerts_triggered=5, win_rate=0.80)}
        sc = _FakeScanner([_alert("orb")] * 2, stats)
        out = _run(sc, monkeypatch)
        row = out["setups"][0]
        assert row["verdict"].startswith("GRACE")
        assert row["effective_win_rate"] == 0.55  # floor baseline despite 80% real

    def test_real_low_genuinely_weak(self, monkeypatch):
        stats = {"vwap_fade": _Stats(alerts_triggered=120, alerts_won=20,
                                     alerts_lost=100, win_rate=0.17)}
        sc = _FakeScanner([_alert("vwap_fade_long")] * 6 + [_alert("vwap_fade_short")] * 2,
                          stats)
        out = _run(sc, monkeypatch)
        row = out["setups"][0]
        assert row["setup_base"] == "vwap_fade"
        assert row["verdict"].startswith("REAL-LOW")
        assert row["effective_win_rate"] == 0.17
        assert set(row["example_setup_types"]) == {"vwap_fade_long", "vwap_fade_short"}

    def test_real_ok_above_floor(self, monkeypatch):
        stats = {"abc": _Stats(alerts_triggered=50, win_rate=0.62)}
        sc = _FakeScanner([_alert("abc_long")] * 4, stats)
        out = _run(sc, monkeypatch)
        assert out["setups"][0]["verdict"].startswith("REAL-OK")

    def test_summary_aggregation(self, monkeypatch):
        stats = {"good": _Stats(alerts_triggered=50, win_rate=0.70),
                 "weak": _Stats(alerts_triggered=50, win_rate=0.20)}
        rows = ([_alert("good")] * 10 + [_alert("weak")] * 5 +
                [_alert("ghost")] * 7)  # ghost unregistered
        out = _run(_FakeScanner(rows, stats), monkeypatch)
        sm = out["summary_by_verdict"]
        assert sm["REAL-OK"]["setups"] == 1 and sm["REAL-OK"]["alerts"] == 10
        assert sm["REAL-LOW"]["setups"] == 1 and sm["REAL-LOW"]["alerts"] == 5
        assert sm["NO-DATA->0%"]["setups"] == 1 and sm["NO-DATA->0%"]["alerts"] == 7

    def test_sorted_by_alert_volume(self, monkeypatch):
        rows = [_alert("a")] * 2 + [_alert("b")] * 9 + [_alert("c")] * 5
        out = _run(_FakeScanner(rows, stats={}), monkeypatch)
        vols = [s["alerts_in_window"] for s in out["setups"]]
        assert vols == sorted(vols, reverse=True)
