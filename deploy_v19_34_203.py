#!/usr/bin/env python3
"""
deploy_v19_34_203.py — idempotent, anchor-based deploy of R0 (earnings_calendar
persistence). Line-number independent + TRANSACTIONAL (writes nothing unless
every anchor is found). Mirrors the v202 deploy pattern.

Run (DGX, from repo root):
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python /tmp/deploy_v19_34_203.py
Then, if ✅ ALL VERIFIED:
    git add -A && git commit -m "v19.34.203 earnings_calendar persistence (R0)" && git push && ./start_backend.sh --force
"""
import os
import py_compile
import subprocess
import sys

ROOT = os.path.expanduser("~/Trading-and-Analysis-Platform")
B = os.path.join(ROOT, "backend")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


EDITS = {}

# ─────────────────────────── earnings_service.py ────────────────────────────
ES = os.path.join(B, "services/earnings_service.py")

ES_IMPORTS_OLD = '''import logging
import os
import requests
from typing import Dict, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv'''
ES_IMPORTS_NEW = '''import asyncio
import logging
import os
import requests
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv'''

ES_METHODS_OLD = '''        except Exception as e:
            logger.warning(f"Failed to get earnings calendar for {symbol}: {e}")
            return {"available": False, "error": str(e)}'''
ES_METHODS_NEW = ES_METHODS_OLD + '''

    async def get_upcoming_earnings(self, days_ahead: int = 21) -> List[Dict]:
        """v19.34.203 — market-wide upcoming earnings via ONE Finnhub
        date-range call (`/calendar/earnings?from=&to=`). Returns the raw
        ``earningsCalendar`` list, or [] on miss / plan restriction."""
        if not self._finnhub_key:
            return []
        today = datetime.now(timezone.utc).date()
        try:
            resp = requests.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={
                    "from": today.isoformat(),
                    "to": (today + timedelta(days=days_ahead)).isoformat(),
                    "token": self._finnhub_key,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                return (resp.json() or {}).get("earningsCalendar", []) or []
            logger.warning("Earnings date-range fetch HTTP %s", resp.status_code)
        except Exception as e:
            logger.warning("Earnings date-range fetch failed: %s", e)
        return []

    async def refresh_earnings_calendar(
        self, db=None, days_ahead: int = 21,
        fallback_symbols: Optional[List[str]] = None,
    ) -> int:
        """v19.34.203 — persist upcoming earnings into the ``earnings_calendar``
        collection the TQS fundamental pillar reads. Approach (a): one
        market-wide date-range call; falls back to (b) per-symbol over the
        active universe (symbol_fundamentals_cache), throttled for free tier.
        Upserts by (symbol, date), prunes rows older than 2 days."""
        if db is None:
            db = _earnings_db()
        if db is None:
            return 0

        docs: List[Dict] = []
        rows = await self.get_upcoming_earnings(days_ahead)
        if rows:
            for e in rows:
                doc = _normalize_earnings_row(e)
                if doc:
                    docs.append(doc)
        else:
            syms = fallback_symbols or [
                d["symbol"] for d in
                db["symbol_fundamentals_cache"].find({}, {"symbol": 1, "_id": 0})
                if d.get("symbol")
            ]
            for sym in syms[:300]:
                try:
                    cal = await self.get_earnings_calendar(sym)
                    ne = cal.get("next_earnings") if cal.get("available") else None
                    if ne and ne.get("date"):
                        doc = _normalize_earnings_row({**ne, "symbol": sym})
                        if doc:
                            docs.append(doc)
                except Exception:
                    pass
                await asyncio.sleep(1.1)

        now_iso = datetime.now(timezone.utc).isoformat()
        written = 0
        for doc in docs:
            doc["fetched_at"] = now_iso
            try:
                db["earnings_calendar"].update_one(
                    {"symbol": doc["symbol"], "date": doc["date"]},
                    {"$set": doc}, upsert=True,
                )
                written += 1
            except Exception as e:
                logger.debug("earnings_calendar upsert failed for %s: %s",
                             doc.get("symbol"), e)

        cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        try:
            db["earnings_calendar"].delete_many({"date": {"$lt": cutoff}})
            db["earnings_calendar"].create_index("symbol", background=True)
        except Exception:
            pass
        logger.info("[earnings] earnings_calendar refresh wrote %d rows "
                    "(%s)", written, "date-range" if rows else "per-symbol")
        return written'''

