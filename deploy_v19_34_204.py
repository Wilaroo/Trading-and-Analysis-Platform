#!/usr/bin/env python3
"""
deploy_v19_34_204.py — idempotent, anchor-based deploy of R4 (institutional
ownership via IB ReportsOwnership). Transactional: writes nothing unless every
anchor matches. Mirrors the v202/v203 deploy pattern.

Run (DGX, from repo root):
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python /tmp/deploy_v19_34_204.py
Then, if ✅ ALL VERIFIED:
    git add -A && git commit -m "v19.34.204 institutional ownership via IB ReportsOwnership (R4)" && git push && ./start_backend.sh --force
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

# ─────────────────────────── ib_fundamentals_parser.py ──────────────────────
PARSER = os.path.join(B, "services/ib_fundamentals_parser.py")
PARSER_OLD = '''    # Convert dividend yield to decimal (IB reports as PCT)
    if "dividend_yield_pct" in out and "dividend_yield" not in out:
        out["dividend_yield"] = out["dividend_yield_pct"] / 100.0

    return out'''
PARSER_NEW = PARSER_OLD + '''


def parse_reports_ownership(
    xml: str, shares_outstanding: Optional[float] = None
) -> Dict[str, Any]:
    """v19.34.204 — parse IB ``ReportsOwnership`` XML → institutional ownership.

    Institutional ownership % = sum of holder quantities / shares-outstanding
    (falls back to / floatShares), capped at 100%. Streams the multi-MB doc with
    iterparse + elem.clear(). Returns {} on parse failure.
    """
    import io

    total_shares = 0.0
    holders = 0
    float_shares = None
    try:
        for _event, elem in ET.iterparse(io.StringIO(xml), events=("end",)):
            tag = elem.tag
            if tag == "quantity":
                try:
                    total_shares += float((elem.text or "0").strip())
                except (TypeError, ValueError):
                    pass
                elem.clear()
            elif tag == "floatShares":
                try:
                    float_shares = float((elem.text or "").strip())
                except (TypeError, ValueError):
                    pass
                elem.clear()
            elif tag == "Owner":
                holders += 1
                elem.clear()
    except ET.ParseError as exc:
        logger.debug("parse_reports_ownership failed: %s", exc)
        return {}

    out = {
        "total_institutional_shares": total_shares,
        "num_institutional_holders": holders,
    }
    if float_shares:
        out["float_shares"] = float_shares
    denom = shares_outstanding or float_shares
    if denom and denom > 0 and total_shares > 0:
        out["institutional_ownership_percent"] = min(
            round(100.0 * total_shares / denom, 2), 100.0
        )
    return out'''
EDITS[PARSER] = [(PARSER_OLD, PARSER_NEW, "def parse_reports_ownership")]

# ─────────────────────────── unified_fundamentals_cache.py ──────────────────
CACHE = os.path.join(B, "services/unified_fundamentals_cache.py")

CACHE_CONST_OLD = '''COLLECTION = "symbol_fundamentals_cache"
DEFAULT_TTL_HOURS = 24'''
CACHE_CONST_NEW = '''COLLECTION = "symbol_fundamentals_cache"
INSTITUTIONAL_COLLECTION = "institutional_ownership_cache"
DEFAULT_TTL_HOURS = 24'''

CACHE_MERGE_OLD = '''        except Exception as exc:
            logger.debug("Short-interest lookup failed for %s: %s", symbol, exc)

    if not source_chain:
        return None'''
CACHE_MERGE_NEW = '''        except Exception as exc:
            logger.debug("Short-interest lookup failed for %s: %s", symbol, exc)

    # 3.6 Institutional ownership % — merged from the separately-maintained
    # `institutional_ownership_cache` (populated weekly by
    # refresh_institutional_ownership; the IB ReportsOwnership doc is multi-MB
    # so it can't live in this 24h hot path). (v19.34.204)
    if db is not None:
        try:
            inst = db[INSTITUTIONAL_COLLECTION].find_one({"symbol": symbol})
            if inst and inst.get("institutional_ownership_percent") is not None:
                merged["institutional_ownership_percent"] = \\
                    inst["institutional_ownership_percent"]
                source_chain.append("ib_ownership")
        except Exception as exc:
            logger.debug("Institutional ownership lookup failed for %s: %s",
                         symbol, exc)

    if not source_chain:
        return None'''

CACHE_FUNC_OLD = '''    if db is not None:
        try:
            db[COLLECTION].update_one(
                {"symbol": symbol}, {"$set": merged}, upsert=True
            )
        except Exception as exc:
            logger.debug("Cache write failed for %s: %s", symbol, exc)

    return merged'''
CACHE_FUNC_NEW = CACHE_FUNC_OLD + '''


async def refresh_institutional_ownership(symbol: str, db=None) -> Optional[float]:
    """v19.34.204 — fetch IB ReportsOwnership (multi-MB) for ``symbol`` via the
    live ib_direct socket, compute institutional ownership %, and upsert it into
    ``institutional_ownership_cache``. Returns the % or None. MUST run inside the
    backend process. Heavy → weekly off-hours job, NOT the hot path."""
    if db is None:
        db = _get_db()
    if db is None:
        return None
    try:
        from services.ib_direct_service import get_ib_direct_service
        from services.ib_fundamentals_parser import parse_reports_ownership
        ibd = get_ib_direct_service()
        if ibd is None or not ibd.is_connected():
            return None

        shares_out = None
        cached = db[COLLECTION].find_one({"symbol": symbol},
                                         {"shares_outstanding": 1})
        if cached:
            shares_out = cached.get("shares_outstanding")

        xml = await ibd.get_fundamental_report(symbol, "ReportsOwnership",
                                               timeout=60.0)
        if not xml:
            return None
        parsed = parse_reports_ownership(xml, shares_outstanding=shares_out)
        pct = parsed.get("institutional_ownership_percent")
        if pct is None:
            return None
        db[INSTITUTIONAL_COLLECTION].update_one(
            {"symbol": symbol},
            {"$set": {
                "symbol": symbol,
                "institutional_ownership_percent": pct,
                "num_institutional_holders": parsed.get("num_institutional_holders"),
                "float_shares_ownership": parsed.get("float_shares"),
                "fetched_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return pct
    except Exception as exc:
        logger.debug("refresh_institutional_ownership failed for %s: %s",
                     symbol, exc)
        return None'''

EDITS[CACHE] = [
    (CACHE_CONST_OLD, CACHE_CONST_NEW, 'INSTITUTIONAL_COLLECTION = "institutional_ownership_cache"'),
    (CACHE_MERGE_OLD, CACHE_MERGE_NEW, 'source_chain.append("ib_ownership")'),
    (CACHE_FUNC_OLD, CACHE_FUNC_NEW, "async def refresh_institutional_ownership"),
]

# ─────────────────────────── trading_scheduler.py ───────────────────────────
TS = os.path.join(B, "services/trading_scheduler.py")

TS_CRON_OLD = '''                id='earnings_calendar_refresh',
                name='Earnings Calendar Refresh',
                replace_existing=True
            )

            # 2. Weekly Report - Friday 4:30 PM ET'''
TS_CRON_NEW = '''                id='earnings_calendar_refresh',
                name='Earnings Calendar Refresh',
                replace_existing=True
            )

            # 1d. Institutional-ownership refresh — Sunday 3:00 AM ET weekly
            #     (v19.34.204). IB ReportsOwnership is multi-MB/symbol, so this
            #     runs off-hours into institutional_ownership_cache; the hot
            #     fundamentals path just reads the pre-computed % (15% pillar).
            self._scheduler.add_job(
                _wrap_async(self._run_institutional_ownership_refresh),
                CronTrigger(
                    day_of_week='sun',
                    hour=3,
                    minute=0,
                    timezone='US/Eastern'
                ),
                id='institutional_ownership_refresh',
                name='Institutional Ownership Refresh',
                replace_existing=True
            )

            # 2. Weekly Report - Friday 4:30 PM ET'''

TS_HANDLER_OLD = "    async def _run_earnings_calendar_refresh(self):"
TS_HANDLER_NEW = '''    async def _run_institutional_ownership_refresh(self):
        """v19.34.204 — weekly: pull IB ReportsOwnership for the active universe
        and persist institutional ownership % into institutional_ownership_cache
        (the 15% fundamental pillar component). Heavy/off-hours; sequential +
        throttled so the multi-MB fetches don't starve the order socket."""
        try:
            import asyncio as _asyncio
            from services.unified_fundamentals_cache import (
                refresh_institutional_ownership, _get_db, COLLECTION,
            )
            db = _get_db()
            if db is None:
                logger.warning("[scheduler] institutional refresh: no DB")
                return
            syms = sorted({
                d["symbol"] for d in
                db[COLLECTION].find({}, {"symbol": 1, "_id": 0})
                if d.get("symbol")
            })
            done = 0
            for sym in syms:
                pct = await refresh_institutional_ownership(sym, db)
                if pct is not None:
                    done += 1
                await _asyncio.sleep(2.0)
            logger.info("[scheduler] institutional ownership refresh: %d/%d "
                        "symbols updated", done, len(syms))
        except Exception as e:
            logger.error("[scheduler] institutional ownership refresh failed: %s", e)

    async def _run_earnings_calendar_refresh(self):'''

TS_TRIGGER_OLD = '''        elif task_type == "earnings_calendar_refresh":
            # v19.34.203 — on-demand earnings calendar refresh.
            await self._run_earnings_calendar_refresh()
        else:'''
TS_TRIGGER_NEW = '''        elif task_type == "earnings_calendar_refresh":
            # v19.34.203 — on-demand earnings calendar refresh.
            await self._run_earnings_calendar_refresh()
        elif task_type == "institutional_ownership_refresh":
            # v19.34.204 — on-demand: background it (full universe is multi-MB ×
            # ~174 symbols → minutes; don't block the HTTP request).
            import asyncio as _a
            _a.create_task(self._run_institutional_ownership_refresh())
        else:'''

EDITS[TS] = [
    (TS_CRON_OLD, TS_CRON_NEW, "id='institutional_ownership_refresh'"),
    (TS_HANDLER_OLD, TS_HANDLER_NEW, "async def _run_institutional_ownership_refresh"),
    (TS_TRIGGER_OLD, TS_TRIGGER_NEW, 'task_type == "institutional_ownership_refresh"'),
]

# ─────────────────────────── the pytest ─────────────────────────────────────
TEST_PATH = os.path.join(B, "tests/test_v19_34_204_institutional_ownership.py")
TEST_BODY = '''"""v19.34.204 — IB ReportsOwnership -> institutional ownership % (R4)."""
from services.ib_fundamentals_parser import parse_reports_ownership

