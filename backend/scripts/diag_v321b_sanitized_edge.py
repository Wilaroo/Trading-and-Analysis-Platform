#!/usr/bin/env python3
"""
v321b — SANITIZED EDGE × OVER-FIRE (READ-ONLY, last-2-weeks clean window)

Supersedes v321a's edge column, which used RAW realized_pnl across ALL eras
(the operator flagged months of garbage; only ~last 2 weeks are clean). This
diag reuses the codebase's CANONICAL sanitizer
(`trade_outcome_hygiene.classify_close`, the same funnel as
diag_sanitized_closed_trades.py) and restricts to a trailing clean window, then
joins per-setup SANITIZED edge (win% / avgR / medR via pnl÷risk_amount) with the
live_alerts OVER-FIRE signal so we rank patch targets on TRUSTWORTHY numbers.

Edge basis  : bot_trades status^closed → full sanitize_v2 funnel → window filter
              → R = net_pnl(or realized_pnl/pnl) ÷ risk_amount  (|R|>10 already
              dropped by the sanitizer).
Over-fire   : live_alerts in the same window → EXCESS over a 2/day cap, tape%,
              priority ceiling, HIGH+ (auto-fire) %.

NOTHING IS WRITTEN.

Usage (from repo root):
  .venv/bin/python backend/scripts/diag_v321b_sanitized_edge.py             # 14 days
  .venv/bin/python backend/scripts/diag_v321b_sanitized_edge.py --days 21
  .venv/bin/python backend/scripts/diag_v321b_sanitized_edge.py --days 14 --min 5
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

BOT_PROVENANCE = {"bot_fired", "bot", "", None}
ADMIN_CLOSE_PREFIXES = (
    "stale_pending", "phantom_sibling_purge", "consolidated", "broker_rejected",
    "execution_exception", "guardrail_veto", "intent_already_pending",
    "rejection_cooldown", "symbol_cooldown", "paper_phase", "simulation_phase",
    "operator_flatten_suppression", "emergency_flatten",
)
DAILY_CAP = 2
SMB_AUDITED = ("rubber_band", "second_chance", "backside", "hitchhiker",
               "fashionably_late", "big_dog")


def _find_backend():
    for cand in (Path.cwd() / "backend", Path(__file__).resolve().parents[1]):
        if (cand / "services" / "trade_outcome_hygiene.py").exists():
            return cand
    print("ERROR: cannot locate backend/ (run from repo root)"); sys.exit(1)


def _load_env(backend_dir):
    env = backend_dir / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _r_multiple(t):
    pnl = t.get("net_pnl")
    if pnl in (None, 0):
        pnl = t.get("realized_pnl") if t.get("realized_pnl") not in (None, 0) else t.get("pnl")
    risk = _f(t.get("risk_amount"))
    pnl = _f(pnl)
    if pnl is None or not risk:
        return None
    return pnl / risk


def _parse_ts(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hold_seconds(t):
    hs = _f(t.get("hold_seconds"))
    if hs is not None and hs > 0:
        return hs
    a, b = _parse_ts(t.get("executed_at")), _parse_ts(t.get("closed_at"))
    if a and b:
        return (b - a).total_seconds()
    return None


def _exclusion_reason(t, classify_close):
    if t.get("entered_by") not in BOT_PROVENANCE:
        return "provenance"
    ec = t.get("entry_context") or {}
    if t.get("learning_only") is True or ec.get("learning_only") is True:
        return "learning_only"
    if "[SIMULATED]" in (t.get("notes") or "") or t.get("trade_type") == "shadow":
        return "simulated"
    cr = str(t.get("close_reason") or "")
    if any(cr.startswith(p) for p in ADMIN_CLOSE_PREFIXES):
        return "admin_close"
    if "orphan" in cr.lower():
        return "legacy_orphan"
    genuine, _tag = classify_close(
        close_reason=cr, entered_by=str(t.get("entered_by") or ""),
        entry_price=_f(t.get("fill_price")) or _f(t.get("entry_price")),
        exit_price=_f(t.get("exit_price")), net_pnl=_f(t.get("net_pnl")),
        hold_seconds=_hold_seconds(t), setup_type=str(t.get("setup_type") or ""),
        direction=t.get("direction"), stop_price=_f(t.get("stop_price")),
        target_prices=t.get("target_prices"), realized_pnl=_f(t.get("realized_pnl")),
        shares=_f(t.get("shares")),
    )
    if not genuine:
        return "hygiene_artifact"
    fill = _f(t.get("fill_price")) or _f(t.get("entry_price")) or 0
    if fill <= 0 or (_f(t.get("shares")) or 0) <= 0:
        return "never_filled"
    if (_f(t.get("exit_price")) or 0) <= 0:
        return "no_exit_price"
    if (_f(t.get("risk_amount")) or 0) <= 0:
        return "no_risk"
    hs = _hold_seconds(t)
    if hs is not None and hs < 10:
        return "sub_10s_hold"
    r = _r_multiple(t)
    if r is not None and abs(r) > 10:
        return "absurd_r"
    return None


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


def _norm_setup(su):
    """collapse directional suffixes so rubber_band_long/short roll up."""
    su = (su or "?").strip().lower()
    for base in SMB_AUDITED:
        if su.startswith(base):
            return base
    return su


def main():
    days = 14
    min_n = 5
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except Exception:
            days = 14
    if "--min" in sys.argv:
        try:
            min_n = int(sys.argv[sys.argv.index("--min") + 1])
        except Exception:
            min_n = 5

    backend = _find_backend()
    _load_env(backend)
    sys.path.insert(0, str(backend))
    from services.trade_outcome_hygiene import classify_close
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"\n=== v321b SANITIZED EDGE × OVER-FIRE — trailing {days} day(s) "
          f"(since {start.strftime('%Y-%m-%d')} ET, min sanitized n={min_n}) ===\n")

    # ---- sanitized closed trades in window ----
    closed = list(db["bot_trades"].find(
        {"status": {"$regex": "^closed"}},
        {"_id": 0, "id": 1, "symbol": 1, "entered_by": 1, "learning_only": 1,
         "entry_context.learning_only": 1, "notes": 1, "trade_type": 1,
         "close_reason": 1, "fill_price": 1, "entry_price": 1, "exit_price": 1,
         "shares": 1, "risk_amount": 1, "net_pnl": 1, "realized_pnl": 1, "pnl": 1,
         "hold_seconds": 1, "executed_at": 1, "closed_at": 1, "created_at": 1,
         "setup_type": 1, "trade_style": 1, "direction": 1, "stop_price": 1,
         "target_prices": 1}))

    raw = len(closed)
    excl = Counter()
    core = []
    for t in closed:
        r = _exclusion_reason(t, classify_close)
        if r is None:
            et = _to_et(t.get("closed_at") or t.get("created_at"))
            if et and et >= start:
                core.append(t)
            else:
                excl["out_of_window"] += 1
        else:
            excl[r] += 1
    print(f"raw closed rows: {raw}   →   sanitized in-window CORE: {len(core)}")
    print("  funnel: " + ", ".join(f"{k}={v}" for k, v in excl.most_common()))

    edge = defaultdict(list)   # base setup -> [R, ...]
    for t in core:
        r = _r_multiple(t)
        if r is not None:
            edge[_norm_setup(t.get("setup_type"))].append(r)

    # ---- live_alerts over-fire in window ----
    al = defaultdict(list)
    for a in db.live_alerts.find({}, {"_id": 0}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if not (et and et >= start):
            continue
        a["_day"] = et.strftime("%Y-%m-%d")
        al[_norm_setup(a.get("setup_type"))].append(a)

    def _overfire(alist):
        n = len(alist)
        by_sd = Counter()
        for a in alist:
            by_sd[(a.get("symbol", "?"), a["_day"])] += 1
        excess = sum(c - DAILY_CAP for c in by_sd.values() if c > DAILY_CAP)
        tape = sum(1 for a in alist if a.get("tape_confirmation") is True)
        hi = sum(1 for a in alist if str(a.get("priority", "")).lower() in ("high", "critical"))
        return n, (100.0 * excess / n if n else 0.0), tape, hi

    # ---- combined table ----
    print("\n" + "=" * 100)
    print(f"SANITIZED EDGE (last {days}d) joined with alert OVER-FIRE  "
          f"[★ = SMB audited]   (edge shown only if n≥{min_n})")
    print("=" * 100)
    print(f"  {'setup':<24} {'sanN':>5} {'win%':>5} {'avgR':>6} {'medR':>6} "
          f"{'alerts':>6} {'exc%':>5} {'tape':>5} {'HI%':>4}")

    setups = set(edge) | set(al)
    table = []
    for su in setups:
        rs = edge.get(su, [])
        n_al, exc, tape, hi = _overfire(al.get(su, []))
        win = (100.0 * sum(1 for r in rs if r > 0) / len(rs)) if rs else None
        avgr = (sum(rs) / len(rs)) if rs else None
        medr = median(rs) if rs else None
        table.append((su, len(rs), win, avgr, medr, n_al, exc, tape, hi))

    # sort: worst avgR first among those with enough sample, then by alert volume
    def _key(row):
        su, sn, win, avgr, medr, n_al, exc, tape, hi = row
        has = sn >= min_n
        return (0 if has else 1, avgr if (has and avgr is not None) else 9e9, -n_al)

    for su, sn, win, avgr, medr, n_al, exc, tape, hi in sorted(table, key=_key):
        star = "★" if su in SMB_AUDITED else " "
        if sn >= min_n:
            w = f"{win:.0f}%"; ar = f"{avgr:+.2f}"; mr = f"{medr:+.2f}"
        else:
            w = ar = mr = "  -"   # sample too small to trust edge
        print(f"{star} {su:<24} {sn:>5} {w:>5} {ar:>6} {mr:>6} "
              f"{n_al:>6} {exc:>4.0f}% {_pct(tape, n_al):>5} {_pct(hi, n_al):>4}")

    # ---- focused SMB rollup ----
    print("\n" + "=" * 100)
    print("SMB CHEAT-SHEET SETUPS — sanitized edge focus")
    print("=" * 100)
    for su in SMB_AUDITED:
        rs = edge.get(su, [])
        n_al, exc, tape, hi = _overfire(al.get(su, []))
        if rs:
            win = 100.0 * sum(1 for r in rs if r > 0) / len(rs)
            print(f"  ★ {su:<20} sanN={len(rs):>3}  win={win:>4.0f}%  "
                  f"avgR={sum(rs) / len(rs):+.2f}  medR={median(rs):+.2f}  "
                  f"| alerts={n_al} exc%={exc:.0f} tape={_pct(tape, n_al)} HI%={_pct(hi, n_al)}")
        else:
            print(f"  ★ {su:<20} sanN=  0  (no sanitized trades in window)  "
                  f"| alerts={n_al} exc%={exc:.0f} tape={_pct(tape, n_al)} HI%={_pct(hi, n_al)}")

    print("\n=== READING THE RESULT ===")
    print(f"• Edge columns are now TRUSTWORTHY: sanitized core only, last {days}d, R=pnl÷risk.")
    print(f"• avgR shown only when sanN≥{min_n}; '-' means too few clean trades to judge edge")
    print("    (a setup can over-fire on alerts yet have ZERO clean trades → unproven, not bad).")
    print("• Patch priority = negative avgR AND (high alert volume or high HI% auto-fire).")
    print("• An SMB setup with sanN=0 but many alerts = we ALERT but rarely TRADE it → the")
    print("    'find it / fire it / trade it' gap (e.g. rubber_band) — a detection problem,")
    print("    not an edge problem.\n")


if __name__ == "__main__":
    main()
