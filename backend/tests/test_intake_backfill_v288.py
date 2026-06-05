"""
test_intake_backfill_v288.py — guards the symbol-trace INTAKE-ELIGIBILITY backfill.

The v287 forward-logger only records `auto_exec_ineligible` drops for NEW alerts
processed after the patch. Pre-existing alerts (or alerts that surfaced through a
non-instrumented path / before a restart) still showed "0 gate-drops, PRE-eval
blind spot". v288 recomputes the auto-execute eligibility verdict from today's
PERSISTED `live_alerts` so the operator sees the WHY immediately. This drives the
read-only `get_symbol_trace` endpoint via a fake scanner + in-memory mongo.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.enhanced_scanner as es  # noqa: E402
from routers import scanner as scanner_router  # noqa: E402


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def __iter__(self):
        return iter(self._rows)


class _FakeCollection:
    def __init__(self, rows):
        self._rows = rows

    def count_documents(self, query):
        return len([r for r in self._rows if self._match(r, query)])

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
    def __init__(self, collections):
        self._collections = collections

    def __getitem__(self, name):
        return _FakeCollection(self._collections.get(name, []))


class _FakeScanner:
    def __init__(self, db, auto_enabled=True):
        self.db = db
        self._auto_execute_enabled = auto_enabled
        self._auto_execute_min_ev_r = 0.10
        self._win_rate_grace_min_trades = 20
        self._min_rvol_filter = 0.8
        self._tier_cache = {"NVDA": "intraday"}
        self._rvol_cache = {"NVDA": (1.25, datetime.now(timezone.utc))}
        self._symbol_last_eval = {"NVDA": {"stage": "scanned", "rvol": 1.25,
                                           "ts": datetime.now(timezone.utc).isoformat()}}
        self._last_wave_batch = {"tier3_wave": ["NVDA"]}


def _run(scanner, monkeypatch):
    monkeypatch.setattr(es, "get_enhanced_scanner", lambda: scanner)
    # symbol_universe.get_universe is wrapped in try/except; force a known answer.
    import services.symbol_universe as su
    monkeypatch.setattr(su, "get_universe", lambda db, tier=None: {"NVDA"})
    return scanner_router.get_symbol_trace("NVDA")


def _alert(priority="medium", tape=False, wr=0.50, eligible=False, setup="9_ema_scalp",
           ev=0.0, outcomes=0):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {"symbol": "NVDA", "priority": priority, "tape_confirmation": tape,
            "strategy_win_rate": wr, "strategy_ev_r": ev, "strategy_outcomes": outcomes,
            "auto_execute_eligible": eligible,
            "setup_type": setup, "created_at": today + "T18:00:00+00:00"}


class TestIntakeBackfill:
    def test_priority_too_low_aggregates(self, monkeypatch):
        db = _FakeDB({"live_alerts": [_alert(priority="medium", tape=True, wr=0.60)] * 9,
                      "trade_drops": []})
        out = _run(_FakeScanner(db), monkeypatch)
        ie = out["intake_eligibility"]
        assert ie["checked"] == 9
        assert ie["auto_exec_enabled"] is True
        assert ie["by_reason"]["priority=medium<high"]["count"] == 9
        assert "INTAKE-INELIGIBLE" in out["verdict"]
        assert "priority=medium<high" in out["verdict"]

    def test_auto_execute_disabled_verdict(self, monkeypatch):
        db = _FakeDB({"live_alerts": [_alert(priority="high", tape=True, wr=0.60)] * 3,
                      "trade_drops": []})
        out = _run(_FakeScanner(db, auto_enabled=False), monkeypatch)
        ie = out["intake_eligibility"]
        assert ie["auto_exec_enabled"] is False
        assert ie["by_reason"]["auto_execute_disabled"]["count"] == 3
        assert "AUTO-EXECUTE GLOBALLY OFF" in out["verdict"]

    def test_eligible_but_no_drop_flags_downstream(self, monkeypatch):
        db = _FakeDB({"live_alerts": [_alert(priority="high", tape=True, wr=0.60, eligible=True)] * 2,
                      "trade_drops": []})
        out = _run(_FakeScanner(db), monkeypatch)
        ie = out["intake_eligibility"]
        assert ie["eligible_no_drop"] == 2
        assert ie["by_reason"] == {}
        assert "DOWNSTREAM" in out["verdict"]

    def test_multi_reason_key(self, monkeypatch):
        # v294: proven setup (>= grace_min outcomes) with negative EV trips the EV
        # condition alongside priority + tape (win-rate floor dropped in v293).
        db = _FakeDB({"live_alerts": [_alert(priority="medium", tape=False,
                                             ev=-0.50, outcomes=30)] * 4,
                      "trade_drops": []})
        out = _run(_FakeScanner(db), monkeypatch)
        ie = out["intake_eligibility"]
        key = "priority=medium<high + tape_unconfirmed + EV -0.50R<=+0.10R"
        assert ie["by_reason"][key]["count"] == 4

    def test_backfill_skipped_when_drops_exist(self, monkeypatch):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        drop = {"symbol": "NVDA", "gate": "rr_below_min", "setup_type": "9_ema_scalp",
                "reason": "x", "context": {}, "ts": today + "T18:00:00+00:00"}
        db = _FakeDB({"live_alerts": [_alert()] * 9, "trade_drops": [drop]})
        out = _run(_FakeScanner(db), monkeypatch)
        # gate_funnel has a drop → backfill must NOT run.
        assert out["intake_eligibility"]["checked"] == 0