_OWNERSHIP = """<OwnershipDetails>
   <floatShares asofDate="2026-03-19">1000000000</floatShares>
   <Owner ownerId="A"><type>2</type><name>BlackRock</name>
      <quantity asofDate="2026-03-31">300000000</quantity></Owner>
   <Owner ownerId="B"><type>5</type><name>Vanguard</name>
      <quantity asofDate="2026-03-31">250000000</quantity></Owner>
   <Owner ownerId="C"><type>5</type><name>State Street</name>
      <quantity asofDate="2026-03-31">150000000</quantity></Owner>
</OwnershipDetails>"""


def test_sums_holders_and_pct():
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=1_600_000_000)
    assert out["num_institutional_holders"] == 3
    assert out["total_institutional_shares"] == 700_000_000.0
    assert out["float_shares"] == 1_000_000_000.0
    assert out["institutional_ownership_percent"] == 43.75


def test_falls_back_to_float():
    out = parse_reports_ownership(_OWNERSHIP)
    assert out["institutional_ownership_percent"] == 70.0


def test_pct_capped_at_100():
    out = parse_reports_ownership(_OWNERSHIP, shares_outstanding=500_000_000)
    assert out["institutional_ownership_percent"] == 100.0


def test_bad_xml_returns_empty():
    assert parse_reports_ownership("<not valid") == {}


def test_no_owners_no_pct():
    out = parse_reports_ownership(
        "<OwnershipDetails><floatShares>100</floatShares></OwnershipDetails>",
        shares_outstanding=1000)
    assert "institutional_ownership_percent" not in out
    assert out["num_institutional_holders"] == 0
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
         "tests/test_v19_34_204_institutional_ownership.py", "-q"], cwd=B)
    if r.returncode != 0:
        print("🔴 pytest FAILED")
        return 1

    print("\n✅ ALL VERIFIED. Now commit + restart:")
    print('  git add -A && git commit -m "v19.34.204 institutional ownership via '
          'IB ReportsOwnership (R4)" && git push && ./start_backend.sh --force')
    return 0


if __name__ == "__main__":
    sys.exit(main())
