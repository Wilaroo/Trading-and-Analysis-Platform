"""
v19.34.27 — Boot rehydration format-string crash hardening.

Pre-fix: bot_persistence.restore_open_trades(...) logged restored trades
with `f"... @ ${trade.fill_price:.2f}, stop=${trade.stop_price:.2f}"`.
When a Mongo `bot_trades` document had `fill_price: null` or
`stop_price: null` (closed/stale records, partial saves before the entry
filled), `dict.get(key, default)` returned None — NOT the default —
because the key is PRESENT but the value is None. Applying `:.2f` to
None raised `unsupported format string passed to NoneType.__format__`,
caught by the surrounding broad except, which warned
`Failed to restore trade SYMBOL` for every record on every boot.

Post-fix: fill_price coerces None → entry_price at restore time, and the
log line further coerces None → 0.0 defensively. Result: no more boot-
time WARN noise from rehydration of partial documents.

This test exercises the format guard directly so the regression is
caught even if the surrounding restore_open_trades() flow gets
restructured later.
"""
from __future__ import annotations


def _format_log_pre_fix(symbol: str, fill_price, stop_price) -> str:
    """Mirror the pre-fix code path so the test fails red on the same
    error the operator saw in production logs."""
    return (
        f"📥 Restored trade: {symbol} long 100 shares "
        f"@ ${fill_price:.2f}, stop=${stop_price:.2f}"
    )


def _format_log_post_fix(symbol: str, fill_price, stop_price) -> str:
    """Mirror the v19.34.27 patched format path."""
    fp = fill_price if fill_price is not None else 0.0
    sp = stop_price if stop_price is not None else 0.0
    return (
        f"📥 Restored trade: {symbol} long 100 shares "
        f"@ ${fp:.2f}, stop=${sp:.2f}"
    )


def test_pre_fix_format_crashes_on_none_fill_price():
    """Sanity: confirm the original failure mode is real."""
    import pytest
    with pytest.raises(TypeError, match="unsupported format string"):
        _format_log_pre_fix("AAPL", None, 142.50)


def test_pre_fix_format_crashes_on_none_stop_price():
    import pytest
    with pytest.raises(TypeError, match="unsupported format string"):
        _format_log_pre_fix("AAPL", 145.10, None)


def test_post_fix_format_handles_none_fill_price():
    out = _format_log_post_fix("AAPL", None, 142.50)
    assert "$0.00" in out
    assert "stop=$142.50" in out


def test_post_fix_format_handles_none_stop_price():
    out = _format_log_post_fix("AAPL", 145.10, None)
    assert "@ $145.10" in out
    assert "stop=$0.00" in out


def test_post_fix_format_handles_both_none():
    out = _format_log_post_fix("AAPL", None, None)
    assert "@ $0.00" in out
    assert "stop=$0.00" in out


def test_post_fix_format_preserves_normal_path():
    out = _format_log_post_fix("AAPL", 145.10, 142.50)
    assert "AAPL" in out
    assert "@ $145.10" in out
    assert "stop=$142.50" in out


def test_actual_implementation_matches_post_fix_path():
    """Read the real source so refactors that drop the None-guard fail."""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "services" / "bot_persistence.py"
    text = src.read_text()
    # Either the explicit fp/sp coercion lines or an equivalent
    # `or 0.0` guard must remain in place.
    assert (
        "fp = trade.fill_price if trade.fill_price is not None else 0.0"
        in text
    ), "v19.34.27 fill_price None-guard missing from bot_persistence.py"
    assert (
        "sp = trade.stop_price if trade.stop_price is not None else 0.0"
        in text
    ), "v19.34.27 stop_price None-guard missing from bot_persistence.py"


def test_fill_price_assignment_coerces_none():
    """The other half of the fix: when trade_doc has fill_price=None,
    we must fall back to entry_price instead of carrying None forward."""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "services" / "bot_persistence.py"
    text = src.read_text()
    assert (
        'raw_fill = trade_doc.get("fill_price")' in text
        and "raw_fill if raw_fill is not None else entry_price" in text
    ), "v19.34.27 fill_price restore-time coercion missing"
