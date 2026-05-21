"""v19.34.69 — `_resolve_orphan_atr` source-priority + safety tests.

Bug fixed: v19.34.68 read `quote.atr / quote.atr_14` directly from the
pusher-relayed L1 feed. The pusher payload doesn't carry ATR (operator
dump 2026-05-12), so the widen-stop path was a silent no-op — every
adopted IB orphan fell back to the 2% pct floor, including the exact
ARM case the patch was meant to fix.

The fix wires ATR resolution through the same chain used by the live
executor + retune-stop endpoint:

  bot._latest_atr_5m → bot._scanner._latest_atr → quote.atr/atr_14
  → "unavailable" (0.0)

These tests stub a minimal bot/scanner and verify each priority tier
works, falls through correctly, and stays safe against garbage inputs.
"""
import pytest

from services.position_reconciler import PositionReconciler


class _FakeScanner:
    def __init__(self, atr_map=None):
        self._latest_atr = atr_map or {}


class _FakeBot:
    def __init__(self, atr_5m=None, scanner_atr=None, has_scanner=True):
        self._latest_atr_5m = atr_5m if atr_5m is not None else {}
        if has_scanner:
            self._scanner = _FakeScanner(scanner_atr or {})
        # else: no scanner attribute at all


def _resolve(bot, symbol, quote=None):
    """Shortcut for the static method under test."""
    return PositionReconciler._resolve_orphan_atr(bot, symbol, quote)


# ─────────────────────── tier 1: bot 5m cache wins ───────────────────────
def test_primary_bot_5m_cache_wins():
    bot = _FakeBot(atr_5m={"ARM": 8.0}, scanner_atr={"ARM": 99.0})
    val, source = _resolve(bot, "ARM", {"atr": 7.0})
    assert val == 8.0
    assert source == "bot_5m_cache"


def test_primary_cache_uppercased_keys_standard_path():
    """Pusher always uppercases symbols before populating the bot's ATR
    caches, so in practice both the lookup key and the stored key are
    upper. This test locks in that standard path."""
    bot = _FakeBot(atr_5m={"ARM": 8.0})
    val, source = _resolve(bot, "ARM", None)
    assert source == "bot_5m_cache"
    assert val == 8.0


def test_primary_cache_lowercase_input_uppercased_by_helper():
    """If a caller ever passes a lowercase symbol, the helper uppercases
    it before the cache lookup, so production-cased ("ARM") cache entries
    still match."""
    bot = _FakeBot(atr_5m={"ARM": 8.0})
    val, source = _resolve(bot, "arm", None)
    assert source == "bot_5m_cache"
    assert val == 8.0


# ─────────────────────── tier 2: scanner cache fallback ───────────────────────
def test_scanner_cache_used_when_bot_cache_empty():
    bot = _FakeBot(atr_5m={}, scanner_atr={"ARM": 7.5})
    val, source = _resolve(bot, "ARM", None)
    assert val == 7.5
    assert source == "scanner_cache"


def test_scanner_cache_used_when_bot_cache_has_other_symbols():
    bot = _FakeBot(atr_5m={"MSFT": 4.0}, scanner_atr={"ARM": 7.5})
    val, source = _resolve(bot, "ARM", None)
    assert source == "scanner_cache"
    assert val == 7.5


def test_scanner_missing_attr_gracefully_falls_through():
    """If bot has no `_scanner` at all, we should not blow up."""
    bot = _FakeBot(atr_5m={}, has_scanner=False)
    val, source = _resolve(bot, "ARM", None)
    assert val == 0.0
    assert source == "unavailable"


# ─────────────────────── tier 3: legacy quote payload ───────────────────────
def test_quote_atr_used_when_both_caches_empty():
    bot = _FakeBot(atr_5m={}, scanner_atr={})
    val, source = _resolve(bot, "ARM", {"atr": 6.25})
    assert val == 6.25
    assert source == "quote_payload"


