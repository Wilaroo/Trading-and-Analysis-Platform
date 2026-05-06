"""
LEGACY SHIM — Alpaca is fully removed from the trading path.

`AlpacaService` here is a thin compatibility wrapper that delegates every
call to the IB-backed `IBDataProvider`. Callers do not need to change —
`get_alpaca_service()` returns an object with the same public interface,
but the data actually comes from the IB pusher + `ib_historical_data`.

To keep Alpaca from silently creeping back in:
    • `ALPACA_ENABLED` is IGNORED — always treated as disabled.
    • The alpaca SDK is NOT imported from this module.
    • `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` environment variables
      are NEVER read by this file.
    • A one-shot deprecation warning is logged the first time anyone
      asks for this service, so stale imports surface in normal operation.

New code MUST use:

    from services.ib_data_provider import get_live_data_service
    live = get_live_data_service()
"""
from __future__ import annotations

import logging
from typing import Optional

from services.ib_data_provider import IBDataProvider, get_live_data_service

logger = logging.getLogger(__name__)

_WARNED = False


def _warn_once():
    global _WARNED
    if _WARNED:
        return
    _WARNED = True
    logger.warning(
        "[ALPACA-SHIM] `alpaca_service` / `AlpacaService` is deprecated — "
        "all calls are now routed through IBDataProvider (IB pusher + "
        "ib_historical_data). Migrate imports to "
        "`from services.ib_data_provider import get_live_data_service`."
    )


class AlpacaService:
    """Deprecated shim. Delegates every method to IBDataProvider.

    Kept only so legacy imports continue to work. The underlying object is
    an `IBDataProvider` so every call reads live IB pusher data + the
    `ib_historical_data` collection — Alpaca is never contacted.
    """

    # Legacy flag — kept for BC but always False now so callers never
    # short-circuit the IB-backed data path.
    DISABLED = False

    def __init__(self):
        _warn_once()
        self._impl: IBDataProvider = get_live_data_service()

    # Forward every public method to the IB-backed implementation. Using
    # __getattr__ keeps the shim resilient to any BC method additions on
    # IBDataProvider without needing to edit this file.
    def __getattr__(self, item):
        return getattr(self._impl, item)


# ── Singleton accessors (BC) ─────────────────────────────────
_alpaca_service: Optional[AlpacaService] = None


def get_alpaca_service() -> AlpacaService:
    """Deprecated — returns the IB-backed shim. Use get_live_data_service()."""
    global _alpaca_service
    if _alpaca_service is None:
        _alpaca_service = AlpacaService()
    return _alpaca_service


def init_alpaca_service() -> AlpacaService:
    global _alpaca_service
    _alpaca_service = AlpacaService()
    return _alpaca_service
