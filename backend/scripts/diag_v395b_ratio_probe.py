#!/usr/bin/env python3
"""
diag_v395b_ratio_probe.py  —  pinpoint WHY the v389 Financial sub-score is 0% covered

PART A (mongo, read-only): field-coverage census of symbol_fundamentals_cache —
  shows which fields the warm-fill actually persisted (confirms valuation fields
  like pe_ratio/market_cap land but roe_pct/net_margin_pct/etc. don't).

PART B (IB ReportSnapshot via dedicated clientId, read-only — RTH-safe): pulls a
  live ReportSnapshot for a few symbols and lists EVERY <Ratio FieldName> code +
  value present, plus what the current parser extracts. Reveals the real IB codes
  for ROE / net margin / EPS growth / debt-to-equity so we can fix the parser map.

NO WRITES. Run from repo root (Part B needs IB up):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v395b_ratio_probe.py
"""
import asyncio
import os
import sys
from collections import Counter

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
PROBE_SYMBOLS = ["AAPL", "MSFT", "JPM"]
WANT = ["roe_pct", "net_margin_pct", "eps_change_pct", "debt_to_equity"]


async def main():
    if not MONGO_URL:
        print("MONGO_URL not set."); sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=4000)[DB_NAME]

    print("=" * 70)
    print("FINANCIAL RATIO PROBE  (v395b)")
    print("=" * 70)

    # ---- PART A: cache field census --------------------------------------
    print("\nPART A — symbol_fundamentals_cache field coverage:")
    fc = db["symbol_fundamentals_cache"]
    total = fc.count_documents({})
    key_counts = Counter()
    sample_doc = None
    for d in fc.find({}, {"_id": 0}).limit(3000):
        if sample_doc is None:
            sample_doc = d
        for k, v in d.items():
            if v is not None:
                key_counts[k] += 1
    n = min(total, 3000)
    print(f"  cached symbols: {total}  (sampled {n})")
    print("  field coverage (non-null), sorted:")
    for k, c in key_counts.most_common():
        star = "  <-- WANTED" if k in WANT else ""
        print(f"     {k:<28} {c:>5}  ({100.0*c/n:.0f}%){star}")
    missing = [w for w in WANT if key_counts.get(w, 0) == 0]
    print(f"  WANTED fields entirely absent from cache: {missing}")

    # ---- PART B: live ReportSnapshot ratio codes -------------------------
    print("\nPART B — live IB ReportSnapshot <Ratio> codes:")
    try:
        from services.ib_fundamentals_client import get_fundamentals_ib_client
        from services.ib_fundamentals_parser import parse_report_snapshot
        import xml.etree.ElementTree as ET
        client = get_fundamentals_ib_client()
        ok = await client.connect()
        if not ok:
            print("  [skip] dedicated fundamentals IB client did not connect.")
        else:
            for sym in PROBE_SYMBOLS:
                try:
                    xml = await client.get_fundamental_report(sym, "ReportSnapshot")
                except Exception as e:
                    print(f"  {sym}: fetch failed: {e}"); continue
                if not xml:
                    print(f"  {sym}: empty ReportSnapshot"); continue
                try:
                    root = ET.fromstring(xml)
                except Exception as e:
                    print(f"  {sym}: XML parse failed: {e}"); continue
                codes = {}
                for r in root.iter("Ratio"):
                    fn = r.get("FieldName")
                    if fn:
                        codes[fn] = (r.text or "").strip()
                print(f"\n  {sym}: {len(codes)} <Ratio> codes present.")
                # spotlight likely profitability/leverage/growth codes
                hot = {k: v for k, v in codes.items() if any(
                    t in k.upper() for t in ("ROE", "ROA", "MGN", "MARGIN", "NPM",
                                              "EPS", "GROWTH", "GRPCT", "D2EQ", "DEBT",
                                              "TTMNI", "QTLE", "REVCHNG", "CHG"))}
                for k, v in sorted(hot.items()):
                    print(f"       {k:<16} = {v}")
                parsed = parse_report_snapshot(xml) or {}
                got = {w: parsed.get(w) for w in WANT}
                print(f"     current parser extracts: {got}")
    except Exception as e:
        print(f"  [skip] Part B error: {e}")

    print("\nRead-only — nothing was modified.")


if __name__ == "__main__":
    asyncio.run(main())
