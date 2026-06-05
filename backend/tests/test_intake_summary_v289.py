"""
test_intake_summary_v289.py — guards the universe-wide intake-summary rollup.

Drives the read-only GET /api/scanner/intake-summary endpoint with a fake scanner
+ in-memory mongo so we lock the window cutoff, eligible/ineligible totals, the
per-condition BOTTLENECK tally (overlapping), combined-reason aggregation, and the
worst-setup ranking.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.enhanced_scanner as es  # noqa: E402
from routers import scanner as scanner_router  # noqa: E402


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
    def __init__(self, db, auto_enabled=True):
        self.db = db
        self._auto_execute_enabled = auto_enabled
        self._auto_execute_min_ev_r = 0.10
        self._win_rate_grace_min_trades = 20


def _alert(symbol="NVDA", priority="medium", tape=False, wr=0.50,
           eligible=False, setup="9_ema_scalp", days_ago=1, ev=0.0, outcomes=0):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago))
    return {"symbol": symbol, "priority": priority, "tape_confirmation": tape,
            "strategy_win_rate": wr, "strategy_ev_r": ev, "strategy_outcomes": outcomes,
            "auto_execute_eligible": eligible,
            "setup_type": setup, "created_at": ts.strftime("%Y-%m-%d") + "T12:00:00+00:00"}


def _run(scanner, monkeypatch, days=30):
    monkeypatch.setattr(es, "get_enhanced_scanner", lambda: scanner)
    return scanner_router.get_intake_summary(days=days)


class TestIntakeSummary:
    def test_totals_and_condition_tally(self, monkeypatch):
        rows = (
            [_alert(priority="high", tape=True, wr=0.60, eligible=True)] * 4 +      # eligible
            [_alert(priority="low", tape=True, wr=0.60)] * 3 +                       # priority only
            [_alert(priority="high", tape=False, ev=-0.50, outcomes=30,
                    setup="orb")] * 2                                                # tape + proven -EV
        )
        out = _run(_FakeScanner(_FakeDB(rows)), monkeypatch)
        t = out["totals"]
        assert t["alerts"] == 9
        assert t["eligible"] == 4
        assert t["ineligible"] == 5
        c = out["condition_tally"]
        assert c["priority_low"] == 3          # 3 low-priority
        assert c["tape_unconfirmed"] == 2      # 2 tape-fail
        assert c["ev_below"] == 2              # 2 proven-negative-EV (overlap with tape)

    def test_by_reason_aggregation_sorted(self, monkeypatch):
        rows = (
            [_alert(priority="low", tape=True, wr=0.60, symbol="AAA")] * 5 +
            [_alert(priority="high", tape=False, wr=0.60, symbol="BBB")] * 2
        )
        out = _run(_FakeScanner(_FakeDB(rows)), monkeypatch)
        br = out["by_reason"]
        assert br[0]["reason"] == "priority=low<high"
        assert br[0]["count"] == 5
        assert br[0]["symbols"] == 1

    def test_window_cutoff_excludes_old(self, monkeypatch):
        rows = [_alert(days_ago=2)] * 3 + [_alert(days_ago=40)] * 4  # 4 outside 30d
        out = _run(_FakeScanner(_FakeDB(rows)), monkeypatch, days=30)
        assert out["totals"]["alerts"] == 3
        assert out["since"] <= datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_worst_setups_ranking(self, monkeypatch):
        rows = (
            [_alert(setup="vwap_fade_long", priority="low", tape=True, wr=0.60)] * 6 +
            [_alert(setup="orb", priority="low", tape=True, wr=0.60)] * 2
        )
        out = _run(_FakeScanner(_FakeDB(rows)), monkeypatch)
        worst = out["by_setup"][0]
        assert worst["setup"] == "vwap_fade_long"
        assert worst["ineligible"] == 6
        assert worst["ineligible_pct"] == 100.0

    def test_auto_execute_disabled_path(self, monkeypatch):
        rows = [_alert(priority="high", tape=True, wr=0.60)] * 3
        out = _run(_FakeScanner(_FakeDB(rows), auto_enabled=False), monkeypatch)
        assert out["auto_exec_enabled"] is False
        assert out["totals"]["ineligible"] == 3
        assert out["condition_tally"]["auto_execute_disabled"] == 3

    def test_days_clamped(self, monkeypatch):
        out = _run(_FakeScanner(_FakeDB([])), monkeypatch, days=9999)
        assert out["days"] == 365
