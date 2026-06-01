#!/usr/bin/env python3
"""
diag_ownership.py — diagnose why institutional_ownership_percent computes to
100% for every symbol. Standalone (clientId 78, like the probe) so it doesn't
touch the bot. Fetches AMD's ReportSnapshot + ReportsOwnership and breaks down
the math: shares-out, float, holder count, summed shares, parents of every
<quantity> tag (to detect over-summing), and the ratio both ways.

Run (DGX, IB Gateway up):
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python backend/scripts/diag_ownership.py AMD
"""
import asyncio
import io
import os
import sys
from collections import Counter
from xml.etree import ElementTree as ET

try:
    from dotenv import load_dotenv
    for _p in ("backend/.env",
               os.path.expanduser("~/Trading-and-Analysis-Platform/backend/.env")):
        if os.path.exists(_p):
            load_dotenv(_p)
            break
except Exception:
    pass

try:
    from ib_async import IB, Stock
except ImportError:
    from ib_insync import IB, Stock

HOST = os.environ.get("IB_DIRECT_HOST", os.environ.get("IB_HOST", "192.168.50.1"))
PORT = int(os.environ.get("IB_DIRECT_PORT", "4002"))
CLIENT_ID = int(os.environ.get("IB_PROBE_CLIENT_ID", "78"))


def _snapshot_shares(xml):
    so = ET.fromstring(xml).find(".//CoGeneralInfo/SharesOut")
    if so is None:
        return None, None
    out = float(so.text.strip()) if (so.text or "").strip() else None
    tf = so.get("TotalFloat")
    return out, (float(tf) if tf else None)


def _ownership_breakdown(xml):
    """Stream the doc and aggregate quantity by the Owner <type> code, so we can
    see which type(s) double-count. Each <Owner> has one <type> and one
    <quantity>."""
    by_type_sum = Counter()
    by_type_count = Counter()
    total_all = 0.0
    n_owner = 0
    float_shares = None
    for event, elem in ET.iterparse(io.StringIO(xml), events=("end",)):
        tag = elem.tag
        if tag == "floatShares":
            try:
                float_shares = float((elem.text or "").strip())
            except (TypeError, ValueError):
                pass
            elem.clear()
        elif tag == "Owner":
            n_owner += 1
            t_el = elem.find("type")
            q_el = elem.find("quantity")
            t = (t_el.text or "?").strip() if t_el is not None else "?"
            try:
                q = float((q_el.text or "0").strip()) if q_el is not None else 0.0
            except (TypeError, ValueError):
                q = 0.0
            by_type_sum[t] += q
            by_type_count[t] += 1
            total_all += q
            elem.clear()
    return {
        "total_all_quantities": total_all,
        "num_owner_tags": n_owner,
        "float_shares": float_shares,
        "by_type_sum": dict(by_type_sum),
        "by_type_count": dict(by_type_count),
    }


async def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "AMD").upper()
    ib = IB()
    print(f"Connecting {HOST}:{PORT} clientId={CLIENT_ID}…")
    await ib.connectAsync(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    print("✓ connected")
    try:
        c = (await ib.qualifyContractsAsync(Stock(sym, "SMART", "USD")))[0]
        snap = await ib.reqFundamentalDataAsync(c, "ReportSnapshot")
        shares_out, total_float_snap = _snapshot_shares(snap)
        print(f"\n{sym} ReportSnapshot:")
        print(f"  shares_outstanding = {shares_out:,.0f}" if shares_out else "  shares_outstanding = None")
        print(f"  TotalFloat (snap)  = {total_float_snap:,.0f}" if total_float_snap else "  TotalFloat = None")

        own = await ib.reqFundamentalDataAsync(c, "ReportsOwnership")
        print(f"\n{sym} ReportsOwnership ({len(own):,} chars):")
        b = _ownership_breakdown(own)
        print(f"  num <Owner> tags          = {b['num_owner_tags']:,}")
        print(f"  floatShares (ownership)   = {b['float_shares']:,.0f}" if b['float_shares'] else "  floatShares = None")
        print(f"  SUM of ALL quantities     = {b['total_all_quantities']:,.0f}")

        denom = shares_out or b["float_shares"] or total_float_snap
        print(f"\n  ── per owner <type> (denom = shares_out {shares_out:,.0f}) ──"
              if shares_out else "\n  ── per owner <type> ──")
        rows = sorted(b["by_type_sum"].items(), key=lambda kv: -kv[1])
        for t, s in rows:
            pct = (100 * s / denom) if denom else 0
            print(f"    type {t:>3}: {b['by_type_count'][t]:>6,} owners, "
                  f"{s:>16,.0f} shares  = {pct:6.1f}% of shares_out")
        print(f"\n  TOTAL (all types) = {100*b['total_all_quantities']/denom:.1f}% "
              f"of shares_out" if denom else "")
    finally:
        ib.disconnect()
        print("\n✓ disconnected")
    print("\n══ READ ══")
    print("  Pick the type(s) whose % lands near the real institutional figure")
    print("  (~60-80% for a large-cap like AMD). Summing ALL types double-counts")
    print("  (funds counted both at fund level and in their parent institution).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
