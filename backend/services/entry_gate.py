"""
v19.34.243 — per-entry batch gate (entry-control safety).

The trading bot's scan→evaluate→execute loop checks the operator PAUSE flag and
the max-open-positions CAP ONCE at the top of each cycle, then iterates a batch
of alerts and fires each without re-checking. Two live incidents traced to this:

  • 2026-06-02: position count overshot the cap to 27 (open=24, cap=25, then a
    3-alert cycle opened 3 more) — the cap was checked once, not per entry, and
    counted only open trades, not in-flight pending ones.
  • 2026-06-03: CEG was entered ~minutes after the operator paused the scanner —
    the cycle was already mid-batch when paused, so the in-flight alerts kept
    firing (pause only gated NEW alert intake at the top of the cycle).

This pure helper is the per-entry decision, re-evaluated before EVERY entry so a
mid-cycle pause or a cap hit HALTS the rest of the batch immediately. Isolated +
dependency-free so it is trivially unit-testable apart from the bot service.
"""


def per_entry_gate_should_stop(open_count, pending_count, cap, paused: bool) -> bool:
    """Return True when the current scan cycle must STOP opening further
    positions: the operator paused mid-cycle, OR open+pending has reached the
    effective position cap. Counting pending makes in-flight entries count
    against the cap (closes the batch-race overshoot). Fail-open: malformed
    counts never spuriously halt trading."""
    if paused:
        return True
    try:
        return (int(open_count) + int(pending_count)) >= int(cap)
    except (TypeError, ValueError):
        return False


# v19.34.244 — DISABLED_SETUPS blocklist. Confirmed money-losing setup VARIANTS
# the bot must not TRADE (scanner still surfaces them for monitoring). Operator
# overrides via the DISABLED_SETUPS env var (env REPLACES this default entirely —
# so the default is the canonical proven-bleeder list; drop the env to use it).
#
# 2026-06-26 — promoted the proven-bleeder blocklist into code (was an env-only
# override of just "daily_breakout,vwap_fade_short", which silently left the
# other leaks enabled). Justified by the 120d realized-R audits
# (/api/slow-learning/setup-ev + entry-feature-discovery, where setup_type was the
# dominant realized-R factor, eta²=0.21):
#   • vwap_fade_short  — 10% win, -3.82R/n60 (the dominant leak)
#   • daily_breakout   — 5.9% win, -0.54R/n17 (30d); volatile, outlier-driven +R on 120d
#   • vwap_bounce      — 16% win, -1.22R/n31
#   • off_sides_short  — 19% win, -0.58R/n16
# vwap_fade_long (+0.22R) and backside (mild -0.19R, operator chose to keep) stay enabled.
DEFAULT_DISABLED_SETUPS = "daily_breakout,vwap_fade_short,vwap_bounce,off_sides_short"


def parse_disabled_setups(raw, default: str = DEFAULT_DISABLED_SETUPS) -> set:
    """Parse a comma-separated DISABLED_SETUPS string into a lowercase set.
    `raw=None` (env unset) falls back to `default`; `raw=""` yields an empty set
    (operator explicitly cleared the blocklist)."""
    src = default if raw is None else raw
    return {s.strip().lower() for s in str(src).split(",") if s.strip()}
