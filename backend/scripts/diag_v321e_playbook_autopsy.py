#!/usr/bin/env python3
"""
v321e — PLAYBOOK-WIDE TRADE AUTOPSY (READ-ONLY)

Runs the v321d alert→trade→sanitization autopsy across EVERY setup at once and
auto-classifies WHERE each one breaks, so the operator gets the whole-playbook
findings in a single table. Two Mongo passes only (live_alerts + bot_trades),
aggregated in Python.

Per setup (directional _long/_short variants merged — footnoted):
  • alerts / HIGH+%        — find + fire-capability (live_alerts, window)
  • trades / exec%         — did alerts become trades? (bot_trades, window)
  • closed / sanitized     — canonical classify_close funnel on closed trades
  • top death reason       — dominant sanitization exclusion bucket
  • edge (win%/avgR)        — survivors, shown only at n≥5
  • VERDICT                — auto-classified failure mode:
       GATE-never-exec   alerts≥20 but exec%<5   (blocked upstream: tape/EV/cap)
       MGMT-mangled      trades>0, closed>0, sanitized≈0, death=hygiene/no_exit/sub10s
       SHADOW            death dominated by simulated/learning_only (mode, not bug)
       EDGE-negative     sanitized≥5 and avgR<0
       CLEAN+EV          sanitized≥5 and avgR≥0
       low-sample        not enough to judge

NOTHING IS WRITTEN.

Usage (repo root):
  .venv/bin/python backend/scripts/diag_v321e_playbook_autopsy.py            # 14d
  .venv/bin/python backend/scripts/diag_v321e_playbook_autopsy.py --days 21
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
SMB_AUDITED = {"rubber_band", "second_chance", "backside", "hitchhiker",
               "fashionably_late", "big_dog", "off_sides"}


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


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


def _norm(su):
    su = (su or "?").strip().lower()
    for suf in ("_long", "_short"):
        if su.endswith(suf):
            return su[: -len(suf)]
    return su


def main():
    days = _arg("--days", 14, int)
    backend = _find_backend()
    _load_env(backend)
    sys.path.insert(0, str(backend))
    from services.trade_outcome_hygiene import classify_close
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"\n=== v321e PLAYBOOK-WIDE TRADE AUTOPSY — trailing {days}d "
          f"(since {start.strftime('%Y-%m-%d')} ET) ===")
    print("    (directional _long/_short variants merged; ★ = SMB cheat-sheet setup)\n")

    # ---- pass 1: alerts ----
    A = defaultdict(lambda: {"n": 0, "hi": 0})
    for a in db.live_alerts.find({}, {"_id": 0, "setup_type": 1, "priority": 1,
                                       "created_at": 1, "timestamp": 1, "ts": 1}):
        et = _to_et(a.get("created_at") or a.get("timestamp") or a.get("ts"))
        if not (et and et >= start):
            continue
        k = _norm(a.get("setup_type"))
        A[k]["n"] += 1
        if str(a.get("priority", "")).lower() in ("high", "critical"):
            A[k]["hi"] += 1

    # ---- pass 2: trades ----
    T = defaultdict(lambda: {"n": 0, "closed": 0, "death": Counter(), "R": []})
    cur = db["bot_trades"].find(
        {},
        {"_id": 0, "setup_type": 1, "status": 1, "entered_by": 1, "learning_only": 1,
         "entry_context.learning_only": 1, "notes": 1, "trade_type": 1, "close_reason": 1,
         "fill_price": 1, "entry_price": 1, "exit_price": 1, "shares": 1, "risk_amount": 1,
         "net_pnl": 1, "realized_pnl": 1, "pnl": 1, "hold_seconds": 1, "executed_at": 1,
         "closed_at": 1, "created_at": 1, "direction": 1, "stop_price": 1, "target_prices": 1})
    for t in cur:
        et = _to_et(t.get("created_at") or t.get("executed_at") or t.get("closed_at"))
        if not (et and et >= start):
            continue
        k = _norm(t.get("setup_type"))
        T[k]["n"] += 1
        if str(t.get("status") or "").startswith("closed"):
            T[k]["closed"] += 1
            reason = _exclusion_reason(t, classify_close)
            if reason is None:
                r = _r_multiple(t)
                if r is not None:
                    T[k]["R"].append(r)
            else:
                T[k]["death"][reason] += 1

    # ---- verdict ----
    def verdict(al, hi, tr, closed, sani, death, R):
        exec_pct = (100.0 * tr / al) if al else 0.0
        if R and len(R) >= 5:
            return "CLEAN+EV" if (sum(R) / len(R)) >= 0 else "EDGE-neg"
        top = death.most_common(1)[0][0] if death else ""
        if top in ("simulated", "learning_only") and death[top] >= max(1, 0.5 * closed):
            return "SHADOW"
        if al >= 20 and exec_pct < 5:
            return "GATE-no-exec"
        if tr > 0 and closed > 0 and len(R) == 0 and top in (
                "hygiene_artifact", "no_exit_price", "sub_10s_hold", "never_filled", "no_risk"):
            return "MGMT-mangled"
        if tr == 0 and al >= 20:
            return "GATE-no-exec"
        return "low-sample"

    setups = set(A) | set(T)
    table = []
    for k in setups:
        al, hi = A[k]["n"], A[k]["hi"]
        tr, closed, death, R = T[k]["n"], T[k]["closed"], T[k]["death"], T[k]["R"]
        sani = len(R)
        v = verdict(al, hi, tr, closed, sani, death, R)
        topdeath = death.most_common(1)[0] if death else ("", 0)
        win = (100.0 * sum(1 for r in R if r > 0) / len(R)) if R else None
        avgr = (sum(R) / len(R)) if R else None
        table.append((al, k, hi, tr, closed, sani, topdeath, win, avgr, v))

    print(f"  {'setup':<24} {'alerts':>6} {'HI%':>4} {'trd':>4} {'exec%':>5} "
          f"{'cls':>4} {'san':>4} {'edge(n≥5)':>11} {'top-death':>16}  VERDICT")
    for al, k, hi, tr, closed, sani, (td, tdn), win, avgr, v in sorted(table, key=lambda x: -x[0]):
        star = "★" if k in SMB_AUDITED else " "
        edge = f"{win:.0f}%/{avgr:+.2f}R" if (win is not None and sani >= 5) else "   -"
        deathstr = f"{td}:{tdn}" if td else "-"
        print(f"{star} {k:<24} {al:>6} {_pct(hi, al):>4} {tr:>4} {_pct(tr, al):>5} "
              f"{closed:>4} {sani:>4} {edge:>11} {deathstr:>16}  {v}")

    # ---- rollups ----
    print("\n" + "=" * 70)
    print("VERDICT ROLLUP")
    print("=" * 70)
    vc = Counter(row[-1] for row in table)
    for v, n in vc.most_common():
        print(f"  {v:<16} {n} setups")
    tot_al = sum(A[k]["n"] for k in A)
    tot_tr = sum(T[k]["n"] for k in T)
    tot_sani = sum(len(T[k]["R"]) for k in T)
    print(f"\n  TOTAL: alerts={tot_al}  trades={tot_tr}  sanitized={tot_sani}  "
          f"(playbook exec%={_pct(tot_tr, tot_al)}, clean-yield%={_pct(tot_sani, tot_al)})")

    print("\n=== READING THE RESULT ===")
    print("• GATE-no-exec dominating → the bottleneck is the FIRE gate (tape/EV/win-rate")
    print("    floor/cap), shared across many setups; the detector quality is moot until")
    print("    alerts can actually execute.")
    print("• MGMT-mangled → trades fire but the exit/hygiene path destroys them.")
    print("• SHADOW → working as designed in paper/shadow; promote to get live outcomes.")
    print("• clean-yield% (sanitized ÷ alerts) is the single health number for the whole")
    print("    alert→clean-trade pipeline.\n")


if __name__ == "__main__":
    main()
