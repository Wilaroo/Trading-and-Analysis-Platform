#!/usr/bin/env python3
"""
v321a — SETUP FIDELITY & OVER-FIRE RANKING (READ-ONLY)

Generalizes the v320z rubber_band methodology across EVERY setup at once so we
patch in PRIORITY order instead of guessing. For each setup_type in the window
it computes the same SMB-cheat-sheet-aware signals:

  • volume      : alerts + per (symbol,day) over-fire EXCESS vs a 2/day cap
                  (SMB scalps are "2 strikes & out"; one-and-done setups are
                  even stricter, so EXCESS is a conservative over-fire floor)
  • conviction  : tape-confirm %, priority ceiling, HIGH+ (auto-fire) %
  • quality     : RVOL median + % meeting the cheat-sheet RVOL≥5 bar
                  (parsed from `reasoning` when not a stored field)
  • clean-trend : % of longs fired in a DOWN regime / shorts in an UP regime
                  (cheat-sheet AVOID: "don't fade a cleanly trending market")
  • edge        : realized win% / mean R / sum pnl from bot_trades (auto-detect)

Output is TWO ranked tables:
  (A) by OVER-FIRE EXCESS%  — who floods the tape on a STATE not a TRIGGER
  (B) by realized EDGE      — who actually loses money

The 6 SMB cheat-sheet setups audited this session are flagged with ★.

NOTHING IS WRITTEN. live_alerts reads project {"_id": 0}; bot_trades read-only.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v321a_setup_fidelity.py            # 5 days
  .venv/bin/python backend/scripts/diag_v321a_setup_fidelity.py --days 10
"""
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

RVOL_QUALITY = 5.0
DAILY_CAP = 2
# session-audited SMB cheat-sheet setups (prefix match on setup_type)
SMB_AUDITED = ("rubber_band", "second_chance", "backside", "hitchhiker",
               "fashionably_late", "big_dog")

_RE_RVOL = re.compile(r"RVOL:\s*([0-9.]+)x")
RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
RANK_NAME = {0: "-", 1: "low", 2: "med", 3: "HIGH", 4: "CRIT"}


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=8000)[env["DB_NAME"]]


def _to_et(v):
    if isinstance(v, str) and len(v) >= 10:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(ET)
        except Exception:
            return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(ET)
    return None


def _pct(n, d):
    return f"{(100.0 * n / d):.0f}%" if d else "n/a"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _prio(a):
    return str(a.get("priority", "")).strip().lower()


def _rvol(a):
    v = _f(a.get("rvol"))
    if v is not None:
        return v
    r = a.get("reasoning")
    txt = " | ".join(map(str, r)) if isinstance(r, (list, tuple)) else str(r or "")
    m = _RE_RVOL.search(txt)
    return _f(m.group(1)) if m else None


def _is_smb(su):
    return any(su.startswith(p) for p in SMB_AUDITED)


