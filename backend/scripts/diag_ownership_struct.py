#!/usr/bin/env python3
"""
diag_ownership_struct.py — dump the STRUCTURE of IB ReportsOwnership so we can
find the correct institutional-ownership figure instead of naively summing a
single <type> (which over-counts 1.3-2.6x due to parent/child fund nesting).

Investigates 4 things:
  1. Root tag + top-level children + any summary/total/percent nodes.
  2. First ~1800 chars of raw XML (the header — often has a pre-computed total).
  3. One full <Owner> element (all child tags + attributes) so we can see if
     there's a per-owner percent, a parent ref, or an asofDate to dedupe on.
  4. Dedup experiment on type==2: collapse duplicate ownerIds (keep latest
     asofDate), and show the top-10 largest type-2 holders by name (to eyeball
     obvious parent/child dups like "BlackRock Inc" + "BlackRock Fund Advisors").

Run (DGX, IB Gateway up):
    .venv/bin/python backend/scripts/diag_ownership_struct.py AB
"""
import asyncio
import io
import os
import re
import sys
from collections import defaultdict
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


def _shares_out(xml):
    so = ET.fromstring(xml).find(".//CoGeneralInfo/SharesOut")
    if so is None:
        return None
    return float(so.text.strip()) if (so.text or "").strip() else None


async def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "AB").upper()
    ib = IB()
    print(f"Connecting {HOST}:{PORT} clientId={CLIENT_ID}…")
    await ib.connectAsync(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    print("✓ connected")
    try:
        c = (await ib.qualifyContractsAsync(Stock(sym, "SMART", "USD")))[0]
        snap = await ib.reqFundamentalDataAsync(c, "ReportSnapshot")
        shares_out = _shares_out(snap)
        own = await ib.reqFundamentalDataAsync(c, "ReportsOwnership")

        print(f"\n{sym}: shares_out={shares_out:,.0f}" if shares_out else
              f"\n{sym}: shares_out=None")
        print(f"{sym} ReportsOwnership: {len(own):,} chars")

        # ---- 1. root + top-level structure ----
        root = ET.fromstring(own)
        print(f"\n── ROOT <{root.tag}> attrs={dict(root.attrib)} ──")
        for child in list(root)[:25]:
            txt = (child.text or "").strip()[:60]
            print(f"   <{child.tag}> attrs={dict(child.attrib)} text={txt!r}")

        # ---- 1b. hunt for summary / total / percent nodes anywhere ----
        print("\n── nodes whose tag mentions total/percent/institution/summary ──")
        seen = set()
        for el in root.iter():
            tl = el.tag.lower()
            if any(k in tl for k in ("total", "percent", "pct", "institution",
                                     "summary", "stat", "outstanding")):
                key = el.tag
                if key not in seen:
                    seen.add(key)
                    print(f"   <{el.tag}> attrs={dict(el.attrib)} "
                          f"text={(el.text or '').strip()[:60]!r}")
        if not seen:
            print("   (none found)")

        # ---- 2. raw header ----
        print("\n── first 1800 chars of raw XML ──")
        print(own[:1800])

        # ---- 3. one full <Owner> (show all child tags/attrs) ----
        print("\n── one full <Owner> element ──")
        owner_el = root.find(".//Owner")
        if owner_el is not None:
            print(f"   <Owner attrs={dict(owner_el.attrib)}>")
            for ch in owner_el:
                print(f"     <{ch.tag} attrs={dict(ch.attrib)}> "
                      f"= {(ch.text or '').strip()[:60]!r}")

        # ---- 4. dedup experiment on type==2 ----
        # collapse duplicate ownerId, keep the largest quantity per ownerId
        per_owner = defaultdict(float)          # ownerId -> max quantity
        per_owner_name = {}
        raw_sum = 0.0
        n_tags = 0
        n_unique = 0
        for ev, elem in ET.iterparse(io.StringIO(own), events=("end",)):
            if elem.tag != "Owner":
                continue
            t_el = elem.find("type")
            if t_el is None or (t_el.text or "").strip() != "2":
                elem.clear()
                continue
            q_el = elem.find("quantity")
            name_el = elem.find("name")
            oid = elem.get("ownerId") or (name_el.text if name_el is not None else "?")
            try:
                q = float((q_el.text or "0").strip()) if q_el is not None else 0.0
            except (TypeError, ValueError):
                q = 0.0
            raw_sum += q
            n_tags += 1
            if oid not in per_owner:
                n_unique += 1
            if q > per_owner[oid]:
                per_owner[oid] = q
                per_owner_name[oid] = (name_el.text or "").strip() if name_el is not None else ""
            elem.clear()

        dedup_sum = sum(per_owner.values())
        denom = shares_out or 1
        print("\n── type==2 dedup experiment ──")
        print(f"   raw type-2 tags         = {n_tags:,}")
        print(f"   unique ownerIds         = {n_unique:,}")
        print(f"   RAW sum                 = {raw_sum:,.0f}  ({100*raw_sum/denom:.1f}% of shares_out)")
        print(f"   DEDUP sum (max/ownerId) = {dedup_sum:,.0f}  ({100*dedup_sum/denom:.1f}% of shares_out)")

        print("\n── top 12 type-2 holders by quantity (eyeball parent/child dups) ──")
        top = sorted(per_owner.items(), key=lambda kv: -kv[1])[:12]
        for oid, q in top:
            print(f"   {100*q/denom:6.1f}%  {q:>15,.0f}  id={oid:<14} {per_owner_name.get(oid,'')[:45]}")
    finally:
        ib.disconnect()
        print("\n✓ disconnected")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
