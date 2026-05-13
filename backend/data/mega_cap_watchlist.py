"""
Mega-Cap Must-Scan Watchlist (v19.34.138)
==========================================
Hardcoded list of 50 high-volume / high-momentum names that MUST be in
Tier 1 of every scan cycle regardless of whether `symbol_adv_cache`
has them, whether they're flagged `unqualifiable`, or whether their
ADV has temporarily fallen below the $50M intraday threshold.

WHY THIS EXISTS
---------------
The wave scanner sources Tier 2 from `symbol_adv_cache.find()` ranked
by `avg_dollar_volume`. That's correct 95% of the time, BUT it has
three known failure modes that silently drop popular movers:

1. UNQUALIFIABLE FALSE-POSITIVES
   Since 2026-04-29 the `UNQUALIFIABLE_FAILURE_THRESHOLD` is 1 strike.
   A single transient "No security definition" from IB during any
   backfill burst permanently nukes a symbol from every scan tier.
   Recently re-listed names (SNDK = Sandisk reborn Feb 2025) and
   newer IPOs are especially vulnerable.

2. STALE `symbol_adv_cache`
   If `IBHistoricalCollector.rebuild_adv_from_ib()` hasn't run for a
   week, big movers that have RECENTLY exploded in volume (e.g. a
   small-cap caught a meme wave) won't be ranked in the top-200
   even though they're objectively in-play TODAY.

3. ADV DIPS BELOW THRESHOLD ON A SLOW DAY
   A $50M-ADV name on a holiday-shortened week can drop just below
   the line and get demoted from intraday → swing tier, falling out
   of Tier 2 for that wave cycle.

For all three failure modes, the answer is the same: pin the names
you ALWAYS want scanned, regardless of cache state. This list is
that pin.

CURATION RATIONALE
------------------
Names below are chosen on three orthogonal axes — pick from each so
the bot doesn't blindspot any popular operator-watched cohort:

  A. MAG-7 + ADJACENTS (10) — AAPL, MSFT, GOOGL, AMZN, NVDA, META,
     TSLA, AVGO, NFLX, ORCL
  B. SEMICONDUCTORS / AI INFRA (10) — AMD, MU, SNDK, ARM, SMCI,
     QCOM, MRVL, TSM, ASML, AVGO (overlaps A — kept for clarity)
  C. CRYPTO / FINTECH HIGH-BETA (8) — COIN, MSTR, HOOD, SOFI, PLTR,
     MARA, RIOT, CLSK
  D. EV / MOBILITY (5) — TSLA (A), RIVN, LCID, NIO, CHPT
  E. STRUCTURAL HIGH-VOL ETFs (10) — SPY, QQQ, IWM, DIA, VIX,
     XLK, XLE, XLF, TLT, GLD
  F. RECENT-CYCLE STANDOUTS (10) — RBLX, AFRM, U, DDOG, NET, SNOW,
     SHOP, ABNB, UBER, DASH

WHEN TO EDIT THIS LIST
----------------------
Quarterly review. Add a name when:
  - It's been in the top-20 trending-search lists for >5 sessions, AND
  - The operator has manually mentioned it in a chat session, AND
  - It's NOT in `symbol_adv_cache` or is unqualifiable.

Remove a name when:
  - It's been below $5M ADV for >30 sessions, AND
  - The operator hasn't mentioned it in 30 days.

Curated 2026-02-13 (v19.34.138).
"""
from __future__ import annotations

from typing import List


# 50 unique tickers, deduped across categories.
# Keep alphabetised for fast visual scan / diff review.
MEGA_CAP_WATCHLIST: List[str] = sorted({
    # Mag-7 + adjacents
    "AAPL", "AMZN", "AVGO", "GOOGL", "META", "MSFT", "NFLX", "NVDA",
    "ORCL", "TSLA",
    # Semis / AI infra
    "AMD", "ARM", "ASML", "MRVL", "MU", "QCOM", "SMCI", "SNDK", "TSM",
    # Crypto / fintech high-beta
    "CLSK", "COIN", "HOOD", "MARA", "MSTR", "PLTR", "RIOT", "SOFI",
    # EV / mobility
    "CHPT", "LCID", "NIO", "RIVN",
    # Structural high-volume ETFs
    "DIA", "GLD", "IWM", "QQQ", "SPY", "TLT", "VIX", "XLE", "XLF", "XLK",
    # Recent-cycle standouts
    "ABNB", "AFRM", "DASH", "DDOG", "NET", "RBLX", "SHOP", "SNOW", "U",
    "UBER",
})


def get_mega_cap_watchlist() -> List[str]:
    """Return a fresh copy so callers can't mutate the module state."""
    return list(MEGA_CAP_WATCHLIST)


def is_mega_cap(symbol: str) -> bool:
    """Quick membership check used by diagnostics + UI badges."""
    if not symbol:
        return False
    return symbol.upper().strip() in MEGA_CAP_WATCHLIST


def get_categories() -> dict:
    """Return the category breakdown for /api/diagnostic/scanner-coverage
    rendering. Kept in sync with the curation rationale above."""
    return {
        "mag7_plus": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
                      "TSLA", "AVGO", "NFLX", "ORCL"],
        "semis_ai_infra": ["AMD", "MU", "SNDK", "ARM", "SMCI", "QCOM",
                           "MRVL", "TSM", "ASML"],
        "crypto_fintech": ["COIN", "MSTR", "HOOD", "SOFI", "PLTR",
                           "MARA", "RIOT", "CLSK"],
        "ev_mobility": ["RIVN", "LCID", "NIO", "CHPT"],
        "structural_etfs": ["SPY", "QQQ", "IWM", "DIA", "VIX", "XLK",
                            "XLE", "XLF", "TLT", "GLD"],
        "recent_standouts": ["RBLX", "AFRM", "U", "DDOG", "NET", "SNOW",
                             "SHOP", "ABNB", "UBER", "DASH"],
    }
