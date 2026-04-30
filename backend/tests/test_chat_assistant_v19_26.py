"""
test_chat_assistant_v19_26.py — pin the AI chat assistant data-plumbing
fixes shipped in v19.26.

Two operator-reported bugs in the same chat session (2026-05-01 chat
log, message timestamps 2:10:21 PM and 2:13:38 PM ET):

  Bug 1 — "what is our stop on SOFI?" → "I don't have a stop price
          recorded for the SOFI long position"
          Root cause: chat_server._get_portfolio_context() reads the
          `bot_open_trades` array from `ib_live_snapshot` directly.
          SOFI/SBUX/OKLO are IB-only orphans with NO entry in that
          array. v19.23.1 lazy-reconcile only patched the SentCom V5
          UI payload — never reached the chat context builder.
  Fix:    Add lazy-reconcile lookup in chat_server: for every IB
          position not present in `bot_open_trades`, query
          `bot_trades` for the most recent matching record and
          surface its stop_price + target_prices into the bot-tracked
          trades context block.

  Bug 2 — "should i go long SQQQ or go short SQQQ right now?" →
          "I don't have a live quote on SQQQ right now"
          Root cause: chat_server only fetches /api/live/symbol-snapshot
          for held positions + (SPY, QQQ, IWM, VIX). SQQQ isn't held
          and isn't in the hardcoded index list, so no live data lands
          in the LLM context. The system prompt's safety rule
          ("never guess prices for symbols not in LIVE DATA") then
          forces the "I don't have a quote" refusal.
  Fix:    Extract ticker-shaped tokens from the user's message,
          filter against a denylist of common all-caps trading
          shorthand (LONG / SHORT / VWAP / RSI / etc.), and include
          up to 5 mentioned tickers in the live-snapshot + technicals
          fetch lists.

Tests run pure-Python — no Mongo, no requests.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --------------------------------------------------------------------------
# Bug 2: ticker extraction from user message
# --------------------------------------------------------------------------

def test_extract_user_mentioned_tickers_basic():
    """The bug-trigger message: 'should i go long SQQQ or go short SQQQ
    right now?' must yield ['SQQQ']. LONG and SHORT are denylisted."""
    from chat_server import _extract_user_mentioned_tickers
    msg = "should i go long SQQQ or go short SQQQ right now?"
    out = _extract_user_mentioned_tickers(msg)
    assert "SQQQ" in out
    assert "LONG" not in out
    assert "SHORT" not in out


def test_extract_handles_multiple_distinct_tickers():
    """Operator paragraph with several names — order preserved, deduped."""
    from chat_server import _extract_user_mentioned_tickers
    msg = "TSLA looks weak, NVDA bouncing off VWAP, what about AMD vs SPY?"
    out = _extract_user_mentioned_tickers(msg)
    assert out == ["TSLA", "NVDA", "AMD", "SPY"]


def test_extract_filters_trading_jargon():
    """Operator's natural trading vocabulary must NOT leak into ticker
    candidates. RSI / VWAP / EMA / ATR / RVOL / FOMC / EOD all stripped."""
    from chat_server import _extract_user_mentioned_tickers
    msg = "is RSI overbought, VWAP rejection on EMA 20, ATR is low, RVOL spike at FOMC, hold to EOD"
    out = _extract_user_mentioned_tickers(msg)
    for jargon in ("RSI", "VWAP", "EMA", "ATR", "RVOL", "FOMC", "EOD"):
        assert jargon not in out, f"{jargon} leaked into ticker candidates"


def test_extract_caps_at_limit():
    """Avoid context bloat — never surface more than `limit` tickers
    even if the operator dumps 10 names."""
    from chat_server import _extract_user_mentioned_tickers
    msg = "watch SPY QQQ TSLA NVDA AAPL META GOOG AMZN MSFT NFLX"
    out = _extract_user_mentioned_tickers(msg, limit=5)
    assert len(out) == 5
    assert out == ["SPY", "QQQ", "TSLA", "NVDA", "AAPL"]


