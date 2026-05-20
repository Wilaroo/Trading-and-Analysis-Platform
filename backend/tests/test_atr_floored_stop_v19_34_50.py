"""v19.34.50 — _atr_floored_stop fail-closed pct fallback when ATR missing/zero.

Covers the regression the 2026-05-20 audit caught: 41/42 guardrail
stop_too_tight vetoes traced to scanner emitting raw tight stops
because snapshot.atr was 0 at scan time.
"""
import pathlib
import pytest


@pytest.fixture
def helper():
    """Extract _atr_floored_stop without triggering enhanced_scanner package init."""
    p = pathlib.Path(__file__).resolve().parents[1] / "services" / "enhanced_scanner.py"
    src = p.read_text()
    start = src.index("def _atr_floored_stop")
    end = src.index("\n    async def ", start)
    fn_src = src[start:end]
    # Re-indent the method body to be a top-level function for isolated exec
    lines = fn_src.split("\n")
    # First line is `def _atr_floored_stop(...):` already at 0 indent after strip
    # Subsequent lines are indented by 8 spaces (method body) — strip 4 to make
    # them function-body level (4 spaces).
    out = [lines[0]]
    for ln in lines[1:]:
        out.append(ln[4:] if ln.startswith("    ") else ln)
    # Prepend a no-op `self` placeholder: replace `self, ` from signature.
    fn_only = "\n".join(out).replace("self, ", "", 1)
    ns = {}
    exec(compile(fn_only, "_atr_floored_stop_extract", "exec"), ns)
    return ns["_atr_floored_stop"]


def test_atr_present_long_widens_to_floor(helper):
    assert helper(entry_price=100.0, raw_stop=99.95, atr=2.0,
                  direction="long", min_atr_mult=0.5) == 99.00

def test_atr_present_short_widens_to_floor(helper):
    assert helper(entry_price=100.0, raw_stop=100.05, atr=2.0,
                  direction="short", min_atr_mult=0.5) == 101.00

def test_atr_present_wide_raw_stop_preserved_long(helper):
    assert helper(entry_price=100.0, raw_stop=97.50, atr=2.0,
                  direction="long", min_atr_mult=0.5) == 97.50

def test_atr_missing_long_pct_fallback(helper, monkeypatch):
    monkeypatch.delenv("ATR_FLOOR_PCT_FALLBACK", raising=False)
    assert helper(entry_price=100.0, raw_stop=99.95, atr=0,
                  direction="long", min_atr_mult=0.5) == 99.00

def test_atr_missing_short_pct_fallback(helper, monkeypatch):
    monkeypatch.delenv("ATR_FLOOR_PCT_FALLBACK", raising=False)
    assert helper(entry_price=100.0, raw_stop=100.05, atr=None,
                  direction="short", min_atr_mult=0.5) == 101.00

def test_atr_missing_env_override(helper, monkeypatch):
    monkeypatch.setenv("ATR_FLOOR_PCT_FALLBACK", "0.02")
    assert helper(entry_price=100.0, raw_stop=99.95, atr=0,
                  direction="long", min_atr_mult=0.5) == 98.00

def test_audit_regression_xly_backside(helper, monkeypatch):
    monkeypatch.delenv("ATR_FLOOR_PCT_FALLBACK", raising=False)
    # XLY case: entry=115.10, raw_stop=115.07, ATR=0 at scan time.
    # Old: returned 115.07 (vetoed). New: 1% pct floor → 113.95.
    assert helper(entry_price=115.10, raw_stop=115.07, atr=0,
                  direction="long", min_atr_mult=0.5) == 113.95

def test_audit_regression_sndk_vwap_fade_short(helper, monkeypatch):
    monkeypatch.delenv("ATR_FLOOR_PCT_FALLBACK", raising=False)
    # SNDK case: entry=1391.83, ATR=0. New: 1% pct floor → 1405.75.
    assert helper(entry_price=1391.83, raw_stop=1384.74, atr=0,
                  direction="short", min_atr_mult=0.5) == 1405.75

def test_invalid_entry_returns_raw(helper):
    assert helper(entry_price=0, raw_stop=99.95, atr=2.0,
                  direction="long", min_atr_mult=0.5) == 99.95
