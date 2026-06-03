#!/usr/bin/env python3
"""
v19.34.248 — LEARNING / FEEDBACK-LOOP DEEP AUDIT (READ-ONLY).

Answers the operator's questions:
  • What data does the learning loop GET?
  • What SHOULD it be getting but doesn't? (coverage / leakage)
  • Is it ACCURATE? (recompute + cross-system consistency)
  • How does it all flow? (inventory + freshness of every sink)

This script does NOT write anything. Run it on the DGX:

    .venv/bin/python backend/scripts/diag_learning_loop_audit_v19_34_248.py
    # optional: --days 14   (close-coverage lookback window)

ARCHITECTURE IT AUDITS (3 parallel outcome/EV stores + gates):
  close_trade ─┬─► record_trade_outcome() ─► trade_outcomes ─► learning_stats
               │                                    └► confidence_gate_log, tilt/trader_profile
               ├─► _record_alert_outcome_bestEffort ─► alert_outcomes ─► strategy_stats  (TQS *setup* pillar EV)
               ├─► _perf_service.record_trade
               └─► _log_trade_to_regime_performance ─► regime_performance
  TQS *execution* pillar reads trade_outcomes DIRECTLY (v217-219).
  close_trade_custom (operator manual close / force-flatten) feeds NONE of the above (suspected leak).
"""
import argparse
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from database import get_database
    db = get_database()
except Exception as e:  # pragma: no cover
    print(f"[FATAL] cannot get database: {e}")
    sys.exit(1)

NOW = datetime.now(timezone.utc)


# ── helpers ─────────────────────────────────────────────────────────
def _parse_dt(ts):
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts if ts < 1e12 else ts / 1000, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(ts, str):
        try:
            d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _age(ts):
    d = _parse_dt(ts)
    if d is None:
        return "—"
    s = (NOW - d).total_seconds()
    if s < 0:
        return "future?"
    if s < 90:
        return f"{int(s)}s"
    if s < 5400:
        return f"{int(s/60)}m"
    if s < 172800:
        return f"{int(s/3600)}h"
    return f"{int(s/86400)}d"


def _count(coll, q=None):
    try:
        return db[coll].count_documents(q or {})
    except Exception:
        return -1


def _latest(coll, ts_field="created_at"):
    try:
        d = db[coll].find_one({}, {"_id": 0, ts_field: 1}, sort=[(ts_field, -1)])
        return d.get(ts_field) if d else None
    except Exception:
        return None


def _base_setup(s):
    return (s or "").lower().replace("_long", "").replace("_short", "")


