"""v19.34.170.1 — follow-up: gate quality_service IB fundamentals fetch.

The v170 deploy patched `trade_context_service._capture_fundamental_context`
but missed a second IB-fundamentals caller in `quality_service._fetch_from_ib`
that fires the same `Not connected to IB` WARN per alert. This patch
gates that caller behind `ib_service.get_connection_status()` too.

Idempotent. Re-running is safe.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # backend/
QS = os.path.join(ROOT, "services", "quality_service.py")


QS_ANCHOR_OLD = '''    async def _fetch_from_ib(self, symbol: str) -> Optional[QualityMetrics]:
        """Fetch fundamental data from Interactive Brokers"""
        if not self.ib_service:
            return None
        
        try:
            fundamentals = await self.ib_service.get_fundamentals(symbol)
            
            if not fundamentals or fundamentals.get("error"):
                return None
            
            metrics = QualityMetrics(symbol=symbol.upper())
            metrics.data_source = "interactive_brokers"
            
            # IB provides limited fundamental data
            # Extract what's available
            if "market_cap" in fundamentals:
                # Can use market cap for relative comparisons
                pass
            
            metrics.data_quality = "low"  # IB fundamentals are limited
            return metrics
            
        except Exception as e:
            logger.warning(f"IB fundamentals fetch failed for {symbol}: {e}")
            return None'''


QS_ANCHOR_NEW = '''    async def _fetch_from_ib(self, symbol: str) -> Optional[QualityMetrics]:
        """Fetch fundamental data from Interactive Brokers.

        v19.34.170.1 — gate behind ``get_connection_status()`` so we
        don't trip the WARN "Not connected to IB" log on every alert
        when the legacy direct ib_insync socket is dormant (which is
        the normal steady-state on the DGX where live data flows
        through the IB pusher RPC). When IB is down we silently fall
        back to the next data source upstream.
        """
        if not self.ib_service:
            return None

        # Skip when the direct IB worker reports disconnected — every
        # other quality data source (FMP, Finnhub) is preferred anyway,
        # and the IB ReportSnapshot XML isn't parsed by this method.
        try:
            status = self.ib_service.get_connection_status()
            if not (status and status.get("connected")):
                return None
        except Exception:
            # If even the status probe fails, the socket is definitely down.
            return None

        try:
            fundamentals = await self.ib_service.get_fundamentals(symbol)

            if not fundamentals or fundamentals.get("error"):
                return None

            metrics = QualityMetrics(symbol=symbol.upper())
            metrics.data_source = "interactive_brokers"

            # IB provides limited fundamental data
            # Extract what's available
            if "market_cap" in fundamentals:
                # Can use market cap for relative comparisons
                pass

            metrics.data_quality = "low"  # IB fundamentals are limited
            return metrics

        except ConnectionError as ce:
            # Lost the socket between status probe and call — demote
            # to debug, no log spam.
            logger.debug(f"IB went stale mid-quality fetch for {symbol}: {ce}")
            return None
        except Exception as e:
            logger.warning(f"IB fundamentals fetch failed for {symbol}: {e}")
            return None'''


def _backup(path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{path}.bak.v170_1.{stamp}"
    shutil.copy2(path, dst)
    return dst


def patch_qs() -> bool:
    with open(QS, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.170.1 — gate behind" in src:
        print("  - quality_service.py already on v170.1 — skipping")
        return False
    if QS_ANCHOR_OLD not in src:
        print(f"ERROR: anchor not found in {QS} — cannot patch")
        print("       (the _fetch_from_ib method may have been refactored)")
        sys.exit(2)
    bak = _backup(QS)
    print(f"  - Backup: {bak}")
    src = src.replace(QS_ANCHOR_OLD, QS_ANCHOR_NEW, 1)
    with open(QS, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - quality_service.py patched (v170.1 IB connection gate)")
    return True


def main():
    print("=" * 60)
    print("v19.34.170.1 — quality_service IB connection gate")
    print("=" * 60)
    changed = patch_qs()
    print()
    print(f"quality_service.py changed: {changed}")
    print()
    print("Next:")
    print("  1. git add -A && git commit -m 'v19.34.170.1: gate quality_service IB call'")
    print("  2. Restart backend (fires your .bat from Windows or ./start_backend.sh --force)")
    print("  3. After ~30s, verify:")
    print("     grep -c 'IB fundamentals fetch failed' /tmp/backend.log    # should stay flat")
    print("     grep -c 'Not connected to IB' /tmp/backend.log              # should stay near 0")


if __name__ == "__main__":
    main()
