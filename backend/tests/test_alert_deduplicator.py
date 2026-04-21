"""Unit tests for AlertDeduplicator (2026-04-21).

Covers the hard-veto semantics that stopped the PRCT vwap_fade_short stacking
disaster: repeat scanner fires on an already-open (symbol, setup, direction)
get dropped, and fresh fires get a 5-min cooldown.
"""
from services.alert_deduplicator import AlertDeduplicator, _key, is_open_for_key


def test_key_normalizes_casing_and_whitespace():
    assert _key(" aapl ", "RUBBER_BAND", "Long") == ("AAPL", "rubber_band", "long")


def test_is_open_for_key_matches_dict_and_obj():
    class T:
        symbol, setup_type, direction = "AAPL", "rubber_band", "long"

    dict_trade = {"symbol": "AAPL", "setup_type": "rubber_band", "direction": "long"}
    key = ("AAPL", "rubber_band", "long")
    assert is_open_for_key(key, [T()]) is True
    assert is_open_for_key(key, [dict_trade]) is True
    assert is_open_for_key(("MSFT", "rubber_band", "long"), [T()]) is False


def test_skip_when_already_open():
    d = AlertDeduplicator(cooldown_s=300)
    open_trades = [{"symbol": "AAPL", "setup_type": "rubber_band", "direction": "long"}]
    r = d.should_skip("AAPL", "rubber_band", "long", open_trades=open_trades)
    assert r.skip and "duplicate_open_position" in r.reason


def test_skip_within_cooldown_window():
    d = AlertDeduplicator(cooldown_s=300)
    d.mark_fired("AAPL", "rubber_band", "long", now=1000.0)
    r = d.should_skip("AAPL", "rubber_band", "long", open_trades=[], now=1100.0)
    assert r.skip and "cooldown_active" in r.reason


def test_allow_after_cooldown_expires():
    d = AlertDeduplicator(cooldown_s=300)
    d.mark_fired("AAPL", "rubber_band", "long", now=1000.0)
    r = d.should_skip("AAPL", "rubber_band", "long", open_trades=[], now=1301.0)
    assert not r.skip


def test_allow_different_direction_same_symbol_same_setup():
    """User may flip long→short after closing long — don't block the new direction."""
    d = AlertDeduplicator(cooldown_s=300)
    d.mark_fired("AAPL", "rubber_band", "long", now=1000.0)
    r = d.should_skip("AAPL", "rubber_band", "short", open_trades=[], now=1100.0)
    assert not r.skip


def test_allow_different_setup_same_symbol_same_direction():
    d = AlertDeduplicator(cooldown_s=300)
    d.mark_fired("AAPL", "rubber_band", "long", now=1000.0)
    r = d.should_skip("AAPL", "abc_scalp", "long", open_trades=[], now=1100.0)
    assert not r.skip


def test_open_position_check_takes_precedence_over_cooldown():
    """If a trade is already open, dedup reason should be 'duplicate_open_position'
    even if the cooldown would also fire — easier to diagnose from logs."""
    d = AlertDeduplicator(cooldown_s=300)
    d.mark_fired("AAPL", "rubber_band", "long", now=1000.0)
    open_trades = [{"symbol": "AAPL", "setup_type": "rubber_band", "direction": "long"}]
    r = d.should_skip("AAPL", "rubber_band", "long", open_trades=open_trades, now=1100.0)
    assert r.skip
    assert "duplicate_open_position" in r.reason
    assert "cooldown_active" not in r.reason


def test_clear_resets_state():
    d = AlertDeduplicator(cooldown_s=300)
    d.mark_fired("AAPL", "rubber_band", "long")
    d.mark_fired("MSFT", "rubber_band", "long")
    n = d.clear()
    assert n == 2
    # After clear, any key should pass
    assert not d.should_skip("AAPL", "rubber_band", "long", open_trades=[]).skip
