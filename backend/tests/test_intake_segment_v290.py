"""
test_intake_segment_v290.py — guards the intake-summary SEGMENTATION (v290).

The 30-day rollup conflated intraday auto-exec candidates (where the tape gate
APPLIES) with swing/positional setups (daily path, no tape — a tape_unconfirmed
"block" there is structural). v290 splits by trade_style/scan_tier + a
tape-applicability flag so we measure the right denominator.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.enhanced_scanner as es  # noqa: E402
from routers import scanner as scanner_router  # noqa: E402
from routers.scanner import _tape_applicable  # noqa: E402


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
    def __init__(self, db, auto_enabled=True, min_wr=0.55):
        self.db = db
        self._auto_execute_enabled = auto_enabled
        self._auto_execute_min_win_rate = min_wr


def _alert(symbol="NVDA", priority="high", tape=True, wr=0.60, eligible=False,
           setup="x", style="intraday", tier="intraday", days_ago=1):
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {"symbol": symbol, "priority": priority, "tape_confirmation": tape,
            "strategy_win_rate": wr, "auto_execute_eligible": eligible,
            "setup_type": setup, "trade_style": style, "scan_tier": tier,
            "created_at": ts.strftime("%Y-%m-%d") + "T12:00:00+00:00"}


def _run(scanner, monkeypatch, days=30):
    monkeypatch.setattr(es, "get_enhanced_scanner", lambda: scanner)
    return scanner_router.get_intake_summary(days=days)


class TestTapeApplicableHelper:
    def test_intraday_styles_true(self):
        assert _tape_applicable("intraday") is True
        assert _tape_applicable("scalp") is True

    def test_positional_styles_false(self):
        for s in ("swing", "multi_day", "position", "investment"):
            assert _tape_applicable(s) is False

    def test_unknown_falls_back_to_scan_tier(self):
        assert _tape_applicable("?", "intraday") is True
        assert _tape_applicable("?", "swing") is False


class TestSegmentation:
    def test_intraday_vs_positional_split(self, monkeypatch):
        rows = (
            [_alert(style="intraday", tape=False, setup="vwap_fade_long")] * 4 +    # intraday, tape fail
            [_alert(style="swing", tape=False, setup="daily_squeeze",
                    tier="swing")] * 6                                              # positional, structural tape fail
        )
        out = _run(_FakeScanner(_FakeDB(rows)), monkeypatch)
        seg = out["segments"]
        assert seg["intraday"]["alerts"] == 4
        assert seg["intraday"]["cond"]["tape_unconfirmed"] == 4
        assert seg["positional"]["alerts"] == 6
        assert seg["positional"]["cond"]["tape_unconfirmed"] == 6

    def test_by_trade_style_flags_tape_applicability(self, monkeypatch):
        rows = ([_alert(style="intraday", eligible=True)] * 3 +
                [_alert(style="swing", tape=False, tier="swing")] * 5)
        out = _run(_FakeScanner(_FakeDB(rows)), monkeypatch)
        bts = {x["trade_style"]: x for x in out["by_trade_style"]}
        assert bts["intraday"]["tape_applicable"] is True
        assert bts["intraday"]["eligible"] == 3
        assert bts["swing"]["tape_applicable"] is False
        assert bts["swing"]["eligible"] == 0

    def test_by_setup_carries_segment_tag(self, monkeypatch):
        rows = [_alert(style="swing", tape=False, tier="swing",
                       setup="accumulation_entry")] * 3
        out = _run(_FakeScanner(_FakeDB(rows)), monkeypatch)
        row = out["by_setup"][0]
        assert row["setup"] == "accumulation_entry"
        assert row["segment"] == "positional"
        assert row["trade_style"] == "swing"

    def test_by_scan_tier_present(self, monkeypatch):
        rows = ([_alert(tier="intraday", eligible=True)] * 2 +
                [_alert(tier="swing", style="swing", tape=False)] * 4)
        out = _run(_FakeScanner(_FakeDB(rows)), monkeypatch)
        tiers = {x["scan_tier"]: x for x in out["by_scan_tier"]}
        assert tiers["intraday"]["total"] == 2
        assert tiers["swing"]["total"] == 4

    def test_segment_cond_sums_match_global(self, monkeypatch):
        rows = (
            [_alert(style="intraday", priority="low", tape=False, wr=0.10)] * 5 +
            [_alert(style="position", priority="medium", tape=False, wr=0.60,
                    tier="investment")] * 3
        )
        out = _run(_FakeScanner(_FakeDB(rows)), monkeypatch)
        glob = out["condition_tally"]
        seg = out["segments"]
        for cond_key in ("win_rate_below", "tape_unconfirmed", "priority_low"):
            seg_sum = (seg["intraday"]["cond"][cond_key]
                       + seg["positional"]["cond"][cond_key])
            assert seg_sum == glob[cond_key], cond_key
