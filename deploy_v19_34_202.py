#!/usr/bin/env python3
"""
deploy_v19_34_202.py — idempotent, line-number-independent deploy of the
IB-sourced fundamentals change (float + short-interest%).

Edits 3 files via ANCHORED string replacement (not line numbers, so it's
robust to sandbox↔DGX divergence), adds the pytest, then verifies with
py_compile + pytest. TRANSACTIONAL: it stages every edit in memory and only
writes to disk if EVERY anchor was found — if any anchor is missing it aborts
without touching a single file (so no half-applied corruption on the bot).

Run (DGX, from repo root):
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python /tmp/deploy_v19_34_202.py
Then, if it prints ✅ ALL VERIFIED:
    git add -A && git commit -m "v19.34.202 IB-sourced fundamentals: float + short-interest%" && git push && ./start_backend.sh --force
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


# (path, [(old, new, idempotency_marker), ...]); idempotency_marker present → skip that edit
EDITS = {}

# ─────────────────────────── ib_direct_service.py ───────────────────────────
IBD_METHOD = '''    async def get_fundamental_report(
        self,
        symbol: str,
        report_type: str = "ReportSnapshot",
        timeout: float = 20.0,
    ):
        """v19.34.202 — fetch an IB Reuters fundamental XML report for ``symbol``
        via the live clientId-11 socket (``reqFundamentalDataAsync``). Returns
        the raw XML string, or ``None`` on miss / not-subscribed / error.

        ``ReportSnapshot`` (~10KB) carries valuation + ``<SharesOut
        TotalFloat=...>`` (shares-outstanding text + float attribute). The
        legacy ``ib_service`` ReportSnapshot path is dead on this deploy, so
        this routes through ``ib_direct`` instead.
        """
        if not self._connected or not self._ib:
            return None
        try:
            from ib_async import Stock
        except ImportError:
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
            logger.debug(
                "[v19.34.202 get_fundamental_report] %s/%s failed: %s",
                symbol, report_type, exc,
            )
            return None

'''
IBD_ANCHOR = "    # ── v19.34.40 — Native MKT-close for EOD / manual / safety flatten ──"
EDITS[os.path.join(B, "services/ib_direct_service.py")] = [
    (IBD_ANCHOR, IBD_METHOD + IBD_ANCHOR, "def get_fundamental_report"),
]

# ─────────────────────────── ib_fundamentals_parser.py ──────────────────────
PARSER_OLD = '''    employees = root.find(".//Employees")
    if employees is not None and employees.text:
        try:
            out["employees"] = int(float(employees.text.strip()))
        except (TypeError, ValueError):
            pass'''
PARSER_NEW = PARSER_OLD + '''

    # CoGeneralInfo/SharesOut → shares outstanding (text) + float (TotalFloat
    # attr). v19.34.202 — e.g. <SharesOut TotalFloat="1623871179.0">1630600639.0</SharesOut>
    shares_out = root.find(".//CoGeneralInfo/SharesOut")
    if shares_out is not None:
        txt = (shares_out.text or "").strip()
        if txt:
            try:
                out["shares_outstanding"] = float(txt)
            except (TypeError, ValueError):
                pass
        total_float = shares_out.get("TotalFloat")
        if total_float:
            try:
                out["float_shares"] = float(total_float)
            except (TypeError, ValueError):
                pass'''
EDITS[os.path.join(B, "services/ib_fundamentals_parser.py")] = [
    (PARSER_OLD, PARSER_NEW, 'out["float_shares"] = float(total_float)'),
]

# ─────────────────────────── unified_fundamentals_cache.py ──────────────────
CACHE_IB_OLD = '''    # 2. IB ReportSnapshot
    try:
        from services.ib_service import get_ib_service
        from services.ib_fundamentals_parser import parse_report_snapshot
        ib = get_ib_service()
        if ib is not None:
            status = ib.get_connection_status()
            if status and status.get("connected"):
                ib_resp = await ib.get_fundamentals(symbol)
                if ib_resp and ib_resp.get("success"):
                    raw = (ib_resp.get("data") or {}).get("raw_data") or ""
                    parsed = parse_report_snapshot(raw)
                    if parsed:
                        merged.update(parsed)
                        source_chain.append("ib_report_snapshot")
    except Exception as exc:
        logger.debug("IB fundamentals lookup failed for %s: %s", symbol, exc)'''
CACHE_IB_NEW = '''    # 2. IB ReportSnapshot — prefer the LIVE ib_direct socket (clientId 11).
    # The legacy ib_service worker is usually disconnected on this deploy
    # (every cached doc historically came from Finnhub). ReportSnapshot is
    # ~10KB and carries float + shares-out via <SharesOut TotalFloat=...>.
    # (v19.34.202)
    try:
        from services.ib_direct_service import get_ib_direct_service
        from services.ib_fundamentals_parser import parse_report_snapshot
        ibd = get_ib_direct_service()
        if ibd is not None and ibd.is_connected():
            xml = await ibd.get_fundamental_report(symbol, "ReportSnapshot")
            if xml:
                parsed = parse_report_snapshot(xml)
                if parsed:
                    merged.update(parsed)
                    source_chain.append("ib_direct_report_snapshot")
    except Exception as exc:
        logger.debug("ib_direct fundamentals lookup failed for %s: %s", symbol, exc)

    # 2b. Legacy ib_service ReportSnapshot — only if ib_direct didn't deliver.
    if "ib_direct_report_snapshot" not in source_chain:
        try:
            from services.ib_service import get_ib_service
            from services.ib_fundamentals_parser import parse_report_snapshot
            ib = get_ib_service()
            if ib is not None:
                status = ib.get_connection_status()
                if status and status.get("connected"):
                    ib_resp = await ib.get_fundamentals(symbol)
                    if ib_resp and ib_resp.get("success"):
                        raw = (ib_resp.get("data") or {}).get("raw_data") or ""
                        parsed = parse_report_snapshot(raw)
                        if parsed:
                            merged.update(parsed)
                            source_chain.append("ib_report_snapshot")
        except Exception as exc:
            logger.debug("IB fundamentals lookup failed for %s: %s", symbol, exc)'''

CACHE_SI_OLD = '''                source_chain.append("finnhub")
        except Exception as exc:
            logger.debug("Finnhub fundamentals lookup failed for %s: %s", symbol, exc)

    if not source_chain:'''
CACHE_SI_NEW = '''                source_chain.append("finnhub")
        except Exception as exc:
            logger.debug("Finnhub fundamentals lookup failed for %s: %s", symbol, exc)

    # 3.5 Short-interest % — FINRA short-interest shares ÷ shares-outstanding.
    # Float/shares come from IB ReportSnapshot above; FINRA gives raw short
    # shares (no %). FINRA is bi-monthly (the accurate cadence). (v19.34.202)
    shares_out = merged.get("shares_outstanding") or merged.get("float_shares")
    if shares_out and float(shares_out) > 0 and db is not None:
        try:
            from services.short_interest_service import ShortInterestService
            si = await ShortInterestService(db).get_short_data_for_symbol(symbol)
            si_shares = (si or {}).get("short_interest")
            pct = compute_short_interest_pct(si_shares, shares_out)
            if pct is not None:
                merged["short_interest_percent"] = pct
                if (si or {}).get("days_to_cover") is not None:
                    merged["days_to_cover"] = si["days_to_cover"]
                source_chain.append("finra_short")
        except Exception as exc:
            logger.debug("Short-interest lookup failed for %s: %s", symbol, exc)

    if not source_chain:'''

CACHE_HELPER_OLD = '''def _ttl_hours_for(symbol: str, db) -> int:
    """Smart TTL: 1h if within 1 day of earnings, else 24h."""'''
CACHE_HELPER_NEW = '''def compute_short_interest_pct(si_shares, shares_out):
    """Short interest as a % of shares outstanding (rounded), or None if the
    inputs are missing/invalid. Pure — unit-testable without IB/Mongo."""
    try:
        if si_shares and shares_out and float(shares_out) > 0:
            return round(100.0 * float(si_shares) / float(shares_out), 2)
    except (TypeError, ValueError):
        pass
    return None


def _ttl_hours_for(symbol: str, db) -> int:
    """Smart TTL: 1h if within 1 day of earnings, else 24h."""'''

EDITS[os.path.join(B, "services/unified_fundamentals_cache.py")] = [
    (CACHE_IB_OLD, CACHE_IB_NEW, 'source_chain.append("ib_direct_report_snapshot")'),
    (CACHE_SI_OLD, CACHE_SI_NEW, 'source_chain.append("finra_short")'),
    (CACHE_HELPER_OLD, CACHE_HELPER_NEW, "def compute_short_interest_pct"),
]

# ─────────────────────────── the pytest file ────────────────────────────────
TEST_PATH = os.path.join(B, "tests/test_v19_34_202_ib_fundamentals.py")
TEST_BODY = '''"""v19.34.202 — IB ReportSnapshot float/shares parse + FINRA short-interest %."""
from services.ib_fundamentals_parser import parse_report_snapshot
from services.unified_fundamentals_cache import compute_short_interest_pct

_SNAPSHOT = """<?xml version="1.0" encoding="UTF-8"?>
<ReportSnapshot Major="1" Minor="0" Revision="1">
  <CoGeneralInfo>
    <Employees LastUpdated="2025-12-27">31000</Employees>
    <SharesOut Date="2026-04-29" TotalFloat="1623871179.0">1630600639.0</SharesOut>
  </CoGeneralInfo>
