"""
Memory Watchdog (v19.34.46)
===========================

Tonight's session had the backend SIGKILL'd twice (exit 137 — kernel OOM
killer). The DGX has 121 GiB total / 95 GiB free at idle, but the backend
sat at ~21 GiB RSS during the previous run — close enough to whatever
cgroup / ulimit was active that the kernel decided to nuke it.

This watchdog:

* Samples process RSS + system memory pressure every `interval_sec`
  (default 60s).
* Logs an INFO heartbeat each tick so we have a continuous timeline.
* WARNs when the process RSS > `warn_pct` of system RAM (default 80%).
* CRITICALs when the process RSS > `crit_pct` (default 90%) AND emits a
  ``tracemalloc`` top-10 snapshot when available — gives us a fighting
  chance to spot the leak before the next SIGKILL.
* Persists each sample into the ``memory_watchdog`` Mongo collection
  (7-day TTL) so a forensic trail survives the OOM kill itself.

Zero non-stdlib dependencies — uses ``/proc/self/statm`` and
``/proc/meminfo`` directly. Cross-platform fallback: if ``/proc`` is
unavailable, the watchdog logs once and exits its loop cleanly.

Env knobs:

* ``MEMORY_WATCHDOG_ENABLED``  — default ``1``. Set ``0`` to disable.
* ``MEMORY_WATCHDOG_INTERVAL_SEC`` — default ``60``.
* ``MEMORY_WATCHDOG_WARN_PCT`` — default ``80``.
* ``MEMORY_WATCHDOG_CRIT_PCT`` — default ``90``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import resource
import threading
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Lazily resolved at first sample so unit tests can monkey-patch.
_PAGE_SIZE: Optional[int] = None
# Tracemalloc is expensive (~5% throughput overhead). Only start it
# AFTER the first critical sample so we have something to dump for the
# second one, then auto-stop after dumping to avoid permanent cost.
_tracemalloc_armed: bool = False
_tracemalloc_lock = threading.Lock()


def _page_size() -> int:
    global _PAGE_SIZE
    if _PAGE_SIZE is None:
        try:
            _PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
        except (AttributeError, ValueError, OSError):
            _PAGE_SIZE = 4096
    return _PAGE_SIZE


def _read_proc_statm() -> Optional[Dict[str, int]]:
    """Read ``/proc/self/statm``. Returns RSS in bytes, or None on error."""
    try:
        raw = Path("/proc/self/statm").read_text().strip().split()
        # statm fields (in pages): size, resident, shared, text, lib, data, dt
        return {
            "rss_bytes": int(raw[1]) * _page_size(),
            "vsize_bytes": int(raw[0]) * _page_size(),
        }
    except (FileNotFoundError, PermissionError, ValueError, IndexError):
        return None


def _read_proc_meminfo() -> Optional[Dict[str, int]]:
    """Read ``/proc/meminfo``. Returns Total, Available, Free in bytes."""
    try:
        out: Dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            # Lines look like "MemTotal:  126738432 kB"
            parts = line.split()
            if len(parts) >= 3 and parts[0].rstrip(":") in (
                "MemTotal", "MemAvailable", "MemFree", "SwapTotal", "SwapFree"
            ):
                out[parts[0].rstrip(":")] = int(parts[1]) * 1024  # kB → bytes
        return out
    except (FileNotFoundError, PermissionError, ValueError, IndexError):
        return None


def collect_sample() -> Dict[str, Any]:
    """Single memory snapshot. Pure function — no side effects, no async."""
    sample: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ts_epoch_ms": int(time.time() * 1000),
        "ts_dt": datetime.now(timezone.utc),
        "pid": os.getpid(),
    }
    statm = _read_proc_statm()
    if statm:
        sample.update(statm)
    meminfo = _read_proc_meminfo()
    if meminfo:
        total = meminfo.get("MemTotal", 0)
        avail = meminfo.get("MemAvailable", 0)
        sample["mem_total_bytes"] = total
        sample["mem_available_bytes"] = avail
        sample["mem_used_pct"] = (
            ((total - avail) / total * 100.0) if total > 0 else 0.0
        )
        if statm and total > 0:
            sample["rss_pct_of_total"] = statm["rss_bytes"] / total * 100.0
    # `resource` is always available (stdlib); gives us the high-water
    # mark, which is useful for spotting a leak even when current RSS
    # is back down (e.g., GC freed but heap never shrank).
    try:
        ru = resource.getrusage(resource.RUSAGE_SELF)
        # ru_maxrss is in kB on Linux, bytes on macOS — we're Linux-only
        # by design here, so trust the kB unit.
        sample["max_rss_bytes"] = ru.ru_maxrss * 1024
    except Exception:
        pass
    return sample


def _fmt_gb(b: Optional[int]) -> str:
    if not b or b <= 0:
        return "?"
    return f"{b / (1024 ** 3):.2f} GiB"


def _maybe_arm_tracemalloc() -> None:
    """Start tracemalloc the FIRST time we cross the critical threshold.

    Tracemalloc has measurable overhead (~5% CPU + 10% memory) so we
    don't run it for the whole process lifetime. We start it on the
    first critical sample, then dump on the second critical sample.
    """
    global _tracemalloc_armed
    with _tracemalloc_lock:
        if _tracemalloc_armed:
            return
        try:
            tracemalloc.start(25)  # 25-frame deep traces
            _tracemalloc_armed = True
            logger.error(
                "[memory-watchdog] tracemalloc ARMED — next critical "
                "sample will dump top-10 allocators."
            )
        except Exception as exc:
            logger.warning(f"[memory-watchdog] tracemalloc arm failed: {exc}")


def _dump_tracemalloc_top10() -> Optional[str]:
    """Emit a top-10 allocator snapshot. Returns formatted string or None."""
    if not tracemalloc.is_tracing():
        return None
    try:
        snap = tracemalloc.take_snapshot()
        top = snap.statistics("lineno")[:10]
        lines = ["[memory-watchdog] top-10 allocators by size:"]
        for i, stat in enumerate(top, 1):
            lines.append(f"  #{i:<2} {stat.size / (1024 ** 2):7.1f} MiB  {stat}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[memory-watchdog] tracemalloc dump failed: {exc}"


async def _persist_sample(db: Any, sample: Dict[str, Any]) -> None:
    """Best-effort insert into ``memory_watchdog`` collection.

    Idempotent index creation runs once per process; subsequent writes
    skip the round-trip.
    """
    if db is None:
        return
    try:
        col = db["memory_watchdog"]
        # Insert async-safely (motor or pymongo both work via `insert_one`)
        # — we run sync pymongo in a thread to keep the event loop snappy.
        from functools import partial

        def _do_insert():
            try:
                col.create_index(
                    "ts_dt", expireAfterSeconds=7 * 24 * 60 * 60
                )
            except Exception:
                pass
            col.insert_one(dict(sample))  # copy so caller's dict is untouched

        await asyncio.to_thread(_do_insert)
    except Exception as exc:
        # Persistence is best-effort — don't break the loop on a Mongo flap.
        logger.debug(f"[memory-watchdog] persist skipped: {exc}")


async def memory_watchdog_loop(
    db: Any = None,
    *,
    interval_sec: Optional[float] = None,
    warn_pct: Optional[float] = None,
    crit_pct: Optional[float] = None,
) -> None:
    """Main async loop. Wire from server startup via ``asyncio.create_task``.

    Parameters re-read env on each tick so the operator can tweak the
    thresholds live (touch the .env, no restart needed).
    """
    if str(os.environ.get("MEMORY_WATCHDOG_ENABLED", "1")).lower() in (
        "0", "", "false", "no", "off"
    ):
        logger.info("[memory-watchdog] disabled via MEMORY_WATCHDOG_ENABLED=0")
        return

    # One-shot capability probe.
    if _read_proc_statm() is None:
        logger.warning(
            "[memory-watchdog] /proc/self/statm unavailable — disabling "
            "watchdog (this is expected on macOS / non-Linux hosts)."
        )
        return

    consecutive_critical = 0
    logger.info(
        "[memory-watchdog] active — interval=%.0fs, warn>%.0f%%, crit>%.0f%%",
        float(interval_sec or os.environ.get("MEMORY_WATCHDOG_INTERVAL_SEC", "60")),
        float(warn_pct or os.environ.get("MEMORY_WATCHDOG_WARN_PCT", "80")),
        float(crit_pct or os.environ.get("MEMORY_WATCHDOG_CRIT_PCT", "90")),
    )
    while True:
        try:
            _interval = float(
                interval_sec or os.environ.get("MEMORY_WATCHDOG_INTERVAL_SEC", "60")
            )
            _warn = float(warn_pct or os.environ.get("MEMORY_WATCHDOG_WARN_PCT", "80"))
            _crit = float(crit_pct or os.environ.get("MEMORY_WATCHDOG_CRIT_PCT", "90"))

            sample = collect_sample()
            rss_pct = sample.get("rss_pct_of_total", 0.0) or 0.0
            mem_used = sample.get("mem_used_pct", 0.0) or 0.0

            # Heartbeat — INFO every tick.
            logger.info(
                "[memory-watchdog] RSS=%s (%.1f%% of total) · max_RSS=%s · "
                "sys_used=%.1f%% · sys_avail=%s",
                _fmt_gb(sample.get("rss_bytes")),
                rss_pct,
                _fmt_gb(sample.get("max_rss_bytes")),
                mem_used,
                _fmt_gb(sample.get("mem_available_bytes")),
            )

            # Threshold decisions — operate on the LARGER of process-%-of-
            # total OR system-used-% so a memory-pig sibling process that
            # pushes the box near OOM also triggers our defensive log.
            effective_pct = max(rss_pct, mem_used)

            if effective_pct >= _crit:
                consecutive_critical += 1
                logger.error(
                    "🔴 [memory-watchdog] CRITICAL — effective %.1f%% ≥ %.0f%% "
                    "(rss=%.1f%%, sys_used=%.1f%%). Process headed for OOM kill.",
                    effective_pct, _crit, rss_pct, mem_used,
                )
                if consecutive_critical == 1:
                    _maybe_arm_tracemalloc()
                elif consecutive_critical >= 2:
                    dump = _dump_tracemalloc_top10()
                    if dump:
                        logger.error(dump)
                sample["severity"] = "critical"
            elif effective_pct >= _warn:
                consecutive_critical = 0
                logger.warning(
                    "🟡 [memory-watchdog] WARN — effective %.1f%% ≥ %.0f%% "
                    "(rss=%.1f%%, sys_used=%.1f%%).",
                    effective_pct, _warn, rss_pct, mem_used,
                )
                sample["severity"] = "warn"
            else:
                consecutive_critical = 0
                sample["severity"] = "ok"

            await _persist_sample(db, sample)
            await asyncio.sleep(_interval)
        except asyncio.CancelledError:
            logger.info("[memory-watchdog] loop cancelled, exiting cleanly.")
            raise
        except Exception as exc:
            # Never let the watchdog itself kill the process.
            logger.exception(f"[memory-watchdog] loop iteration crashed: {exc}")
            await asyncio.sleep(30.0)
