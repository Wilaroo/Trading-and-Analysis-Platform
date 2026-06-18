#!/usr/bin/env python3
"""diag_v371 (READ-ONLY) — PROVE trade_style fragmentation + locate where the
style diverges from the setup's canonical doctrine.

Context: v370 showed the SAME setup (second_chance, backside, gap_fade,
fashionably_late, ...) recorded under MANY styles (scalp/intraday/multi_day/
trade_2_hold), and EWT/IWF scalp-doctrine setups whose live_alert said
"intraday" but whose bot_trade said "scalp". This diag confirms the cause:
the scanner overrides a setup's canonical default_style by market context /
A+ at emission (enhanced_scanner _populate_smb_fields ~711-750), so a setup's
style — and therefore its geometry / EOD policy / R-target / caps — varies
trade-to-trade, making per-setup edge attribution untrustworthy.

Sections (NOTHING WRITTEN):
A) per setup_type → DISTINCT trade_styles stamped on GENUINE recent trades,
   with n / net_pnl per style + the CANONICAL style the taxonomy says it
   SHOULD be (SETUP_TO_STYLE). Flags setups carrying >1 style (fragmented).
B) alert→trade style JOIN by alert_id: for genuine recent trades, compare the
   originating live_alert.trade_style vs the recorded bot_trade.trade_style.
   Tallies MATCH vs DIVERGE and prints divergence examples.
C) summary: fragmented-setup count, divergence rate.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v371_style_fragmentation.py --days 21
"""
import sys
import os
from collections import defaultdict


def _arg(flag, d, c):
    if flag in sys.argv:
        try:
            return c(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return d
    return d


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


_GARBAGE = ("reconcil", "external", "phantom", "operator", "import", "orphan")


def _is_genuine(t):
    eb = str(t.get("entered_by") or "").lower()
    if any(g in eb for g in _GARBAGE):
        return False
    if str(t.get("trade_style") or "").lower() == "reconciled":
        return False
    return True


def _pnl(t):
    p = t.get("net_pnl")
    return p if isinstance(p, (int, float)) else (t.get("pnl") or 0.0)


def main():
    from datetime import datetime, timedelta, timezone
    days = _arg("--days", 21, int)
    # make `services.*` importable when run from repo root
    if os.path.isdir("backend") and "backend" not in sys.path:
        sys.path.insert(0, "backend")
    try:
        from services.trade_style_classifier import SETUP_TO_STYLE, resolve_trade_style
    except Exception as e:
        print(f"WARN: could not import trade_style_classifier ({e}); "
              f"canonical column will show 'n/a'")
        SETUP_TO_STYLE = {}
        resolve_trade_style = None

    db = _load_db()
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    proj = {"_id": 0, "setup_type": 1, "setup_variant": 1, "trade_style": 1,
            "entered_by": 1, "net_pnl": 1, "pnl": 1, "status": 1, "alert_id": 1,
            "symbol": 1, "closed_at": 1, "created_at": 1}
    rows = []
    for t in db["bot_trades"].find({"status": {"$in": ["closed", "open"]}}, proj):
        ca = t.get("closed_at") or t.get("created_at")
        if isinstance(ca, str) and ca < cut:
            continue
        if not _is_genuine(t):
            continue
        rows.append(t)

    # ── A) per setup_type → distinct styles ──────────────────────────────
    per_setup = defaultdict(lambda: defaultdict(lambda: {"n": 0, "pnl": 0.0}))
    for t in rows:
        su = (t.get("setup_type") or "?").strip().lower()
        st = (t.get("trade_style") or "?").strip().lower()
        per_setup[su][st]["n"] += 1
        per_setup[su][st]["pnl"] += _pnl(t)

    print(f"\n=== v371 A) trade_style per setup_type (GENUINE, last {days}d, "
          f"{len(rows)} trades) ===")
    print("  ⚠ = setup carries >1 style (fragmented → untrustworthy per-setup edge)")
    print(f"  {'setup_type':<26}{'canon':<11}{'styles stamped (n / netPnl)'}")
    frag = 0
    for su in sorted(per_setup, key=lambda s: -len(per_setup[s])):
        canon = SETUP_TO_STYLE.get(su, "n/a")
        styles = per_setup[su]
        flag = "⚠ " if len(styles) > 1 else "  "
        if len(styles) > 1:
            frag += 1
        parts = []
        for st, a in sorted(styles.items(), key=lambda kv: -kv[1]["n"]):
            mark = "" if (canon == "n/a" or st == canon) else "*"
            parts.append(f"{st}{mark}:{a['n']}/{a['pnl']:+.0f}")
        print(f"  {flag}{su:<24}{canon:<11}{'  '.join(parts)}")
    print("  (* = stamped style != canonical SETUP_TO_STYLE)")

    # ── B) alert→trade style JOIN by alert_id ────────────────────────────
    aids = [t.get("alert_id") for t in rows if t.get("alert_id")]
    alert_style = {}
    if aids:
        for a in db["live_alerts"].find(
                {"alert_id": {"$in": aids}},
                {"_id": 0, "alert_id": 1, "trade_style": 1, "setup_type": 1}):
            alert_style[a.get("alert_id")] = (a.get("trade_style") or "?").strip().lower()
        # some stores key the alert under `id`
        if len(alert_style) < len(set(aids)):
            for a in db["live_alerts"].find(
                    {"id": {"$in": aids}},
                    {"_id": 0, "id": 1, "trade_style": 1}):
                alert_style.setdefault(a.get("id"),
                                       (a.get("trade_style") or "?").strip().lower())

    match = diverge = no_alert = 0
    examples = []
    for t in rows:
        aid = t.get("alert_id")
        a_st = alert_style.get(aid)
        if a_st is None:
            no_alert += 1
            continue
        tr_st = (t.get("trade_style") or "?").strip().lower()
        if a_st == tr_st:
            match += 1
        else:
            diverge += 1
            if len(examples) < 20:
                examples.append((t.get("symbol"), t.get("setup_type"), a_st, tr_st))

    print(f"\n=== v371 B) alert→trade style JOIN (by alert_id) ===")
    print(f"  matched alert+trade rows : {match + diverge}  "
          f"(no matching alert: {no_alert})")
    print(f"  STYLE MATCH   : {match}")
    print(f"  STYLE DIVERGE : {diverge}"
          + (f"  ({100*diverge/(match+diverge):.0f}%)" if (match + diverge) else ""))
    for sym, su, a_st, tr_st in examples:
        print(f"    {sym:<6} {su:<22} alert={a_st:<12} -> trade={tr_st}")

    # ── C) summary ───────────────────────────────────────────────────────
    print(f"\n=== v371 C) summary ===")
    print(f"  setups carrying >1 style (fragmented): {frag} / {len(per_setup)}")
    print(f"  alert→trade style divergence: {diverge} / {match + diverge}")
    print("\n=== READING ===")
    print("• If A) shows the SAME setup under multiple styles, per-setup edge is")
    print("  un-attributable: each style drives different geometry/EOD/R-target/caps.")
    print("• If B) divergence is high, the style is being RE-DERIVED between alert")
    print("  emission and trade-create (context/A+ override in _populate_smb_fields,")
    print("  vs the alert.trade_style threaded into the evaluator at line ~1737).")
    print("• Canonical target per setup = SETUP_TO_STYLE (trade_style_classifier).\n")


if __name__ == "__main__":
    main()
