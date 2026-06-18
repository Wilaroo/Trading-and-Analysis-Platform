"""Dedicated read-only IB connection for fundamental reports (v386b).

Heavy fundamental pulls (``ReportsOwnership`` is multi-MB) used to share the
clientId-11 trading socket, so they could only run off-hours. This module opens a
SEPARATE ``ib_async`` connection on its own clientId (``IB_FUNDAMENTALS_CLIENT_ID``,
default 12) — isolated from orders/quotes — so fundamentals can be fetched during
RTH without contending with the trading path. Read-only, lazy-connect (nothing
happens until the first request → zero boot/startup risk).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from ib_async import IB, Stock
    _HAVE_IB = True
except ImportError:  # pragma: no cover
    _HAVE_IB = False


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


class FundamentalsIBClient:
    """Singleton, read-only ib_async connection for Reuters fundamental XML."""

    def __init__(self) -> None:
        self._ib: Optional["IB"] = None
        self._lock = asyncio.Lock()
        self.host = os.environ.get("IB_DIRECT_HOST",
                                   os.environ.get("IB_HOST", "192.168.50.1"))
        self.port = _int_env("IB_DIRECT_PORT", 4002)
        # Separate clientId so this never collides with pusher(10)/bot-direct(11).
        self.client_id = _int_env("IB_FUNDAMENTALS_CLIENT_ID", 12)

    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    async def connect(self) -> bool:
        if not _HAVE_IB:
            return False
        if self.is_connected():
            return True
        async with self._lock:
            if self.is_connected():
                return True
            try:
                self._ib = IB()
                await self._ib.connectAsync(
                    host=self.host, port=self.port,
                    clientId=self.client_id, readonly=True, timeout=15,
                )
                logger.info("[IB-FUND] connected %s:%d clientId=%d (read-only)",
                            self.host, self.port, self.client_id)
                return True
            except Exception as exc:
                logger.warning("[IB-FUND] connect failed (clientId=%d): %s",
                               self.client_id, exc)
                self._ib = None
                return False

    async def get_fundamental_report(self, symbol: str,
                                     report_type: str = "ReportSnapshot",
                                     timeout: float = 30.0) -> Optional[str]:
        """Fetch a Reuters fundamental XML report. Same signature/behaviour as
        IBDirectService.get_fundamental_report, but on the dedicated socket."""
        if not await self.connect():
            return None
        try:
            contract = Stock(symbol.upper(), "SMART", "USD")
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                return None
            xml = await asyncio.wait_for(
                self._ib.reqFundamentalDataAsync(qualified[0], report_type),
                timeout=timeout,
            )
            return xml or None
        except Exception as exc:
            logger.debug("[IB-FUND] %s/%s failed: %s", symbol, report_type, exc)
            return None


_client: Optional[FundamentalsIBClient] = None


def get_fundamentals_ib_client() -> "FundamentalsIBClient":
    global _client
    if _client is None:
        _client = FundamentalsIBClient()
    return _client
