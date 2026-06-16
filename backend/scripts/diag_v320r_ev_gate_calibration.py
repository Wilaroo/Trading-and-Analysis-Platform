#!/usr/bin/env python3
"""
v320r-precheck — EV-GATE CALIBRATION (READ-ONLY): would promoting the Tier-1
intraday scalps to HIGH actually produce auto-fires, or will the EV gate block them?

WHY
---
Auto-execution requires THREE things (verified in enhanced_scanner.py L1560):
    priority in {HIGH, CRITICAL}  AND  tape_confirmation  AND  EV-quality-gate PASS
The proposed v320r change only fixes the FIRST leg (gives medium-capped intraday
scalps a tape-gated HIGH branch). This script confirms the THIRD leg won't silently
neutralize it — i.e. that the EV gate is calibrated to LET TRADES FIRE.

EV GATE (mirror of `_passes_ev_quality_gate`, enhanced_scanner.py L1576):
  base = setup_type without _long/_short
  stats = strategy_stats[base]
  - not registered                       -> FAIL  (no_strategy_stats)
  - alerts_triggered <  GRACE_MIN (20)   -> PASS  (cold-start grace)
  - alerts_triggered >= GRACE_MIN AND
        expected_value_r >  EV_FLOOR(0.10)-> PASS  (proven positive expectancy)
  - else                                  -> FAIL  (EV <= +0.10R)

Knobs are HARDCODED in enhanced_scanner.__init__:
  _auto_execute_min_ev_r       = 0.10   (L1176)
  _win_rate_grace_min_trades   = 20     (L1185)
(not env-overridable; if you've changed them in code, pass --ev-floor / --grace-min).

The strategy_stats collection is the gate's source of truth (reloaded every
SCANNER_STATS_RELOAD_SEC=300s; upserted by pnl_compute on every close), so reading
it directly shows EXACTLY what the live gate sees.

NOTHING IS WRITTEN. All reads project {"_id": 0}.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v320r_ev_gate_calibration.py
  .venv/bin/python backend/scripts/diag_v320r_ev_gate_calibration.py --ev-floor 0.10 --grace-min 20
"""
import sys
from pymongo import MongoClient

# --- the proposed Tier-1 (option A) intraday scalp promotions ---
TIER1 = ["big_dog", "second_chance", "fashionably_late", "backside", "gap_pick_roll"]
# context: appeared medium-capped in v320q but base-stripped to these
CONTEXT = ["vwap_fade", "off_sides", "orb"]
# currently-auto-firing daily setups — used as a CALIBRATION CONTROL: if these
# don't PASS, the gate is globally broken (they fire today, so they MUST pass).
CONTROL_DAILY = ["daily_breakout", "daily_squeeze", "stage_2_breakout",
                 "pocket_pivot", "vcp_breakout", "power_trend_stack",
                 "rs_leader_break", "breakout"]

EV_FLOOR = 0.10
GRACE_MIN = 20


def _argval(flag, default):
    if flag in sys.argv:
        try:
            return type(default)(sys.argv[sys.argv.index(flag) + 1])
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
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _base(setup):
    return str(setup or "").split("_long")[0].split("_short")[0].strip().lower()


def _verdict(stats, ev_floor, grace_min):
    """Exact mirror of _passes_ev_quality_gate."""
    if stats is None:
        return "FAIL", "no_strategy_stats (unregistered → bot won't auto-trade)"
    o = int(stats.get("alerts_triggered", 0) or 0)
    if o < grace_min:
        return "PASS", f"cold-start grace ({o}<{grace_min} graded outcomes)"
    ev = float(stats.get("expected_value_r", 0.0) or 0.0)
    if ev > ev_floor:
        return "PASS", f"proven EV {ev:+.2f}R > +{ev_floor:.2f}R"
    return "FAIL", f"EV {ev:+.2f}R <= +{ev_floor:.2f}R (proven non-positive)"


def _row(db, setups, ev_floor, grace_min, by_base):
    out = []
    for s in setups:
        b = _base(s)
        st = by_base.get(b)
        o = int(st.get("alerts_triggered", 0) or 0) if st else 0
        rn = len(st.get("r_outcomes", []) or []) if st else 0
        ev = float(st.get("expected_value_r", 0.0) or 0.0) if st else 0.0
        wr = float(st.get("win_rate", 0.0) or 0.0) if st else 0.0
        v, why = _verdict(st, ev_floor, grace_min)
        out.append((s, b, "yes" if st else "NO", o, rn, ev, wr, v, why))
    return out


