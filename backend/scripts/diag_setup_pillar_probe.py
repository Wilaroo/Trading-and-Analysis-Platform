#!/usr/bin/env python3
"""
diag_setup_pillar_probe.py — READ-ONLY deep-dive on the two SETUP-pillar
sub-scores the v393 inverse re-verify flagged:
  • setup.win_rate  (25% sub-weight — HIGHEST) — corr was −0.62/−0.19 (anti-signal)
  • setup.pattern   (20% sub-weight)            — corr was −0.08/−0.13 (weak inverse)

Goal: understand WHY before any scoring edit. For each sub-score it reports:
  1. VALUE DISTRIBUTION (quantiles + fixed buckets + % pinned at common defaults
     50/100) → is the signal degenerate (mostly default) or genuinely varied?
  2. corr(sub_score, realized_R) + win%/avgR by FIXED value bucket → is it the
     HIGH end that underperforms (over-extension/overfit), or noise?
  3. For win_rate: the RAW historical win-rate (0..1) distribution + a per-
     setup_type cross-tab (which setups carry a high stamped WR yet lose live).
  4. For pattern: a per-setup_type table (avg pattern_score vs realized win%/avgR)
     → which setups the static SMB ranking MIS-ranks.

Sample = sanitized bot-own closed trades (canonical hygiene funnel), joined to
their scoring-time tqs_breakdown — PREFERS the v393 top-level
`bot_trades.tqs_breakdown`, falls back to the live_alerts/alerts join for pre-
v393 closes. R = pnl÷risk, winsorized ±3. Windows 14/21/30d (sign stability).

NOTHING IS WRITTEN. Run from repo root on the DGX:
  .venv/bin/python backend/scripts/diag_setup_pillar_probe.py
  .venv/bin/python backend/scripts/diag_setup_pillar_probe.py --days 14,21,30 --min 20
  .venv/bin/python backend/scripts/diag_setup_pillar_probe.py --selftest
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
SCORE_BUCKETS = [(-1, 40), (40, 50), (50, 60), (60, 75), (75, 90), (90, 101)]
WR_BUCKETS = [(-1, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 2.0)]


# ── backend discovery / env ────────────────────────────────────────────────
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


# ── sanitizer helpers (verbatim from diag_tqs_inverse_verify) ───────────────
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


# ── stats helpers ──────────────────────────────────────────────────────────
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


def _comp(bd, pillar, comp):
    try:
        return float(bd[pillar]["components"][comp])
    except (KeyError, TypeError, ValueError):
        return None


def _raw(bd, pillar, key):
    try:
        return float(bd[pillar]["raw_values"][key])
    except (KeyError, TypeError, ValueError):
        return None


def _quantiles(vals):
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    q = lambda p: s[min(n - 1, int(p * n))]
    return {"min": s[0], "p25": q(.25), "p50": median(s), "p75": q(.75), "max": s[-1]}


def _bucket_table(pairs, buckets, label_fmt):
    """pairs=[(value,R)] -> printable rows per bucket."""
    rows = []
    for lo, hi in buckets:
        rs = [r for v, r in pairs if lo < v <= hi] if lo != -1 else [r for v, r in pairs if v <= hi]
        if not rs:
            rows.append((label_fmt(lo, hi), 0, None, None))
        else:
            win = 100.0 * sum(1 for r in rs if r > 0) / len(rs)
            rows.append((label_fmt(lo, hi), len(rs), win, sum(rs) / len(rs)))
    return rows


# ── breakdown index (live_alerts + alerts fallback for pre-v393 closes) ─────
def _build_breakdown_index(db, alert_ids):
    idx = {}
    if not alert_ids:
        return idx
    ids = list(alert_ids)
    for coll in ("live_alerts", "alerts"):
        try:
            cur = db[coll].find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "tqs_breakdown": 1})
        except Exception:
            continue
        for d in cur:
            aid, bd = d.get("id"), d.get("tqs_breakdown") or {}
            if aid and (aid not in idx or (not idx[aid] and bd)):
                idx[aid] = bd
    return idx


def _gather(core_all, bd_index, days):
    now = datetime.now(ET)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []  # (R, bd, setup_type)
    src_direct = src_joined = 0
    for t in core_all:
        et = _to_et(t.get("closed_at") or t.get("created_at"))
        if not (et and et >= start):
            continue
        r = _r_multiple(t)
        if r is None:
            continue
        bd_direct = t.get("tqs_breakdown") if isinstance(t.get("tqs_breakdown"), dict) else None
        aid = t.get("alert_id")
        bd = bd_direct or (bd_index.get(aid) if aid else None)
        if bd:
            src_direct += 1 if bd_direct else 0
            src_joined += 0 if bd_direct else 1
            rows.append((_winsor(r), bd, str(t.get("setup_type") or "?")))
    return rows, start, src_direct, src_joined


def _probe_subscore(rows, pillar, comp, min_n, raw_key=None, raw_buckets=None):
    pairs = [( _comp(bd, pillar, comp), r) for r, bd, _ in rows]
    pairs = [(v, r) for v, r in pairs if v is not None]
    print(f"\n  ── {pillar}.{comp}  (n={len(pairs)}) ──")
    if len(pairs) < 3:
        print("     too few to analyze")
        return
    vals = [v for v, _ in pairs]
    qd = _quantiles(vals)
    at50 = 100.0 * sum(1 for v in vals if abs(v - 50) < 0.5) / len(vals)
    at100 = 100.0 * sum(1 for v in vals if v >= 99.5) / len(vals)
    print(f"     score dist: min={qd['min']:.0f} p25={qd['p25']:.0f} p50={qd['p50']:.0f} "
          f"p75={qd['p75']:.0f} max={qd['max']:.0f}   pinned@50={at50:.0f}%  @100={at100:.0f}%")
    corr = _pearson(vals, [r for _, r in pairs])
    print(f"     corr(score,R) = {('%+.3f'%corr) if corr is not None else 'n/a (zero variance)'}")
    if len(pairs) >= min_n:
        print(f"     {'score bucket':<14}{'n':>5}{'win%':>8}{'avgR':>8}")
        for lab, n, win, avgr in _bucket_table(
                pairs, SCORE_BUCKETS,
                lambda lo, hi: f"<= {hi:.0f}" if lo == -1 else f"{lo:.0f}-{hi:.0f}"):
            if n:
                print(f"     {lab:<14}{n:>5}{win:>7.0f}%{avgr:>+8.2f}")
            else:
                print(f"     {lab:<14}{n:>5}{'-':>8}{'-':>8}")
    else:
        print(f"     (below min n={min_n} for bucket table)")

    if raw_key:
        rpairs = [(_raw(bd, pillar, raw_key), r) for r, bd, _ in rows]
        rpairs = [(v, r) for v, r in rpairs if v is not None]
        if rpairs:
            rv = [v for v, _ in rpairs]
            qr = _quantiles(rv)
            default = 100.0 * sum(1 for v in rv if abs(v - 0.5) < 0.005) / len(rv)
            print(f"     RAW {raw_key}: min={qr['min']:.2f} p50={qr['p50']:.2f} max={qr['max']:.2f}  "
                  f"@0.50(default)={default:.0f}%   (n={len(rpairs)})")
            if len(rpairs) >= min_n and raw_buckets:
                print(f"     {'raw bucket':<14}{'n':>5}{'win%':>8}{'avgR':>8}")
                for lab, n, win, avgr in _bucket_table(
                        rpairs, raw_buckets,
                        lambda lo, hi: f"<= {hi:.2f}" if lo == -1 else f"{lo:.2f}-{hi:.2f}"):
                    if n:
                        print(f"     {lab:<14}{n:>5}{win:>7.0f}%{avgr:>+8.2f}")


def _setup_xtab(rows, pillar, comp, min_per=4):
    by = defaultdict(list)  # setup_type -> [(score,R)]
    for r, bd, st in rows:
        v = _comp(bd, pillar, comp)
        if v is not None:
            by[st].append((v, r))
    print(f"\n     per-setup_type ({pillar}.{comp}, setups with n>={min_per}):")
    print(f"     {'setup_type':<26}{'n':>4}{'avgScore':>9}{'win%':>7}{'avgR':>8}")
    for st, ps in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if len(ps) < min_per:
            continue
        n = len(ps)
        avg_s = sum(v for v, _ in ps) / n
        rs = [r for _, r in ps]
        win = 100.0 * sum(1 for r in rs if r > 0) / n
        print(f"     {st[:26]:<26}{n:>4}{avg_s:>9.1f}{win:>6.0f}%{sum(rs)/n:>+8.2f}")


def _analyze(core_all, bd_index, days, min_n):
    rows, start, sd, sj = _gather(core_all, bd_index, days)
    print("\n" + "=" * 90)
    print(f"WINDOW trailing {days}d (since {start.strftime('%Y-%m-%d')} ET)   "
          f"trades-with-breakdown={len(rows)} (direct={sd} joined={sj})")
    print("=" * 90)
    if len(rows) < 3:
        print("  insufficient breakdown-joined trades")
        return
    _probe_subscore(rows, "setup", "win_rate", min_n,
                    raw_key="win_rate", raw_buckets=WR_BUCKETS)
    _setup_xtab(rows, "setup", "win_rate")
    _probe_subscore(rows, "setup", "pattern", min_n)
    _setup_xtab(rows, "setup", "pattern")


def _selftest():
    print("SELFTEST")
    assert _pearson([0, 1, 2, 3], [3, 2, 1, 0]) < -0.99
    assert _comp({"setup": {"components": {"win_rate": 75.0}}}, "setup", "win_rate") == 75.0
    assert _raw({"setup": {"raw_values": {"win_rate": 0.5}}}, "setup", "win_rate") == 0.5
    assert _winsor(9) == 3.0
    bt = _bucket_table([(95, 1.0), (95, -1.0), (30, 0.5)], SCORE_BUCKETS,
                       lambda lo, hi: f"{lo}-{hi}")
    assert any(n == 2 for _, n, _, _ in bt) and any(n == 1 for _, n, _, _ in bt)
    q = _quantiles([1, 2, 3, 4, 5])
    assert q["p50"] == 3
    print("  ✅ pearson/comp/raw/winsor/bucket/quantile OK\nSELFTEST PASS")


def main():
    if "--selftest" in sys.argv:
        _selftest(); return
    days_list = [14, 21, 30]
    min_n = 20
    if "--days" in sys.argv:
        try:
            days_list = [int(x) for x in sys.argv[sys.argv.index("--days") + 1].split(",") if x.strip()]
        except Exception:
            pass
    if "--min" in sys.argv:
        try:
            min_n = int(sys.argv[sys.argv.index("--min") + 1])
        except Exception:
            pass

    backend = _find_backend()
    _load_env(backend)
    sys.path.insert(0, str(backend))
    from services.trade_outcome_hygiene import classify_close
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    print("=" * 90)
    print("diag_setup_pillar_probe — setup.win_rate (25% wt) + setup.pattern (20% wt) deep-dive")
    print(f"windows={days_list} min_n={min_n} winsor=±{WINSOR}  {datetime.now(timezone.utc).isoformat()[:19]}Z")
    print("=" * 90)

    closed = list(db["bot_trades"].find(
        {"status": {"$regex": "^closed"}},
        {"_id": 0, "id": 1, "alert_id": 1, "symbol": 1, "entered_by": 1,
         "learning_only": 1, "entry_context.learning_only": 1, "notes": 1,
         "trade_type": 1, "close_reason": 1, "fill_price": 1, "entry_price": 1,
         "exit_price": 1, "shares": 1, "risk_amount": 1, "net_pnl": 1,
         "realized_pnl": 1, "pnl": 1, "hold_seconds": 1, "executed_at": 1,
         "closed_at": 1, "created_at": 1, "setup_type": 1, "direction": 1,
         "stop_price": 1, "target_prices": 1, "tqs_breakdown": 1}))

    excl = Counter()
    core_all = []
    for t in closed:
        reason = _exclusion_reason(t, classify_close)
        (core_all.append(t) if reason is None else excl.__setitem__(reason, excl[reason] + 1))
    print(f"\nraw closed: {len(closed)}  →  sanitized survivors: {len(core_all)}")
    print("  funnel: " + ", ".join(f"{k}={v}" for k, v in excl.most_common()))

    bd_index = _build_breakdown_index(
        db, {t.get("alert_id") for t in core_all if t.get("alert_id")})
    print(f"  alert breakdowns indexed (fallback for pre-v393): {len(bd_index)}")

    for d in sorted(days_list):
        _analyze(core_all, bd_index, d, min_n)

    print("\n" + "=" * 90)
    print("READ: if win_rate's HIGH score buckets (75-100) show LOW win%/negative avgR while LOW")
    print("buckets win — the stamped historical win-rate is overfit/regime-stale (anti-predictive).")
    print("If RAW win_rate is mostly pinned @0.50, the sub-score is largely degenerate (default).")
    print("The per-setup_type x-tab shows WHICH setups carry a high score yet lose live. NOTHING WRITTEN.")
    print("=" * 90)


if __name__ == "__main__":
    main()
