#!/usr/bin/env python3
"""
v320n — TRADE-MIX DIAGNOSTIC (READ-ONLY): why "too many multi-day, not enough scalp/intraday".

Answers, from live Mongo, WHERE the intraday/scalp frequency is actually lost:

  1. OPEN BOOK COMPOSITION — current status="open" bot_trades by trade_style,
     split INTRADAY_GROUP (scalp+intraday) vs CARRY_GROUP (multi_day/swing/
     position/investment). Shows how many of the position-cap slots are already
     consumed by overnight carries BEFORE today's scalps can enter.
  2. POSITION CAP + HEADROOM — effective max_open_positions vs slots used.
  3. TODAY'S FILLS by trade_style + setup_type, with first-fill hour-of-day (ET).
  4. ALERTS TODAY by trade_style (generation funnel — are scalps even detected?).
  5. TRADE-DROPS TODAY by gate x style (are scalp alerts blocked, and where?).

NOTHING is written. Safe to run anytime.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v320n_trade_mix.py [YYYY-MM-DD]   # default = today ET
"""
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

INTRADAY_STYLES = {"scalp", "intraday"}
CARRY_STYLES = {"multi_day", "swing", "position", "investment"}


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _day_bounds(date_str):
    d = (datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ET)
         if date_str else datetime.now(ET))
    s = d.replace(hour=0, minute=0, second=0, microsecond=0)
    e = s.replace(hour=23, minute=59, second=59, microsecond=999000)
    return s, e, s.strftime("%Y-%m-%d")


def _to_et(row):
    """Best-effort entry timestamp -> ET datetime, or None."""
    for k in ("executed_at", "created_at", "pre_submit_at", "entry_time"):
        v = row.get(k)
        if isinstance(v, str) and len(v) >= 10:
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(ET)
            except Exception:
                pass
        if isinstance(v, datetime):
            dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            return dt.astimezone(ET)
    ms = row.get("entry_time_ms")
    if isinstance(ms, (int, float)) and ms > 0:
        try:
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).astimezone(ET)
        except Exception:
            return None
    return None


def _grp(style):
    s = (style or "").strip().lower()
    if s in INTRADAY_STYLES:
        return "INTRADAY"
    if s in CARRY_STYLES:
        return "CARRY"
    return "OTHER"


def _bar(n, total, width=30):
    if total <= 0:
        return ""
    fill = int(round(width * n / total))
    return "█" * fill + "·" * (width - fill)