def test_quote_atr_14_alternate_field():
    bot = _FakeBot(atr_5m={}, scanner_atr={})
    val, source = _resolve(bot, "ARM", {"atr_14": 5.5})
    assert val == 5.5
    assert source == "quote_payload"


# ─────────────────────── tier 4: unavailable ───────────────────────
def test_unavailable_when_all_sources_empty():
    bot = _FakeBot()
    val, source = _resolve(bot, "ARM", {})
    assert val == 0.0
    assert source == "unavailable"


def test_unavailable_when_quote_is_none():
    bot = _FakeBot()
    val, source = _resolve(bot, "ARM", None)
    assert val == 0.0
    assert source == "unavailable"


# ─────────────────────── safety: garbage inputs ───────────────────────
def test_zero_atr_in_bot_cache_skipped():
    """ATR of 0 in the cache should be treated as missing, not used.
    Otherwise we'd set atr_distance=0 and silently lose widening."""
    bot = _FakeBot(atr_5m={"ARM": 0.0}, scanner_atr={"ARM": 7.5})
    val, source = _resolve(bot, "ARM", None)
    assert val == 7.5
    assert source == "scanner_cache"


def test_negative_atr_in_bot_cache_skipped():
    """Pusher snapshot occasionally serves negative ATR after a contract
    switch (legacy bug). Treat as missing."""
    bot = _FakeBot(atr_5m={"ARM": -3.0}, scanner_atr={"ARM": 7.5})
    val, source = _resolve(bot, "ARM", None)
    assert source == "scanner_cache"
    assert val == 7.5


def test_none_atr_in_caches_skipped():
    bot = _FakeBot(atr_5m={"ARM": None}, scanner_atr={"ARM": None})
    val, source = _resolve(bot, "ARM", {"atr": 4.0})
    assert source == "quote_payload"
    assert val == 4.0


def test_bot_with_no_atr_attrs_safe():
    """Older bot snapshots predate `_latest_atr_5m`. Should not raise."""

    class _BareBot:
        pass

    val, source = _resolve(_BareBot(), "ARM", None)
    assert val == 0.0
    assert source == "unavailable"


def test_empty_symbol_safe():
    bot = _FakeBot(atr_5m={"": 5.0})
    # Even though we technically have a value for "", upper("") == "" — the
    # helper safely returns 0.0 because the cache lookup happens to match
    # an empty-key entry. That's a non-issue: callers always pass a real
    # symbol. This test just locks in "no crash."
    val, source = _resolve(bot, "", None)
    # Either it picks up the empty-key value or returns unavailable —
    # both are acceptable, but it MUST NOT raise.
    assert source in {"bot_5m_cache", "unavailable"}
    assert val >= 0


# ─────────────────────── priority ordering invariant ───────────────────────
def test_priority_order_invariant():
    """When all four tiers have data, primary (bot_5m_cache) wins."""
    bot = _FakeBot(atr_5m={"ARM": 1.0}, scanner_atr={"ARM": 2.0})
    val, source = _resolve(bot, "ARM", {"atr": 3.0, "atr_14": 4.0})
    assert source == "bot_5m_cache"
    assert val == 1.0


def test_priority_skips_to_scanner_then_quote():
    bot = _FakeBot(atr_5m={}, scanner_atr={})
    val, source = _resolve(bot, "ARM", {"atr_14": 4.0})
    assert source == "quote_payload"
    assert val == 4.0


# ─────────────────────── exception swallowing ───────────────────────
def test_cache_raises_on_access_falls_through():
    """If the cache attribute access itself raises (e.g. shadow property
    backed by a broken descriptor), we must not crash the reconciler."""

    class _ExplodingBot:
        @property
        def _latest_atr_5m(self):
            raise RuntimeError("cache exploded")

        _scanner = _FakeScanner({"ARM": 5.0})

    val, source = _resolve(_ExplodingBot(), "ARM", None)
    assert source == "scanner_cache"
    assert val == 5.0
