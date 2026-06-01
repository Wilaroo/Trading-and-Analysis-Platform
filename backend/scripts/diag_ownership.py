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
    """Stream the doc: sum quantities, count owners, note quantity parents,
    and ALSO sum quantities that are direct children of <Owner> only."""
    total_all = 0.0
    n_qty = 0
    n_owner = 0
    float_shares = None
    parent_tags = Counter()
    # build a parent map cheaply via iterparse start/end stack
    stack = []
    owner_only_total = 0.0
    for event, elem in ET.iterparse(io.StringIO(xml), events=("start", "end")):
        if event == "start":
            stack.append(elem.tag)
        else:  # end
            tag = elem.tag
            if tag == "quantity":
                parent = stack[-2] if len(stack) >= 2 else "?"
                parent_tags[parent] += 1
                try:
                    q = float((elem.text or "0").strip())
                    total_all += q
                    n_qty += 1
                    if parent == "Owner":
                        owner_only_total += q
                except (TypeError, ValueError):
                    pass
            elif tag == "floatShares":
                try:
                    float_shares = float((elem.text or "").strip())
                except (TypeError, ValueError):
                    pass
            elif tag == "Owner":
                n_owner += 1
            if stack:
                stack.pop()
            elem.clear()
    return {
        "total_all_quantities": total_all,
        "owner_only_total": owner_only_total,
        "num_quantity_tags": n_qty,
        "num_owner_tags": n_owner,
        "float_shares": float_shares,
        "quantity_parents": dict(parent_tags),
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
        print(f"  num <quantity> tags       = {b['num_quantity_tags']:,}")
        print(f"  quantity parents          = {b['quantity_parents']}")
        print(f"  floatShares (ownership)   = {b['float_shares']:,.0f}" if b['float_shares'] else "  floatShares = None")
        print(f"  SUM of ALL quantities     = {b['total_all_quantities']:,.0f}")
        print(f"  SUM (Owner-direct only)   = {b['owner_only_total']:,.0f}")

        denom_so = shares_out
        denom_fl = b["float_shares"] or total_float_snap
        print("\n  ── resulting ratios ──")
        for label, total in (("ALL-qty", b["total_all_quantities"]),
                             ("Owner-only", b["owner_only_total"])):
            if denom_so:
                print(f"  {label} / shares_out = {100*total/denom_so:6.1f}%")
            if denom_fl:
                print(f"  {label} / float      = {100*total/denom_fl:6.1f}%")
    finally:
        ib.disconnect()
        print("\n✓ disconnected")
    print("\n══ READ ══")
    print("  If 'Owner-only / shares_out' ≈ 60-90% but 'ALL-qty' >> 100%, the bug")
    print("  is over-summing quantity tags outside <Owner>. If both are >100%,")
    print("  the denominator (float vs shares_out) or double-counting is the issue.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
