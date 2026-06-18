"""
ib_executions_persister.py — v19.34.315 (Feb 2026)
==================================================
Background poll loop that mirrors the live IB fill tape into Mongo's
`ib_executions` collection so downstream forensic + attribution tooling
(unmatched_short_close, EOD reports, scale-out audit) has a persistent
history. Idempotent via `exec_id` unique index.

WHY:
  IB's `self.ib.fills()` is session-bound (cleared on disconnect/restart).
  Without a persister, every restart blows away today's fill ledger from
  the bot's POV. The `ib_executions` collection was historically the
  forensic store, but the writer was removed at some point — leaving
  every reader silently blind (confirmed empty: 0 rows of all time,
  see diag_v311_ib_executions_writer_status).

WHAT IT WRITES (per fill, keyed by exec_id):
  exec_id, order_id, perm_id, account, symbol, side, shares, price,
  time (ISO UTC), commission, realized_pnl, last_liquidity, written_at,
  source="ib_persister_v19_34_315"

HOW (R2 path — diag_v311_ib_executions_writer_status §recommendation):
  • 30s tick. Reads `ibd._ib.fills()` via asyncio.to_thread.
  • Upserts each unseen exec_id ($setOnInsert) — no overwrites; the
    first persisted shape wins.
  • Skips silently if ib_direct isn't connected (watchdog handles it).
  • Stagger 20s on startup so other init tasks run first.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_PERSIST_SOURCE = "ib_persister_v19_34_315"
_INDEX_CREATED = False
_STATS = {
    "iterations": 0,
    "inserted": 0,
    "skipped_dupes": 0,
    "errors": 0,
    "last_run": None,
    "last_inserted": 0,
}


def get_persister_stats() -> dict:
    """Diagnostic snapshot of the loop's lifetime counters."""
    return dict(_STATS)


def _normalize_side(s: Optional[str]) -> str:
    s = (s or "").strip().upper()
    if s in ("BOT", "BOUGHT", "B"):
        return "BUY"
    if s in ("SLD", "SOLD", "S", "SS", "SSHORT", "SELL_SHORT"):
        return "SELL"
    return s or "?"


def _doc_from_fill(f) -> Optional[dict]:
    """Build a Mongo doc from an ib_insync Fill object."""
    try:
        exe = f.execution
        cr = getattr(f, "commissionReport", None)
        if exe is None:
            return None
        exec_id = getattr(exe, "execId", "") or ""
        if not exec_id:
            return None
        t = getattr(exe, "time", None)
        t_iso = t.isoformat() if hasattr(t, "isoformat") else (str(t) if t else None)
        doc = {
            "exec_id":   exec_id,
            "order_id":  int(getattr(exe, "orderId", 0) or 0),
            "perm_id":   int(getattr(exe, "permId", 0) or 0),
            "account":   getattr(exe, "acctNumber", "") or "",
            "symbol":    (getattr(f.contract, "symbol", "") or "").upper(),
            "side":      _normalize_side(getattr(exe, "side", None)),
            "shares":    float(getattr(exe, "shares", 0) or 0),
            "price":     float(getattr(exe, "price", 0) or 0),
            "time":      t_iso,
            "last_liquidity": int(getattr(exe, "lastLiquidity", 0) or 0),
            "commission":     float(getattr(cr, "commission", 0) or 0) if cr else 0.0,
            "realized_pnl":   float(getattr(cr, "realizedPNL", 0) or 0) if cr else 0.0,
            "written_at":     datetime.now(timezone.utc).isoformat(),
            "source":         _PERSIST_SOURCE,
        }
        return doc
    except Exception as e:
        logger.debug("[v19.34.315] _doc_from_fill failed: %s", e)
        return None


def _ensure_index(db) -> None:
    global _INDEX_CREATED
    if _INDEX_CREATED:
        return
    try:
        db["ib_executions"].create_index(
            "exec_id", unique=True, name="exec_id_unique_v19_34_315"
        )
        _INDEX_CREATED = True
    except Exception as e:
        # Index already exists / different name. Ignore — readers don't care.
        logger.debug("[v19.34.315] index create no-op: %s", e)
        _INDEX_CREATED = True


def _persist_batch(db, fills) -> tuple:
    """Returns (inserted, skipped_dupes, errors)."""
    inserted = skipped = errors = 0
    coll = db["ib_executions"]
    for f in fills:
        doc = _doc_from_fill(f)
        if doc is None:
            errors += 1
            continue
        try:
            res = coll.update_one(
                {"exec_id": doc["exec_id"]},
                {"$setOnInsert": doc},
                upsert=True,
            )
            if res.upserted_id is not None:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            logger.debug("[v19.34.315] upsert failed for %s: %s",
                         doc.get("exec_id"), e)
    return inserted, skipped, errors


async def ib_executions_persist_loop(
    db,
    interval_s: int = 30,
    stagger_s: int = 20,
) -> None:
    """30s background loop. Skips silently if IB not connected."""
    await asyncio.sleep(stagger_s)
    _ensure_index(db)
    log_every = 10  # ~ every 5 minutes
    while True:
        try:
            from services.ib_direct_service import get_ib_direct_service
            ibd = get_ib_direct_service()
            if ibd is None or not (
                getattr(ibd, "_ib", None) and ibd.is_connected()
            ):
                _STATS["iterations"] += 1
                _STATS["last_run"] = datetime.now(timezone.utc).isoformat()
                _STATS["last_inserted"] = 0
                await asyncio.sleep(interval_s)
                continue
            fills = await asyncio.to_thread(ibd._ib.fills)
            ins, dup, err = await asyncio.to_thread(_persist_batch, db, fills)
            _STATS["iterations"] += 1
            _STATS["inserted"] += ins
            _STATS["skipped_dupes"] += dup
            _STATS["errors"] += err
            _STATS["last_run"] = datetime.now(timezone.utc).isoformat()
            _STATS["last_inserted"] = ins
            if ins > 0 or _STATS["iterations"] % log_every == 0:
                logger.info(
                    "[v19.34.315 ib_executions] tick=%d inserted_now=%d "
                    "dupes_now=%d errors_now=%d totals=%d/%d/%d",
                    _STATS["iterations"], ins, dup, err,
                    _STATS["inserted"], _STATS["skipped_dupes"], _STATS["errors"],
                )
        except Exception as e:
            _STATS["errors"] += 1
            logger.warning("[v19.34.315] persist loop error: %s", e)
        await asyncio.sleep(interval_s)
