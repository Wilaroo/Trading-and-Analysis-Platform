"""Memory Watchdog (v19.34.46) — see CHANGELOG."""
from __future__ import annotations
import asyncio, logging, os, resource, threading, time, tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
_PAGE_SIZE: Optional[int] = None
_tracemalloc_armed = False
_tracemalloc_lock = threading.Lock()


def _page_size() -> int:
    global _PAGE_SIZE
    if _PAGE_SIZE is None:
        try: _PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
        except Exception: _PAGE_SIZE = 4096
    return _PAGE_SIZE


def _read_proc_statm():
    try:
        raw = Path("/proc/self/statm").read_text().strip().split()
        return {"rss_bytes": int(raw[1]) * _page_size(),
                "vsize_bytes": int(raw[0]) * _page_size()}
    except Exception:
        return None


def _read_proc_meminfo():
    try:
        out = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].rstrip(":") in (
                "MemTotal","MemAvailable","MemFree","SwapTotal","SwapFree"):
                out[parts[0].rstrip(":")] = int(parts[1]) * 1024
        return out
    except Exception:
        return None


def collect_sample():
    s = {"ts": datetime.now(timezone.utc).isoformat(),
         "ts_epoch_ms": int(time.time()*1000),
         "ts_dt": datetime.now(timezone.utc), "pid": os.getpid()}
    statm = _read_proc_statm()
    if statm: s.update(statm)
    mi = _read_proc_meminfo()
    if mi:
        t = mi.get("MemTotal",0); a = mi.get("MemAvailable",0)
        s["mem_total_bytes"] = t; s["mem_available_bytes"] = a
        s["mem_used_pct"] = ((t-a)/t*100.0) if t>0 else 0.0
        if statm and t>0:
            s["rss_pct_of_total"] = statm["rss_bytes"]/t*100.0
    try:
        ru = resource.getrusage(resource.RUSAGE_SELF)
        s["max_rss_bytes"] = ru.ru_maxrss * 1024
    except Exception: pass
    return s


def _fmt_gb(b):
    if not b or b <= 0: return "?"
    return f"{b/(1024**3):.2f} GiB"


def _maybe_arm_tracemalloc():
    global _tracemalloc_armed
    with _tracemalloc_lock:
        if _tracemalloc_armed: return
        try:
            tracemalloc.start(25); _tracemalloc_armed = True
            logger.error("[memory-watchdog] tracemalloc ARMED.")
        except Exception as e:
            logger.warning(f"[memory-watchdog] tracemalloc arm failed: {e}")


def _dump_tracemalloc_top10():
    if not tracemalloc.is_tracing(): return None
    try:
        snap = tracemalloc.take_snapshot()
        top = snap.statistics("lineno")[:10]
        lines = ["[memory-watchdog] top-10 allocators:"]
        for i,st in enumerate(top,1):
            lines.append(f"  #{i:<2} {st.size/(1024**2):7.1f} MiB  {st}")
        return "\n".join(lines)
    except Exception as e:
        return f"[memory-watchdog] dump failed: {e}"


async def _persist_sample(db, sample):
    if db is None: return
    try:
        col = db["memory_watchdog"]
        def _do():
            try: col.create_index("ts_dt", expireAfterSeconds=7*24*60*60)
            except Exception: pass
            col.insert_one(dict(sample))
        await asyncio.to_thread(_do)
    except Exception as e:
        logger.debug(f"[memory-watchdog] persist skipped: {e}")


async def memory_watchdog_loop(db=None, *, interval_sec=None,
                                warn_pct=None, crit_pct=None):
    if str(os.environ.get("MEMORY_WATCHDOG_ENABLED","1")).lower() in (
        "0","","false","no","off"):
        logger.info("[memory-watchdog] disabled.")
        return
    if _read_proc_statm() is None:
        logger.warning("[memory-watchdog] /proc unavailable, disabling.")
        return
    consecutive_critical = 0
    logger.info("[memory-watchdog] active (interval=%ss, warn=%s%%, crit=%s%%)",
                interval_sec or os.environ.get("MEMORY_WATCHDOG_INTERVAL_SEC","60"),
                warn_pct or os.environ.get("MEMORY_WATCHDOG_WARN_PCT","80"),
                crit_pct or os.environ.get("MEMORY_WATCHDOG_CRIT_PCT","90"))
    while True:
        try:
            _iv = float(interval_sec or os.environ.get("MEMORY_WATCHDOG_INTERVAL_SEC","60"))
            _w = float(warn_pct or os.environ.get("MEMORY_WATCHDOG_WARN_PCT","80"))
            _c = float(crit_pct or os.environ.get("MEMORY_WATCHDOG_CRIT_PCT","90"))
            s = collect_sample()
            rss_p = s.get("rss_pct_of_total",0.0) or 0.0
            mem_p = s.get("mem_used_pct",0.0) or 0.0
            logger.info(
                "[memory-watchdog] RSS=%s (%.1f%%) max=%s sys=%.1f%% avail=%s",
                _fmt_gb(s.get("rss_bytes")), rss_p,
                _fmt_gb(s.get("max_rss_bytes")), mem_p,
                _fmt_gb(s.get("mem_available_bytes")))
            eff = max(rss_p, mem_p)
            if eff >= _c:
                consecutive_critical += 1
                logger.error("\U0001f534 [memory-watchdog] CRITICAL %.1f%% >= %.0f%%", eff, _c)
                if consecutive_critical == 1: _maybe_arm_tracemalloc()
                elif consecutive_critical >= 2:
                    d = _dump_tracemalloc_top10()
                    if d: logger.error(d)
                s["severity"] = "critical"
            elif eff >= _w:
                consecutive_critical = 0
                logger.warning("\U0001f7e1 [memory-watchdog] WARN %.1f%% >= %.0f%%", eff, _w)
                s["severity"] = "warn"
            else:
                consecutive_critical = 0
                s["severity"] = "ok"
            await _persist_sample(db, s)
            await asyncio.sleep(_iv)
        except asyncio.CancelledError:
            logger.info("[memory-watchdog] cancelled.")
            raise
        except Exception as e:
            logger.exception(f"[memory-watchdog] tick crashed: {e}")
            await asyncio.sleep(30.0)
