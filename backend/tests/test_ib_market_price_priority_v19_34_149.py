"""v19.34.149 — IB.marketPrice source priority for bot PnL.

After v19.34.148 healed avg_cost drift, the operator's audit still
showed ~$400 of delta clustering 100% on `pnl_source=quote_last`.
Root cause: the bot used the L1 pusher's `last` tick while IB
computed its own `unrealizedPNL` against `updatePortfolio().marketPrice`
— two different feeds tick at slightly different cadence, on a
750-sh SIVR position the gap can be ~$150.

Fix: when IB pushes a positive `marketPrice` for a symbol via its
portfolio snapshot, prefer it over `quote_last`. Bot and IB then
mathematically agree on the mark; audit delta collapses to ~$0.

This file pins:
  • New `pnl_source` value `ib_market_price` on bot rows
  • Priority chain: ib_market_price > quote_last > quote_close >
    trade_current_price_stale > entry_price_fallback > unknown
  • The classifier matches the production source as a contract
    string-search test
"""

import pytest


# Pure-function mirror of the v19.34.149 inline logic in
# sentcom_service.get_our_positions (bot-row branch).
def _classify_bot_pnl_source_v149(
    *, ib_market_price, live_quote, trade_current_price, entry
):
    pnl_source = "unknown"
    live_price = live_quote.get("last") or live_quote.get("close")
    if ib_market_price and float(ib_market_price) > 0:
        pnl_source = "ib_market_price"
    elif live_price and float(live_price) > 0:
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


class TestIbMarketPriceWinsOverQuoteLast:

    def test_ib_market_price_present_wins(self):
        """Both IB.marketPrice and quote_last are positive → IB wins."""
        src = _classify_bot_pnl_source_v149(
            ib_market_price=137.50,
            live_quote={"last": 137.45, "close": 137.40},
            trade_current_price=137.30,
            entry=135.00,
        )
        assert src == "ib_market_price"

    def test_ib_market_price_zero_falls_through_to_quote_last(self):
        src = _classify_bot_pnl_source_v149(
            ib_market_price=0,
            live_quote={"last": 137.45},
            trade_current_price=137.30,
            entry=135.00,
        )
        assert src == "quote_last"

    def test_ib_market_price_none_falls_through(self):
        src = _classify_bot_pnl_source_v149(
            ib_market_price=None,
            live_quote={"last": 137.45},
            trade_current_price=137.30,
            entry=135.00,
        )
        assert src == "quote_last"

    def test_ib_market_price_and_no_quote_still_wins(self):
        """If IB's snapshot is the only positive source, use it."""
        src = _classify_bot_pnl_source_v149(
            ib_market_price=137.50,
            live_quote={},
            trade_current_price=0,
            entry=135.00,
        )
        assert src == "ib_market_price"

    def test_fallback_chain_unchanged_when_ib_absent(self):
        # quote_last
        assert _classify_bot_pnl_source_v149(
            ib_market_price=0, live_quote={"last": 100},
            trade_current_price=99, entry=95,
        ) == "quote_last"
        # quote_close
        assert _classify_bot_pnl_source_v149(
            ib_market_price=0, live_quote={"close": 100},
            trade_current_price=99, entry=95,
        ) == "quote_close"
        # trade_current_price_stale
        assert _classify_bot_pnl_source_v149(
            ib_market_price=0, live_quote={},
            trade_current_price=99, entry=95,
        ) == "trade_current_price_stale"
        # entry_price_fallback
        assert _classify_bot_pnl_source_v149(
            ib_market_price=0, live_quote={},
            trade_current_price=0, entry=95,
        ) == "entry_price_fallback"
        # unknown
        assert _classify_bot_pnl_source_v149(
            ib_market_price=0, live_quote={},
            trade_current_price=0, entry=0,
        ) == "unknown"


class TestProductionContract:

    def test_sentcom_service_prefers_ib_market_price(self):
        """The production code must read ib_market_price from
        ib_pos_by_symbol BEFORE consulting live_quote.last."""
        import inspect
        from services.sentcom_service import get_sentcom_service
        svc = get_sentcom_service()
        src = inspect.getsource(svc.get_our_positions)
        # The new branch is in the source.
        assert 'pnl_source = "ib_market_price"' in src
        assert 'ib_pos_info.get("market_price")' in src
        # The v149 marker comment.
        assert "v19.34.149" in src

    def test_audit_hint_map_documents_ib_market_price(self):
        """The cluster-hint map must include a description for the
        new `ib_market_price` source so dominant-cluster lines surface
        a meaningful remediation."""
        import inspect
        from routers.diagnostic_router import position_pnl_audit
        src = inspect.getsource(position_pnl_audit)
        assert '"ib_market_price"' in src
        # Surrounding hint copy.
        assert "broker-side" in src.lower() or "broker side" in src.lower()


@pytest.mark.parametrize("ib_mark,quote_last,expected", [
    (137.50, 137.45, "ib_market_price"),
    (0,      137.45, "quote_last"),
    (None,   137.45, "quote_last"),
    (137.50, None,   "ib_market_price"),
])
def test_priority_table(ib_mark, quote_last, expected):
    lq = {"last": quote_last} if quote_last is not None else {}
    src = _classify_bot_pnl_source_v149(
        ib_market_price=ib_mark, live_quote=lq,
        trade_current_price=100, entry=95,
    )
    assert src == expected
