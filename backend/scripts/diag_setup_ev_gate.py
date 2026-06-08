#!/usr/bin/env python3
"""
SETUP EV-GATE TABLE (read-only) — which setups CAN auto-execute, and which the
EV gate blocks, with the real numbers the gate reads.

The v19.34.293 auto-exec EV gate (per setup `base`):
  • not in strategy_stats          → FAIL  (no_strategy_stats)
  • alerts_triggered < grace_min(20)→ PASS  (cold-start grace: fire on priority+tape)
  • alerts_triggered >= 20          → PASS only if expected_value_r > min_ev_r(0.10)

This dumps the `strategy_stats` collection sorted by EV, showing per setup:
  outcomes (alerts_triggered), win_rate, avg_win_r, avg_loss_r, expected_value_r,
  and the GATE VERDICT (GRACE / PASS / BLOCK-EV). Use it to tell apart:
   - "few positive-EV setups" (gate correct; surface/learn more) vs
   - "a quality setup shows EV<=0.10 that shouldn't" (EV miscalibration / commission drag).

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_setup_ev_gate.py
"""
from pymongo import MongoClient

GRACE_MIN = 20      # _win_rate_grace_min_trades
MIN_EV_R = 0.10     # _auto_execute_min_ev_r

# With-trend "quality" setups (AGENTS.md §16) — flagged so a wrongly-blocked one stands out.
QUALITY = {
    "9_ema_scalp", "vwap_continuation", "big_dog", "hod_breakout", "second_chance",
    "the_3_30_trade", "first_vwap_pullback", "gap_give_go", "premarket_high_break",
    "range_break", "bouncy_ball", "hitchhiker", "back_through_open", "spencer_scalp",
    "power_trend_stack", "rs_leader_breakout", "pocket_pivot", "stage_2_breakout",
}


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _verdict(outcomes, ev):
    if outcomes < GRACE_MIN:
        return "GRACE"          # cold-start: can fire on priority+tape alone
    return "PASS" if ev > MIN_EV_R else "BLOCK-EV"


def main():
    db = _load_db()
    rows = list(db.strategy_stats.find({}, {"_id": 0}))
    if not rows:
        print("strategy_stats is EMPTY — every setup hits 'no_strategy_stats' and "
              "CANNOT auto-execute. The learning loop hasn't populated stats. That alone "
              "explains zero trades.")
        return

    enriched = []
    for d in rows:
        s = d.get("setup_type", "?")
        o = int(d.get("alerts_triggered", 0) or 0)
        ev = float(d.get("expected_value_r", 0.0) or 0.0)
        enriched.append({
            "setup": s, "outcomes": o,
            "win_rate": float(d.get("win_rate", 0.0) or 0.0),
            "avg_win_r": float(d.get("avg_win_r", 0.0) or 0.0),
            "avg_loss_r": float(d.get("avg_loss_r", 0.0) or 0.0),
            "ev": ev, "verdict": _verdict(o, ev),
        })

    enriched.sort(key=lambda r: r["ev"], reverse=True)

    print(f"SETUP EV-GATE TABLE  (grace_min={GRACE_MIN}, min_ev_r=+{MIN_EV_R:.2f}R)\n")
    print(f"{'setup':<26}{'out':>4}{'win%':>6}{'avgW':>7}{'avgL':>7}{'EV(R)':>8}  verdict")
    print("-" * 78)
    counts = {"GRACE": 0, "PASS": 0, "BLOCK-EV": 0}
    for r in enriched:
        counts[r["verdict"]] += 1
        q = " ★" if r["setup"] in QUALITY else ""
        flag = ""
        if r["verdict"] == "BLOCK-EV" and r["setup"] in QUALITY:
            flag = "  <<< QUALITY setup blocked on EV — verify the stat is trustworthy"
        print(f"{r['setup']:<26}{r['outcomes']:>4}{r['win_rate']*100:>6.0f}"
              f"{r['avg_win_r']:>7.2f}{r['avg_loss_r']:>7.2f}{r['ev']:>+8.2f}  "
              f"{r['verdict']}{q}{flag}")

    eligible = [r for r in enriched if r["verdict"] in ("GRACE", "PASS")]
    print(f"\nSUMMARY: {counts['PASS']} PASS (proven +EV), {counts['GRACE']} GRACE "
          f"(cold, can fire), {counts['BLOCK-EV']} BLOCK-EV (proven weak).")
    print(f"→ {len(eligible)} setups are EV-eligible to auto-execute "
          f"(still need HIGH/CRITICAL priority + tape confirmation at signal time).")
    q_pass = [r['setup'] for r in eligible if r['setup'] in QUALITY]
    print(f"→ EV-eligible QUALITY (with-trend) setups: "
          f"{', '.join(q_pass) if q_pass else 'NONE — this is why good trades rarely fire'}")


if __name__ == "__main__":
    main()
