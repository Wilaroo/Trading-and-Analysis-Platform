#!/usr/bin/env python3
"""
v338 — EOD-FLATTEN ENFORCEMENT AUDIT for intraday / short fades (READ-ONLY)

Part A root-cause diag. v334 proved the catastrophic tail (WTI/USO short fades)
came from intraday/short-fade trades that RODE OVERNIGHT (USO held 1434m ≈ 24h),
then a gap blew the GTC market-stop far past trigger. v336 prevents ENTRY of that
profile; Part A must ensure any intraday/fade that DOES open is reliably
EOD-flattened so it never holds overnight.

This diag answers, on GENUINE bot-own CLOSED trades (classify_close + is_adopted_entry):
  1. Which genuine trades HELD OVERNIGHT (entry ET-date != exit ET-date)?
  2. For each, what does the AUTHORITATIVE policy say —
       order_policy_registry.should_close_at_eod(trade)  (v19.34.245 path,
       which resolves trade_2_hold through the canonical classifier)?
  3. THE BUG SURFACE: trades where should_close_at_eod == True (policy: flatten
     at EOD) but they STILL held overnight → they slipped past the Journey-3
     EOD path. Bucketed by setup_type / trade_style / close_reason / direction.
  4. ENTANGLEMENT CHECK (Issue-3): how many of those overnight-leak trades carry
     the legacy default trade_style 'trade_2_hold', and how does the canonical
     classifier RE-RESOLVE them (does it now correctly say close_at_eod, i.e.
     the v245 fix already covers them, or do they resolve to a HOLD style)?

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v338_eod_flatten_audit.py --days 120
"""
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _g(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _dt(v):
    """Parse a stored timestamp → tz-aware UTC datetime (or None)."""
    if v is None or v == "":
        return None
    # epoch ms / s
    try:
        f = float(v)
        if f > 1e12:
            f /= 1000.0
        if f > 1e8:
            return datetime.fromtimestamp(f, tz=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _et_date(dt):
    if dt is None:
        return None
    return (dt.astimezone(_ET) if _ET else dt).date()


def main():
    days = _arg("--days", 120, int)
    sys.path.insert(0, "backend")
    since = datetime.now(timezone.utc).timestamp() - days * 86400

    db = _load_db()

    try:
        from services.trade_outcome_hygiene import classify_close, is_adopted_entry
    except Exception as e:
        print(f"FATAL: cannot import trade_outcome_hygiene: {e}")
        return
    try:
        from services.order_policy_registry import should_close_at_eod, get_policy_for_trade
        have_policy = True
    except Exception as e:
        print(f"WARN: order_policy_registry unavailable ({e}); policy columns skipped")
        have_policy = False
    try:
        from services.trade_style_classifier import resolve_trade_style
    except Exception:
        resolve_trade_style = None

    print(f"\n=== v338 EOD-FLATTEN ENFORCEMENT AUDIT — last {days}d (genuine bot-own closed) ===")

    n_seen = n_genuine = n_overnight = 0
    leak_rows = []                       # should_close_at_eod==True but held overnight
    held_ok_style = Counter()            # overnight + policy says HOLD (correct)
    leak_setup = Counter()
    leak_style = Counter()
    leak_close_reason = Counter()
    leak_dir = Counter()
    leak_style2_resolved = Counter()     # canonical re-resolution of leak trades
    overnight_by_style = Counter()

    for t in db.bot_trades.find({"status": "closed"}, {"_id": 0}):
        n_seen += 1
        entry_dt = _dt(_g(t, "executed_at", "created_at", "entry_time", "entry_time_ms", "opened_at"))
        exit_dt = _dt(_g(t, "closed_at", "exit_time", "closed_at_ms"))
        if entry_dt is None or entry_dt.timestamp() < since:
            continue
        cr = str(_g(t, "close_reason", "exit_reason") or "")
        eb = str(_g(t, "entered_by") or "")
        st = str(_g(t, "setup_type", "setup") or "")
        try:
            ok, _reason = classify_close(
                close_reason=cr, entered_by=eb,
                entry_price=None, exit_price=None,
                net_pnl=None, hold_seconds=None, setup_type=st)
        except Exception:
            ok = True
        if not ok:
            continue
        try:
            if is_adopted_entry(entered_by=eb, source=str(_g(t, "source") or ""), close_reason=cr):
                continue
        except Exception:
            pass
        n_genuine += 1

        if exit_dt is None:
            continue
        ed, xd = _et_date(entry_dt), _et_date(exit_dt)
        if ed is None or xd is None or xd <= ed:
            continue  # same-day (intraday) — fine
        n_overnight += 1
        style = str(_g(t, "trade_style") or "(none)")
        overnight_by_style[style] += 1

        # authoritative policy
        flatten = None
        if have_policy:
            try:
                flatten = should_close_at_eod(t)
            except Exception:
                flatten = None

        if flatten is True:
            # LEAK: policy said flatten at EOD, but it held overnight
            side = str(_g(t, "side", "direction") or "?").lower()
            leak_setup[st or "(none)"] += 1
            leak_style[style] += 1
            leak_close_reason[cr or "(none)"] += 1
            leak_dir[side] += 1
            if resolve_trade_style is not None:
                try:
                    rs = resolve_trade_style({
                        "trade_style": _g(t, "trade_style"),
                        "setup_type": st,
                        "setup_variant": _g(t, "setup_variant"),
                        "timeframe": _g(t, "timeframe"),
                    })
                    leak_style2_resolved[str(rs)] += 1
                except Exception:
                    pass
            if len(leak_rows) < 20:
                hold_h = (exit_dt - entry_dt).total_seconds() / 3600.0
                leak_rows.append(
                    f"  {str(_g(t,'symbol') or '?'):<6} {side:<5} {st:<22} "
                    f"style={style:<14} cr={cr:<22} held={hold_h:6.1f}h "
                    f"R={_g(t,'realized_r','r_multiple','r') or '?'} "
                    f"pnl={_g(t,'net_pnl','realized_pnl','pnl') or '?'}")
        elif flatten is False:
            held_ok_style[style] += 1

    print(f"\nclosed seen(in-window genuine)={n_genuine}  overnight-held={n_overnight}")
    print("\novernight holds by trade_style:", dict(overnight_by_style.most_common(15)))

    print(f"\n=== 🔴 LEAK SURFACE — policy=should_close_at_eod(True) BUT held overnight: "
          f"{sum(leak_setup.values())} ===")
    print(" by setup_type:", dict(leak_setup.most_common(15)))
    print(" by trade_style:", dict(leak_style.most_common(15)))
    print(" by direction:", dict(leak_dir))
    print(" by close_reason:", dict(leak_close_reason.most_common(12)))
    if leak_style2_resolved:
        print(" canonical resolve_trade_style of LEAK rows:", dict(leak_style2_resolved.most_common()))
    print("\n sample leak rows (<=20):")
    for r in leak_rows:
        print(r)

    print(f"\n=== ✅ overnight holds where policy=HOLD (correct, NOT a leak): "
          f"{sum(held_ok_style.values())} ===")
    print(" by trade_style:", dict(held_ok_style.most_common(15)))

    print("\n=== READING ===")
    print("• LEAK SURFACE > 0 → genuine intraday/scalp trades (close_at_eod=True) are riding")
    print("  overnight → Journey-3 EOD enforcement is missing them. Bucket by close_reason:")
    print("    - 'stop_loss'/'eod_*' absent & generic close → never reached EOD branch (the gap).")
    print("• If leak trade_style dominated by 'trade_2_hold' AND canonical re-resolve still")
    print("  yields an intraday/scalp style → Issue-3 classifier default IS the cause; the v245")
    print("  policy path should have flattened them → trace WHY check_eod_close skipped them.")
    print("• If canonical re-resolve yields HOLD styles (multi_day/swing) → those are NOT leaks;")
    print("  they're correctly held (the should_close_at_eod read on stored style was stale).\n")


if __name__ == "__main__":
    main()