ES_HELPERS_OLD = '''# Global service instance
_earnings_service: Optional[EarningsService] = None


def get_earnings_service() -> EarningsService:'''
ES_HELPERS_NEW = '''# Global service instance
_earnings_service: Optional[EarningsService] = None

_earnings_db_handle = None


def _earnings_db():
    """Lazy pymongo DB handle (mirrors unified_fundamentals_cache._get_db)."""
    global _earnings_db_handle
    if _earnings_db_handle is not None:
        return _earnings_db_handle
    try:
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL"),
                             serverSelectionTimeoutMS=2000)
        _earnings_db_handle = client[os.environ.get("DB_NAME", "tradecommand")]
    except Exception as exc:
        logger.debug("earnings_service DB init failed: %s", exc)
    return _earnings_db_handle


def _normalize_earnings_row(e: Dict) -> Optional[Dict]:
    """Finnhub earnings row -> earnings_calendar doc, or None if unusable.
    Stores date as ISO datetime (noon UTC) so the pillar's string-range query
    and datetime.fromisoformat both work."""
    sym = (e.get("symbol") or "").upper().strip()
    d = (e.get("date") or "").strip()
    if not sym or len(d) < 10:
        return None
    return {
        "symbol": sym,
        "date": f"{d[:10]}T12:00:00+00:00",
        "date_only": d[:10],
        "hour": e.get("hour"),
        "eps_estimate": e.get("epsEstimate"),
        "revenue_estimate": e.get("revenueEstimate"),
        "quarter": e.get("quarter"),
        "year": e.get("year"),
        "source": "finnhub",
    }


def get_earnings_service() -> EarningsService:'''

EDITS[ES] = [
    (ES_IMPORTS_OLD, ES_IMPORTS_NEW, "from typing import Dict, List, Optional"),
    (ES_METHODS_OLD, ES_METHODS_NEW, "async def refresh_earnings_calendar"),
    (ES_HELPERS_OLD, ES_HELPERS_NEW, "def _normalize_earnings_row"),
]

# ─────────────────────────── trading_scheduler.py ───────────────────────────
TS = os.path.join(B, "services/trading_scheduler.py")

TS_CRON_OLD = "            # 2. Weekly Report - Friday 4:30 PM ET"
TS_CRON_NEW = '''            # 1c. Earnings-calendar refresh — 6:00 AM ET daily (v19.34.203)
            self._scheduler.add_job(
                _wrap_async(self._run_earnings_calendar_refresh),
                CronTrigger(
                    hour=6,
                    minute=0,
                    timezone='US/Eastern'
                ),
                id='earnings_calendar_refresh',
                name='Earnings Calendar Refresh',
                replace_existing=True
            )

            # 2. Weekly Report - Friday 4:30 PM ET'''

TS_HANDLER_OLD = "    async def _run_daily_analysis(self):"
TS_HANDLER_NEW = '''    async def _run_earnings_calendar_refresh(self):
        """v19.34.203 — persist upcoming earnings into earnings_calendar so the
        TQS fundamental pillar's earnings-proximity component (15%) works."""
        try:
            from services.earnings_service import get_earnings_service
            n = await get_earnings_service().refresh_earnings_calendar()
            logger.info("[scheduler] earnings_calendar refresh wrote %d rows", n)
        except Exception as e:
            logger.error("[scheduler] earnings_calendar refresh failed: %s", e)

    async def _run_daily_analysis(self):'''

TS_TRIGGER_OLD = '''        elif task_type == "learning_stats_rebuild":
            # v19.34.200 — on-demand rebuild so the operator can refresh
            # the setup-pillar win-rate feed without waiting for 5:30 PM ET.
            await self._run_learning_stats_rebuild()
        else:'''
TS_TRIGGER_NEW = '''        elif task_type == "learning_stats_rebuild":
            # v19.34.200 — on-demand rebuild so the operator can refresh
            # the setup-pillar win-rate feed without waiting for 5:30 PM ET.
            await self._run_learning_stats_rebuild()
        elif task_type == "earnings_calendar_refresh":
            # v19.34.203 — on-demand earnings calendar refresh.
            await self._run_earnings_calendar_refresh()
        else:'''