def test_extract_handles_empty_or_none_message():
    """Defensive guards — must never raise on empty or non-string input."""
    from chat_server import _extract_user_mentioned_tickers
    assert _extract_user_mentioned_tickers(None) == []
    assert _extract_user_mentioned_tickers("") == []
    assert _extract_user_mentioned_tickers("   ") == []
    assert _extract_user_mentioned_tickers(123) == []  # type: ignore


def test_extract_strips_lowercase_words():
    """Tickers MUST be all-caps. 'long', 'short', 'sqqq' all skipped."""
    from chat_server import _extract_user_mentioned_tickers
    msg = "should I go long sqqq or short sqqq?"
    out = _extract_user_mentioned_tickers(msg)
    assert out == []  # nothing all-caps survived denylist filter


def test_extract_picks_up_dotted_tickers():
    """Some tickers contain a dot (BRK.A, BRK.B). Regex allows
    `[A-Z][A-Z0-9.]{0,4}` so these get captured."""
    from chat_server import _extract_user_mentioned_tickers
    out = _extract_user_mentioned_tickers("compare BRK.B vs BRK.A")
    assert "BRK.B" in out
    assert "BRK.A" in out


# --------------------------------------------------------------------------
# Bug 1: lazy-reconcile in chat context (source-level pin)
# --------------------------------------------------------------------------

def test_chat_context_has_lazy_reconcile_block():
    """`_get_portfolio_context` MUST include a lazy-reconcile lookup
    against `bot_trades` for IB orphan positions. Without this, the
    chat assistant cannot tell the operator the stop price on
    SOFI/SBUX/OKLO when those positions exist."""
    import inspect
    import chat_server as cs
    src = inspect.getsource(cs._get_portfolio_context)
    # Must reference bot_trades collection
    assert 'db["bot_trades"].find_one' in src
    # Must scan IB positions for orphans (not in bot_open_trades)
    assert "tracked_symbols" in src
    assert "orphan_positions" in src
    # Must surface stop_price + target_prices on the reconciled rows
    assert "stop_price" in src
    assert "target_prices" in src
    # Must mark reconciled rows in the debug payload so we can audit
    # which symbols got the lookup
    assert "lazy_reconciled" in src


def test_chat_context_signature_accepts_user_message():
    """v19.26 changed the signature so the `/chat` endpoint can pass
    in `request.message`. If this regresses, Bug-2 ticker extraction
    silently stops working."""
    import inspect
    from chat_server import _get_portfolio_context
    sig = inspect.signature(_get_portfolio_context)
    assert "user_message" in sig.parameters


def test_chat_context_passes_user_message_to_extractor():
    """The chat() endpoint must pass `request.message` into context
    builder. Source pin so a refactor can't drop it."""
    import inspect
    import chat_server as cs
    chat_src = inspect.getsource(cs.chat)
    assert "_get_portfolio_context(user_message=request.message)" in chat_src


def test_chat_context_hydrates_user_mentioned_tickers_in_live_block():
    """Source pin: the live-snapshot fetch loop must include every
    user-mentioned ticker in its target list, with cap bumped from
    10 to 15 so the user-mentioned tickers don't get truncated by
    a busy book. Without this, the SQQQ refusal regresses."""
    import inspect
    import chat_server as cs
    src = inspect.getsource(cs._get_portfolio_context)
    # The extractor must be called with the user_message
    assert "_extract_user_mentioned_tickers(user_message" in src
    # And the resulting tickers must feed into the snapshot target list
    assert "user_mentioned_tickers" in src
    # Cap bumped from 10 to 15
    assert "_live_snapshot_targets[:15]" in src
    # Technicals loop also bumped (12 → 15)
    assert "held_symbols[:15]" in src


def test_chat_context_extractor_runs_before_live_snapshot_block():
    """Ordering matters: the ticker extraction must run BEFORE the
    live-snapshot fetch loop so the extracted tickers are available
    when the loop builds its target list."""
    import inspect
    import chat_server as cs
    src = inspect.getsource(cs._get_portfolio_context)
    extract_idx = src.find("_extract_user_mentioned_tickers(user_message")
    fetch_loop_idx = src.find("_live_snapshot_targets[:15]")
    assert extract_idx > 0
    assert fetch_loop_idx > 0
    assert extract_idx < fetch_loop_idx, (
        "ticker extraction must run before the live-snapshot fetch loop"
    )
