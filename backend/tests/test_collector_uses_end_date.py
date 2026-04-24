"""
Regression guard: the Windows collector MUST pass the queue row's `end_date`
into `ib_insync.reqHistoricalData(endDateTime=...)`. If it hardcodes "" again,
every walkback chunk re-fetches the same latest window and IB throttles with
the 15s "identical request" rule. This silently broke a 21k-request backfill
for ~36 hours on 2026-04-24.

2026-04-26: widened to allow either "space" (legacy, default) or "hyphen"
(newer, silences IB Warning 2174) format via env flag IB_ENDDATE_FORMAT.

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

    m = re.search(r"reqHistoricalData\((?P<body>.*?)\)", src, re.DOTALL)
    assert m, "reqHistoricalData call not found in collector"
    body = m.group("body")

    assert 'endDateTime=""' not in body, (
        "REGRESSION: collector hardcodes endDateTime=\"\" — walkback is broken. "
        "Pass the queue row's end_date through instead."
    )
    assert re.search(r"endDateTime\s*=\s*end_date\b", body), (
        "reqHistoricalData must use endDateTime=end_date from the request dict"
    )


def test_collector_normalizes_both_date_formats():
    """Collector must support BOTH formats via IB_ENDDATE_FORMAT env:
       space form (legacy, default):  'YYYYMMDD HH:MM:SS'
       hyphen form (newer, 2174 fix): 'YYYYMMDD-HH:MM:SS'
    The normalization block must flip queue rows into the configured form
    so legacy/new rows coexist across a rolling env change."""
    src = _read(COLLECTOR_PATH)
    # Env-driven format selection
    assert 'IB_ENDDATE_FORMAT' in src, (
        "collector must read IB_ENDDATE_FORMAT env var to gate space/hyphen format"
    )
    # Must still reference the char-index-8 separator (date/time boundary)
    assert 'end_date[8]' in src, (
        "collector must inspect end_date[8] (date/time separator) to normalise"
    )
    # Both substitutions must appear: '-' -> ' ' (legacy path) and ' ' -> '-'
    # (preferred path). Exact code shape may differ but both substrings exist.
    assert 'end_date[:8] + "-" + end_date[9:]' in src, (
        "collector must be able to flip space -> hyphen when IB_ENDDATE_FORMAT=hyphen"
    )
    assert 'end_date[:8] + " " + end_date[9:]' in src, (
        "collector must be able to flip hyphen -> space (legacy path)"
    )


def test_backend_planner_is_env_gated_and_supports_both_formats():
    """Planner must read IB_ENDDATE_FORMAT and emit matching strftime."""
    src = _read(BACKEND_PLANNER_PATH)
    assert 'IB_ENDDATE_FORMAT' in src, (
        "planner must read IB_ENDDATE_FORMAT env var to choose date format"
    )
    # Both strftime patterns must be present (env selects which runs)
    assert '"%Y%m%d %H:%M:%S"' in src, (
        "planner must support space-format strftime (legacy / default)"
    )
    assert '"%Y%m%d-%H:%M:%S"' in src, (
        "planner must support hyphen-format strftime (IB 2174 preferred)"
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
