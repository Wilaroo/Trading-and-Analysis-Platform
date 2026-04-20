"""Tests for audit_setup_coverage.py using mongomock fixtures.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_audit_setup_coverage.py -v
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import mongomock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import audit_setup_coverage as audit  # noqa: E402


@pytest.fixture
def mock_db(monkeypatch):
    client = mongomock.MongoClient()
    db = client["tradecommand"]

    # manual trades
    db["trades"].insert_many([
        # rubber_band: 8 rows total (6 wins, 2 losses → 75% wr)
        {"setup_type": "rubber_band_long", "r_multiple": 1.5},
        {"setup_type": "rubber_band_long", "r_multiple": -1.0},
        {"setup_type": "rubber_band_long", "r_multiple": 2.1},
        {"setup_type": "rubber_band_long", "r_multiple": 0.5},
        {"setup_type": "rubber_band_long", "r_multiple": 1.8},
        {"setup_type": "rubber_band_long", "r_multiple": 0.9},
        {"setup_type": "rubber_band_long", "r_multiple": -0.7},
        {"setup_type": "spencer_scalp", "r_multiple": 0.8},
        {"setup_type": "bella_fade", "r_multiple": -1.0},
        # Non-taxonomy code (drift)
        {"setup_type": "mystery_setup_xyz", "r_multiple": 0.5},
        {"setup_type": "mystery_setup_xyz", "r_multiple": 0.3},
    ])
    # bot trades
    db["bot_trades"].insert_many([
        {"setup_type": "rubber_band_short", "r_multiple": 1.2},
        {"setup_type": "spencer_scalp", "r_multiple": -1.0},
        {"setup_type": "approaching_breakout", "r_multiple": 0.9},
    ])
    # no-r-multiple fallback path
    db["trade_snapshots"].insert_many([
        {"setup_type": "hitchhiker", "pnl": 42.0},
        {"setup_type": "hitchhiker", "pnl": -15.0},
    ])
    # live alerts (no outcome typically)
    db["live_alerts"].insert_many([
        {"setup_type": "hod_breakout"},
        {"setup_type": "hod_breakout"},
    ])

    monkeypatch.setattr(audit, "get_db", lambda: db)
    return db


def test_normalize_setup_code():
    assert audit.normalize_setup_code("rubber_band_long") == "rubber_band"
    assert audit.normalize_setup_code("rubber_band_short") == "rubber_band"
    assert audit.normalize_setup_code("approaching_breakout") == "breakout"
    assert audit.normalize_setup_code("BREAKOUT_CONFIRMED") == "breakout"
    assert audit.normalize_setup_code("spencer_scalp") == "spencer_scalp"
    assert audit.normalize_setup_code(None) is None
    assert audit.normalize_setup_code("") is None
    assert audit.normalize_setup_code("  Mystery_SETUP_XYZ  ") == "mystery_setup_xyz"


def test_aggregate_collects_and_normalizes(mock_db):
    stats_trades = audit._aggregate_collection(mock_db, "trades")
    # 7 rubber_band_long rows bucketed under rubber_band; 5 wins (1.5, 2.1, 0.5, 1.8, 0.9), 2 losses (-1.0, -0.7)
    assert stats_trades["rubber_band"]["count"] == 7
    assert stats_trades["rubber_band"]["wins"] == 5
    assert stats_trades["rubber_band"]["losses"] == 2

    stats_bots = audit._aggregate_collection(mock_db, "bot_trades")
    # rubber_band_short → rubber_band, approaching_breakout → breakout
    assert stats_bots["rubber_band"]["count"] == 1
    assert stats_bots["breakout"]["count"] == 1


def test_merge_and_finalize(mock_db):
    all_stats = [audit._aggregate_collection(mock_db, c)
                 for c in audit.COLLECTIONS]
    merged = audit.merge_stats(all_stats)

    # rubber_band: 7 (trades) + 1 (bot_trades) = 8
    assert merged["rubber_band"]["count"] == 8
    assert merged["rubber_band"]["wins"] == 6
    assert merged["rubber_band"]["losses"] == 2

    # hitchhiker: pnl fallback path
    assert merged["hitchhiker"]["count"] == 2
    assert merged["hitchhiker"]["wins"] == 1
    assert merged["hitchhiker"]["losses"] == 1

    # hod_breakout: no outcome at all
    assert merged["hod_breakout"]["count"] == 2
    assert merged["hod_breakout"]["wins"] == 0
    assert merged["hod_breakout"]["losses"] == 0

    rows = audit.finalize(merged)
    # Sorted by count desc
    assert rows[0]["count"] >= rows[-1]["count"]

    # rubber_band flagged in taxonomy
    rb = next(r for r in rows if r["setup_code"] == "rubber_band")
    assert rb["in_taxonomy"] is True
    assert rb["win_rate"] == 6 / 8

    # mystery_setup_xyz flagged NOT in taxonomy
    mx = next(r for r in rows if r["setup_code"] == "mystery_setup_xyz")
    assert mx["in_taxonomy"] is False


def test_classify_buckets(mock_db):
    all_stats = [audit._aggregate_collection(mock_db, c)
                 for c in audit.COLLECTIONS]
    merged = audit.merge_stats(all_stats)
    rows = audit.finalize(merged)

    # Lower min_count to exercise trainable bucket on small fixtures.
    # too_few_floor = max(5, min_count//2) so with min_count=8 → floor=5.
    verdicts = {r["setup_code"]: audit.classify(r, min_count=8, min_win_rate=0.40)
                for r in rows}
    # rubber_band has 8 rows, 75% win rate → trainable
    assert verdicts["rubber_band"] == "trainable"
    # bella_fade: 1 row → too_few
    assert verdicts["bella_fade"] == "too_few"
    # hod_breakout: 2 rows no outcome → too_few (floor is 5)
    assert verdicts["hod_breakout"] == "too_few"


def test_markdown_report_contains_sections(mock_db, tmp_path, monkeypatch,
                                            capsys):
    out_md = tmp_path / "audit.md"
    out_json = tmp_path / "audit.json"
    monkeypatch.setattr(sys, "argv", [
        "audit", "--min-count", "8", "--min-win-rate", "0.40",
        "--output", str(out_md), "--json", str(out_json),
    ])
    audit.main()

    text = out_md.read_text()
    assert "# Setup Coverage Audit" in text
    assert "## Summary" in text
    assert "Phase 2E Tier-1 training targets" in text
    # Taxonomy setups with zero data section shows up
    assert "NO tagged data" in text
    # Non-taxonomy drift section triggers because we have mystery_setup_xyz
    # (but only if count >= 10; with our fixture it has 2 — won't trigger).
    # So just confirm the summary section exists.

    data = json.loads(out_json.read_text())
    assert isinstance(data, list)
    assert any(r["setup_code"] == "rubber_band" for r in data)

    # stdout had the compact summary
    captured = capsys.readouterr().out
    assert "SETUP COVERAGE AUDIT" in captured
    assert "Top 10 by volume" in captured
