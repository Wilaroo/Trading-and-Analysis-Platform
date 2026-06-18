"""v19.34.318 — Morning Readiness "Held Overnight" section."""
import sys
from pathlib import Path
from unittest.mock import MagicMock
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _t(symbol, style, setup="daily_breakout", shares=100, stop=None, targets=None,
       direction="long"):
    """Synthesize an open-trade dataclass-ish object."""
    return SimpleNamespace(
        symbol=symbol,
        trade_style=style,
        setup_type=setup,
        shares=shares,
        remaining_shares=shares,
        direction=direction,
        stop_price=stop,
        target_prices=targets or [],
        opened_at="2026-06-12T15:00:00+00:00",
        timeframe=None,
        setup_variant=None,
        close_at_eod=False,
    )


def _bot(trades):
    return SimpleNamespace(
        _open_trades={f"tid_{t.symbol}": t for t in trades},
        _db=None,
    )


# ── core behaviour ────────────────────────────────────────────────────

def test_section_present_in_compute_output():
    from services.morning_readiness_service import compute_morning_readiness
    out = compute_morning_readiness(db=None, bot=_bot([]))
    assert "held_overnight" in out["checks"], \
        "v318 contract: new check 'held_overnight' must appear in checks"


def test_empty_book_returns_green():
    from services.morning_readiness_service import _held_overnight_summary
    res = _held_overnight_summary(None, bot=_bot([]))
    assert res["status"] == "green"
    assert res["held_count"] == 0
    assert res["held"] == []


def test_multi_day_position_surfaces_with_gtc():
    from services.morning_readiness_service import _held_overnight_summary
    bot = _bot([
        _t("DVN", "multi_day", setup="fashionably_late", shares=56,
           stop=43.70, targets=[44.54, 44.96, 46.65]),
    ])
    res = _held_overnight_summary(None, bot=bot)
    assert res["status"] == "green"
    assert res["held_count"] == 1
    row = res["held"][0]
    assert row["symbol"] == "DVN"
    assert row["trade_style"] == "multi_day"
    assert row["setup_type"] == "fashionably_late"
    assert row["shares"] == 56
    assert row["stop_price"] == 43.70
    assert row["target_prices"] == [44.54, 44.96, 46.65]
    # Policy maps long-horizon styles to GTC.
    assert row["bracket_tif"] == "GTC"


def test_intraday_position_excluded():
    """Only long-horizon holds appear in this section."""
    from services.morning_readiness_service import _held_overnight_summary
    bot = _bot([
        _t("AAL", "intraday", setup="orb"),
        _t("CRS", "trade_2_hold", setup="daily_breakout"),
    ])
    res = _held_overnight_summary(None, bot=bot)
    # `intraday` is force-close, `trade_2_hold` is a hold via setup-horizon.
    syms = [r["symbol"] for r in res["held"]]
    assert "AAL" not in syms
    assert "CRS" in syms


def test_position_missing_stop_yellows_the_check():
    from services.morning_readiness_service import _held_overnight_summary
    bot = _bot([
        _t("DKNG", "multi_day", setup="squeeze", stop=None,
           targets=[100.0]),
    ])
    res = _held_overnight_summary(None, bot=bot)
    # Carrying a multi-day overnight without a stop is operator-attention.
    assert res["status"] == "yellow", res
    assert res["held_count"] == 1
    assert "no_stop" in res.get("warnings", "")


def test_summary_string_lists_horizon_breakdown():
    from services.morning_readiness_service import _held_overnight_summary
    bot = _bot([
        _t("A", "multi_day", stop=1.0, targets=[2.0]),
        _t("B", "multi_day", stop=1.0, targets=[2.0]),
        _t("C", "swing",     stop=1.0, targets=[2.0]),
        _t("D", "investment",stop=1.0, targets=[2.0]),
    ])
    res = _held_overnight_summary(None, bot=bot)
    assert res["held_count"] == 4
    assert "multi_day" in res["detail"]
    assert "swing" in res["detail"]


def test_no_bot_yellows_gracefully():
    from services.morning_readiness_service import _held_overnight_summary
    from unittest.mock import patch
    # Force get_trading_bot_service to return None so we hit the yellow path.
    with patch("services.trading_bot_service.get_trading_bot_service",
               return_value=None):
        res = _held_overnight_summary(None, bot=None)
    assert res["status"] == "yellow"
    assert "unavailable" in res["detail"].lower()
