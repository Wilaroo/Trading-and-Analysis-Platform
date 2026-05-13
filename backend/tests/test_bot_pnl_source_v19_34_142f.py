"""v19.34.142f — Bot-row `pnl_source` instrumentation.

Pre-v19.34.142f, bot-tracked positions (CW, ENTG, etc.) emitted
`pnl_source: null` in `get_our_positions()`. When the audit endpoint
flagged them as DRIFT_ABS / DRIFT_PCT, the operator had NO way to
distinguish:
  - Stale `trade.current_price` (position_manager timer hasn't fired)
  - Missing live quote (pusher not streaming this symbol)
  - Valid mark, but bot's `entry_price` is wrong (avg_cost drift)

This file pins the v19.34.142f classifier behavior so future agents
don't accidentally drop `pnl_source` from the bot-row payload.
"""

import pytest


# Pure-function mirror of the v19.34.142f inline logic in
# sentcom_service.get_our_positions (bot-row branch, ~line 2192).
# Keep this in lockstep with the production code; any drift here
# means the test no longer guards the actual behavior.
def _classify_bot_pnl_source(*, live_quote, trade_current_price, entry):
    pnl_source = "unknown"
    live_price = live_quote.get("last") or live_quote.get("close")
    if live_price and float(live_price) > 0:
        if live_quote.get("last") and float(live_quote.get("last") or 0) > 0:
            pnl_source = "quote_last"
        elif live_quote.get("close") and float(live_quote.get("close") or 0) > 0:
            pnl_source = "quote_close"
        else:
            pnl_source = "quote_unknown_key"
    elif trade_current_price and float(trade_current_price or 0) > 0:
        pnl_source = "trade_current_price_stale"
    elif entry and float(entry) > 0:
        pnl_source = "entry_price_fallback"
    return pnl_source


class TestBotPnLSourceClassification:

    def test_quote_last_takes_precedence(self):
        """Happy path: pusher is streaming live last."""
        src = _classify_bot_pnl_source(
            live_quote={"last": 150.25, "close": 148.50},
            trade_current_price=149.0,
            entry=140.0,
        )
        assert src == "quote_last"

    def test_quote_close_when_last_missing(self):
        """Pusher has prior-close snapshot but no live last (off-hours)."""
        src = _classify_bot_pnl_source(
            live_quote={"close": 148.50},
            trade_current_price=149.0,
            entry=140.0,
        )
        assert src == "quote_close"

    def test_quote_close_when_last_is_zero(self):
        """`last=0` falls through to `close` per Python truthiness."""
        src = _classify_bot_pnl_source(
            live_quote={"last": 0, "close": 148.50},
            trade_current_price=149.0,
            entry=140.0,
        )
        assert src == "quote_close"

    def test_trade_current_price_when_no_live_quote(self):
        """The CW/ENTG diagnostic scenario — the manage tick supplied
        a stale `current_price` and the pusher quote is empty."""
        src = _classify_bot_pnl_source(
            live_quote={},
            trade_current_price=149.0,
            entry=140.0,
        )
        assert src == "trade_current_price_stale"

    def test_entry_fallback_when_everything_missing(self):
        """Worst case: no quote, no manage tick. PnL collapses to 0 vs
        entry. Operator should see `entry_price_fallback` and know
        the row is mark-less."""
        src = _classify_bot_pnl_source(
            live_quote={},
            trade_current_price=0,
            entry=140.0,
        )
        assert src == "entry_price_fallback"

    def test_unknown_when_no_data_at_all(self):
        """Pathological: no quote, no manage tick, no entry. Test
        future-proofs against a half-broken legacy trade."""
        src = _classify_bot_pnl_source(
            live_quote={},
            trade_current_price=None,
            entry=0,
        )
        assert src == "unknown"

    def test_live_quote_with_only_bid_ask_not_taken(self):
        """Bot-row classifier intentionally only looks at last/close
        (those are what `current` actually gets set to). Bid/ask are
        the orphan-row fallback chain, not the bot-row one. This test
        documents that the bot row does NOT consult bid/ask."""
        src = _classify_bot_pnl_source(
            live_quote={"bid": 150.20, "ask": 150.30},
            trade_current_price=149.0,
            entry=140.0,
        )
        # Falls through to trade_current_price, not "quote_bid".
        assert src == "trade_current_price_stale"


class TestPnLSourceContractWithProductionCode:
    """Pin the production code to keep emitting `pnl_source` on every
    bot row. If a future refactor strips it, this test fires."""

    def test_bot_row_payload_includes_pnl_source_field(self):
        """The bot-row payload dict must include a `pnl_source` key.
        We inspect the source of `get_our_positions` to enforce this
        without spinning up the full async stack."""
        import inspect
        from services.sentcom_service import get_sentcom_service
        svc = get_sentcom_service()
        src = inspect.getsource(svc.get_our_positions)
        # The bot-row block must stamp pnl_source.
        assert '"pnl_source": pnl_source' in src
        # And the classifier vocabulary must be present.
        assert "trade_current_price_stale" in src
        assert "entry_price_fallback" in src
        assert "quote_last" in src

    def test_orphan_row_still_emits_pnl_source(self):
        """The orphan-row payload (v19.34.142a) already emits
        pnl_source. Belt-and-suspenders test: both branches stamp it."""
        import inspect
        from services.sentcom_service import get_sentcom_service
        svc = get_sentcom_service()
        src = inspect.getsource(svc.get_our_positions)
        # Both branches should stamp pnl_source. Count occurrences:
        # we expect at least 2 (orphan branch + bot branch).
        assert src.count('"pnl_source"') >= 2


@pytest.mark.parametrize("live_quote,trade_cp,entry,expected", [
    ({"last": 100.5}, 99.0, 95.0, "quote_last"),
    ({"close": 100.5}, 99.0, 95.0, "quote_close"),
    ({}, 99.0, 95.0, "trade_current_price_stale"),
    ({}, 0, 95.0, "entry_price_fallback"),
    ({}, None, 0, "unknown"),
])
def test_classifier_parametrized(live_quote, trade_cp, entry, expected):
    assert _classify_bot_pnl_source(
        live_quote=live_quote,
        trade_current_price=trade_cp,
        entry=entry,
    ) == expected
