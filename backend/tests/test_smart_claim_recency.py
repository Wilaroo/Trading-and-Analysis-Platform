"""
Regression guard for the `skipped_complete` bug fixed 2026-04-24.

BUG: `POST /api/ib/smart-batch-claim` checked ONLY bar count against a
threshold to decide `skipped_complete`. A symbol with 32k bars whose newest
was 38 days old got instantly marked complete without ever hitting IB. That
silently froze SPY/QQQ/DIA/IWM at their March-16 cutoff for the entire
training universe.

FIX: Skip-complete now requires BOTH count ≥ threshold AND the latest bar
to be within a bar_size-specific recency window (`_latest_bar_too_old`
helper).
"""
from pathlib import Path
import re

IB_ROUTER = Path(__file__).parent.parent / "routers" / "ib.py"
SRC = IB_ROUTER.read_text()


def test_smart_batch_claim_has_recency_helper():
    """Must define the `_latest_bar_too_old` helper that checks max(date)."""
    assert "def _latest_bar_too_old" in SRC, (
        "smart-batch-claim must define _latest_bar_too_old to prevent "
        "coverage-by-existence false-positives for stale symbols."
    )
    # Must read max(date) from ib_historical_data
    idx = SRC.find("def _latest_bar_too_old")
    window = SRC[idx : idx + 1500]
    assert 'sort=[("date", -1)]' in window, (
        "_latest_bar_too_old must query the newest bar via sort(date, -1)."
    )
    assert "fromisoformat" in window, (
        "_latest_bar_too_old must parse ISO dates."
    )
    # Fail-safe: on parse error, treat as stale → fetch
    assert re.search(r"except\s+Exception:\s*(?:#[^\n]*\n\s*)*return True", window), (
        "_latest_bar_too_old must fail-safe to True (= fetch, don't skip) "
        "on parse errors. Otherwise an unknown-format date could mask "
        "missing-data silently."
    )


def test_skipped_complete_requires_both_count_and_recency():
    """The skip branch must AND count with recency — old version was count-only."""
    # Find the exact skip check and assert recency is in the boolean.
    m = re.search(
        r"if\s+bar_count_existing\s*>=\s*threshold\s+and\s+not\s+_latest_bar_too_old",
        SRC,
    )
    assert m is not None, (
        "smart-batch-claim skip condition must AND the count check with "
        "`not _latest_bar_too_old(...)`. If the staleness check is missing "
        "or stripped out, we're back to the SPY-frozen-at-March-16 bug."
    )


def test_stale_days_map_covers_all_barsizes():
    """STALE_DAYS must cover every bar_size the collector can request."""
    assert "STALE_DAYS = {" in SRC, "STALE_DAYS map missing in ib.py"
    # Every bar_size from COMPLETENESS_THRESHOLDS must also have a STALE_DAYS entry
    threshold_block = re.search(r"COMPLETENESS_THRESHOLDS\s*=\s*\{(.*?)\}", SRC, re.DOTALL)
    stale_block = re.search(r"STALE_DAYS\s*=\s*\{(.*?)\}", SRC, re.DOTALL)
    assert threshold_block and stale_block, "Could not locate both maps."
    threshold_keys = set(re.findall(r'"([^"]+)"\s*:', threshold_block.group(1)))
    stale_keys = set(re.findall(r'"([^"]+)"\s*:', stale_block.group(1)))
    missing = threshold_keys - stale_keys
    assert not missing, (
        f"STALE_DAYS must cover every bar_size in COMPLETENESS_THRESHOLDS. "
        f"Missing: {missing}"
    )


def test_recency_window_tighter_than_training_cadence():
    """Intraday bar thresholds must be ≤ 7 days. If they drift up, users can
    silently train on weeks-stale data again."""
    stale_block = re.search(r"STALE_DAYS\s*=\s*\{(.*?)\}", SRC, re.DOTALL)
    pairs = re.findall(r'"([^"]+)"\s*:\s*(\d+)', stale_block.group(1))
    values = {k: int(v) for k, v in pairs}
    # Anchor the tightest: intraday timeframes must be ≤ 7 days stale
    for bs in ("1 min", "5 mins", "15 mins", "30 mins", "1 hour"):
        assert values[bs] <= 7, (
            f"STALE_DAYS['{bs}'] = {values[bs]} days is too loose. "
            "Intraday training needs bars within the last trading week."
        )
