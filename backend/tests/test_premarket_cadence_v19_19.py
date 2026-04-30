"""
v19.19 — Premarket scan cadence + heartbeat fixes (2026-04-30).

Pre-v19.19:
1. Premarket scans ran only every 10th cycle × 120s sleep =
   20 minutes between real premarket scans. Operator at 8:40 AM
   ET expected to see alerts accumulating in the opening-bell
   watchlist, saw none because the scanner was still waiting
   for the next `% 10` window.
2. The `_last_scan_time` attribute was only updated in the RTH
   branch — during premarket and after-hours, it stayed at
   whatever RTH value it had (or None). This made
   `/api/system/morning-readiness` report "scanner silent"
   falsely during the morning prep window.
3. `morning_readiness_service.py` was reading
   `_last_scan_at` (wrong attr name) which always returned
   None, forcing the fallback "cycle_count" message instead
   of showing actual scanner activity.

v19.19 fixes all three in one pass:
- Premarket cadence `% 10` → `% 2` (4 min between real scans).
- `_last_scan_time` is stamped on EVERY tick (premarket, RTH,
  after-hours) so readiness checks see a fresh heartbeat.
- `morning_readiness_service._check_scanner_running` now reads
  the correct attribute name.
"""
from __future__ import annotations

import os


def _scanner_src() -> str:
    p = os.path.join(
        os.path.dirname(__file__), "..", "services", "enhanced_scanner.py"
    )
    with open(p) as f:
        return f.read()


def _readiness_src() -> str:
    p = os.path.join(
        os.path.dirname(__file__), "..", "services",
        "morning_readiness_service.py",
    )
    with open(p) as f:
        return f.read()


# --------------------------------------------------------------------------
# Cadence pin
# --------------------------------------------------------------------------

def test_premarket_cadence_is_every_2nd_cycle():
    """v19.19 cadence — premarket scan runs on every 2nd cycle
    (not every 10th as pre-fix).

    With 120s sleep between cycles, `% 2` gives a real premarket
    scan every 4 min. 7:00-9:30 AM ET window = 150 min = ~37
    scan refreshes. Enough to track gap evolution without
    thrashing the pusher.
    """
    src = _scanner_src()
    # Pin the v19.19 premarket `% 2` form explicitly.
    assert (
        "if self._scan_count % 2 == 0 or self._scan_count == 0:"
        in src
    ), "premarket cadence regressed from v19.19 `% 2` form"
    # Defensive: guard against silent revert to the old `% 10`.
    # Only check the modulus expression form in the premarket block
    # (not comments that might mention the v19.19 change history).
    premarket_idx = src.find(
        "PRE-MARKET MODE: Build morning watchlist"
    )
    assert premarket_idx > 0
    block = src[premarket_idx:premarket_idx + 2500]
    assert "self._scan_count % 10 == 0" not in block, (
        "v19.19 premarket cadence regressed — `% 10` modulus is back "
        "inside the PREMARKET block"
    )


# --------------------------------------------------------------------------
# Heartbeat pin
# --------------------------------------------------------------------------

def test_last_scan_time_stamped_during_premarket():
    """The premarket branch MUST assign `self._last_scan_time` each
    cycle so morning_readiness sees a fresh heartbeat during the
    morning prep window.
    """
    src = _scanner_src()
    premarket_idx = src.find(
        "PRE-MARKET MODE: Build morning watchlist"
    )
    assert premarket_idx > 0
    # Look for the heartbeat stamp within the next 2000 chars.
    block = src[premarket_idx:premarket_idx + 2000]
    assert "self._last_scan_time = datetime.now(timezone.utc)" in block, (
        "premarket branch missing the v19.19 heartbeat stamp"
    )


def test_last_scan_time_stamped_during_afterhours():
    """After-hours branch must also stamp `_last_scan_time` so
    morning_readiness during pre-RTH (when we've just transitioned
    from after-hours) shows the scanner as alive, not dead."""
    src = _scanner_src()
    ah_idx = src.find("After-hours sweep #")
    assert ah_idx > 0
    # Walk back to the enclosing if block.
    block = src[max(0, ah_idx - 500):ah_idx + 2000]
    assert "self._last_scan_time = datetime.now(timezone.utc)" in block, (
        "after-hours branch missing the v19.19 heartbeat stamp"
    )


# --------------------------------------------------------------------------
# morning_readiness reads the correct attr name
# --------------------------------------------------------------------------

def test_morning_readiness_reads_last_scan_time_correctly():
    """The scanner's attr is `_last_scan_time` (not `_last_scan_at`).
    If the readiness check uses the wrong name, `scan_age_s` will
    always be None and the operator sees the fallback "cycle_count"
    message instead of real activity timing."""
    src = _readiness_src()
    assert 'getattr(scanner, "_last_scan_time"' in src
    # The wrong attribute name must be gone.
    assert '_last_scan_at' not in src, (
        "morning_readiness still references the (wrong) _last_scan_at "
        "attribute — scanner.age will always be None"
    )


# --------------------------------------------------------------------------
# Heuristic — make sure the cadence numbers make sense at a glance
# --------------------------------------------------------------------------

def test_premarket_real_scan_interval_is_approximately_4_minutes():
    """At `% 2` cadence with 120s sleep, real premarket scans
    fire every 240s (4 min). Convert the constants directly from
    the source and assert.
    """
    src = _scanner_src()
    premarket_idx = src.find(
        "PRE-MARKET MODE: Build morning watchlist"
    )
    block = src[premarket_idx:premarket_idx + 2500]
    # Pull the `% N` modulus + the `sleep(X)` argument.
    import re
    mod_match = re.search(r"self\._scan_count %\s*(\d+)", block)
    sleep_match = re.search(r"await asyncio\.sleep\((\d+)\)", block)
    assert mod_match, "couldn't find % modulus in premarket block"
    assert sleep_match, "couldn't find sleep() in premarket block"
    modulus = int(mod_match.group(1))
    sleep_s = int(sleep_match.group(1))
    real_scan_interval_s = modulus * sleep_s
    assert 180 <= real_scan_interval_s <= 360, (
        f"premarket cadence {real_scan_interval_s}s is outside the "
        f"reasonable 3-6 min window. modulus={modulus}, sleep={sleep_s}"
    )
