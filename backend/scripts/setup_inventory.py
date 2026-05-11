"""
setup_inventory.py  ·  v19.34.95
─────────────────────────────────────────────────────────────────────────────
Categorized inventory of every setup the SentCom scanner can emit.

Buckets by user's 5 trade-style categories:
  scalp · intraday · swing · investment · position

For each setup we report:
  - config-enabled  (registered in SETUP_REGISTRY / _enabled_setups / daily-scan)
  - direction bias  (long / short / both)
  - SMB category    (trend_momentum / catalyst_driven / reversal / consolidation / specialized)
  - last_fired_at   (overlay from MongoDB bot_trades + carry_forward_alerts + live_alerts)

Run this on the DGX where MongoDB has the live data:
    cd ~/Trading-and-Analysis-Platform/backend
    MONGO_URL=mongodb://localhost:27017 DB_NAME=tradecommand python3 scripts/setup_inventory.py

It works offline too — without MongoDB, you still get the static config inventory.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running from repo root or backend/
HERE = Path(__file__).resolve()
BACKEND_DIR = HERE.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.smb_integration import (  # noqa: E402
    SETUP_REGISTRY,
    SetupCategory,
    SetupDirection,
    TradeStyle,
)


# ── Daily-bar setups (run by `_scan_daily_setups` every 10th cycle) ──────────
# Not in SETUP_REGISTRY (registry is intraday-focused). These are pure
# swing/position plays driven off daily OHLCV bars.
DAILY_SWING_SETUPS: Dict[str, Dict[str, str]] = {
    "daily_squeeze":          {"style": "swing",    "direction": "both",  "category": "consolidation"},
    "trend_continuation":     {"style": "swing",    "direction": "both",  "category": "trend_momentum"},
    "daily_breakout":         {"style": "swing",    "direction": "long",  "category": "trend_momentum"},
    "base_breakout":          {"style": "swing",    "direction": "long",  "category": "consolidation"},
    "accumulation_entry":     {"style": "position", "direction": "long",  "category": "consolidation"},
    "breakdown_confirmed":    {"style": "swing",    "direction": "short", "category": "trend_momentum"},
}

# Carry-forward overnight watchlist setups (emitted by `_rank_carry_forward_setups_for_tomorrow`)
CARRY_FORWARD_SETUPS: Dict[str, Dict[str, str]] = {
    "day_2_continuation": {"style": "swing", "direction": "both", "category": "trend_momentum"},
    "gap_fill_open":      {"style": "swing", "direction": "both", "category": "reversal"},
}

# Style → user-facing bucket
STYLE_TO_BUCKET = {
    TradeStyle.SCALP.value:     "scalp",
    TradeStyle.INTRADAY.value:  "intraday",
    TradeStyle.MULTI_DAY.value: "swing",
    "swing":                    "swing",
    "position":                 "position",
    "investment":               "investment",
}

BUCKETS = ["scalp", "intraday", "swing", "investment", "position"]


def build_static_inventory() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    # 1) Registered intraday setups from SETUP_REGISTRY
    for name, cfg in SETUP_REGISTRY.items():
        rows.append({
            "setup": name,
            "display_name": cfg.display_name,
            "style": cfg.default_style.value,
            "bucket": STYLE_TO_BUCKET.get(cfg.default_style.value, "intraday"),
            "direction": cfg.direction.value,
            "category": cfg.category.value,
            "source": "SETUP_REGISTRY",
            "config_enabled": True,
        })

    # 2) Daily swing/position setups
    for name, meta in DAILY_SWING_SETUPS.items():
        rows.append({
            "setup": name,
            "display_name": name.replace("_", " ").title(),
            "style": meta["style"],
            "bucket": meta["style"],
            "direction": meta["direction"],
            "category": meta["category"],
            "source": "DAILY_SCAN",
            "config_enabled": True,
        })

    # 3) Carry-forward overnight setups
    for name, meta in CARRY_FORWARD_SETUPS.items():
        rows.append({
            "setup": name,
            "display_name": name.replace("_", " ").title(),
            "style": meta["style"],
            "bucket": meta["style"],
            "direction": meta["direction"],
            "category": meta["category"],
            "source": "CARRY_FORWARD",
            "config_enabled": True,
        })

    return rows


def overlay_last_fired(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Overlay last_fired_at from MongoDB if available."""
    try:
        from pymongo import MongoClient
    except Exception:
        return rows

    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME") or "tradecommand"

    try:
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
    except Exception as exc:
        print(f"⚠️  MongoDB unreachable ({exc}). Static inventory only.\n")
        return rows

    db = client[db_name]
    last_fired: Dict[str, datetime] = {}
    counts: Dict[str, int] = defaultdict(int)

    # Pull from bot_trades (execution layer)
    try:
        cur = db["bot_trades"].aggregate([
            {"$match": {"setup_type": {"$exists": True}}},
            {"$group": {
                "_id": "$setup_type",
                "last": {"$max": "$created_at"},
                "n": {"$sum": 1},
            }},
        ])
        for doc in cur:
            st = (doc.get("_id") or "").strip()
            if not st:
                continue
            counts[st] += int(doc.get("n", 0))
            ts = doc.get("last")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    ts = None
            if isinstance(ts, datetime):
                cur_last = last_fired.get(st)
                if cur_last is None or ts > cur_last:
                    last_fired[st] = ts
    except Exception as exc:
        print(f"⚠️  bot_trades scan failed: {exc}")

    # Pull from carry_forward_alerts
    try:
        for doc in db["carry_forward_alerts"].find({"setup_type": {"$exists": True}}, {"_id": 0, "setup_type": 1, "created_at": 1}):
            st = (doc.get("setup_type") or "").strip()
            ts = doc.get("created_at")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    ts = None
            if isinstance(ts, datetime):
                counts[st] += 1
                cur_last = last_fired.get(st)
                if cur_last is None or ts > cur_last:
                    last_fired[st] = ts
    except Exception:
        pass

    # Apply
    for row in rows:
        name = row["setup"]
        row["last_fired_at"] = last_fired.get(name).isoformat() if last_fired.get(name) else None
        row["lifetime_fires"] = counts.get(name, 0)

    return rows


