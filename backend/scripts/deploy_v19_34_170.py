"""v19.34.170 — Pre-restart deploy: timestamp helpers + fundamentals reconnect.

Idempotent edits to:
  1. backend/utils/timestamps.py                     (CREATE — new file)
       Canonical now_iso / now_bson / parse_to_bson / parse_to_iso /
       stamps / epoch_ms helpers so cross-collection Mongo queries
       stop silently returning 0 rows when ISO/BSON types don't match.

  2. backend/services/position_manager.py            (PATCH — EOD heartbeat)
       Rewrite v169 heartbeat to canonical sentcom_thoughts schema
       (kind=system, content, ISO timestamp, BSON created_at). Keeps
       top-level category='eod_heartbeat' so the v169 operator query
       still works.

  3. backend/services/trade_context_service.py       (PATCH — fundamentals)
       Gate IB get_fundamentals() behind get_connection_status() and
       fall back to FundamentalDataService (Finnhub) when disconnected.
       Kills the "Not connected to IB" WARN spam.

Re-running is SAFE. Each patch detects its own marker and skips.

After running:
    .venv/bin/python -m pytest backend/tests/test_v19_34_170_timestamps_and_fundamentals.py -v
        (only present if you also pulled the test file — not required for deploy)
    .venv/bin/python -c "from backend.utils.timestamps import now_iso, now_bson, parse_to_bson; \
                          print(now_iso(), parse_to_bson(now_iso()))"
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

# This script lives at backend/scripts/deploy_v19_34_170.py.
# ROOT is the backend/ directory.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UTILS_DIR = os.path.join(ROOT, "utils")
TIMESTAMPS_PATH = os.path.join(UTILS_DIR, "timestamps.py")
PM = os.path.join(ROOT, "services", "position_manager.py")
TC = os.path.join(ROOT, "services", "trade_context_service.py")


# --------------------------------------------------------------------------
# 1) utils/timestamps.py — full file content
# --------------------------------------------------------------------------
TIMESTAMPS_CONTENT = '''"""
Canonical timestamp helpers — v19.34.170
=========================================

The SentCom codebase grew up writing timestamps in two incompatible
shapes across collections:

  * `bot_trades`, `alert_outcomes`, `shadow_decisions`  -> ISO 8601 strings
  * `bracket_lifecycle_events`, `sentcom_thoughts.created_at` -> BSON datetime
  * `sentcom_thoughts.timestamp`                       -> ISO 8601 string
  * `trade_drops` (new in v164)                        -> BOTH ts (ISO) + ts_dt (BSON)

When a query mixed types ($gte: iso_string against a BSON-datetime field)
Mongo silently returned 0 rows, which masked real bugs (e.g. the EOD
heartbeat write in v169 used `created_at = iso_string` but the
TTL-index on `_persist_thought` expects BSON datetime, so heartbeats
were never aged out via TTL).

Use these helpers for ALL new writes. For new collections, prefer
writing BOTH fields (`ts` ISO for humans, `ts_dt` BSON for TTL +
range queries) to stay query-shape-compatible with either side.

Querying: when a comparison value comes from the wire (e.g. a router
`?since=2026-01-01` arg), pass it through `parse_to_bson` /
`parse_to_iso` so the same router can serve collections that store
either type.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union

ISO_OR_BSON = Union[str, datetime, None]


def now_bson() -> datetime:
    """Current UTC time as a tz-aware ``datetime`` (BSON-storable)."""
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """Current UTC time as an ISO 8601 string with offset."""
    return now_bson().isoformat()


