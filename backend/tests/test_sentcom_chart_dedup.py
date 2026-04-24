"""
Regression guard: `/api/sentcom/chart` must return bars that are strictly
ascending and unique by `time`. Duplicates crash lightweight-charts on the
frontend with "Assertion failed: data must be asc ordered by time" and
corrupt EMA/BB windows computed server-side.

Reproducer (2026-04-24): chunked backfill merged two overlapping windows
at a session boundary, yielding two bars with identical unix-second
timestamps — the Command Center crashed at ChartPanel with index=42.
"""
from __future__ import annotations

import re
from pathlib import Path

SENTCOM_CHART_PATH = Path("/app/backend/routers/sentcom_chart.py")


def _read(p: Path) -> str:
    assert p.exists(), f"missing file: {p}"
    return p.read_text(encoding="utf-8")


def test_chart_endpoint_dedupes_by_time():
    """The chart endpoint must de-duplicate bars by `time` after sorting
    so lightweight-charts never sees two rows with the same timestamp."""
    src = _read(SENTCOM_CHART_PATH)

    # Must still sort ascending
    assert 'normalised.sort(key=lambda r: r["time"])' in src, (
        "chart endpoint must sort bars ascending by time"
    )

    # Must then dedupe — look for the distinctive pattern that collapses
    # consecutive equal-time rows.
    dedupe_pattern = re.compile(
        r'if\s+deduped\s+and\s+deduped\[-1\]\["time"\]\s*==\s*r\["time"\]',
        re.MULTILINE,
    )
    assert dedupe_pattern.search(src), (
        "chart endpoint must dedupe consecutive bars with identical time"
    )

    # Dedup must precede indicator computation (EMA / BB rely on unique x-axis).
    sort_idx = src.index('normalised.sort(key=lambda r: r["time"])')
    ema_idx = src.index("_ema(closes")
    dedupe_idx = dedupe_pattern.search(src).start()
    assert sort_idx < dedupe_idx < ema_idx, (
        "dedupe must happen AFTER sort and BEFORE indicator computation"
    )


def test_chart_endpoint_keeps_freshest_duplicate():
    """When two bars share a timestamp, the later one (freshest chunk)
    must win. Comment + implementation should reflect that contract."""
    src = _read(SENTCOM_CHART_PATH)
    # Either the assignment overwrites the last element, or there's explicit
    # freshness handling. We check for the simpler "overwrite" form.
    assert "deduped[-1] = r" in src, (
        "dedupe must keep the last-seen row so freshest backfill chunk wins"
    )
