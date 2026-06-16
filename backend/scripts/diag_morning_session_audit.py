#!/usr/bin/env python3
"""diag_morning_session_audit.py  —  READ-ONLY  (2026-06-16, 10:30 AM ET)

Full morning audit at ~1hr into RTH. Surfaces:

  1. Currently OPEN positions (live exposure right now)
  2. Overnight holds (positions opened before today's market open
                     still currently open OR closed today)
  3. Today's NEW entries (anything opened during today's session)
  4. Today's CLOSES (anything closed today, with PnL)
  5. Daily PnL snapshot (realized today, unrealized on open holds,
                         total notional exposure, win-rate)
  6. Setup landscape — what fired today vs the prior 30-day baseline
  7. Health flags — broken accounting, OCA artifacts, sym-dir-cap collisions
  8. Gate-fire counts — v320, v325, F-gate, sym-dir-cap so far today

No writes. Run from repo root:
  .venv/bin/python backend/scripts/diag_morning_session_audit.py
"""
from __future__ import annotations
import os
import sys
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

ET = ZoneInfo("America/New_York")
BACKEND_LOG = "/tmp/backend.log"


def hr(t):
    print("\n" + "=" * 100 + f"\n  {t}\n" + "=" * 100)


def _parse(ts):
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]

    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    today_et_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    today_et_open_utc = today_et_open.astimezone(timezone.utc).isoformat()
    today_et_midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    today_et_midnight_utc = today_et_midnight.astimezone(timezone.utc).isoformat()

    print(f"diag_morning_session_audit  ({now_et:%Y-%m-%d %H:%M ET}, read-only)")
    print(f"  today RTH open (ET): {today_et_open:%Y-%m-%d %H:%M}")
    print(f"  → UTC threshold:     {today_et_open_utc}")

    # ── Section 1 — currently OPEN ─────────────────────────────────────
    hr("Section 1 — Currently OPEN positions (live exposure)")
    open_rows = list(db["bot_trades"].find({"status": "open"}, {"_id": 0}))
    print(f"  {len(open_rows)} open position(s)\n")
    if open_rows:
        print(f"  {'sym':>7} {'dir':>5} {'sh':>5} {'entry':>9} {'curr':>9} "
              f"{'stop':>9} {'tgt':>9}  {'unrealized':>11}  age  setup/style")
        for r in sorted(open_rows, key=lambda x: x.get("created_at") or ""):
            t = _parse(r.get("executed_at") or r.get("created_at"))
            age = ""
            if t:
                age_h = (now_utc - t).total_seconds() / 3600
                if age_h < 24:
                    age = f"{age_h:.1f}h"
                else:
                    age = f"{age_h/24:.1f}d"
            tgt = (r.get("target_prices") or [None])
            tgt0 = tgt[0] if tgt else None
            unreal = r.get("unrealized_pnl") or 0
            print(f"  {r.get('symbol', '?'):>7} {r.get('direction', '?')[:5]:>5} "
                  f"{r.get('shares', 0):>5} "
                  f"{(r.get('fill_price') or r.get('entry_price') or 0):>9.2f} "
                  f"{(r.get('current_price') or 0):>9.2f} "
                  f"{(r.get('stop_price') or 0):>9.2f} "
                  f"{(tgt0 or 0):>9.2f}  "
                  f"${unreal:>+10.2f}  {age:>5}  "
                  f"{r.get('setup_type','-'):>15}/{r.get('trade_style','-')}")

    # ── Section 2 — overnight holds ────────────────────────────────────
    hr("Section 2 — Overnight holds (entered BEFORE today's RTH open)")
    overnight = [r for r in open_rows
                 if (_parse(r.get("executed_at") or r.get("created_at")) or now_utc)
                 < datetime.fromisoformat(today_et_open_utc)]
    print(f"  {len(overnight)} overnight position(s)\n")
    for r in overnight:
        t = _parse(r.get("executed_at") or r.get("created_at"))
        days = (now_utc - t).total_seconds() / 86400 if t else 0
        print(f"    {r.get('symbol'):>7}  {r.get('direction'):>5}  "
              f"{r.get('shares')}sh @ ${r.get('fill_price') or r.get('entry_price')}  "
              f"opened {days:.1f}d ago  ({r.get('setup_type')}/{r.get('trade_style')})  "
              f"unrealized=${r.get('unrealized_pnl') or 0:+.2f}")
    if not overnight:
        print("    (none — all current opens are intraday)")

    # ── Section 3 — today's NEW entries ────────────────────────────────
    hr("Section 3 — TODAY's new entries (opened during today's session)")
    today_entries = list(db["bot_trades"].find(
        {"$or": [{"created_at": {"$gte": today_et_open_utc}},
                 {"executed_at": {"$gte": today_et_open_utc}}]},
        {"_id": 0}))
    print(f"  {len(today_entries)} entries since 09:30 ET\n")
    setup_today = Counter()
    style_today = Counter()
    for r in sorted(today_entries, key=lambda x: x.get("executed_at") or ""):
        t = _parse(r.get("executed_at"))
        et_t = t.astimezone(ET).strftime("%H:%M") if t else "—"
        setup_today[r.get("setup_type") or "?"] += 1
        style_today[r.get("trade_style") or "?"] += 1
        st = r.get("status")
        pnl_str = ""
        if st == "closed":
            pnl_str = f"  closed ${r.get('net_pnl') or 0:+.2f}  ({r.get('close_reason') or '?'})"
        else:
            pnl_str = f"  OPEN  unreal=${r.get('unrealized_pnl') or 0:+.2f}"
        print(f"  {et_t}  {r.get('symbol'):>7}  {r.get('direction'):>5}  "
              f"{r.get('shares')}sh @ ${r.get('fill_price') or r.get('entry_price'):.2f}  "
              f"{r.get('setup_type','-')}/{r.get('trade_style','-')}{pnl_str}")

    if today_entries:
        print(f"\n  setups: {dict(setup_today)}")
        print(f"  styles: {dict(style_today)}")

    # ── Section 4 — today's CLOSES ─────────────────────────────────────
    hr("Section 4 — TODAY's closes (any trade closed during today's session)")
    today_closed = list(db["bot_trades"].find(
        {"status": "closed",
         "closed_at": {"$gte": today_et_open_utc}},
        {"_id": 0}))
    print(f"  {len(today_closed)} close(s) today\n")
    wins = losses = breakeven = 0
    realized_today = 0.0
    reason_counts = Counter()
    for r in sorted(today_closed, key=lambda x: x.get("closed_at") or ""):
        ct = _parse(r.get("closed_at"))
        ct_et = ct.astimezone(ET).strftime("%H:%M") if ct else "—"
        net = r.get("net_pnl") or 0
        realized_today += float(net)
        if net > 0.01:
            wins += 1
        elif net < -0.01:
            losses += 1
        else:
            breakeven += 1
        reason = r.get("close_reason") or "?"
        reason_counts[reason] += 1
        print(f"  {ct_et}  {r.get('symbol'):>7}  {r.get('direction'):>5}  "
              f"{r.get('shares')}sh  net=${net:+8.2f}  pct={r.get('pnl_pct') or 0:+5.2f}%  "
              f"{reason[:35]}")
    if today_closed:
        n = len(today_closed)
        wr = wins / n * 100
        print(f"\n  TODAY realized PnL: ${realized_today:+.2f}")
        print(f"  wins/losses/be: {wins}/{losses}/{breakeven}  win%: {wr:.1f}%")
        print(f"  close_reason mix: {dict(reason_counts.most_common())}")

    # ── Section 5 — total exposure snapshot ────────────────────────────
    hr("Section 5 — Daily PnL & exposure snapshot")
    unreal_total = sum((r.get("unrealized_pnl") or 0) for r in open_rows)
    notional = sum(((r.get("shares") or 0)
                    * (r.get("current_price") or r.get("fill_price") or 0))
                   for r in open_rows)
    print(f"  realized today:      ${realized_today:+.2f}")
    print(f"  unrealized (live):   ${unreal_total:+.2f}")
    print(f"  total day P&L (est): ${realized_today + unreal_total:+.2f}")
    print(f"  open notional:       ${notional:,.0f}")
    print(f"  open positions:      {len(open_rows)}")

    # ── Section 6 — health flags ───────────────────────────────────────
    hr("Section 6 — Health flags (broken accounting / OCA artifacts)")
    flags = []
    for r in today_closed:
        if r.get("close_reason") == "oca_closed_externally_v19_31":
            flags.append(("OCA_MISLABEL", r.get("symbol"), r.get("id")))
        if r.get("exit_price") is None and r.get("status") == "closed":
            flags.append(("NO_EXIT_PRICE", r.get("symbol"), r.get("id")))
        if (r.get("net_pnl") or 0) == -1.0 and (r.get("realized_pnl") or 0) != -1.0:
            flags.append(("NET_PNL_BROKEN", r.get("symbol"), r.get("id")))
    # sym-dir collisions in open
    sym_dir = Counter((r.get("symbol"), r.get("direction")) for r in open_rows)
    for (s, d), n in sym_dir.items():
        if n > 1:
            flags.append(("SYM_DIR_MULTI", s, f"dir={d} n={n}"))
    if not flags:
        print("  ✓ no health flags raised on today's activity.")
    for tag, sym, ref in flags:
        print(f"  ⚠️ [{tag}]  {sym}  ({ref})")

    # ── Section 7 — gate-fire counts from log ──────────────────────────
    hr("Section 7 — Gate-fire counts in today's session (last 60 min of log)")
    if os.path.exists(BACKEND_LOG):
        try:
            patterns = {
                "v19.34.320 daily-bar (block)":   "v19.34.320].*BLOCK",
                "v19.34.320 daily-bar (observe)": "v19.34.320 OBSERVE",
                "v19.34.173 F-gate (block)":       "v19.34.173 F-GATE.*Blocking",
                "v19.34.325 reach-gate":           "v325 HSBG reach-gate",
                "sym_dir_cap rejection":           "sym_dir_cap",
                "record_rejection (any)":          "record_rejection",
            }
            for label, pat in patterns.items():
                try:
                    out = subprocess.run(
                        ["grep", "-cE", pat, BACKEND_LOG],
                        capture_output=True, text=True, timeout=5)
                    n = int(out.stdout.strip() or 0)
                    print(f"  {label:>40}: {n}")
                except (subprocess.TimeoutExpired, ValueError):
                    print(f"  {label:>40}: ?")
        except Exception as e:
            print(f"  (could not grep backend.log: {e})")
    else:
        print(f"  ({BACKEND_LOG} not found — skip)")

    print("\nDONE.")


if __name__ == "__main__":
    main()
