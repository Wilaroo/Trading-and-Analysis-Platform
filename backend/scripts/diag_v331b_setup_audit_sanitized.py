#!/usr/bin/env python3
"""
v331b — SANITIZED setup audit (READ-ONLY). Corrects v331's trade counts.

v331 counted RAW bot_trades, which mixes in (a) execution/reconciliation ARTIFACTS
(phantom/sweep/reconcile/instant-unwind/corrupt-PnL) and (b) ADOPTED/external
positions the bot merely attributed (a 30d audit found 46% of closes were adopted).
This version applies the SSOT hygiene tests — trade_outcome_hygiene.classify_close
(+is_adopted_entry) — and counts only GENUINE, BOT-OWN closes per setup. It also
prints the contamination breakdown and a field-coverage check so the mapping is auditable.

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v331b_setup_audit_sanitized.py --days 30
"""
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


def _g(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _hold_seconds(t):
    et, xt = _g(t, "entry_time", "opened_at", "created_at"), _g(t, "exit_time", "closed_at")
    for a, b in [(et, xt)]:
        try:
            da = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
            db = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
            return (db - da).total_seconds()
        except Exception:
            pass
    return _f(_g(t, "hold_seconds"))


def main():
    days = _arg("--days", 30, int)
    sys.path.insert(0, "backend")
    from services.trade_outcome_hygiene import classify_close, is_adopted_entry
    from services.setup_taxonomy import canonicalize, style_of, setup_class, is_edge_excluded
    from services.smb_integration import SETUP_REGISTRY

    reg_style = {canonicalize(n): getattr(getattr(c, "default_style", None), "value", None)
                 for n, c in SETUP_REGISTRY.items()}

    db = _load_db()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    fires = Counter()
    for a in db.live_alerts.find({"created_at": {"$gte": since}}, {"_id": 0, "setup_type": 1}):
        st = a.get("setup_type")
        if st:
            fires[canonicalize(st)] += 1

    raw = Counter(); genuine_own = Counter(); artifact = Counter(); adopted = Counter()
    cov = Counter(); ntot = 0
    cur = db.bot_trades.find({"created_at": {"$gte": since}})
    for t in cur:
        ntot += 1
        st = _g(t, "setup_type", "strategy") or "unknown"
        canon = canonicalize(st)
        raw[canon] += 1
        # field coverage probe
        for fld, keys in {"close_reason": ("close_reason", "exit_reason"),
                          "entered_by": ("entered_by", "entry_source", "source"),
                          "entry_price": ("entry_price", "fill_price", "avg_entry_price"),
                          "exit_price": ("exit_price", "avg_exit_price"),
                          "net_pnl": ("net_pnl", "pnl", "realized_pnl")}.items():
            if _g(t, *keys) is not None:
                cov[fld] += 1
        reason = _g(t, "close_reason", "exit_reason") or ""
        eb = _g(t, "entered_by", "entry_source", "source") or ""
        src = _g(t, "source") or ""
        tps = _g(t, "target_prices") or [x for x in [_g(t, "tp_price", "target", "target_price")] if x]
        genuine, tag = classify_close(
            close_reason=reason, entered_by=str(eb),
            entry_price=_f(_g(t, "entry_price", "fill_price", "avg_entry_price")),
            exit_price=_f(_g(t, "exit_price", "avg_exit_price")),
            net_pnl=_f(_g(t, "net_pnl", "pnl", "realized_pnl")),
            hold_seconds=_hold_seconds(t),
            setup_type=str(st),
            direction=str(_g(t, "direction") or "long"),
            stop_price=_f(_g(t, "stop_price", "stop_loss")),
            target_prices=tps,
            realized_pnl=_f(_g(t, "realized_pnl", "net_pnl", "pnl")),
            shares=_f(_g(t, "shares", "quantity")),
        )
        adopted_row = is_adopted_entry(entered_by=str(eb), source=str(src), close_reason=str(reason))
        if not genuine:
            artifact[canon] += 1
        elif adopted_row:
            adopted[canon] += 1
        else:
            genuine_own[canon] += 1

    names = sorted(set(reg_style) | set(fires) | set(raw))
    print(f"\n=== v331b SANITIZED setup audit — last {days}d  ({ntot} bot_trades rows) ===\n")
    print("  FIELD COVERAGE (mapping sanity): " +
          ", ".join(f"{k}={100*v//max(ntot,1)}%" for k, v in cov.items()))
    print()
    hdr = (f"  {'setup':<26}{'style':<11}{'fires':>6}{'rawTr':>6}{'GENUINE_OWN':>12}"
           f"{'artifact':>9}{'adopted':>8}  flags")
    print(hdr); print("  " + "-" * (len(hdr) + 4))
    real_find_no_trade = []
    for n in names:
        if is_edge_excluded(n):
            continue
        f, rw, go, ar, ad = fires.get(n, 0), raw.get(n, 0), genuine_own.get(n, 0), artifact.get(n, 0), adopted.get(n, 0)
        flags = []
        if f >= 20 and go == 0:
            flags.append("FIND-NO-GENUINE-TRADE")
            real_find_no_trade.append((n, f, rw, ar, ad))
        if rw > 0 and go == 0 and (ar + ad) > 0:
            flags.append("ALL-CONTAMINATED")
        print(f"  {n:<26}{reg_style.get(n) or '—':<11}{f:>6}{rw:>6}{go:>12}{ar:>9}{ad:>8}  {'; '.join(flags)}")

    tot_raw = sum(raw.values()); tot_go = sum(genuine_own.values())
    tot_ar = sum(artifact.values()); tot_ad = sum(adopted.values())
    print("\n" + "=" * 72)
    print("CONTAMINATION SUMMARY")
    print("=" * 72)
    print(f"  raw trades        : {tot_raw}")
    print(f"  GENUINE bot-own   : {tot_go}  ({100*tot_go//max(tot_raw,1)}%)")
    print(f"  artifact closes   : {tot_ar}  ({100*tot_ar//max(tot_raw,1)}%)")
    print(f"  adopted/external  : {tot_ad}  ({100*tot_ad//max(tot_raw,1)}%)")

    print("\nCORRECTED FIND-NO-TRADE (fires>=20, ZERO genuine bot-own trades):")
    for n, f, rw, ar, ad in sorted(real_find_no_trade, key=lambda x: -x[1]):
        note = f"(raw {rw}: {ar} artifact, {ad} adopted)" if rw else ""
        print(f"  {n:<26} {f} fires, 0 genuine {note}")

    print("\n=== READING ===")
    print("• GENUINE_OWN is the ONLY trustworthy trade count per setup (post-sanitization).")
    print("• Setups whose raw trades were ALL artifact/adopted = effectively never traded by")
    print("    the bot's own edge → treat as FIND-NO-TRADE for the sweep/triage.")
    print("• Compare GENUINE_OWN totals by style to see which TIERS the bot actually trades.\n")


if __name__ == "__main__":
    main()
