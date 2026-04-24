"""
Regression guard for the IBPacingManager dedup-key widening fixed 2026-04-24.

BUG: The old dedup key was `(symbol, bar_size)`, causing every chunk of a
walk-back request for the same symbol+bar_size to wait 13.9s for the IB
identical-request cooldown — even though the chunks differed in `duration`
and would NOT be identical in IB's eyes. This slowed the 21k-request
backfill to ~15 h.

FIX: Dedup key is now `(symbol, bar_size, duration, end_date)` which
matches IB's actual identical-request definition. Overall 60/10min window
limit is still enforced — this only changes the 15s cooldown.
"""
from pathlib import Path
import re
import sys

# The Windows collector script lives in /app/documents/scripts
SCRIPT = Path(__file__).parent.parent.parent / "documents" / "scripts" / "ib_historical_collector.py"
SRC = SCRIPT.read_text()


def test_pacing_manager_has_duration_aware_key():
    """IBPacingManager methods must accept `duration` + `end_date` kwargs."""
    for method in ("can_make_request", "record_request", "wait_time"):
        sig = re.search(
            rf"def\s+{method}\(self[^)]*duration[^)]*end_date[^)]*\)",
            SRC,
        )
        assert sig is not None, (
            f"IBPacingManager.{method}() must accept duration + end_date kwargs. "
            "Without this, chunked backfill requests pay the 15s cooldown "
            "even when they are not identical to IB."
        )


def test_pacing_key_helper_uses_all_four_fields():
    """The `_key` helper must build a 4-tuple from (symbol, bar_size, duration, end_date)."""
    assert "def _key(self, symbol" in SRC, "Missing _key helper on IBPacingManager."
    # Match `return (symbol, bar_size, duration or "", end_date or "")`
    assert re.search(
        r"return\s*\(\s*symbol\s*,\s*bar_size\s*,\s*duration\s*or\s*\"\"\s*,\s*end_date\s*or\s*\"\"\s*\)",
        SRC,
    ), "IBPacingManager._key must return (symbol, bar_size, duration, end_date) with None-safe fallbacks."


def test_fetch_historical_passes_duration_to_pacing():
    """fetch_historical_data must pass duration/end_date into the pacing checks
    so the widened key actually takes effect on the hot path."""
    # All three call sites should now pass 4 args
    for call in ("can_make_request", "record_request", "wait_time"):
        pattern = rf"self\.pacing\.{call}\(\s*symbol\s*,\s*bar_size\s*,\s*duration\s*,\s*end_date\s*\)"
        assert re.search(pattern, SRC), (
            f"fetch_historical_data must call self.pacing.{call}"
            f"(symbol, bar_size, duration, end_date). Old 2-arg calls "
            "bypass the fix and re-create the 13.9s cooldown."
        )


def test_window_limit_still_enforced():
    """The 60/10min window limit must NOT have been removed — it's the
    last line of defense against IB pacing violations."""
    assert re.search(
        r"if\s+len\(self\.request_times\)\s*>=\s*self\.max_requests",
        SRC,
    ), (
        "Window-based rate limit check was removed. Without it, the "
        "collector could hit IB pacing violations and get blocked for "
        "5-10 minutes."
    )
    assert "window_seconds" in SRC, "window_seconds config must still exist."


def test_max_requests_default_is_conservative():
    """Default max_requests must stay ≤ 60 (IB's hard limit) with headroom."""
    m = re.search(r"max_requests:\s*int\s*=\s*(\d+)", SRC)
    assert m is not None, "max_requests default not found in __init__."
    assert int(m.group(1)) <= 60, (
        f"max_requests default = {m.group(1)}. IB's hard limit is 60 per "
        "10 min per client ID — a buffer is required."
    )
