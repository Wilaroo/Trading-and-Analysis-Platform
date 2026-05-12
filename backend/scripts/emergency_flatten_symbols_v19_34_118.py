"""
emergency_flatten_symbols_v19_34_118.py
─────────────────────────────────────────────────────────────────────────────
EMERGENCY FLATTEN — Routes through the v19.34.45 *nuclear* endpoint
`/api/safety/emergency-flatten-ib`, which bypasses `bot._open_trades`
and `close_trade()` entirely. Reads the live IB position list via
`ib_direct_service` (clientId 11), cancels working orders, fires a
single MKT close per symbol.

Use this when the regular "Close all / cancel" button reports
"close_returned_false" for every position — the exact failure mode
v19.34.45 was built to fix.

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform/backend
    APP_URL=http://localhost:8001 \
        python3 scripts/emergency_flatten_symbols_v19_34_118.py ONON RJF MTB CCJ

Or to flatten EVERY IB position the direct API sees:
    APP_URL=http://localhost:8001 \
        python3 scripts/emergency_flatten_symbols_v19_34_118.py --all

Requires:
  - `ib_direct_service` connected (IB_DIRECT_ENABLED=true, clientId=11).
  - If not connected the script tells you, and your only remaining
    paths are TWS-manual or `/api/safety/flatten-all` (which is the
    path that just failed for you).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any


def _post(url: str, payload: dict, timeout: int = 60) -> tuple[int, Any]:
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


def _get(url: str, timeout: int = 10) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, str(exc)
    except Exception as exc:
        return 0, str(exc)


def main(argv: list[str]) -> int:
    app_url = (os.environ.get("APP_URL") or "http://localhost:8001").rstrip("/")

    flatten_all = "--all" in argv
    symbols = [a.upper() for a in argv if not a.startswith("--")]

    print(f"\n=== v19.34.118 Emergency Flatten (nuclear path) ===")
    print(f"Bot URL : {app_url}")
    print(f"Symbols : {'ALL IB-held' if flatten_all else symbols}")
    print()

    # Pre-flight: check ib_direct connection
    status, body = _get(f"{app_url}/api/ib/pusher-health")
    if isinstance(body, dict):
        hb = body.get("heartbeat") or {}
        print(f"Pusher connected   : {body.get('pusher_connected')}")
        print(f"IB-direct connected: {hb.get('ib_direct_connected')}")
    else:
        print(f"Pusher health probe failed: {status} {body}")

    payload: dict[str, Any] = {"confirm": "FLATTEN_IB"}
    if symbols and not flatten_all:
        payload["symbols"] = symbols

    print(f"\nCalling POST {app_url}/api/safety/emergency-flatten-ib …")
    status, body = _post(
        f"{app_url}/api/safety/emergency-flatten-ib", payload, timeout=120,
    )
    print(f"HTTP {status}")
    if isinstance(body, dict):
        print(json.dumps(body, indent=2, default=str)[:8000])
        success = bool(body.get("success"))
        summary = body.get("summary") or {}
        closes = summary.get("closes") or []
        if closes:
            print(f"\n── per-symbol results ──")
            for c in closes:
                ok = "✓" if c.get("close_success") else "✗"
                print(
                    f"  {ok} {c.get('symbol'):8s} qty={c.get('qty'):>6}  "
                    f"action={c.get('close_action'):4s}  "
                    f"status={c.get('close_status')}  "
                    f"err={c.get('close_error', '')}"
                )
        return 0 if success else 2
    else:
        print(body)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["--all"]))