def _print(title, rows):
    print(f"\n{title}")
    print(f"  {'setup':<22} {'base':<16} {'reg':>3} {'grded':>5} {'rN':>4} "
          f"{'EV_R':>7} {'win%':>6}  verdict")
    for s, b, reg, o, rn, ev, wr, v, why in rows:
        mark = "✅" if v == "PASS" else "❌"
        print(f"  {s:<22} {b:<16} {reg:>3} {o:>5} {rn:>4} {ev:>+7.2f} "
              f"{wr*100:>5.0f}%  {mark} {v}  — {why}")


def main():
    ev_floor = _argval("--ev-floor", EV_FLOOR)
    grace_min = _argval("--grace-min", GRACE_MIN)
    db = _load_db()

    docs = list(db.strategy_stats.find({}, {"_id": 0}))
    by_base = {}
    for d in docs:
        by_base[_base(d.get("setup_type"))] = d

    print(f"\n=== v320r-precheck EV-GATE CALIBRATION ===")
    print(f"strategy_stats docs: {len(docs)}   EV_FLOOR=+{ev_floor:.2f}R   "
          f"GRACE_MIN={grace_min} graded outcomes")
    print("(grded = alerts_triggered used by the gate; rN = len(r_outcomes) used "
          "to compute EV_R)")

    t1 = _row(db, TIER1, ev_floor, grace_min, by_base)
    _print("TIER-1 PROMOTION TARGETS (option A) — would these fire after the HIGH branch?",
           t1)
    _print("CONTEXT setups (base-stripped; not in option A)",
           _row(db, CONTEXT, ev_floor, grace_min, by_base))
    _print("CONTROL — daily setups that ALREADY auto-fire (must PASS, else gate is broken)",
           _row(db, CONTROL_DAILY, ev_floor, grace_min, by_base))

    # ---- global gate sanity: is the gate letting trades fire at all? ----
    g_pass = g_grace = g_proven = g_fail = 0
    for d in docs:
        v, why = _verdict(d, ev_floor, grace_min)
        if v == "PASS":
            g_pass += 1
            if "grace" in why:
                g_grace += 1
            else:
                g_proven += 1
        else:
            g_fail += 1
    print(f"\nGLOBAL GATE SANITY ({len(docs)} registered setups):")
    print(f"  PASS={g_pass}  (grace={g_grace}, proven-EV={g_proven})   FAIL={g_fail}")
    if g_pass == 0:
        print("  ⚠️ NOTHING passes → gate is globally blocking; investigate before promoting.")
    elif g_proven == 0 and g_grace > 0:
        print("  ⚠️ ALL passes are grace-only → no setup has yet PROVEN +EV; promotions will")
        print("     fire on the cold-start grace pass (expected for thin data; watch EV accrue).")

    # ---- verdict for option A ----
    t1_pass = [r for r in t1 if r[7] == "PASS"]
    t1_grace = [r for r in t1_pass if "grace" in r[8]]
    t1_proven = [r for r in t1_pass if "proven" in r[8]]
    t1_fail = [r for r in t1 if r[7] == "FAIL"]
    print("\n=== VERDICT FOR OPTION A ===")
    print(f"  Of {len(TIER1)} Tier-1 setups: {len(t1_pass)} would CLEAR the EV gate "
          f"({len(t1_proven)} on proven +EV, {len(t1_grace)} on cold-start grace), "
          f"{len(t1_fail)} would be EV-BLOCKED.")
    if t1_fail:
        print("  EV-blocked (promoting to HIGH is a NO-OP for these — gate stops them):")
        for r in t1_fail:
            print(f"     {r[0]:<20} {r[8]}")
    if t1_pass:
        print("  → promoting the PASS setups WILL produce intraday auto-fires when tape confirms.")
    if not t1_pass:
        print("  → ⚠️ NONE would fire; the EV gate would neutralize option A. Reconsider scope.")
    print("\nNOTE: a CONTROL daily setup showing FAIL/unregistered means its base name differs")
    print("in strategy_stats (e.g. directional split) — not necessarily a broken gate; confirm")
    print("by scanning the full docs list. The Tier-1 verdict above is what governs option A.\n")


if __name__ == "__main__":
    main()