def main():
    days = 5
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception:
            days = 5

    db = _load_db()
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"\n=== v321a SETUP FIDELITY & OVER-FIRE — trailing {days} day(s) "
          f"(since {start.strftime('%Y-%m-%d')} ET) ===\n")

    rows = defaultdict(list)
    total = 0
    for a in db.live_alerts.find({}, {"_id": 0}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if not (et and et >= start):
            continue
        a["_day"] = et.strftime("%Y-%m-%d")
        su = (a.get("setup_type") or "?").strip().lower()
        rows[su].append(a)
        total += 1

    if not total:
        print("No live_alerts in window. (try --days 1, or run intraday.)\n")
        return
    print(f"alerts in window: {total}   distinct setups: {len(rows)}\n")

    # ---- realized edge map from bot_trades (one pass, auto-detect schema) ----
    edge = {}  # setup -> (n, win%, meanR, sumpnl)
    try:
        bt = db["bot_trades"]
        sample = list(bt.find({}, {}).sort("created_at", -1).limit(3000))
        keys = Counter()
        for d in sample:
            keys.update(d.keys())
        sf = next((k for k in ("setup_type", "setup", "strategy", "pattern", "strategy_name")
                   if keys.get(k)), None)
        rf = next((k for k in ("r_multiple", "realized_r", "r", "pnl_r") if keys.get(k)), None)
        pf = next((k for k in ("realized_pnl", "pnl", "net_pnl", "pnl_after_fees", "gross_pnl")
                   if keys.get(k)), None)
        print(f"bot_trades schema → setup='{sf}' R='{rf}' pnl='{pf}'  (scanned {len(sample)})\n")
        agg = defaultdict(lambda: {"n": 0, "rs": [], "pn": []})
        if sf:
            for d in sample:
                su = str(d.get(sf, "")).strip().lower()
                if not su:
                    continue
                agg[su]["n"] += 1
                rv = _f(d.get(rf)) if rf else None
                if rv is not None:
                    agg[su]["rs"].append(rv)
                pv = _f(d.get(pf)) if pf else None
                if pv is not None:
                    agg[su]["pn"].append(pv)
            for su, v in agg.items():
                win = (sum(1 for x in v["rs"] if x > 0) / len(v["rs"]) * 100) if v["rs"] else None
                meanr = (sum(v["rs"]) / len(v["rs"])) if v["rs"] else None
                sump = sum(v["pn"]) if v["pn"] else None
                edge[su] = (v["n"], win, meanr, sump)
    except Exception as e:
        print(f"bot_trades probe skipped: {e}\n")

    def _edge_for(su):
        # match exact, else prefix (handles rubber_band_long vs rubber_band)
        if su in edge:
            return edge[su]
        for k, v in edge.items():
            if k.startswith(su) or su.startswith(k):
                return v
        return (0, None, None, None)

    # ---- per-setup metrics ----
    table = []
    for su, alist in rows.items():
        n = len(alist)
        tape = sum(1 for a in alist if a.get("tape_confirmation") is True)
        ceil = max((RANK.get(_prio(a), 0) for a in alist), default=0)
        hi = sum(1 for a in alist if _prio(a) in ("high", "critical"))
        rv = [_rvol(a) for a in alist]
        rv = [x for x in rv if x is not None]
        rv_med = sorted(rv)[len(rv) // 2] if rv else None
        rv_q = (sum(1 for x in rv if x >= RVOL_QUALITY) / len(rv) * 100) if rv else None
        # over-fire
        by_sd = Counter()
        for a in alist:
            by_sd[(a.get("symbol", "?"), a["_day"])] += 1
        excess = sum(c - DAILY_CAP for c in by_sd.values() if c > DAILY_CAP)
        excess_pct = 100.0 * excess / n if n else 0.0
        maxday = max(by_sd.values(), default=0)
        # clean-trend violation
        viol = 0
        for a in alist:
            d = (a.get("direction") or "").lower()
            reg = str(a.get("market_regime", "")).lower()
            if d == "long" and "down" in reg:
                viol += 1
            elif d == "short" and "up" in reg:
                viol += 1
        en, ewin, emeanr, epnl = _edge_for(su)
        table.append({
            "su": su, "n": n, "tape": tape, "ceil": ceil, "hi": hi,
            "rv_med": rv_med, "rv_q": rv_q, "excess": excess, "excess_pct": excess_pct,
            "maxday": maxday, "viol": viol,
            "en": en, "ewin": ewin, "emeanr": emeanr, "epnl": epnl,
        })

    def _fmt_edge(t):
        if not t["en"]:
            return "no trades"
        parts = [f"n={t['en']}"]
        if t["ewin"] is not None:
            parts.append(f"win={t['ewin']:.0f}%")
        if t["emeanr"] is not None:
            parts.append(f"R={t['emeanr']:+.2f}")
        if t["epnl"] is not None:
            parts.append(f"pnl={t['epnl']:+.0f}")
        return " ".join(parts)

    # ---- TABLE A: by over-fire excess% ----
    print("=" * 104)
    print("TABLE A — ranked by OVER-FIRE EXCESS% (alerts beyond a 2/day cap = STATE-not-TRIGGER signature)")
    print("=" * 104)
    print(f"  {'setup':<26} {'n':>4} {'exc%':>5} {'mx/d':>4} {'tape':>5} {'ceil':>5} "
          f"{'HI%':>4} {'rvMed':>5} {'rv≥5':>5} {'fade':>5}  edge")
    for t in sorted(table, key=lambda x: (-x["excess_pct"], -x["n"])):
        star = "★" if _is_smb(t["su"]) else " "
        rvm = f"{t['rv_med']:.1f}" if t["rv_med"] is not None else "-"
        rvq = f"{t['rv_q']:.0f}%" if t["rv_q"] is not None else "-"
        print(f"{star} {t['su']:<26} {t['n']:>4} {t['excess_pct']:>4.0f}% {t['maxday']:>4} "
              f"{_pct(t['tape'], t['n']):>5} {RANK_NAME[t['ceil']]:>5} "
              f"{_pct(t['hi'], t['n']):>4} {rvm:>5} {rvq:>5} {_pct(t['viol'], t['n']):>5}  {_fmt_edge(t)}")

    # ---- TABLE B: by realized edge (worst first) ----
    print("\n" + "=" * 104)
    print("TABLE B — ranked by realized EDGE (worst sum-pnl first; only setups with trades)")
    print("=" * 104)
    traded = [t for t in table if t["en"]]
    if not traded:
        print("  No setups have matching bot_trades in the scanned window.")
    else:
        print(f"  {'setup':<26} {'trades':>6} {'win%':>5} {'meanR':>6} {'sumPnl':>8} "
              f"{'alerts':>6} {'exc%':>5}")
        for t in sorted(traded, key=lambda x: (x["epnl"] if x["epnl"] is not None else 0)):
            star = "★" if _is_smb(t["su"]) else " "
            win = f"{t['ewin']:.0f}%" if t["ewin"] is not None else "-"
            mr = f"{t['emeanr']:+.2f}" if t["emeanr"] is not None else "-"
            pl = f"{t['epnl']:+.0f}" if t["epnl"] is not None else "-"
            print(f"{star} {t['su']:<26} {t['en']:>6} {win:>5} {mr:>6} {pl:>8} "
                  f"{t['n']:>6} {t['excess_pct']:>4.0f}%")

    print("\n=== READING THE RESULT ===")
    print("• TABLE A top rows = worst over-firers. High exc% + low rv≥5 + weak/negative edge")
    print("    ⇒ STATE-not-TRIGGER + loose quality. Fix = add a real break TRIGGER + daily")
    print("    cap + raise RVOL quality, in THIS order of priority.")
    print("• TABLE B negative sumPnl with many alerts = actively bleeding; promote a fix or")
    print("    consider suppression. (★ = SMB cheat-sheet setup audited this session.)")
    print("• Cross-reference: a setup that is BOTH high in TABLE A and negative in TABLE B is")
    print("    the highest-ROI patch target.\n")


if __name__ == "__main__":
    main()
