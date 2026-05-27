"""v19.34.168.1 — Fix endpoint routing collision.

Problem: v19.34.168 added `/api/market-regime/history` and
`/api/market-regime/stats` as bare `@app.get(...)` decorators in
server.py. The first one collided with the Daily Engine A router
(`routers/market_regime.py` line 131) which is mounted at prefix
`/api/market-regime`, so the daily route shadowed the new intraday
one. The `/stats` endpoint never registered cleanly and returned 404.

Fix: rename to `/api/market-regime/composite/history` and
`/api/market-regime/composite/stats` (under the composite namespace
established by v19.34.167.1) and re-inject them next to the working
`/api/market-regime/composite` route.

This script is IDEMPOTENT — running it multiple times produces the
same final state.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /.../backend
SERVER = os.path.join(ROOT, "server.py")
SERVICE = os.path.join(ROOT, "services", "regime_persistence_service.py")

NEW_BLOCK = '''
@app.get("/api/market-regime/composite/history")
async def get_market_regime_composite_history(hours: int = 24, limit: int = 500):
    """v19.34.168 — Intraday composite regime snapshot history.

    Reads from the `regime_snapshots` collection (written by the scanner
    on regime/agreement/divergence transitions). Distinct from the Daily
    Engine A `/api/market-regime/history` endpoint, which serves
    `market_regime_state` rows.
    """
    from services.regime_persistence_service import query_history
    try:
        hours = max(1, min(int(hours), 24 * 30))
        limit = max(1, min(int(limit), 5000))
        snapshots = query_history(db, hours=hours, limit=limit)
        return {
            "success": True,
            "hours": hours,
            "count": len(snapshots),
            "snapshots": snapshots,
            "source": "regime_snapshots",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "snapshots": [], "source": "regime_snapshots"}


@app.get("/api/market-regime/composite/stats")
async def get_market_regime_composite_stats(hours: int = 24):
    """v19.34.168 — % time-in-regime over the last N hours, computed from
    `regime_snapshots` gaps. Answers questions like 'what fraction of the
    last 6h was SPY/QQQ/IWM in strong_uptrend vs volatile'.
    """
    from services.regime_persistence_service import query_stats
    try:
        hours = max(1, min(int(hours), 24 * 30))
        stats = query_stats(db, hours=hours)
        return {
            "success": True,
            "source": "regime_snapshots",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **stats,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "source": "regime_snapshots"}

'''


def _backup(path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{path}.bak.v168_1.{stamp}"
    shutil.copy2(path, dst)
    return dst


def _strip_broken_v168_routes(src: str) -> tuple[str, int]:
    """Remove the previously-injected broken routes:
       @app.get("/api/market-regime/history")
       @app.get("/api/market-regime/stats")
    Also strips any leftover 'composite/history' / 'composite/stats'
    so re-runs don't duplicate the function definitions.
    """
    removed = 0
    patterns = [
        r'\n@app\.get\("/api/market-regime/history"\)\s*\nasync def [^\n]+\n(?:.*?\n)*?(?=\n@app\.|\nif __name__|\Z)',
        r'\n@app\.get\("/api/market-regime/stats"\)\s*\nasync def [^\n]+\n(?:.*?\n)*?(?=\n@app\.|\nif __name__|\Z)',
        r'\n@app\.get\("/api/market-regime/composite/history"\)\s*\nasync def [^\n]+\n(?:.*?\n)*?(?=\n@app\.|\nif __name__|\Z)',
        r'\n@app\.get\("/api/market-regime/composite/stats"\)\s*\nasync def [^\n]+\n(?:.*?\n)*?(?=\n@app\.|\nif __name__|\Z)',
    ]
    for pat in patterns:
        new_src, n = re.subn(pat, "\n", src, flags=re.DOTALL)
        removed += n
        src = new_src
    return src, removed


def patch_server() -> None:
    if not os.path.exists(SERVER):
        print(f"ERROR: {SERVER} not found")
        sys.exit(1)

    with open(SERVER, "r", encoding="utf-8") as f:
        src = f.read()

    if '@app.get("/api/market-regime/composite")' not in src:
        print("ERROR: /api/market-regime/composite anchor not found. "
              "v19.34.167.1 may not be deployed. Aborting.")
        sys.exit(2)

    backup = _backup(SERVER)
    print(f"  - Backup written: {backup}")

    src, removed = _strip_broken_v168_routes(src)
    if removed:
        print(f"  - Stripped {removed} prior v168 route definition(s)")

    # Inject right before the `if __name__ == "__main__":` guard so the
    # new routes live near `/composite`.
    anchor = '\nif __name__ == "__main__":'
    if anchor not in src:
        print("ERROR: could not locate `if __name__ == \"__main__\":` anchor.")
        sys.exit(3)
    src = src.replace(anchor, NEW_BLOCK + anchor, 1)

    with open(SERVER, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - server.py patched with /composite/history and /composite/stats")


def verify_service() -> None:
    if not os.path.exists(SERVICE):
        print(f"ERROR: {SERVICE} missing. v19.34.168 service file expected.")
        sys.exit(4)
    with open(SERVICE, "r", encoding="utf-8") as f:
        src = f.read()
    for needed in ("def record_if_changed", "def query_history", "def query_stats"):
        if needed not in src:
            print(f"ERROR: regime_persistence_service.py missing `{needed}`.")
            sys.exit(5)
    print("  - regime_persistence_service.py verified")


def main() -> None:
    print("=" * 60)
    print("v19.34.168.1 — Composite regime endpoint routing fix")
    print("=" * 60)
    verify_service()
    patch_server()
    print()
    print("DONE. Next steps:")
    print("  1. git add -A && git commit -m 'v19.34.168.1: composite/history+stats routing fix'")
    print("  2. Restart backend (your .bat or `sudo systemctl restart sentcom-backend`)")
    print("  3. curl -s http://localhost:8001/api/market-regime/composite/history?hours=6")
    print("  4. curl -s http://localhost:8001/api/market-regime/composite/stats?hours=6")


if __name__ == "__main__":
    main()