def parse_to_bson(value: ISO_OR_BSON) -> Optional[datetime]:
    """Coerce an ISO string OR a ``datetime`` to a tz-aware ``datetime``.

    Returns ``None`` for ``None`` / empty / unparseable input. Never raises.
    Naive datetimes are assumed to be UTC.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Tolerate trailing "Z" -- fromisoformat in <3.11 rejects it.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def parse_to_iso(value: ISO_OR_BSON) -> Optional[str]:
    """Coerce an ISO string OR a ``datetime`` to an ISO 8601 string.

    Returns ``None`` for ``None`` / unparseable input. Never raises.
    """
    dt = parse_to_bson(value)
    return dt.isoformat() if dt is not None else None


def stamps(value: ISO_OR_BSON = None) -> dict:
    """Return a ``{"ts": iso, "ts_dt": bson}`` dict for writes.

    Use this in new collection writes so queries can filter by either
    type. Defaults to "now" when ``value`` is ``None``.
    """
    dt = parse_to_bson(value) or now_bson()
    return {"ts": dt.isoformat(), "ts_dt": dt}


def epoch_ms(value: ISO_OR_BSON = None) -> int:
    """Return Unix epoch milliseconds for the supplied (or current) time."""
    dt = parse_to_bson(value) or now_bson()
    return int(dt.timestamp() * 1000)
'''


# --------------------------------------------------------------------------
# 2) position_manager.py EOD heartbeat — string-replace v169 block
# --------------------------------------------------------------------------
PM_ANCHOR_OLD = '''                    db["sentcom_thoughts"].insert_one({
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "category": "eod_heartbeat",
                        "thought": (
                            f"EOD window tick {hb_stamp} ET — eligible "
                            f"close_at_eod positions: {eod_eligible_count}, "
                            f"executed_today={bot._eod_close_executed_today}, "
                            f"half_day={is_half_day}, "
                            f"window={eod_hour:02d}:{eod_minute:02d}-{market_close_hour:02d}:00 ET"
                        ),
                        "metadata": {
                            "eligible_positions": eod_eligible_count,
                            "executed_today": bot._eod_close_executed_today,
                            "is_half_day": is_half_day,
                            "eod_hour": eod_hour,
                            "eod_minute": eod_minute,
                        },
                    })'''

PM_ANCHOR_NEW = '''                    # v19.34.170 — normalize sentcom_thoughts schema:
                    #   * created_at as BSON datetime (matches TTL index +
                    #     _persist_thought convention; v169 wrote ISO string
                    #     here which the TTL would never expire)
                    #   * timestamp as ISO string (matches diagnostics.py
                    #     `{"timestamp": {"$gte": cutoff_iso}}` queries)
                    #   * kind + content (canonical schema fields)
                    #   * top-level `category` kept for the operator's
                    #     existing `db.sentcom_thoughts.find({category:
                    #     'eod_heartbeat'})` query shipped in v169
                    from utils.timestamps import now_bson, now_iso
                    _eod_thought_text = (
                        f"EOD window tick {hb_stamp} ET — eligible "
                        f"close_at_eod positions: {eod_eligible_count}, "
                        f"executed_today={bot._eod_close_executed_today}, "
                        f"half_day={is_half_day}, "
                        f"window={eod_hour:02d}:{eod_minute:02d}-{market_close_hour:02d}:00 ET"
                    )
                    db["sentcom_thoughts"].insert_one({
                        "kind": "system",
                        "content": _eod_thought_text,
                        "thought": _eod_thought_text,  # legacy alias
                        "category": "eod_heartbeat",
                        "symbol": None,
                        "timestamp": now_iso(),
                        "created_at": now_bson(),
                        "metadata": {
                            "category": "eod_heartbeat",
                            "eligible_positions": eod_eligible_count,
                            "executed_today": bot._eod_close_executed_today,
                            "is_half_day": is_half_day,
                            "eod_hour": eod_hour,
                            "eod_minute": eod_minute,
                            "hb_stamp": hb_stamp,
                        },
                    })'''


# --------------------------------------------------------------------------
# 3) trade_context_service.py _capture_fundamental_context patch
# --------------------------------------------------------------------------
TC_ANCHOR_OLD = '''    async def _capture_fundamental_context(self, context: TradeContext, symbol: str):
        """Capture fundamental data from IB or cache"""
        fundamentals = FundamentalContext()
        
        try:
            # Try IB Gateway first
            if self._ib_service is not None:
                ib_data = await self._ib_service.get_fundamentals(symbol)
                
                if ib_data and ib_data.get('success'):
                    fund = ib_data.get('data', {})
                    fundamentals.short_interest_percent = fund.get('short_interest_percent', 0.0)
                    fundamentals.float_shares = fund.get('float_shares', 0)
                    fundamentals.institutional_ownership_percent = fund.get('institutional_ownership_percent', 0.0)
                    fundamentals.pe_ratio = fund.get('pe_ratio')
                    fundamentals.market_cap = fund.get('market_cap')
                    
            # Check for upcoming earnings
            if self._db is not None:
                earnings = self._check_earnings_proximity(symbol)
                if earnings:
                    fundamentals.earnings_days_away = earnings.get('days_away')
                    fundamentals.earnings_score = earnings.get('score', 0)
                    if fundamentals.earnings_days_away is not None and fundamentals.earnings_days_away <= 7:
                        fundamentals.has_catalyst = True
                        fundamentals.catalyst_type = "earnings"
                        
        except Exception as e:
            logger.warning(f"Error capturing fundamental context for {symbol}: {e}")
            
        context.fundamentals = fundamentals'''

TC_ANCHOR_NEW = '''    async def _capture_fundamental_context(self, context: TradeContext, symbol: str):
        """Capture fundamental data from IB (when connected) or Finnhub fallback.

        v19.34.170 — Previously this unconditionally called
        ``self._ib_service.get_fundamentals(symbol)``, which raises
        ``ConnectionError("Not connected to IB")`` whenever the
        ib_insync direct connection is stale (which is most of the
        time on this DGX install, since the live data path is the IB
        pusher, not the direct ib_service). That filled the logs with
        WARN noise and left ``FundamentalContext`` empty.

        Now we:
          1. Check ``ib_service.get_connection_status()`` first and
             only call IB when the worker thread reports connected.
          2. Fall back to the Finnhub-backed
             ``FundamentalDataService`` so the alert payload still
             gets ``pe_ratio`` / ``market_cap`` / ``beta``.
          3. Always look up earnings proximity from the DB regardless
             of either upstream.
        """
        fundamentals = FundamentalContext()

        try:
            ib_connected = False
            if self._ib_service is not None:
                try:
                    status = self._ib_service.get_connection_status()
                    ib_connected = bool(status and status.get("connected"))
                except Exception as e:
                    logger.debug(f"IB status probe failed for {symbol}: {e}")

            if ib_connected:
                try:
                    ib_data = await self._ib_service.get_fundamentals(symbol)
                    if ib_data and ib_data.get('success'):
                        fund = ib_data.get('data', {}) or {}
                        fundamentals.short_interest_percent = fund.get('short_interest_percent', 0.0)
                        fundamentals.float_shares = fund.get('float_shares', 0)
                        fundamentals.institutional_ownership_percent = fund.get('institutional_ownership_percent', 0.0)
                        fundamentals.pe_ratio = fund.get('pe_ratio')
                        fundamentals.market_cap = fund.get('market_cap')
                except ConnectionError as ce:
                    # Connection dropped between status probe and call.
                    logger.debug(f"IB went stale mid-fundamentals for {symbol}: {ce}")
                except Exception as e:
                    logger.debug(f"IB fundamentals call failed for {symbol}: {e}")

            # Fallback / supplement: Finnhub fundamentals (always
            # populated for valuation context, since IB's
            # ReportSnapshot XML isn't parsed by this codebase).
            if fundamentals.pe_ratio is None or fundamentals.market_cap is None:
                try:
                    from services.fundamental_data_service import get_fundamental_data_service
                    fund_svc = get_fundamental_data_service()
                    fdata = await fund_svc.get_fundamentals(symbol)
                    if fdata is not None:
                        if fundamentals.pe_ratio is None:
                            fundamentals.pe_ratio = fdata.pe_ratio
                        if fundamentals.market_cap is None:
                            # Finnhub returns market cap in millions; keep
                            # as-is to match the historical IB shape.
                            fundamentals.market_cap = fdata.market_cap
                except Exception as e:
                    logger.debug(f"Finnhub fundamentals fallback failed for {symbol}: {e}")

            # Check for upcoming earnings (DB lookup — independent of IB)
            if self._db is not None:
                earnings = self._check_earnings_proximity(symbol)
                if earnings:
                    fundamentals.earnings_days_away = earnings.get('days_away')
                    fundamentals.earnings_score = earnings.get('score', 0)
                    if fundamentals.earnings_days_away is not None and fundamentals.earnings_days_away <= 7:
                        fundamentals.has_catalyst = True
                        fundamentals.catalyst_type = "earnings"

        except Exception as e:
            logger.warning(f"Error capturing fundamental context for {symbol}: {e}")

        context.fundamentals = fundamentals'''


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _backup(path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{path}.bak.v170.{stamp}"
    shutil.copy2(path, dst)
    return dst


def write_timestamps() -> bool:
    os.makedirs(UTILS_DIR, exist_ok=True)
    init = os.path.join(UTILS_DIR, "__init__.py")
    if not os.path.exists(init):
        with open(init, "w", encoding="utf-8") as f:
            f.write("")
        print(f"  - Created {init}")
    if os.path.exists(TIMESTAMPS_PATH):
        with open(TIMESTAMPS_PATH, "r", encoding="utf-8") as f:
            existing = f.read()
        if "v19.34.170" in existing and "def now_bson" in existing and "def parse_to_bson" in existing:
            print(f"  - {TIMESTAMPS_PATH} already present — skipping")
            return False
        print(f"  - {TIMESTAMPS_PATH} exists but missing markers — overwriting (backup taken)")
        _backup(TIMESTAMPS_PATH)
    with open(TIMESTAMPS_PATH, "w", encoding="utf-8") as f:
        f.write(TIMESTAMPS_CONTENT)
    print(f"  - Wrote {TIMESTAMPS_PATH}")
    return True


def patch_pm() -> bool:
    with open(PM, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.170 — normalize sentcom_thoughts schema" in src:
        print("  - position_manager.py already on v170 schema — skipping")
        return False
    if PM_ANCHOR_OLD not in src:
        print(f"ERROR: anchor not found in {PM} — cannot patch")
        print("       (the v169 EOD heartbeat block may have been refactored)")
        sys.exit(3)
    bak = _backup(PM)
    print(f"  - Backup: {bak}")
    src = src.replace(PM_ANCHOR_OLD, PM_ANCHOR_NEW, 1)
    with open(PM, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - position_manager.py patched (v170 heartbeat schema)")
    return True


def patch_tc() -> bool:
    with open(TC, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.170 — Previously this unconditionally" in src:
        print("  - trade_context_service.py already on v170 — skipping")
        return False
    if TC_ANCHOR_OLD not in src:
        print(f"ERROR: anchor not found in {TC} — cannot patch")
        print("       (the _capture_fundamental_context block may have been refactored)")
        sys.exit(4)
    bak = _backup(TC)
    print(f"  - Backup: {bak}")
    src = src.replace(TC_ANCHOR_OLD, TC_ANCHOR_NEW, 1)
    with open(TC, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - trade_context_service.py patched (fundamentals reconnect)")
    return True


def self_test() -> None:
    """Import + smoke-test the new helpers — runs in-process after patch."""
    # Reimport fresh from the on-disk file we just wrote.
    import importlib
    import importlib.util
    spec = importlib.util.spec_from_file_location("utils.timestamps", TIMESTAMPS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    iso = mod.now_iso()
    bson = mod.now_bson()
    assert isinstance(iso, str) and iso.endswith("+00:00"), f"now_iso shape wrong: {iso!r}"
    assert bson.tzinfo is not None, "now_bson must be tz-aware"
    rt = mod.parse_to_bson(iso)
    assert rt is not None and rt.year == bson.year
    assert mod.parse_to_bson(None) is None
    assert mod.parse_to_bson("garbage") is None
    stamps = mod.stamps()
    assert set(stamps.keys()) == {"ts", "ts_dt"}
    print("  - self_test: utils.timestamps imports + round-trips OK")


def main():
    print("=" * 60)
    print("v19.34.170 — timestamp helpers + fundamentals reconnect")
    print("=" * 60)
    ts_changed = write_timestamps()
    pm_changed = patch_pm()
    tc_changed = patch_tc()
    print()
    print(f"utils/timestamps.py changed:        {ts_changed}")
    print(f"position_manager.py changed:        {pm_changed}")
    print(f"trade_context_service.py changed:   {tc_changed}")
    print()
    print("Running self-test ...")
    self_test()
    print()
    print("Next steps on DGX:")
    print("  1. git add -A && git commit -m 'v19.34.170: timestamp helpers + fundamentals reconnect'")
    print("  2. Restart backend (./start_backend.sh --force)  -- or your .bat from Windows")
    print("  3. Grep next backend.log for 'Not connected to IB' -- should be ~0 hits")
    print("  4. After 15:45 ET today:")
    print("     mongosh tradecommand --eval 'db.sentcom_thoughts.find({category:\"eod_heartbeat\"}).sort({_id:-1}).limit(5).pretty()'")
    print("     Should show docs with kind=system, content, timestamp (ISO), created_at (BSON Date)")


if __name__ == "__main__":
    main()
