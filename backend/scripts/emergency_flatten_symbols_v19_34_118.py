"""
emergency_flatten_symbols_v19_34_118.py
─────────────────────────────────────────────────────────────────────────────
Per-symbol emergency flatten. Targets the bot.close_trade() path used by
the safety_router so every bracket leg is properly cancelled at IB.

Run on the DGX (where the bot service is actually live):
    cd ~/Trading-and-Analysis-Platform/backend
    MONGO_URL=mongodb://localhost:27017 DB_NAME=tradecommand \
        APP_URL=http://localhost:8001 \
        python3 scripts/emergency_flatten_symbols_v19_34_118.py ONON RJF MTB CCJ

The script:
  1. Resolves every OPEN bot_trades doc for each symbol.
  2. Calls POST /api/safety/flatten-symbol per trade_id (one-by-one so
     a single failure doesn't block the rest).
  3. Prints a summary of OK / FAIL.

Safer than /flatten-all because it ONLY touches the listed symbols.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND_DIR = HERE.parent.parent
sys.path.insert(0, str(BACKEND_DIR))


def _post(url: str, payload: dict, timeout: int = 30) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, str(exc)
    except Exception as exc:
        return 0, str(exc)


def main(symbols: list[str]) -> int:
    from pymongo import MongoClient

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    app_url = (os.environ.get("APP_URL") or "http://localhost:8001").rstrip("/")
    if not mongo_url:
        print("ERROR: MONGO_URL not set.")
        return 1

    client = MongoClient(mongo_url)
    db = client[db_name]
    symbols = [s.upper() for s in symbols]
    print(f"\n=== Emergency flatten target symbols: {symbols} ===")
    print(f"=== Bot service URL: {app_url} ===\n")

    trade_ids: list[tuple[str, str]] = []
    for sym in symbols:
        for t in db.bot_trades.find(
            {"symbol": sym, "status": {"$in": ["open", "OPEN", "partial", "filled"]}},
            {"_id": 0, "id": 1, "trade_id": 1, "symbol": 1, "shares": 1, "direction": 1},
        ):
            tid = t.get("id") or t.get("trade_id")
            if not tid:
                continue
            trade_ids.append((sym, tid))
            print(
                f"  found OPEN  {sym}  trade_id={tid}  "
                f"shares={t.get('shares')}  dir={t.get('direction')}"
            )

    if not trade_ids:
        print("  no open trades found in bot_trades — nothing to do.")
        return 0

    print(f"\nFlattening {len(trade_ids)} trade(s) via bot.close_trade …")
    ok, fail = 0, 0
    for sym, tid in trade_ids:
        status, body = _post(
            f"{app_url}/api/trading-bot/close-trade",
            {"trade_id": tid, "reason": "emergency_flatten_v19_34_118"},
        )
        if 200 <= status < 300:
            ok += 1
            print(f"  ✓ {sym} {tid}  → {status}  {body if isinstance(body, str) else body.get('status', body)}")
        else:
            fail += 1
            print(f"  ✗ {sym} {tid}  → {status}  {body}")

    print(f"\nDone. OK={ok}  FAIL={fail}")
    if fail:
        print("\nRetry the failed ones, or fall back to /api/safety/flatten-all?confirm=FLATTEN")
        print("(or manually flatten in IB Gateway).")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    syms = sys.argv[1:] or ["ONON", "RJF", "MTB", "CCJ"]
    sys.exit(main(syms))
