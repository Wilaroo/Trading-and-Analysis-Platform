#!/usr/bin/env python3
"""
diag_eod_pusher.py — EVIDENCE probe for the two 15:45 ET mysteries
====================================================================
Operator reports (2026-06-12):
  A. "EOD close sequence still closes every position regardless of
     trade style or time horizon."
  B. "IB pusher seems to go dead right around 3:45-3:50pm every day."

Both windows coincide with the bot's RegT machinery, all anchored at
15:45 ET since v19.34.154:
  15:35  soft entry cut (warn-only)
  15:45  HARD entry cut ("flatten-only mode" — answer to 'safety guard?')
  15:45  EOD close pass fires (mass parallel MKT closes)
  15:45+ naked-flatten guard polls ib_direct every 20s
  15:47  T-2 force-MKT escalation     15:48  T-1 operator alert
  15:56  v302 force-flatten of bracketed sweep-misses
  16:10  EOD grading

This probe mines the DB for hard evidence (READ-ONLY):
  1. EOD close style audit — every close 15:30-16:10 ET (last 10
     sessions) grouped by close reason × trade_style → shows exactly
     which styles each EOD path flattened (the smoking gun for A: the
     naked-flatten guard was reading the broken close_at_eod ATTRIBUTE
     instead of the v245 policy — fixed in v332).
  2. state_integrity_events in the window (eod_naked_flatten,
     eod_v302_force_flatten, naked_overnight_hold).
  3. Pusher liveness timeline — per-minute write counts into
     ib_historical_data (collected_at) 15:30-16:10 ET per session →
     shows WHEN data stops and whether it's a hard stop at 15:45
     (backend-coupled) or a gradual decay (load).
  4. eod_heartbeat thoughts (scheduler visibility).
  5. historical_data_requests completion gaps in the window.

Run from repo root:  .venv/bin/python /tmp/diag_eod_pusher.py
For LIVE confirmation also run scripts/watch_pusher_eod.py 3:40-4:05pm.
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def find_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / "backend" / "services" / "position_manager.py").exists():
            return cand
    print("FATAL: run from repo root")
    sys.exit(1)


def load_env(root: Path) -> None:
    p = root / "backend" / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def parse_ts(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def hr(t):
    print("\n" + "=" * 74 + f"\n  {t}\n" + "=" * 74)


def main():
    print(f"diag_eod_pusher — {datetime.now(ET):%Y-%m-%d %H:%M ET}  (read-only)")
    root = find_root()
    load_env(root)
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    now_utc = datetime.now(timezone.utc)
    since_10d = (now_utc - timedelta(days=14)).isoformat()

    # ── 1. EOD close style audit ─────────────────────────────────────────
    hr("1. CLOSES 15:30-16:10 ET, last 14 calendar days — reason × style")
    audit = Counter()
    rows = []
    for doc in db["bot_trades"].find(
        {"closed_at": {"$ne": None, "$gte": since_10d}},
        {"_id": 0, "symbol": 1, "closed_at": 1, "close_reason": 1,
         "exit_reason": 1, "reason": 1, "trade_style": 1, "setup_type": 1,
         "close_at_eod": 1, "pnl": 1},
    ):
        ts = parse_ts(doc.get("closed_at"))
        if not ts:
            continue
        ts_et = ts.astimezone(ET)
        mins = ts_et.hour * 60 + ts_et.minute
        if not (15 * 60 + 30 <= mins <= 16 * 60 + 10):
            continue
        reason = (doc.get("close_reason") or doc.get("exit_reason")
                  or doc.get("reason") or "?")
        style = doc.get("trade_style") or "?"
        audit[(str(reason), str(style))] += 1
        if any(k in str(reason).lower() for k in ("eod", "naked", "force")):
            rows.append((ts_et, doc.get("symbol"), reason, style,
                         doc.get("setup_type"), doc.get("close_at_eod"),
                         doc.get("pnl")))
    if not audit:
        print("   (no closes found in the window — check field names/dates)")
    for (reason, style), n in sorted(audit.items(), key=lambda x: -x[1]):
        flag = ""
        if style in ("swing", "multi_day", "position", "investment") and \
                any(k in reason.lower() for k in ("eod", "naked", "force")):
            flag = "   <<< LONG-HORIZON STYLE FLATTENED BY EOD PATH"
        print(f"   {n:4d}×  {reason:32s} style={style}{flag}")
    if rows:
        print("\n   EOD-path closes (detail, most recent 25):")
        for ts_et, sym, reason, style, setup, cae, pnl in sorted(rows)[-25:]:
            print(f"     {ts_et:%m-%d %H:%M} {sym:6s} {reason:28s} "
                  f"style={style:10s} setup={setup} close_at_eod_attr={cae} "
                  f"pnl={pnl}")

    # ── 2. state_integrity_events in the window ──────────────────────────
    hr("2. state_integrity_events (eod/naked/force), last 14 days")
    ev = Counter()
    for doc in db["state_integrity_events"].find(
        {"ts": {"$gte": since_10d}},
        {"_id": 0, "event": 1, "symbol": 1, "ts": 1, "kind": 1},
    ):
        e = str(doc.get("event") or "")
        if any(k in e for k in ("eod", "naked", "force")):
            ts = parse_ts(doc.get("ts"))
            day = ts.astimezone(ET).strftime("%m-%d") if ts else "?"
            ev[(day, e, str(doc.get("kind") or ""))] += 1
    if not ev:
        print("   (none)")
    for (day, e, kind), n in sorted(ev.items()):
        print(f"   {day}  {n:3d}× {e} {('['+kind+']') if kind else ''}")

    # ── 3. Pusher liveness timeline (per-minute ingest) ──────────────────
    hr("3. ib_historical_data ingest per minute, 15:30-16:10 ET (last 5 sessions)")
    per_day_minute = defaultdict(Counter)
    cutoff = (now_utc - timedelta(days=8)).isoformat()
    for doc in db["ib_historical_data"].find(
        {"collected_at": {"$gte": cutoff}},
        {"_id": 0, "collected_at": 1},
    ):
        ts = parse_ts(doc.get("collected_at"))
        if not ts:
            continue
        ts_et = ts.astimezone(ET)
        if ts_et.weekday() >= 5:
            continue
        mins = ts_et.hour * 60 + ts_et.minute
        if 15 * 60 + 30 <= mins <= 16 * 60 + 10:
            per_day_minute[ts_et.strftime("%m-%d")][ts_et.strftime("%H:%M")] += 1
    if not per_day_minute:
        print("   (no ingest rows in window)")
    for day in sorted(per_day_minute)[-5:]:
        cnts = per_day_minute[day]
        line = f"   {day}: "
        dead_from = None
        for m in range(15 * 60 + 30, 16 * 60 + 11):
            key = f"{m // 60:02d}:{m % 60:02d}"
            n = cnts.get(key, 0)
            ch = "█" if n >= 20 else ("▓" if n >= 5 else ("░" if n >= 1 else "·"))
            line += ch
            if n == 0 and dead_from is None and m <= 16 * 60:
                dead_from = key
            elif n > 0:
                dead_from = None
        total = sum(cnts.values())
        line += f"  (total {total}"
        if dead_from:
            line += f", DEAD from {dead_from}"
        line += ")"
        print(line)
    print("   legend: █ ≥20/min  ▓ ≥5  ░ ≥1  · zero   (15:30 → 16:10)")

    # ── 4. eod_heartbeat thoughts ─────────────────────────────────────────
    hr("4. eod_heartbeat thoughts (last 3 sessions)")
    hb = list(db["sentcom_thoughts"].find(
        {"category": "eod_heartbeat"},
        {"_id": 0, "content": 1, "timestamp": 1},
    ).sort("timestamp", -1).limit(36))
    if not hb:
        print("   (none)")
    for doc in reversed(hb[:18]):
        print(f"   {str(doc.get('content'))[:110]}")

    # ── 5. queue completion gaps in the window ────────────────────────────
    hr("5. historical_data_requests completed per minute, 15:30-16:10 ET (5 sessions)")
    q = defaultdict(Counter)
    for doc in db["historical_data_requests"].find(
        {"completed_at": {"$gte": cutoff}},
        {"_id": 0, "completed_at": 1},
    ):
        ts = parse_ts(doc.get("completed_at"))
        if not ts:
            continue
        ts_et = ts.astimezone(ET)
        mins = ts_et.hour * 60 + ts_et.minute
        if 15 * 60 + 30 <= mins <= 16 * 60 + 10 and ts_et.weekday() < 5:
            q[ts_et.strftime("%m-%d")][ts_et.strftime("%H:%M")] += 1
    if not q:
        print("   (no completions in window — pusher idle or queue empty)")
    for day in sorted(q)[-5:]:
        total = sum(q[day].values())
        first = min(q[day]); last = max(q[day])
        print(f"   {day}: {total} completions, window {first}-{last}")

    print("\ndone (read-only). For live confirmation Monday: run "
          "scripts/watch_pusher_eod.py from ~15:40 ET.")


if __name__ == "__main__":
    main()
