#!/usr/bin/env python3
"""
probe_ib_fundamentals.py — READ-ONLY probe of IB Reuters fundamental reports.

Goal (for option B — IB-sourced fundamentals): confirm the IB account actually
serves `reqFundamentalData` and capture the REAL raw XML schema for:
  • ReportSnapshot   → valuation + CommonShares (shares outstanding)
  • ReportsOwnership → FLOAT + INSTITUTIONAL ownership %  (the fields the TQS
    fundamental pillar is starved of)
  • CalendarReport   → next earnings date (catalyst / earnings proximity)

SAFE: connects to IB Gateway with a SEPARATE clientId (default 77, override
`IB_PROBE_CLIENT_ID`) so it can NOT collide with the live bot's clientId 11.
No orders, no writes, disconnects when done.

Run (DGX, from repo root, while IB Gateway is up):
    cd ~/Trading-and-Analysis-Platform
    .venv/bin/python backend/scripts/probe_ib_fundamentals.py            # AMD AVGO
    .venv/bin/python backend/scripts/probe_ib_fundamentals.py NVDA TSLA  # custom
"""
import asyncio
import os
import sys

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
    try:
        from ib_insync import IB, Stock
    except ImportError:
        print("🔴 neither ib_async nor ib_insync importable in this venv")
        sys.exit(1)

HOST = os.environ.get("IB_DIRECT_HOST", os.environ.get("IB_HOST", "192.168.50.1"))
PORT = int(os.environ.get("IB_DIRECT_PORT", "4002"))
CLIENT_ID = int(os.environ.get("IB_PROBE_CLIENT_ID", "77"))

REPORTS = ["ReportSnapshot", "ReportsOwnership", "CalendarReport"]
MAX_DUMP = 4500  # chars of raw XML per report


async def probe_symbol(ib, symbol):
    print(f"\n{'='*70}\n SYMBOL: {symbol}\n{'='*70}")
    try:
        contract = Stock(symbol.upper(), "SMART", "USD")
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            print(f"  🔴 could not qualify contract for {symbol}")
            return
        contract = qualified[0]
    except Exception as e:
        print(f"  🔴 qualify failed: {e}")
        return

    for report in REPORTS:
        print(f"\n  ── reqFundamentalData({report}) ──")
        try:
            xml = await asyncio.wait_for(
                ib.reqFundamentalDataAsync(contract, report), timeout=30)
        except AttributeError:
            # older API — sync variant
            try:
                xml = ib.reqFundamentalData(contract, report)
            except Exception as e:
                print(f"    🔴 error: {e}")
                continue
        except Exception as e:
            print(f"    🔴 error: {e}")
            continue

        if not xml:
            print("    ⚠️  EMPTY (no data / not subscribed for this report)")
            continue
        print(f"    ✓ {len(xml)} chars")
        print("    ── RAW XML (truncated) ──")
        print("\n".join("    " + ln for ln in xml[:MAX_DUMP].splitlines()))
        if len(xml) > MAX_DUMP:
            print(f"    … (+{len(xml) - MAX_DUMP} more chars)")


async def main():
    symbols = [s.upper() for s in (sys.argv[1:] or ["AMD", "AVGO"])]
    ib = IB()
    print(f"Connecting IB {HOST}:{PORT} clientId={CLIENT_ID} (probe — separate "
          f"from the bot's clientId 11)…")
    try:
        await ib.connectAsync(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    except Exception as e:
        print(f"🔴 connect failed: {e}")
        print("   (Is IB Gateway up? Is clientId 77 free? Try "
              "IB_PROBE_CLIENT_ID=78)")
        return 1
    print(f"✓ connected (server v{ib.client.serverVersion()})")

    try:
        for sym in symbols:
            await probe_symbol(ib, sym)
    finally:
        ib.disconnect()
        print("\n✓ disconnected")

    print("\n══ READ ══")
    print("  Paste the ReportsOwnership XML back — I need its real tag names")
    print("  (Float / institutional %) to write the parser. EMPTY ReportsOwnership")
    print("  = the account lacks the Reuters ownership subscription → we fall back")
    print("  to shares-outstanding from ReportSnapshot CommonShares + FINRA.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
