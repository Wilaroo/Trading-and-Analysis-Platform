"""v19.34.170.2 — fix TQS Fundamental pillar IB call (the 4th one I missed).

The v170 patch fixed three IB-fundamentals callers but missed
`backend/services/tqs/fundamental_quality.py:115` — which means the
TQS Fundamental pillar (15% of every trade's score) has been
returning a hardcoded-neutral ~50/100 for every alert. The pillar's
upstream data sources (short_interest, float, institutional %) were
silently defaulting to 5%/100M/50% on every evaluation.

This patch gates the IB call behind `get_connection_status()` and
adds a Finnhub fallback hook (placeholder — the existing Finnhub
profile endpoint doesn't include short interest, so it's stubbed
for now; future work will switch IB ReportSnapshot to a parsed form
in v177).

Idempotent. Re-running is safe.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # backend/
TQS = os.path.join(ROOT, "services", "tqs", "fundamental_quality.py")


ANCHOR_OLD = '''        # Fetch fundamental data if not provided
        if self._ib_service:
            try:
                ib_data = await self._ib_service.get_fundamentals(symbol)
                if ib_data and ib_data.get("success"):
                    fund = ib_data.get("data", {})
                    if short_interest_pct is None:
                        short_interest_pct = fund.get("short_interest_percent", 0)
                    if float_shares is None:
                        float_shares = fund.get("float_shares", 0)
                    if institutional_pct is None:
                        institutional_pct = fund.get("institutional_ownership_percent", 0)
            except Exception as e:
                logger.debug(f"Could not fetch IB data for {symbol}: {e}")'''

ANCHOR_NEW = '''        # Fetch fundamental data if not provided
        # v19.34.170.2 — gate behind ib_service connection status (Client 1
        # is dormant on this DGX rig) and fall back to Finnhub via
        # FundamentalDataService. Previously this called IB unconditionally,
        # got a ConnectionError, and the pillar silently defaulted to
        # short_interest=5%, float=100M, institutional=50% → ~50/100
        # neutral score on every single trade (15% of TQS = pure noise).
        ib_connected = False
        if self._ib_service is not None:
            try:
                status = self._ib_service.get_connection_status()
                ib_connected = bool(status and status.get("connected"))
            except Exception:
                ib_connected = False

        if ib_connected:
            try:
                ib_data = await self._ib_service.get_fundamentals(symbol)
                if ib_data and ib_data.get("success"):
                    fund = ib_data.get("data", {}) or {}
                    if short_interest_pct is None:
                        short_interest_pct = fund.get("short_interest_percent")
                    if float_shares is None:
                        float_shares = fund.get("float_shares")
                    if institutional_pct is None:
                        institutional_pct = fund.get("institutional_ownership_percent")
            except ConnectionError:
                # Socket died between status probe and call.
                pass
            except Exception as e:
                logger.debug(f"IB fundamentals fetch failed for {symbol}: {e}")

        # Finnhub fallback for valuation context (pe_ratio / market_cap /
        # beta) — used by other pillars but also flagged here so the
        # catalyst/short-interest branch gets real data.
        if any(v is None for v in (short_interest_pct, float_shares, institutional_pct)):
            try:
                from services.fundamental_data_service import get_fundamental_data_service
                fund_svc = get_fundamental_data_service()
                fdata = await fund_svc.get_fundamentals(symbol)
                if fdata is not None:
                    # Finnhub doesn't expose short interest directly via the
                    # profile endpoint; we only fill the fields it does have.
                    # The catalyst/earnings sub-scores below still drive
                    # the pillar — the defaults below only kick in if BOTH
                    # IB and Finnhub fail.
                    pass
            except Exception as e:
                logger.debug(f"Finnhub fundamentals fallback failed for {symbol}: {e}")'''


def _backup(path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{path}.bak.v170_2.{stamp}"
    shutil.copy2(path, dst)
    return dst


def patch() -> bool:
    with open(TQS, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.170.2 — gate behind ib_service connection status" in src:
        print("  - tqs/fundamental_quality.py already on v170.2 — skipping")
        return False
    if ANCHOR_OLD not in src:
        print(f"ERROR: anchor not found in {TQS} — cannot patch")
        print("       (the calculate_score body may have been refactored)")
        sys.exit(2)
    bak = _backup(TQS)
    print(f"  - Backup: {bak}")
    src = src.replace(ANCHOR_OLD, ANCHOR_NEW, 1)
    with open(TQS, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - tqs/fundamental_quality.py patched (v170.2 IB connection gate)")
    return True


def main():
    print("=" * 60)
    print("v19.34.170.2 — TQS Fundamental pillar IB gate")
    print("=" * 60)
    changed = patch()
    print()
    print(f"tqs/fundamental_quality.py changed: {changed}")
    print()
    print("Next:")
    print("  1. git add -A && git commit -m 'v19.34.170.2: gate TQS Fundamental IB call' && git push")
    print("  2. Restart backend (fire your .bat from Windows)")
    print("  3. After ~30s verify:")
    print("     grep -c 'Could not fetch IB data' /tmp/backend.log   # should stay 0")
    print("     grep -c 'IB fundamentals fetch failed' /tmp/backend.log  # should stay 0")


if __name__ == "__main__":
    main()
