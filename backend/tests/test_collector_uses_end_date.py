"""
Regression guard: the Windows collector MUST pass the queue row's `end_date`
into `ib_insync.reqHistoricalData(endDateTime=...)`. If it hardcodes "" again,
every walkback chunk re-fetches the same latest window and IB throttles with
the 15s "identical request" rule. This silently broke a 21k-request backfill
for ~36 hours on 2026-04-24.

These contracts don't import ib_insync (not available on the DGX), they
parse the collector source instead. Fast, deterministic, no network.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

COLLECTOR_PATH = Path("/app/documents/scripts/ib_historical_collector.py")
BACKEND_PLANNER_PATH = Path("/app/backend/services/ib_historical_collector.py")


def _read(p: Path) -> str:
    assert p.exists(), f"missing file: {p}"
    return p.read_text(encoding="utf-8")


def test_collector_reqhistoricaldata_uses_end_date():
    """reqHistoricalData(endDateTime=...) must reference the request's end_date,
    NOT a hardcoded empty string. If this regresses, chunk walkback breaks."""
    src = _read(COLLECTOR_PATH)

    # Find the reqHistoricalData call
    m = re.search(r"reqHistoricalData\((?P<body>.*?)\)", src, re.DOTALL)
    assert m, "reqHistoricalData call not found in collector"
    body = m.group("body")

    # Must pass endDateTime=end_date (variable), NOT endDateTime="" literal.
    assert 'endDateTime=""' not in body, (
        "REGRESSION: collector hardcodes endDateTime=\"\" — walkback is broken. "
        "Pass the queue row's end_date through instead."
    )
    assert re.search(r"endDateTime\s*=\s*end_date\b", body), (
        "reqHistoricalData must use endDateTime=end_date from the request dict"
    )


def test_collector_normalizes_hyphen_end_date_to_space():
    """IB's TWS API requires endDateTime in 'YYYYMMDD HH:MM:SS' form. Legacy
    queue rows stored a hyphen; the collector must normalize before the call."""
    src = _read(COLLECTOR_PATH)
    # Look for the normalization logic: replace hyphen at index 8 with a space.
    assert 'end_date[8] == "-"' in src, (
        "collector must tolerate legacy hyphen-form end_date rows in the queue"
    )
    assert 'end_date[:8] + " " + end_date[9:]' in src, (
        "hyphen -> space normalization must occur before reqHistoricalData"
    )


def test_backend_planner_emits_space_format_end_date():
    """Backend planner must emit 'YYYYMMDD HH:MM:SS' (space), not hyphen form."""
    src = _read(BACKEND_PLANNER_PATH)
    assert '"%Y%m%d %H:%M:%S"' in src, (
        "planner must strftime('%Y%m%d %H:%M:%S') — space-separated, IB-native"
    )
    # The old hyphen form should no longer be used for enqueueing walkbacks.
    # (It may still appear in comments or unrelated log lines; restrict match
    # to actual strftime calls to avoid false positives.)
    bad = re.findall(r'strftime\(\s*"[^"]*%Y%m%d-%H:%M:%S[^"]*"', src)
    assert not bad, (
        f"planner still produces hyphen-form end_date via strftime: {bad}"
    )


def test_pacing_key_includes_duration_and_end_date():
    """IBPacingManager dedup key must be (symbol, bar_size, duration, end_date)
    — widening this from (symbol, bar_size) is what makes chunked walkbacks
    actually progress without paying the 15s identical-request tax."""
    src = _read(COLLECTOR_PATH)
    m = re.search(
        r"def\s+_key\s*\(.*?\):.*?return\s+\((?P<tuple>[^)]+)\)",
        src,
        re.DOTALL,
    )
    assert m, "_key method not found in IBPacingManager"
    tup = m.group("tuple")
    for part in ("symbol", "bar_size", "duration", "end_date"):
        assert part in tup, f"_key tuple missing `{part}`: {tup!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