</ReportSnapshot>"""


def test_parse_shares_and_float():
    out = parse_report_snapshot(_SNAPSHOT)
    assert out["shares_outstanding"] == 1630600639.0
    assert out["float_shares"] == 1623871179.0
    assert out["employees"] == 31000


def test_parse_missing_sharesout_is_safe():
    out = parse_report_snapshot(
        "<ReportSnapshot><CoGeneralInfo></CoGeneralInfo></ReportSnapshot>")
    assert "shares_outstanding" not in out
    assert "float_shares" not in out


def test_short_interest_pct_basic():
    assert compute_short_interest_pct(50_000_000, 1_630_600_639) == 3.07


def test_short_interest_pct_high():
    assert compute_short_interest_pct(200_000_000, 1_000_000_000) == 20.0


def test_short_interest_pct_guards():
    assert compute_short_interest_pct(0, 1_000_000) is None
    assert compute_short_interest_pct(1_000_000, 0) is None
    assert compute_short_interest_pct(None, 1_000_000) is None
    assert compute_short_interest_pct("x", "y") is None
'''


def main():
    # ---- STAGE (transactional): compute new content for every file ----
    staged = {}
    for path, edits in EDITS.items():
        if not os.path.exists(path):
            print(f"🔴 ABORT: missing file {path}")
            return 1
        s = read(path)
        for old, new, marker in edits:
            if marker in s:
                print(f"  ↩ {os.path.basename(path)}: '{marker[:40]}' already present (skip)")
                continue
            if old not in s:
                print(f"🔴 ABORT: anchor not found in {os.path.basename(path)} "
                      f"for marker '{marker[:40]}'. No files written.")
                print("   → paste me this file and I'll regenerate.")
                return 1
            s = s.replace(old, new, 1)
        staged[path] = s

    # ---- COMMIT to disk ----
    for path, content in staged.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  ✓ wrote {os.path.relpath(path, ROOT)}")
    with open(TEST_PATH, "w", encoding="utf-8") as f:
        f.write(TEST_BODY)
    print(f"  ✓ wrote {os.path.relpath(TEST_PATH, ROOT)}")

    # ---- VERIFY ----
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
        [sys.executable, "-m", "pytest", "tests/test_v19_34_202_ib_fundamentals.py", "-q"],
        cwd=B)
    if r.returncode != 0:
        print("🔴 pytest FAILED")
        return 1

    print("\n✅ ALL VERIFIED. Now commit + restart:")
    print('  git add -A && git commit -m "v19.34.202 IB-sourced fundamentals: '
          'float + short-interest%" && git push && ./start_backend.sh --force')
    return 0


if __name__ == "__main__":
    sys.exit(main())