def hdr(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def verdict(ok, warn, label, detail=""):
    tag = "✅ PASS" if ok else ("⚠️  WARN" if warn else "❌ FAIL")
    print(f"  {tag}  {label}" + (f"  — {detail}" if detail else ""))
    return tag


FINDINGS = []  # (severity, text)


def gap(sev, text):
    FINDINGS.append((sev, text))


# ── args ────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=14)
args = ap.parse_args()
cutoff = (NOW - timedelta(days=args.days))
cutoff_iso = cutoff.isoformat()

print(f"\nLEARNING-LOOP AUDIT  ·  {NOW.isoformat()}  ·  window={args.days}d")


# ── SECTION 1 — inventory & freshness ───────────────────────────────
hdr("1. SINK INVENTORY & FRESHNESS")
COLLS = [
    ("bot_trades", "created_at"),
    ("trade_outcomes", "created_at"),
    ("learning_stats", "last_updated"),
    ("alert_outcomes", "closed_at"),
    ("strategy_stats", "last_updated"),
    ("ev_tracking", "last_updated"),
    ("confidence_gate_log", "timestamp"),
    ("shadow_decisions", "created_at"),
    ("regime_performance", "created_at"),
    ("calibration_log", "timestamp"),
    ("trader_profile", "last_updated"),
    ("setup_grade_records", "date"),
    ("weekly_intelligence_reports", "created_at"),
]
print(f"  {'collection':<28} {'count':>9}  {'latest age':>10}")
for c, tf in COLLS:
    n = _count(c)
    last = _latest(c, tf)
    print(f"  {c:<28} {n:>9}  {_age(last):>10}")
    if n == 0:
        gap("HIGH", f"{c} is EMPTY — a learning sink getting no data.")
    elif n == -1:
        gap("INFO", f"{c} not present / unreadable.")


# ── SECTION 2 — close-path coverage (leakage) ───────────────────────
hdr(f"2. CLOSE-PATH COVERAGE  (closed bot_trades last {args.days}d vs outcome sinks)")
try:
    closed = list(db["bot_trades"].find(
        {"status": "closed", "closed_at": {"$gte": cutoff_iso}},
        {"_id": 0, "trade_id": 1, "id": 1, "symbol": 1, "setup_type": 1,
         "closed_at": 1, "entered_by": 1, "close_reason": 1, "realized_pnl": 1},
    ))
except Exception as e:
    closed = []
    print(f"  [warn] bot_trades query failed: {e}")

n_closed = len(closed)
# trade_outcomes keyed by bot_trade_id
to_ids = set()
try:
    for d in db["trade_outcomes"].find(
        {"created_at": {"$gte": cutoff_iso}}, {"_id": 0, "bot_trade_id": 1}
    ):
        to_ids.add(d.get("bot_trade_id"))
except Exception:
    pass
ao_ids = set()
try:
    for d in db["alert_outcomes"].find(
        {"closed_at": {"$gte": cutoff_iso}}, {"_id": 0, "trade_id": 1, "bot_trade_id": 1}
    ):
        ao_ids.add(d.get("trade_id") or d.get("bot_trade_id"))
except Exception:
    pass

missing_to, missing_ao = [], []
by_reason_missing = {}
for t in closed:
    tid = t.get("trade_id") or t.get("id")
    if tid not in to_ids:
        missing_to.append(t)
        r = t.get("close_reason") or "?"
        by_reason_missing[r] = by_reason_missing.get(r, 0) + 1
    if tid not in ao_ids:
        missing_ao.append(t)

print(f"  closed bot_trades         : {n_closed}")
print(f"  → in trade_outcomes       : {n_closed - len(missing_to)}   (missing {len(missing_to)})")
print(f"  → in alert_outcomes       : {n_closed - len(missing_ao)}   (missing {len(missing_ao)})")
if by_reason_missing:
    print("  missing-from-trade_outcomes by close_reason:")
    for r, c in sorted(by_reason_missing.items(), key=lambda x: -x[1]):
        print(f"      {r:<32} {c}")
if n_closed:
    cov_to = (n_closed - len(missing_to)) / n_closed
    verdict(cov_to >= 0.98, cov_to >= 0.9, "trade_outcomes coverage", f"{cov_to*100:.0f}%")
    if cov_to < 0.98:
        gap("HIGH", f"{len(missing_to)}/{n_closed} closed trades have NO trade_outcomes row "
                    f"(suspected close_trade_custom / operator-close leak).")
    cov_ao = (n_closed - len(missing_ao)) / n_closed
    verdict(cov_ao >= 0.98, cov_ao >= 0.9, "alert_outcomes coverage", f"{cov_ao*100:.0f}%")
    if cov_ao < 0.98:
        gap("HIGH", f"{len(missing_ao)}/{n_closed} closed trades have NO alert_outcomes row "
                    f"→ starves strategy_stats (TQS setup-pillar EV).")
else:
    print("  (no closed trades in window — run after a trading session)")


# ── SECTION 3 — trade_outcomes field completeness ───────────────────
hdr("3. trade_outcomes FIELD COMPLETENESS (feature richness for ML)")
try:
    sample = list(db["trade_outcomes"].find(
        {"created_at": {"$gte": cutoff_iso}}, {"_id": 0}
    ).limit(5000))
except Exception:
    sample = []
ns = len(sample)
if ns:
    def pct(pred):
        return 100.0 * sum(1 for d in sample if pred(d)) / ns

    p_cat = pct(lambda d: bool(d.get("catalyst_tag")))
    p_gap = pct(lambda d: float(d.get("gap_pct") or 0) != 0)
    p_reg = pct(lambda d: (d.get("context") or {}).get("market_regime") not in (None, "", "unknown"))
    p_tod = pct(lambda d: (d.get("context") or {}).get("time_of_day") not in (None, ""))
    p_r = pct(lambda d: d.get("actual_r") is not None)
    p_exec = pct(lambda d: bool(d.get("execution")))
    print(f"  sample={ns}")
    print(f"  catalyst_tag populated    : {p_cat:5.1f}%")
    print(f"  gap_pct populated         : {p_gap:5.1f}%")
    print(f"  context.market_regime set : {p_reg:5.1f}%")
    print(f"  context.time_of_day set   : {p_tod:5.1f}%")
    print(f"  actual_r present          : {p_r:5.1f}%")
    print(f"  execution block present   : {p_exec:5.1f}%")
    if p_cat < 30:
        gap("MED", f"catalyst_tag empty on {100-p_cat:.0f}% of outcomes → Phase-D edge ranker "
                   f"bucketing degraded (close_trade omits catalyst_tag/gap_pct).")
    if p_reg < 70:
        gap("MED", f"market_regime missing on {100-p_reg:.0f}% → regime-conditional learning starved.")
    if p_r < 95:
        gap("HIGH", f"actual_r missing on {100-p_r:.0f}% → EV/win-rate math runs on partial data.")
else:
    print("  (no trade_outcomes in window)")


# ── SECTION 4 — cross-system EV consistency ─────────────────────────
hdr("4. CROSS-SYSTEM EV CONSISTENCY  (strategy_stats vs learning_stats vs recomputed)")
# recompute per base_setup from trade_outcomes
recomputed = {}
try:
    for d in db["trade_outcomes"].find({}, {"_id": 0, "setup_type": 1, "outcome": 1, "actual_r": 1}):
        bs = _base_setup(d.get("setup_type"))
        if not bs:
            continue
        recomputed.setdefault(bs, []).append(d)
except Exception:
    pass

def _wr_ev(rows):
    wins = sum(1 for r in rows if r.get("outcome") == "won")
    dec = sum(1 for r in rows if r.get("outcome") in ("won", "lost"))
    wr = wins / dec if dec else 0.0
    win_rs = [abs(float(r.get("actual_r") or 0)) for r in rows if r.get("outcome") == "won"]
    loss_rs = [abs(float(r.get("actual_r") or 0)) for r in rows if r.get("outcome") == "lost"]
    aw = sum(win_rs)/len(win_rs) if win_rs else 0.0
    al = sum(loss_rs)/len(loss_rs) if loss_rs else 1.0
    ev = wr*aw - (1-wr)*al
    return wr, ev, len(rows)

ss = {d.get("base_setup") or d.get("setup_type"): d
      for d in db["strategy_stats"].find({}, {"_id": 0}) } if _count("strategy_stats") > 0 else {}
ls = {d.get("context_key"): d
      for d in db["learning_stats"].find({}, {"_id": 0})} if _count("learning_stats") > 0 else {}

print(f"  {'setup':<24} {'n(TO)':>6} {'wr_TO':>6} {'wr_SS':>6} {'wr_LS':>6} {'ev_TO':>6} {'ev_SS':>6}")
divergent = 0
for bs in sorted(recomputed, key=lambda k: -len(recomputed[k]))[:25]:
    wr, ev, n = _wr_ev(recomputed[bs])
    ss_d = ss.get(bs, {})
    ls_d = ls.get(bs, {})
    wr_ss = ss_d.get("win_rate")
    wr_ls = ls_d.get("win_rate")
    ev_ss = ss_d.get("expected_value_r")
    def f(x):
        return f"{x:.2f}" if isinstance(x, (int, float)) else "  —"
    print(f"  {bs:<24} {n:>6} {f(wr)} {f(wr_ss)} {f(wr_ls)} {f(ev)} {f(ev_ss)}")
    if isinstance(wr_ss, (int, float)) and abs(wr_ss - wr) > 0.12 and n >= 8:
        divergent += 1
if divergent:
    gap("MED", f"{divergent} setups: strategy_stats win_rate diverges >12pp from "
               f"trade_outcomes recompute → the two EV systems disagree on the SAME trades.")
print("  (wr_TO/ev_TO = recomputed from trade_outcomes; SS = strategy_stats; LS = learning_stats)")


# ── SECTION 5 — actual_r accuracy spot-check ────────────────────────
hdr("5. actual_r ACCURACY SPOT-CHECK (recompute from prices)")
try:
    spot = list(db["trade_outcomes"].find(
        {"actual_r": {"$ne": None}},
        {"_id": 0, "entry_price": 1, "exit_price": 1, "stop_price": 1,
         "direction": 1, "actual_r": 1, "symbol": 1},
    ).sort("created_at", -1).limit(200))
except Exception:
    spot = []
bad = 0
checked = 0
for d in spot:
    ep, xp, sp = d.get("entry_price"), d.get("exit_price"), d.get("stop_price")
    if not all(isinstance(v, (int, float)) and v for v in (ep, xp, sp)):
        continue
    risk = abs(ep - sp)
    if risk <= 0:
        continue
    long = str(d.get("direction", "")).lower().startswith("l")
    pnl_ps = (xp - ep) if long else (ep - xp)
    rr = pnl_ps / risk
    checked += 1
    if abs(rr - float(d.get("actual_r") or 0)) > 0.15:
        bad += 1
print(f"  checked={checked}  mismatched(>0.15R)={bad}")
if checked:
    verdict(bad / checked < 0.05, bad / checked < 0.15, "stored actual_r matches recompute",
            f"{100*bad/checked:.0f}% mismatch")
    if bad / checked >= 0.05:
        gap("MED", f"{bad}/{checked} outcomes: stored actual_r != recompute from entry/exit/stop "
                   f"(likely weighted-avg fill / scale-out / first-target approximations).")


# ── SECTION 6 — shadow vs real ──────────────────────────────────────
hdr("6. SHADOW vs REAL (ties to the 18-pt gap investigation)")
try:
    sd = list(db["shadow_decisions"].find(
        {"created_at": {"$gte": cutoff_iso}}, {"_id": 0, "executed": 1,
         "recommendation": 1, "would_pnl": 1, "pnl": 1, "outcome": 1}))
except Exception:
    sd = []
if sd:
    ex = [d for d in sd if d.get("executed")]
    nex = [d for d in sd if not d.get("executed")]
    def _wr(rows, key="outcome"):
        w = sum(1 for r in rows if r.get(key) == "won")
        dec = sum(1 for r in rows if r.get(key) in ("won", "lost"))
        return (w/dec*100) if dec else None
    print(f"  shadow decisions={len(sd)}  executed={len(ex)}  not-executed={len(nex)}")
    wre, wrn = _wr(ex), _wr(nex)
    print(f"  executed win%={wre}   not-executed would-win%={wrn}")
    if wre is not None and wrn is not None and (wrn - (wre or 0)) > 8:
        gap("MED", f"Shadow not-executed would-win% ({wrn:.0f}) >> executed ({wre:.0f}) → "
                   f"AI/gate is too conservative OR execution erodes edge (18pt-gap candidate).")
else:
    print("  (no shadow_decisions in window — shadow_update loop may be idle)")


# ── SECTION 7 — scheduler liveness ──────────────────────────────────
hdr("7. SCHEDULER LIVENESS (is the loop actually turning?)")
checks = [
    ("learning_stats", "last_updated", 36 * 3600, "nightly rebuild 17:30 ET"),
    ("calibration_log", "timestamp", 8 * 86400, "calibration recommendations"),
    ("confidence_gate_log", "timestamp", 36 * 3600, "gate outcome recording"),
    ("regime_performance", "created_at", 5 * 86400, "per-trade regime log"),
    ("weekly_intelligence_reports", "created_at", 9 * 86400, "weekly report Fri 16:30"),
    ("setup_grade_records", "date", 5 * 86400, "EOD setup grading 16:05"),
]
for coll, tf, max_s, desc in checks:
    last = _latest(coll, tf)
    d = _parse_dt(last)
    fresh = d is not None and (NOW - d).total_seconds() <= max_s
    verdict(fresh, last is not None, f"{coll}", f"last {_age(last)} ({desc})")
    if last is None:
        gap("MED", f"{coll} has no dated rows — '{desc}' may never have run.")
    elif not fresh:
        gap("MED", f"{coll} stale ({_age(last)}) — '{desc}' likely not firing.")


# ── SUMMARY ─────────────────────────────────────────────────────────
hdr("SUMMARY — PRIORITIZED GAPS")
if not FINDINGS:
    print("  ✅ No gaps detected. Learning loop fully fed, fresh, and consistent.")
else:
    order = {"HIGH": 0, "MED": 1, "INFO": 2}
    for sev, text in sorted(FINDINGS, key=lambda x: order.get(x[0], 3)):
        print(f"  [{sev:>4}] {text}")
print("\nDone. (read-only — nothing was modified)\n")
