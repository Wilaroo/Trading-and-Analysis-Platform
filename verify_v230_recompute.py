#!/usr/bin/env python3
"""
verify_v230_recompute.py  (READ-ONLY, offline before/after)

Proves the v19.34.230 de-compression works by RE-SCORING the same recent
live_alerts with the flags OFF (legacy) vs ON (decompress) — isolating exactly
the two changed pillars (Setup A1/A2, Execution B3). No waiting for market hours;
nothing is written.

For each sampled alert we recompute:
  • Setup pillar OFF vs ON   (varies per alert: risk_reward / smb / tape / WR)
  • Execution pillar OFF vs ON (varies by setup_type via the B3 history map;
    global tilt/streak are constant right now, so exec_ON-exec_OFF isolates B3)
Then project the new composite = stored_tqs + w_setup*(setupON-setupOFF)
                                            + w_exec*(execON-execOFF).

USAGE on the DGX (MUST use the venv — imports backend services):
    curl -s https://paste.rs/XXXX -o /tmp/verify_v230.py
    ~/Trading-and-Analysis-Platform/.venv/bin/python /tmp/verify_v230.py 2
    # arg = lookback days (default 2). Add a 2nd arg to cap the sample, e.g. ... 2 1500
"""
import asyncio
import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone


def _find_repo():
    for cand in (os.getcwd(), os.path.dirname(os.path.abspath(__file__)),
                 os.path.expanduser("~/Trading-and-Analysis-Platform")):
        cur = cand
        for _ in range(8):
            if os.path.isfile(os.path.join(cur, "backend", "server.py")):
                return cur
            p = os.path.dirname(cur)
            if p == cur:
                break
            cur = p
    raise SystemExit("ERROR: repo root not found (need backend/server.py).")


REPO = _find_repo()
sys.path.insert(0, os.path.join(REPO, "backend"))

# load MONGO_URL / DB_NAME from backend/.env if not exported
if not os.environ.get("MONGO_URL"):
    envp = os.path.join(REPO, "backend", ".env")
    if os.path.isfile(envp):
        for line in open(envp):
            line = line.strip()
            if line.startswith("MONGO_URL="):
                os.environ["MONGO_URL"] = line.split("=", 1)[1]
            elif line.startswith("DB_NAME="):
                os.environ["DB_NAME"] = line.split("=", 1)[1]

from pymongo import MongoClient  # noqa: E402
from services.tqs.setup_quality import get_setup_quality_service  # noqa: E402
from services.tqs import execution_quality as eqmod  # noqa: E402