def main():
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    db = _load_db()
    start_et, end_et, day = _day_bounds(date_arg)
    print(f"\n=== v320n TRADE-MIX DIAGNOSTIC — {day} ET ===\n")

    # ── 1+2. OPEN BOOK + CAP ──────────────────────────────────────────
    opens = list(db.bot_trades.find({"status": "open"}, {"_id": 0}))
    by_style = Counter()
    by_group = Counter()
    bot_fired = Counter()
    for t in opens:
        st = (t.get("trade_style") or "?").strip().lower()
        by_style[st] += 1
        by_group[_grp(st)] += 1
        if (t.get("entered_by") or "") == "bot_fired":
            bot_fired[_grp(st)] += 1

    # effective cap
    cap = None
    try:
        bs = db.bot_state.find_one({}, {"_id": 0}) or {}
        rp = bs.get("risk_params") or bs.get("risk_parameters") or {}
        cap = rp.get("max_open_positions") or bs.get("max_open_positions")
    except Exception:
        pass

    print("1) OPEN BOOK COMPOSITION (status=open)")
    print(f"   total open: {len(opens)}   "
          f"INTRADAY={by_group['INTRADAY']}  CARRY={by_group['CARRY']}  OTHER={by_group['OTHER']}")
    for st, n in by_style.most_common():
        print(f"     {st:<14} {n:>3}   ({_grp(st)})")
    print()
    print("2) POSITION CAP + HEADROOM")
    if cap:
        used = len(opens)
        print(f"   max_open_positions = {cap}   used = {used}   headroom = {cap - used}")
        carry = by_group["CARRY"]
        print(f"   CARRY slots consumed = {carry}  -> "
              f"{(100.0*carry/cap):.0f}% of the cap is overnight carry before today's scalps")
        if cap and (cap - used) <= max(2, int(0.15 * cap)):
            print("   ⚠️  BOOK NEAR-FULL: new intraday/scalp entries will be cap-blocked.")
    else:
        print("   (could not resolve max_open_positions from bot_state)")
    print()

    # ── 3. TODAY'S FILLS ──────────────────────────────────────────────
    fills = []
    for t in db.bot_trades.find({}, {"_id": 0}):
        et = _to_et(t)
        if et and start_et <= et <= end_et:
            fills.append((et, t))
    print(f"3) TODAY'S FILLS — {len(fills)} bot_trades entered {day} ET")
    style_ct = Counter()
    group_ct = Counter()
    setup_ct = Counter()
    hour_grp = defaultdict(Counter)
    for et, t in fills:
        st = (t.get("trade_style") or "?").strip().lower()
        style_ct[st] += 1
        g = _grp(st)
        group_ct[g] += 1
        setup_ct[(st, t.get("setup_type") or "?")] += 1
        hour_grp[et.hour][g] += 1
    print(f"   by group:  INTRADAY={group_ct['INTRADAY']}  CARRY={group_ct['CARRY']}  OTHER={group_ct['OTHER']}")
    for st, n in style_ct.most_common():
        print(f"     {st:<14} {n:>3}   ({_grp(st)})")
    if setup_ct:
        print("   top (style, setup_type):")
        for (st, su), n in setup_ct.most_common(12):
            print(f"     {st:<12} {su:<24} {n:>3}")
    if hour_grp:
        print("   entry hour-of-day (ET)  [I=intraday C=carry O=other]:")
        for h in sorted(hour_grp):
            c = hour_grp[h]
            print(f"     {h:02d}:00  I={c['INTRADAY']:<3} C={c['CARRY']:<3} O={c['OTHER']:<3}")
    print()

    # ── 4. ALERTS TODAY by style (generation) ─────────────────────────
    print("4) ALERTS GENERATED TODAY by trade_style")
    alert_style = Counter()
    alert_total = 0
    for coll in ("live_alerts", "alerts"):
        try:
            cur = db[coll].find({}, {"_id": 0, "trade_style": 1, "created_at": 1,
                                     "timestamp": 1, "ts": 1})
        except Exception:
            continue
        for a in cur:
            et = _to_et({"created_at": a.get("created_at") or a.get("timestamp") or a.get("ts")})
            if et and start_et <= et <= end_et:
                alert_style[(a.get("trade_style") or "?").strip().lower()] += 1
                alert_total += 1
        if alert_total:
            print(f"   source={coll}  total={alert_total}")
            break
    for st, n in alert_style.most_common():
        print(f"     {st:<14} {n:>4}  {_bar(n, alert_total)}  ({_grp(st)})")
    if not alert_total:
        print("   (no alerts found today in live_alerts/alerts with a parseable timestamp)")
    print()

    # ── 5. TRADE-DROPS TODAY by gate x style ──────────────────────────
    print("5) TRADE-DROPS TODAY by gate (blocked entries)")
    gate_ct = Counter()
    gate_style = defaultdict(Counter)
    drop_total = 0
    try:
        for d in db.trade_drops.find({}, {"_id": 0}):
            et = _to_et({"created_at": d.get("ts") or d.get("created_at") or d.get("timestamp")})
            if not (et and start_et <= et <= end_et):
                continue
            drop_total += 1
            gate = d.get("gate") or d.get("first_killing_gate") or "?"
            ctx = d.get("context") or d.get("alert") or {}
            st = (ctx.get("trade_style") or d.get("trade_style") or "?").strip().lower()
            gate_ct[gate] += 1
            gate_style[gate][_grp(st)] += 1
    except Exception as e:
        print(f"   (trade_drops read failed: {e})")
    print(f"   total drops today: {drop_total}")
    for gate, n in gate_ct.most_common(15):
        g = gate_style[gate]
        print(f"     {gate:<32} {n:>4}   I={g['INTRADAY']} C={g['CARRY']} O={g['OTHER']}")
    print()

    # ── VERDICT HINTS ─────────────────────────────────────────────────
    print("=== READING THE RESULT ===")
    print("• If §2 shows CARRY consuming most of the cap and headroom ~0  ->")
    print("    the book is full of overnight swings; scalps are CAP-BLOCKED.")
    print("    Lever: reserve N slots for intraday, or cap concurrent carries.")
    print("• If §4 shows few scalp/intraday alerts -> detection/universe problem")
    print("    (scalps not even surfacing), not a sizing problem.")
    print("• If §4 has many scalp alerts but §5 shows scalp drops on a specific")
    print("    gate (confidence/EV/in_play/liquidity) -> that gate is the choke.")
    print()


if __name__ == "__main__":
    main()
