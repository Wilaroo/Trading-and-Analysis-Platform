"""
Regression test — EOD-postmortem swing-hold FALSE ALARM fix.

Bug (observed 2026-06-25/26): `/api/diagnostic/eod-postmortem` flagged
"🔴 N INTRADAY position(s) held overnight despite close_at_eod=True" for
swing/position trades (DSGX, FOX, CCK, BOOT, TLT) that have GTC brackets and
are SUPPOSED to hold overnight. Root cause: it read the stale per-trade
`close_at_eod` field (blanket default True for setups missing a config key,
v334 / v19.34.245) instead of the authoritative policy resolver
`order_policy_registry.should_close_at_eod`.

Fix: the postmortem now resolves each position's `policy_close_at_eod` via
`should_close_at_eod` and uses `_eod_overnight_anomalies` (policy-based) for
the diagnosis. Swing/position/investment/multi_day holds must NOT be flagged;
genuine scalp/intraday holds MUST be.
"""
from services.order_policy_registry import should_close_at_eod
from routers.diagnostic_router import _eod_overnight_anomalies


# ── Authoritative policy resolution (the source the postmortem now uses) ──

def test_swing_with_stale_raw_flag_resolves_to_hold():
    # Mirrors the real June-25 trade: raw close_at_eod=True is a stale default;
    # the POLICY (swing) must win → hold overnight (not an EOD anomaly).
    swing = {"trade_style": "swing", "setup_type": "breakdown_confirmed", "close_at_eod": True}
    assert should_close_at_eod(swing) is False


def test_position_styles_hold_overnight():
    for style in ("multi_day", "investment"):
        assert should_close_at_eod({"trade_style": style, "close_at_eod": True}) is False


def test_intraday_and_scalp_close_at_eod():
    assert should_close_at_eod({"trade_style": "intraday"}) is True
    assert should_close_at_eod({"trade_style": "scalp"}) is True


# ── The postmortem anomaly filter (policy-resolved) ──

def _pos(symbol, policy_eod, qty=10):
    # `close_at_eod` is intentionally the STALE True to prove it is ignored.
    return {"symbol": symbol, "position": qty,
            "policy_close_at_eod": policy_eod, "close_at_eod": True}


def test_overnight_anomalies_excludes_legitimate_swing_holds():
    # The exact June-25 false-alarm set — all swing/position holds.
    positions = [_pos(s, False) for s in ("DSGX", "FOX", "CCK", "BOOT", "TLT")]
    assert _eod_overnight_anomalies(positions) == []


def test_overnight_anomalies_flags_only_real_intraday():
    positions = [
        _pos("AAA", True),          # intraday held overnight = REAL bug
        _pos("BBB", False),         # swing hold = fine
        _pos("CCC", True, qty=0),   # flat → ignored
        _pos("DDD", None),          # unresolved policy → not flagged
    ]
    flagged = sorted(p["symbol"] for p in _eod_overnight_anomalies(positions))
    assert flagged == ["AAA"]