def _pct(s, p):
    if not s:
        return None
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k); hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _row(label, vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return f"  {label:<26} n=0 (no data)"
    s = sorted(vals)
    return (f"  {label:<26} n={len(s):<5} min={s[0]:6.1f}  med={_pct(s,50):6.1f}  "
            f"mean={st.mean(s):6.1f}  max={s[-1]:6.1f}  stdev={(st.pstdev(s) if len(s)>1 else 0):5.2f}")


async def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
    db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=2500)[
        os.environ.get("DB_NAME") or "tradecommand"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = list(db["live_alerts"].find(
        {"created_at": {"$gte": cutoff}, "tqs_score": {"$gt": 0}},
        {"setup_type": 1, "direction": 1, "trade_style": 1, "tape_score": 1,
         "tape_confirmation": 1, "trade_grade": 1, "smb_score_total": 1,
         "risk_reward": 1, "priority": 1, "strategy_win_rate": 1, "strategy_ev_r": 1,
         "tqs_score": 1, "tqs_pillar_scores": 1, "tqs_weights": 1, "_id": 0},
    ).limit(cap))
    print("=" * 80)
    print(f"v19.34.230 RECOMPUTE (offline) — {len(rows)} alerts since {cutoff} ({days}d)")
    print("=" * 80)
    if not rows:
        print("No alerts in window."); return

    setup_svc = get_setup_quality_service()

    def setenv(on):
        v = "1" if on else "0"
        os.environ["TQS_SETUP_DECOMPRESS"] = v
        os.environ["TQS_EXEC_DECOMPRESS"] = v

    # ---- execution per unique base setup_type (ON & OFF) ----
    def base(stp):
        return (stp or "").lower().replace("_long", "").replace("_short", "")
    uniq = sorted({base(r.get("setup_type")) for r in rows if r.get("setup_type")})
    exec_cache = {}
    for on in (False, True):
        setenv(on)
        eqmod._HIST_CACHE["map"] = {}; eqmod._HIST_CACHE["fetched_at"] = 0.0
        for b in uniq:
            res = await eqmod.get_execution_quality_service().calculate_score(symbol="X", setup_type=b)
            exec_cache.setdefault(b, {})[on] = res.score

    # ---- setup per alert (ON & OFF) + composite projection ----
    setup_off, setup_on = [], []
    exec_off, exec_on = [], []
    comp_old, comp_new = [], []
    for r in rows:
        stp = r.get("setup_type") or "unknown"
        kw = dict(
            setup_type=stp, symbol="X",
            tape_score=float(r.get("tape_score") or 0),
            tape_confirmation=bool(r.get("tape_confirmation")),
            smb_grade=r.get("trade_grade"),
            smb_5var_score=int(r.get("smb_score_total") or 25),
            risk_reward=float(r.get("risk_reward") or 2.0),
            alert_priority=str(r.get("priority") or "medium"),
            win_rate_override=(r.get("strategy_win_rate") or None),
            ev_r_override=(r.get("strategy_ev_r") or None),
        )
        setenv(False)
        soff = (await setup_svc.calculate_score(**kw)).score
        setenv(True)
        son = (await setup_svc.calculate_score(**kw)).score
        setup_off.append(soff); setup_on.append(son)

        b = base(stp)
        eoff = exec_cache.get(b, {}).get(False, 60.0)
        eon = exec_cache.get(b, {}).get(True, 60.0)
        exec_off.append(eoff); exec_on.append(eon)

        w = r.get("tqs_weights") or {}
        w_setup = float(w.get("setup", 0.25)); w_exec = float(w.get("execution", 0.15))
        old_c = float(r.get("tqs_score"))
        new_c = old_c + w_setup * (son - soff) + w_exec * (eon - eoff)
        comp_old.append(old_c); comp_new.append(new_c)

    setenv(True)  # leave flags on
    print("\n[SETUP pillar]   OFF (legacy)  vs  ON (decompress)")
    print(_row("setup OFF", setup_off))
    print(_row("setup ON ", setup_on))
    print("\n[EXECUTION pillar]   OFF  vs  ON")
    print(_row("exec OFF", exec_off))
    print(_row("exec ON ", exec_on))
    print("\n[COMPOSITE]   stored(old)  vs  projected(new)")
    print(_row("composite OLD", comp_old))
    print(_row("composite NEW", comp_new))

    so, sn = st.pstdev(setup_off), st.pstdev(setup_on)
    co, cn = st.pstdev(comp_old), st.pstdev(comp_new)
    print("\n[SUMMARY]")
    print(f"  setup stdev     {so:5.2f} → {sn:5.2f}   ({'+' if sn>=so else ''}{sn-so:.2f})")
    print(f"  setup max       {max(setup_off):5.1f} → {max(setup_on):5.1f}")
    print(f"  composite stdev {co:5.2f} → {cn:5.2f}   ({'+' if cn>=co else ''}{cn-co:.2f})")
    print(f"  composite med   {_pct(sorted(comp_old),50):5.1f} → {_pct(sorted(comp_new),50):5.1f}")

    # show per-setup exec history spread (B3)
    print("\n[EXEC by setup_type]  (B3 — history now varies by setup)")
    for b in uniq[:14]:
        c = exec_cache.get(b, {})
        print(f"  {b:<26} OFF={c.get(False,60):5.1f}  ON={c.get(True,60):5.1f}")
    print("\nDONE (read-only). Flags left ON.")


if __name__ == "__main__":
    asyncio.run(main())
