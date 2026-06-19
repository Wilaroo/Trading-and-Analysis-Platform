#!/usr/bin/env python3
"""
diag_v395c_full_ratios.py  —  dump ALL <Ratio> codes from live ReportSnapshot

Read-only. Prints every FieldName=value (no filter) for a few symbols so we know
exactly which profitability / growth / leverage codes IB provides, before fixing
the parser map. Also dumps the <ForecastData> block (forward growth lives there).

  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v395c_full_ratios.py
"""
import asyncio
import sys

PROBE = ["AAPL", "JPM"]


async def main():
    try:
        from services.ib_fundamentals_client import get_fundamentals_ib_client
        import xml.etree.ElementTree as ET
    except Exception as e:
        print("import failed:", e); sys.exit(1)

    client = get_fundamentals_ib_client()
    if not await client.connect():
        print("IB fundamentals client did not connect."); sys.exit(1)

    for sym in PROBE:
        print("=" * 60)
        print(sym)
        print("=" * 60)
        try:
            xml = await client.get_fundamental_report(sym, "ReportSnapshot")
        except Exception as e:
            print(f"  fetch failed: {e}"); continue
        if not xml:
            print("  empty"); continue
        root = ET.fromstring(xml)
        print("  ALL <Ratio> codes:")
        for r in sorted(root.iter("Ratio"), key=lambda x: x.get("FieldName") or ""):
            print(f"    {(r.get('FieldName') or ''):<18} = {(r.text or '').strip()}")
        # ForecastData (forward EPS / growth estimates)
        fc = list(root.iter("ForecastData"))
        if fc:
            print("  <ForecastData> ratios:")
            for r in fc[0].iter("Ratio"):
                ft = r.get("FieldName") or r.get("Type") or "?"
                val = ""
                v = r.find("Value")
                if v is not None:
                    val = (v.text or "").strip()
                print(f"    {ft:<18} = {val}")
    print("\nRead-only — nothing was modified.")


if __name__ == "__main__":
    asyncio.run(main())