EDITS[TS] = [
    (TS_CRON_OLD, TS_CRON_NEW, "id='earnings_calendar_refresh'"),
    (TS_HANDLER_OLD, TS_HANDLER_NEW, "async def _run_earnings_calendar_refresh"),
    (TS_TRIGGER_OLD, TS_TRIGGER_NEW, 'task_type == "earnings_calendar_refresh"'),
]

# ─────────────────────────── the pytest ─────────────────────────────────────
TEST_PATH = os.path.join(B, "tests/test_v19_34_203_earnings_calendar.py")
TEST_BODY = '''"""v19.34.203 — earnings_calendar persistence (R0)."""
from datetime import datetime, timezone, timedelta

from services.earnings_service import _normalize_earnings_row


def test_normalize_basic():
    doc = _normalize_earnings_row({
        "symbol": "amd", "date": "2026-06-15", "hour": "amc",
        "epsEstimate": 1.2, "quarter": 2, "year": 2026,
    })
    assert doc["symbol"] == "AMD"
    assert doc["date"] == "2026-06-15T12:00:00+00:00"
    assert doc["date_only"] == "2026-06-15"
    assert doc["hour"] == "amc"
    assert doc["source"] == "finnhub"


def test_normalize_rejects_missing():
    assert _normalize_earnings_row({"symbol": "AMD"}) is None
    assert _normalize_earnings_row({"date": "2026-06-15"}) is None
    assert _normalize_earnings_row({"symbol": "", "date": ""}) is None


def test_future_earnings_sorts_after_now():
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=7)).date().isoformat()
    doc = _normalize_earnings_row({"symbol": "X", "date": future})
    assert doc["date"] >= now.isoformat()


def test_same_day_format():
    today = datetime.now(timezone.utc).date().isoformat()
    doc = _normalize_earnings_row({"symbol": "X", "date": today})
    assert doc["date"] == f"{today}T12:00:00+00:00"


def test_within_14d_window():
    now = datetime.now(timezone.utc)
    d = (now + timedelta(days=10)).date().isoformat()
    doc = _normalize_earnings_row({"symbol": "X", "date": d})
    upper = (now + timedelta(days=14)).isoformat()
    assert now.isoformat() <= doc["date"] <= upper
'''


def main():
    staged = {}
    for path, edits in EDITS.items():
        if not os.path.exists(path):
            print(f"🔴 ABORT: missing file {path}")
            return 1
        s = read(path)
        for old, new, marker in edits:
            if marker in s:
                print(f"  ↩ {os.path.basename(path)}: '{marker[:40]}' present (skip)")
                continue
            if old not in s:
                print(f"🔴 ABORT: anchor not found in {os.path.basename(path)} "
                      f"for '{marker[:40]}'. No files written.")
                print("   → paste me this file and I'll regenerate.")
                return 1
            s = s.replace(old, new, 1)
        staged[path] = s

    for path, content in staged.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  ✓ wrote {os.path.relpath(path, ROOT)}")
    with open(TEST_PATH, "w", encoding="utf-8") as f:
        f.write(TEST_BODY)
    print(f"  ✓ wrote {os.path.relpath(TEST_PATH, ROOT)}")

    print("\n── py_compile ──")
    for path in list(EDITS.keys()) + [TEST_PATH]:
        try:
            py_compile.compile(path, doraise=True)
            print(f"  ✓ {os.path.basename(path)}")
        except py_compile.PyCompileError as e:
            print(f"🔴 COMPILE FAILED: {e}")
            return 1

    print("\n── pytest ──")
    r = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_v19_34_203_earnings_calendar.py", "-q"], cwd=B)
    if r.returncode != 0:
        print("🔴 pytest FAILED")
        return 1

    print("\n✅ ALL VERIFIED. Now commit + restart:")
    print('  git add -A && git commit -m "v19.34.203 earnings_calendar '
          'persistence (R0)" && git push && ./start_backend.sh --force')
    return 0


if __name__ == "__main__":
    sys.exit(main())
