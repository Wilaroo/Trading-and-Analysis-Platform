#!/usr/bin/env python3
"""
v331 — SETUP CATEGORY / STYLE / TEMPLATE AUDIT (READ-ONLY)

Answers two operator asks (2026-06):
  1. "Are certain scalps tagged as intraday (or vice-versa)? Do we need to
     recategorize?"  -> compares each setup's REGISTRY default_style
     (smb_integration.SETUP_REGISTRY) against the SSOT resolved style
     (setup_taxonomy.style_of) and against live behavior (fire counts), and
     flags mismatches.
  2. "Generalize the find->trade-replay->rewrite template to all scalps."
     -> splits the scalps into FADE-class (the v329/v330 SNAPBACK template
     applies directly) vs MOMENTUM-class (needs a CONTINUATION replay template),
     so the sweep uses the right geometry per setup.

Pulls the SSOT live (truth), then joins last-N-day fire counts from live_alerts
and trade counts from bot_trades. NOTHING IS WRITTEN.

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v331_setup_category_audit.py --days 30
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
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
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def main():
    days = _arg("--days", 30, int)
    sys.path.insert(0, "backend")

    # --- SSOT imports (truth) ---
    from services.setup_taxonomy import (
        canonicalize, style_of, setup_class, strategy_family, exit_archetype_prior)
    from services.smb_integration import SETUP_REGISTRY

    reg = {}
    for name, cfg in SETUP_REGISTRY.items():
        ds = getattr(cfg, "default_style", None)
        cat = getattr(cfg, "category", None)
        reg[canonicalize(name)] = {
            "default_style": getattr(ds, "value", str(ds)),
            "smb_category": getattr(cat, "value", str(cat)),
        }

    db = _load_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    fires = Counter()
    for a in db.live_alerts.find({"created_at": {"$gte": since}}, {"_id": 0, "setup_type": 1}):
        st = a.get("setup_type")
        if st:
            fires[canonicalize(st)] += 1
    trades = Counter()
    for t in db.bot_trades.find({"created_at": {"$gte": since}}, {"_id": 0, "setup_type": 1, "strategy": 1}):
        st = t.get("setup_type") or t.get("strategy")
        if st:
            trades[canonicalize(st)] += 1

    names = sorted(set(reg) | set(fires) | set(trades))

    print(f"\n=== v331 SETUP CATEGORY / STYLE / TEMPLATE AUDIT — last {days}d ===\n")
    hdr = (f"  {'setup':<26}{'reg_style':<11}{'ssot_style':<11}{'class':<9}"
           f"{'family':<13}{'fires':>6}{'trades':>7}  flags")
    print(hdr)
    print("  " + "-" * (len(hdr) + 6))

    by_style = defaultdict(list)
    mismatches, find_no_trade = [], []
    for n in names:
        r = reg.get(n, {})
        reg_style = r.get("default_style", "—")
        ssot_style = style_of(n)
        cls = setup_class(n)
        fam = strategy_family(n)
        f = fires.get(n, 0)
        tr = trades.get(n, 0)
        flags = []
        if reg_style != "—" and ssot_style and reg_style != ssot_style:
            flags.append(f"STYLE: reg={reg_style}!=ssot={ssot_style}")
            mismatches.append((n, reg_style, ssot_style))
        if f >= 20 and tr == 0:
            flags.append("FIND-NO-TRADE")
            find_no_trade.append((n, f))
        by_style[reg_style].append(n)
        print(f"  {n:<26}{reg_style:<11}{ssot_style:<11}{cls:<9}{fam:<13}"
              f"{f:>6}{tr:>7}  {'; '.join(flags)}")

    print("\n" + "=" * 72)
    print("SCALP TEMPLATE SPLIT (which replay geometry the rewrite sweep needs)")
    print("=" * 72)
    scalps = [n for n in names if reg.get(n, {}).get("default_style") == "scalp"]
    fade = [n for n in scalps if setup_class(n) == "fade"]
    mom = [n for n in scalps if setup_class(n) == "momentum"]
    other = [n for n in scalps if setup_class(n) not in ("fade", "momentum")]
    print(f"  FADE-class scalps  (snapback template v329/v330 applies): {len(fade)}")
    print("     " + ", ".join(fade))
    print(f"  MOMENTUM-class scalps (need CONTINUATION replay template): {len(mom)}")
    print("     " + ", ".join(mom))
    if other:
        print(f"  OTHER/unclassified: {', '.join(other)}")

    print("\n" + "=" * 72)
    print("STYLE MISMATCHES (registry default_style vs SSOT style_of)")
    print("=" * 72)
    if mismatches:
        for n, rs, ss in mismatches:
            print(f"  {n:<26} registry={rs:<10} ssot={ss}")
    else:
        print("  none — registry and SSOT agree on every setup's style.")

    print("\nFIND-NO-TRADE (fires>=20 in window but 0 trades — detector fires, nothing executes):")
    if find_no_trade:
        for n, f in sorted(find_no_trade, key=lambda x: -x[1]):
            print(f"  {n:<26} {f} fires, 0 trades")
    else:
        print("  none")

    print("\nCOUNTS BY REGISTRY STYLE:")
    for s in ("scalp", "intraday", "multi_day", "swing", "investment", "position", "—"):
        if by_style.get(s):
            print(f"  {s:<11} {len(by_style[s])}: {', '.join(by_style[s])}")

    print("\n=== READING THE RESULT ===")
    print("• STYLE mismatch rows = candidates to recategorize (or fix the registry/SSOT).")
    print("• FADE scalps → reuse the v329/v330 snapback replay+rewrite as-is.")
    print("• MOMENTUM scalps → build a CONTINUATION replay (entry on consolidation-break,")
    print("    stop below pullback low, target=measured-move/trail) before rewriting them.")
    print("• FIND-NO-TRADE = detector emits but the gate/exec blocks → triage post-v328.\n")


if __name__ == "__main__":
    main()
