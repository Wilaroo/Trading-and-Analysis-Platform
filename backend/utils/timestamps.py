"""
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
