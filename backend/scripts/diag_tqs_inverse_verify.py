#!/usr/bin/env python3
"""
diag_tqs_inverse_verify.py — READ-ONLY re-verification of the INVERSE-signed
TQS inputs before we touch any scoring logic.
============================================================================
Operator asked to "verify the inverse signed one more time and if confirmed
then do B" (apply the fix). This diag is the confirmation instrument.

It RE-RUNS the diag_pillar_exit_edge finding on a FRESH sanitized sample:

  1. Sanitize closed `bot_trades` with the codebase's CANONICAL hygiene
     funnel (same sanitize_v2 used by diag_sanitized_closed_trades.py /
     diag_v321b_sanitized_edge.py: provenance, learning_only, simulated,
     admin_close, legacy_orphan, hygiene_artifact, never_filled,
     no_exit_price, no_risk, sub_10s_hold, absurd_r).
  2. Join each survivor to its scoring-time `live_alerts.tqs_breakdown`
     (bot_trades.alert_id == live_alerts.id; falls back to the `alerts`
     collection). bot_trades does NOT persist tqs_breakdown (integrity gap),
     so the alert collection is the only place the per-sub-score values live.
  3. For each sub-score, compute Pearson corr(sub_score, realized_R) and a
     low/mid/high TERCILE win% + avgR spread. R = pnl÷risk_amount, winsorized
     to ±3 (|R|>10 already dropped by the sanitizer).
  4. Report across MULTIPLE trailing windows (default 14 + 21 days) so we
     judge SIGN STABILITY, not a single noisy window.

SUSPECTED-INVERSE TARGETS (the fix candidates):
   setup.pattern · context.regime · context.relative_strength
CONFIRMING CONTROLS (should stay >= 0):
   setup.tape · fundamental.catalyst · setup.win_rate · context.day (spurious +)

VERDICT per target: INVERSE CONFIRMED only if corr < 0 in EVERY window with
n >= --min (default 30). Anything else = NOT confirmed (don't flip the fix).

NOTHING IS WRITTEN. Run from repo root on the DGX:
  .venv/bin/python backend/scripts/diag_tqs_inverse_verify.py
  .venv/bin/python backend/scripts/diag_tqs_inverse_verify.py --days 14,21,30 --min 25
  .venv/bin/python backend/scripts/diag_tqs_inverse_verify.py --selftest
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

WINSOR = 3.0

# (label, pillar, component) — pillar/component keys mirror the *_quality
# to_dict() "components" maps.
TARGETS = [
    ("setup.pattern",             "setup",   "pattern"),
    ("context.regime",            "context", "regime"),
    ("context.relative_strength", "context", "relative_strength"),
]
CONTROLS = [
    ("setup.tape",            "setup",       "tape"),
    ("fundamental.catalyst",  "fundamental", "catalyst"),
    ("setup.win_rate",        "setup",       "win_rate"),
    ("context.day",           "context",     "day"),
]


# ── env / backend discovery (matches the canonical diags) ──────────────────
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


# ── shared sanitizer helpers (verbatim from diag_v321b) ────────────────────
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


# ── stats helpers (pure stdlib) ────────────────────────────────────────────
def _winsor(r):
    return max(-WINSOR, min(WINSOR, r))


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / ((vx * vy) ** 0.5)


def _sub(bd, pillar, comp):
    """Pull a sub-score out of a persisted tqs_breakdown dict."""
    try:
        v = bd[pillar]["components"][comp]
        return float(v)
    except (KeyError, TypeError, ValueError):
        return None


def _terciles(pairs):
    """pairs = [(subscore, R)] -> (low, mid, high) dicts of {n, win, avgR}."""
    if len(pairs) < 6:
        return None
    pairs = sorted(pairs, key=lambda p: p[0])
    n = len(pairs)
    c1, c2 = n // 3, 2 * n // 3
    out = []
    for chunk in (pairs[:c1], pairs[c1:c2], pairs[c2:]):
        rs = [r for _, r in chunk]
        if not rs:
            out.append({"n": 0, "win": 0.0, "avgR": 0.0})
            continue
        out.append({
            "n": len(rs),
            "win": 100.0 * sum(1 for r in rs if r > 0) / len(rs),
            "avgR": sum(rs) / len(rs),
        })
    return tuple(out)


# ── breakdown index from the alert collections ─────────────────────────────
def _build_breakdown_index(db, alert_ids):
    """id -> tqs_breakdown, preferring a NON-empty breakdown. Queries
    live_alerts first, then the historical `alerts` collection for any miss."""
    idx = {}
    if not alert_ids:
        return idx
    ids = list(alert_ids)
    for coll in ("live_alerts", "alerts"):
        try:
            cur = db[coll].find(
                {"id": {"$in": ids}},
                {"_id": 0, "id": 1, "tqs_breakdown": 1},
            )
        except Exception:
            continue
        for d in cur:
            aid = d.get("id")
            bd = d.get("tqs_breakdown") or {}
            if not aid:
                continue
            if aid not in idx or (not idx[aid] and bd):
                idx[aid] = bd
    return idx


def _analyze_window(core_all, classify_close, bd_index, days, min_n):
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    rows = []  # (R, breakdown)
    joined = 0
    have_bd = 0
    for t in core_all:
        et = _to_et(t.get("closed_at") or t.get("created_at"))
        if not (et and et >= start):
            continue
        r = _r_multiple(t)
        if r is None:
            continue
        aid = t.get("alert_id")
        bd = bd_index.get(aid) if aid else None
        if bd is not None:
            joined += 1
            if bd:
                have_bd += 1
                rows.append((_winsor(r), bd))

    print("\n" + "=" * 86)
    print(f"WINDOW: trailing {days}d (since {start.strftime('%Y-%m-%d')} ET)   "
          f"in-window sanitized={sum(1 for t in core_all if (lambda e: e and e>=start)(_to_et(t.get('closed_at') or t.get('created_at'))))}"
          f"  alert-joined={joined}  with-breakdown={have_bd}")
    print("=" * 86)
    if have_bd < 3:
        print("  ⚠ too few breakdown-joined trades to correlate — INSUFFICIENT")
        return {}

    results = {}
    print(f"  {'sub-score':<28} {'n':>4} {'corr':>7}  "
          f"{'loT win/avgR':>16}  {'midT win/avgR':>16}  {'hiT win/avgR':>16}")
    for grp_name, grp in (("TARGETS (expect INVERSE / corr<0)", TARGETS),
                          ("CONTROLS (expect >=0)", CONTROLS)):
        print(f"  --- {grp_name} ---")
        for label, pillar, comp in grp:
            pairs = []
            for r, bd in rows:
                s = _sub(bd, pillar, comp)
                if s is not None:
                    pairs.append((s, r))
            if len(pairs) < min_n:
                print(f"  {label:<28} {len(pairs):>4}    n/a   (below min n={min_n})")
                results[label] = {"n": len(pairs), "corr": None}
                continue
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            corr = _pearson(xs, ys)
            terc = _terciles(pairs)
            results[label] = {"n": len(pairs), "corr": corr}
            def _fmt(b):
                return f"{b['win']:4.0f}% {b['avgR']:+.2f}" if b else "      -"
            lo, mid, hi = terc if terc else (None, None, None)
            cs = f"{corr:+.3f}" if corr is not None else "  n/a"
            print(f"  {label:<28} {len(pairs):>4} {cs:>7}  "
                  f"{_fmt(lo):>16}  {_fmt(mid):>16}  {_fmt(hi):>16}")
    return results


def _selftest():
    print("SELFTEST — correlation/tercile math on synthetic data")
    # Perfectly inverse: higher x -> lower R.
    inv = [(float(i), -float(i) + 10.0) for i in range(30)]
    c = _pearson([p[0] for p in inv], [p[1] for p in inv])
    assert c is not None and c < -0.99, c
    pos = [(float(i), float(i)) for i in range(30)]
    c2 = _pearson([p[0] for p in pos], [p[1] for p in pos])
    assert c2 is not None and c2 > 0.99, c2
    t = _terciles([(float(i), 1.0 if i >= 20 else -1.0) for i in range(30)])
    assert t and t[0]["win"] == 0.0 and t[2]["win"] == 100.0, t
    assert _winsor(9.0) == 3.0 and _winsor(-9.0) == -3.0
    assert _sub({"context": {"components": {"regime": 25.0}}}, "context", "regime") == 25.0
    assert _sub({}, "context", "regime") is None
    print("  ✅ pearson(inverse)=%.3f  pearson(pos)=%.3f  terciles+winsor+sub OK" % (c, c2))
    print("SELFTEST PASS")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return

    days_list = [14, 21]
    min_n = 30
    if "--days" in sys.argv:
        try:
            days_list = [int(x) for x in sys.argv[sys.argv.index("--days") + 1].split(",") if x.strip()]
        except Exception:
            days_list = [14, 21]
    if "--min" in sys.argv:
        try:
            min_n = int(sys.argv[sys.argv.index("--min") + 1])
        except Exception:
            min_n = 30

    backend = _find_backend()
    _load_env(backend)
    sys.path.insert(0, str(backend))
    from services.trade_outcome_hygiene import classify_close
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    max_days = max(days_list)
    print("=" * 86)
    print(f"diag_tqs_inverse_verify — sanitized bot-own × live_alerts breakdown")
    print(f"windows={days_list}  min_n={min_n}  winsor=±{WINSOR}  "
          f"{datetime.now(timezone.utc).isoformat()[:19]}Z")
    print("=" * 86)

    closed = list(db["bot_trades"].find(
        {"status": {"$regex": "^closed"}},
        {"_id": 0, "id": 1, "alert_id": 1, "symbol": 1, "entered_by": 1,
         "learning_only": 1, "entry_context.learning_only": 1, "notes": 1,
         "trade_type": 1, "close_reason": 1, "fill_price": 1, "entry_price": 1,
         "exit_price": 1, "shares": 1, "risk_amount": 1, "net_pnl": 1,
         "realized_pnl": 1, "pnl": 1, "hold_seconds": 1, "executed_at": 1,
         "closed_at": 1, "created_at": 1, "setup_type": 1, "direction": 1,
         "stop_price": 1, "target_prices": 1}))

    excl = Counter()
    core_all = []          # all sanitized survivors (any era)
    for t in closed:
        reason = _exclusion_reason(t, classify_close)
        if reason is None:
            core_all.append(t)
        else:
            excl[reason] += 1
    print(f"\nraw closed rows: {len(closed)}   →   sanitized survivors (all eras): {len(core_all)}")
    print("  funnel: " + ", ".join(f"{k}={v}" for k, v in excl.most_common()))

    with_alert = sum(1 for t in core_all if t.get("alert_id"))
    print(f"  survivors carrying alert_id: {with_alert}/{len(core_all)} "
          f"({100.0*with_alert/max(len(core_all),1):.0f}%)")

    bd_index = _build_breakdown_index(
        db, {t.get("alert_id") for t in core_all if t.get("alert_id")})
    print(f"  alert breakdowns indexed (live_alerts+alerts): {len(bd_index)}")

    per_window = {}
    for d in sorted(days_list):
        per_window[d] = _analyze_window(core_all, classify_close, bd_index, d, min_n)

    # ── VERDICT ────────────────────────────────────────────────────────────
    print("\n" + "=" * 86)
    print("VERDICT — INVERSE CONFIRMED only if corr<0 in EVERY window with n>=min")
    print("=" * 86)
    any_confirmed = False
    for label, _p, _c in TARGETS:
        signs = []
        detail = []
        for d in sorted(days_list):
            res = per_window.get(d, {}).get(label, {})
            corr = res.get("corr")
            n = res.get("n", 0)
            detail.append(f"{d}d: corr={'%+.3f'%corr if corr is not None else 'n/a'} (n={n})")
            if corr is None or n < min_n:
                signs.append(None)
            else:
                signs.append(corr < 0)
        usable = [s for s in signs if s is not None]
        if usable and all(usable):
            verdict = "✅ INVERSE CONFIRMED"
            any_confirmed = True
        elif usable and not any(usable):
            verdict = "❌ POSITIVE (not inverse)"
        elif usable:
            verdict = "🟡 MIXED across windows"
        else:
            verdict = "⚠ INSUFFICIENT (n too low)"
        print(f"  {label:<28} {verdict}")
        print(f"        {'  |  '.join(detail)}")

    print("\nREAD: if ALL three targets show ✅ across windows, the inverse-signing is")
    print("re-confirmed → proceed to the fix patch. Any 🟡/⚠ on a target = do NOT flip")
    print("that one yet (insufficient/unstable evidence). NOTHING WAS WRITTEN.")
    print("=" * 86)


if __name__ == "__main__":
    main()
