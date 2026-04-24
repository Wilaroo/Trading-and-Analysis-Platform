"""
Regression guard for the gap-analysis / fill-gaps staleness bug fixed 2026-04-24.

BUG: Before this fix, `/api/ib-collector/gap-analysis` and `/fill-gaps` treated
"symbol has any historical bar" as "symbol has data". So a symbol like SPY with
32,396 bars — all older than 2026-03-16 — was reported as `has_data`, `coverage
100%`, `needs_fill: false`. The training pipeline froze at a March-16 cutoff
while the NIA "Fill Gaps" button silently did nothing for core ETFs.

FIX: Both endpoints now run an index-backed `$group → $max(date)` aggregation
and flag a symbol as a gap if its latest bar is older than a bar_size-specific
threshold (e.g. >3 days old for 5-min bars).

These are pure static/source checks — they do NOT require a live Mongo or IB,
so they run in CI on every commit.
"""
from pathlib import Path
import re

ROUTER = Path(__file__).parent.parent / "routers" / "ib_collector_router.py"
SRC = ROUTER.read_text()


def test_gap_analyzer_computes_max_date_per_symbol():
    """Analyzer must do $max(date) per symbol, not just `$group: _id: symbol`."""
    # The fix replaces the old `distinct("symbol", ...)` with an aggregation
    # that includes `{"max_date": {"$max": "$date"}}`.
    assert '"$max": "$date"' in SRC, (
        "Gap analyzer must compute $max(date) per symbol to detect stale tails. "
        "Before the fix it used distinct() which only checks symbol existence."
    )


def test_gap_analyzer_defines_staleness_thresholds():
    """Must have per-bar_size staleness thresholds (days)."""
    assert "STALE_DAYS" in SRC, "Staleness threshold map missing."
    # Must cover every bar_size the tiers reference
    for bs in ["1 min", "5 mins", "15 mins", "30 mins", "1 hour", "1 day", "1 week"]:
        assert f'"{bs}"' in SRC, f"STALE_DAYS must cover bar_size '{bs}'"


def test_gap_analyzer_exposes_stale_vs_missing_split():
    """Response payload must distinguish `missing` (no bars) from `stale` (old bars)
    so the UI can show both cases — critical for telling the user 'your SPY data
    is OLD' vs 'you have no SPY data at all'."""
    for key in ["total_missing_symbols", "total_stale_symbols",
                "has_data_fresh", "has_data_stale", "sample_stale"]:
        assert key in SRC, f"Gap-analysis response must expose '{key}'."


def test_fill_gaps_queues_stale_symbols_not_just_missing():
    """/fill-gaps must include BOTH missing and stale symbols in the collection
    job — otherwise the analyzer reports a gap and the fill button does nothing."""
    # The fix concatenates both buckets via `needs_fill = missing_symbols + stale_symbols`
    assert "needs_fill = missing_symbols + stale_symbols" in SRC, (
        "/fill-gaps must queue stale_symbols in addition to missing_symbols. "
        "Previously only zero-data symbols were queued, so stale-tail SPY was ignored."
    )


def test_staleness_parser_handles_iso_with_tz_suffixes():
    """_is_stale must handle ISO strings with +HH:MM, -HH:MM, or Z suffixes
    (all three exist in the production DB). If parsing breaks, the symbol
    must be treated as stale (fail-safe) so it gets refreshed."""
    # Check proximity rather than regexing across nested function bodies.
    idx_def = SRC.find("def _is_stale")
    assert idx_def != -1, "Couldn't locate _is_stale body."
    # Window of ~1200 chars from the first _is_stale def should contain the
    # Z-normalization, fromisoformat call, and a fail-safe return True.
    window = SRC[idx_def : idx_def + 1200]
    assert 'replace("Z", "+00:00")' in window, (
        "_is_stale must normalize 'Z' suffix before fromisoformat."
    )
    assert "fromisoformat" in window, "_is_stale must parse ISO dates."
    assert re.search(r"except\s+Exception:\s*\n\s*return True", window), (
        "_is_stale must fail-safe to True on parse errors so unknown-format "
        "bars don't silently mask a missing collection."
    )


def test_defined_in_both_endpoints():
    """Both /gap-analysis and /fill-gaps must use the same staleness logic."""
    # Count occurrences — should appear at least twice (one per endpoint)
    assert SRC.count("STALE_DAYS = {") >= 2, (
        "Both /gap-analysis and /fill-gaps must define STALE_DAYS so they "
        "stay in sync. If they diverge, the analyzer and the fill button "
        "can disagree about what needs collecting."
    )
    assert SRC.count("def _is_stale") >= 2, (
        "Both endpoints must define their own _is_stale (scope is inside "
        "each thread-pool function)."
    )