def render(rows: List[Dict[str, Any]]) -> None:
    rows_by_bucket: Dict[str, List[Dict[str, Any]]] = {b: [] for b in BUCKETS}
    for r in rows:
        rows_by_bucket.setdefault(r["bucket"], []).append(r)

    now = datetime.now(timezone.utc)
    print("=" * 96)
    print(f"  SENTCOM SETUP INVENTORY  ·  {now.isoformat(timespec='seconds')}")
    print("=" * 96)

    grand_total = 0
    for bucket in BUCKETS:
        items = sorted(rows_by_bucket.get(bucket, []), key=lambda x: x["setup"])
        print()
        print(f"── {bucket.upper():<12} ── ({len(items)} setups)")
        if not items:
            print("    (no setups assigned to this bucket)")
            continue
        for r in items:
            last = r.get("last_fired_at") or "—"
            fires = r.get("lifetime_fires", 0)
            mark = "●" if r["config_enabled"] else "○"
            print(f"    {mark} {r['setup']:<30s}  dir={r['direction']:<5s}  cat={r['category']:<17s}  last={last[:19]:<19s}  fires={fires}")
        grand_total += len(items)

    print()
    print("=" * 96)
    print(f"TOTAL: {grand_total} setups across {len(BUCKETS)} buckets")
    print("Legend:  ●=config-enabled  ○=defined-but-disabled  last=last fired (UTC)  fires=lifetime bot_trades count")
    print("=" * 96)


def main() -> int:
    rows = build_static_inventory()
    rows = overlay_last_fired(rows)
    render(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
