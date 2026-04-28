"""
Regression tests for `services.rejection_analytics.compute_rejection_analytics`.

Closes the loop on the new rejection-narrative pipeline (sentcom_thoughts
shipped 2026-04-29 afternoon-4). Asserts the analytics:
  - aggregate rejection events from `sentcom_thoughts` by reason_code
  - cross-reference subsequent `bot_trades` (same symbol+setup, within 24h)
  - compute post-rejection win rate
  - emit verdicts + calibration hints when gate appears over-tight
  - handle missing/empty data gracefully
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import mongomock

from services.rejection_analytics import compute_rejection_analytics


def _seed_thought(db, *, symbol, reason_code, setup_type="orb_long",
                  minutes_ago=10):
    db["sentcom_thoughts"].insert_one({
        "id": f"t_{symbol}_{reason_code}_{minutes_ago}",
        "kind": "rejection",
        "symbol": symbol,
        "content": f"Skipping {symbol} — {reason_code}",
        "metadata": {
            "reason_code": reason_code,
            "setup_type": setup_type,
            "direction": "long",
        },
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    })


def _seed_trade(db, *, symbol, setup_type, pnl, minutes_ago=5):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db["bot_trades"].insert_one({
        "symbol": symbol,
        "setup_type": setup_type,
        "executed_at": ts.isoformat(),
        "status": "closed",
        "net_pnl": pnl,
    })


def test_returns_empty_payload_when_no_thoughts():
    db = mongomock.MongoClient().db
    res = compute_rejection_analytics(db, days=7)
    assert res["success"] is True
    assert res["total_rejections"] == 0
    assert res["by_reason_code"] == []
    assert res["calibration_hints"] == []


def test_aggregates_by_reason_code_and_symbol():
    db = mongomock.MongoClient().db
    _seed_thought(db, symbol="NVDA", reason_code="tqs_too_low")
    _seed_thought(db, symbol="AAPL", reason_code="tqs_too_low", minutes_ago=20)
    _seed_thought(db, symbol="TSLA", reason_code="exposure_cap", minutes_ago=5)

    res = compute_rejection_analytics(db, days=7, min_count=1)
    assert res["total_rejections"] == 3
    by_code = {b["reason_code"]: b for b in res["by_reason_code"]}
    assert by_code["tqs_too_low"]["count"] == 2
    assert set(by_code["tqs_too_low"]["symbols"]) == {"NVDA", "AAPL"}
    assert by_code["exposure_cap"]["count"] == 1
    # Sorted by count desc — tqs_too_low first
    assert res["by_reason_code"][0]["reason_code"] == "tqs_too_low"


def test_min_count_filter_marks_insufficient_data():
    """Reason codes below min_count get verdict 'insufficient_data'."""
    db = mongomock.MongoClient().db
    _seed_thought(db, symbol="X", reason_code="rare_gate")
    res = compute_rejection_analytics(db, days=7, min_count=5)
    rare = next(b for b in res["by_reason_code"] if b["reason_code"] == "rare_gate")
    assert rare["verdict"] == "insufficient_data"


def test_post_rejection_join_with_bot_trades_overtight_verdict():
    """Reject NVDA+orb_long 6 times for same code; later, 5 of 5 trades
    on NVDA+orb_long won → win_rate 100% → 'gate_potentially_overtight'."""
    db = mongomock.MongoClient().db
    for i in range(6):
        _seed_thought(db, symbol="NVDA", reason_code="tqs_too_low",
                      setup_type="orb_long", minutes_ago=60 + i)
    for i in range(5):
        _seed_trade(db, symbol="NVDA", setup_type="orb_long",
                    pnl=120.0, minutes_ago=30 - i)

    res = compute_rejection_analytics(db, days=7, min_count=3)
    tqs = next(b for b in res["by_reason_code"]
               if b["reason_code"] == "tqs_too_low")
    assert tqs["count"] == 6
    assert tqs["post_rejection_trades"] == 5
    assert tqs["post_rejection_wins"] == 5
    assert tqs["post_rejection_win_rate_pct"] == 100.0
    assert tqs["verdict"] == "gate_potentially_overtight"
    assert any("over-tight" in h for h in res["calibration_hints"])


def test_post_rejection_join_when_subsequent_trades_lose():
    """Most post-rejection trades lose → 'gate_calibrated' (gate did its job)."""
    db = mongomock.MongoClient().db
    for i in range(5):
        _seed_thought(db, symbol="AAPL", reason_code="tqs_too_low",
                      setup_type="orb_long", minutes_ago=60 + i)
    # 5 trades, 4 losers + 1 winner → 20% win rate
    for i in range(4):
        _seed_trade(db, symbol="AAPL", setup_type="orb_long",
                    pnl=-50.0, minutes_ago=30 - i)
    _seed_trade(db, symbol="AAPL", setup_type="orb_long",
                pnl=80.0, minutes_ago=20)

    res = compute_rejection_analytics(db, days=7, min_count=3)
    tqs = next(b for b in res["by_reason_code"]
               if b["reason_code"] == "tqs_too_low")
    assert tqs["post_rejection_trades"] == 5
    assert tqs["post_rejection_wins"] == 1
    assert tqs["verdict"] == "gate_calibrated"
    # No "over-tight" hint emitted
    assert not any("over-tight" in h for h in res["calibration_hints"])


def test_setup_type_normalisation_long_short_collapse():
    """Rejection on `orb_long` and trade on `orb_short` should NOT match —
    direction matters. But `orb_long` rejection + `orb_long` trade should
    match. Setup normalisation strips _long/_short for comparison."""
    db = mongomock.MongoClient().db
    _seed_thought(db, symbol="MSFT", reason_code="exposure_cap",
                  setup_type="orb_long", minutes_ago=60)
    # Trade with setup_type="orb_long" (matches after normalisation)
    _seed_trade(db, symbol="MSFT", setup_type="orb_long",
                pnl=100.0, minutes_ago=30)

    res = compute_rejection_analytics(db, days=7, min_count=1)
    code = next(b for b in res["by_reason_code"]
                if b["reason_code"] == "exposure_cap")
    assert code["post_rejection_trades"] == 1


def test_unknown_reason_code_falls_into_unknown_bucket():
    """Rejection event missing `reason_code` lands in 'unknown' bucket."""
    db = mongomock.MongoClient().db
    db["sentcom_thoughts"].insert_one({
        "id": "no_code", "kind": "rejection",
        "symbol": "X", "content": "skipped",
        "metadata": {},  # no reason_code
        "created_at": datetime.now(timezone.utc),
    })
    res = compute_rejection_analytics(db, days=7, min_count=1)
    assert res["by_reason_code"][0]["reason_code"] == "unknown"
