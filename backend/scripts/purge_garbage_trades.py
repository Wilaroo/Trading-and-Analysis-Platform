#!/usr/bin/env python3
"""
purge_garbage_trades.py — REVERSIBLE archive-then-purge of GARBAGE bot_trades
older than a cutoff, defined by the CANONICAL hygiene sanitizer so the
genuine "sanitized trades list" is provably never touched.

Definition (back-checked against the sanitizer used by the TQS edge diags):
  • KEEP  = genuine survivors (closed trades that PASS the full hygiene funnel)
            — i.e. EXACTLY the sanitized list. These are never in the delete set.
  • PURGE = everything else pre-cutoff: hygiene artifacts (broken-path) + never-
            filled / no-exit / no-risk / sub-10s / absurd-R, plus non-closed dead
            intents (cancelled/rejected/pending that never became a real trade).
  • By DEFAULT, real-but-non-bot rows are SPARED: provenance (adopted/external)
    + simulated + learning_only are KEPT unless you add them via --also.

Each purged doc is first copied (original _id) to  bot_trades__garbage_pre_<date>
then deleted. Restore anytime with --rollback. Default is a SAFE DRY-RUN.

USAGE (repo root, DGX):
  .venv/bin/python backend/scripts/purge_garbage_trades.py --before 2026-06-01
  .venv/bin/python backend/scripts/purge_garbage_trades.py --before 2026-06-01 --confirm
  .venv/bin/python backend/scripts/purge_garbage_trades.py --before 2026-06-01 --rollback --confirm
  # widen what counts as garbage (e.g. also wipe adopted + shadow):
  .venv/bin/python backend/scripts/purge_garbage_trades.py --before 2026-06-01 --also provenance,simulated,learning_only
"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BROKEN_PATH = {  # default garbage set (clearly junk / broken-path)
    "hygiene_artifact", "never_filled", "no_exit_price", "no_risk",
    "sub_10s_hold", "absurd_r", "legacy_orphan",
}
SPARED_BY_DEFAULT = {"provenance", "simulated", "learning_only", "admin_close"}
BOT_PROVENANCE = {"bot_fired", "bot", "", None}
ADMIN_CLOSE_PREFIXES = (
    "stale_pending", "phantom_sibling_purge", "consolidated", "broker_rejected",
    "execution_exception", "guardrail_veto", "intent_already_pending",
    "rejection_cooldown", "symbol_cooldown", "paper_phase", "simulation_phase",
    "operator_flatten_suppression", "emergency_flatten",
)
BATCH = 1000


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
    pnl = t.get("net_pnl") or t.get("realized_pnl") or t.get("pnl")
    risk = _f(t.get("risk_amount"))
    pnl = _f(pnl)
    return pnl / risk if (pnl is not None and risk) else None


def classify(t, classify_close):
    """Return 'genuine' (KEEP) or an exclusion-reason string (candidate garbage)."""
    status = str(t.get("status") or "")
    if not status.startswith("closed"):
        return f"non_closed:{status or 'unknown'}"
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
    g, _ = classify_close(
        close_reason=cr, entered_by=str(t.get("entered_by") or ""),
        entry_price=_f(t.get("fill_price")) or _f(t.get("entry_price")),
        exit_price=_f(t.get("exit_price")), net_pnl=_f(t.get("net_pnl")),
        hold_seconds=_f(t.get("hold_seconds")), setup_type=str(t.get("setup_type") or ""),
        direction=t.get("direction"), stop_price=_f(t.get("stop_price")),
        target_prices=t.get("target_prices"), realized_pnl=_f(t.get("realized_pnl")),
        shares=_f(t.get("shares")))
    if not g:
        return "hygiene_artifact"
    if (_f(t.get("fill_price")) or _f(t.get("entry_price")) or 0) <= 0 or (_f(t.get("shares")) or 0) <= 0:
        return "never_filled"
    if (_f(t.get("exit_price")) or 0) <= 0:
        return "no_exit_price"
    if (_f(t.get("risk_amount")) or 0) <= 0:
        return "no_risk"
    hs = _f(t.get("hold_seconds"))
    if hs is not None and hs < 10:
        return "sub_10s_hold"
    r = _r_multiple(t)
    if r is not None and abs(r) > 10:
        return "absurd_r"
    return "genuine"


def main():
    cutoff = "2026-06-01"
    confirm = "--confirm" in sys.argv
    rollback = "--rollback" in sys.argv
    extra = set()
    if "--before" in sys.argv:
        try: cutoff = sys.argv[sys.argv.index("--before") + 1]
        except Exception: pass
    if "--also" in sys.argv:
        try: extra = {x.strip() for x in sys.argv[sys.argv.index("--also") + 1].split(",") if x.strip()}
        except Exception: pass
    cutoff_iso = cutoff if "T" in cutoff else cutoff + "T00:00:00+00:00"
    garbage_reasons = set(BROKEN_PATH) | (extra & SPARED_BY_DEFAULT)

    backend = _find_backend()
    _load_env(backend)
    sys.path.insert(0, str(backend))
    from services.trade_outcome_hygiene import classify_close
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    compact = cutoff.split("T")[0].replace("-", "")
    arch_name = f"bot_trades__garbage_pre_{compact}"

    print("=" * 84)
    print(f"purge_garbage_trades  cutoff={cutoff}  mode={'EXECUTE' if confirm else 'DRY-RUN'}"
          f"{'  ROLLBACK' if rollback else ''}")
    print(f"  garbage reasons: {sorted(garbage_reasons)}")
    print(f"  spared (kept): genuine + {sorted(SPARED_BY_DEFAULT - garbage_reasons)}")
    print(f"  DB={os.environ.get('DB_NAME','tradecommand')}  {datetime.now(timezone.utc).isoformat()[:19]}Z")
    print("=" * 84)

    if rollback:
        if arch_name not in set(db.list_collection_names()):
            print(f"  no archive {arch_name} — nothing to restore."); return
        docs = list(db[arch_name].find({}))
        print(f"  archive {arch_name} has {len(docs)} docs")
        if not confirm:
            print("  DRY-RUN: would restore all back into bot_trades."); return
        for i in range(0, len(docs), BATCH):
            db["bot_trades"].insert_many(docs[i:i+BATCH], ordered=False)
        print(f"  restored {len(docs)} → bot_trades (archive left in place; drop manually)")
        return

    pre = list(db["bot_trades"].find(
        {"created_at": {"$lt": cutoff_iso}},
        {"_id": 1, "status": 1, "entered_by": 1, "learning_only": 1,
         "entry_context.learning_only": 1, "notes": 1, "trade_type": 1,
         "close_reason": 1, "fill_price": 1, "entry_price": 1, "exit_price": 1,
         "shares": 1, "risk_amount": 1, "net_pnl": 1, "realized_pnl": 1, "pnl": 1,
         "hold_seconds": 1, "setup_type": 1, "direction": 1, "stop_price": 1,
         "target_prices": 1}))
    reason_counts = Counter()
    del_ids, genuine_ids = [], []
    for t in pre:
        r = classify(t, classify_close)
        reason_counts[r] += 1
        if r == "genuine":
            genuine_ids.append(t["_id"])
        elif r in garbage_reasons or r.startswith("non_closed:"):
            del_ids.append(t["_id"])
    # safety: delete set must NOT intersect genuine set
    assert not (set(del_ids) & set(genuine_ids)), "SAFETY VIOLATION: genuine in delete set"

    print(f"\n  pre-cutoff bot_trades: {len(pre)}")
    print(f"  {'classification':<26}{'count':>8}{'action':>10}")
    for r, c in reason_counts.most_common():
        act = "KEEP" if r == "genuine" else ("PURGE" if (r in garbage_reasons or r.startswith("non_closed:")) else "keep")
        # collapse non_closed:* display
        print(f"  {r[:26]:<26}{c:>8}{act:>10}")
    kept_genuine = len(genuine_ids)
    print(f"\n  → GENUINE survivors KEPT (your sanitized list): {kept_genuine}  [BACK-CHECK: never deleted]")
    print(f"  → GARBAGE to purge: {len(del_ids)}")

    if not confirm:
        print(f"\n  DRY-RUN — nothing written. Re-run with --confirm to archive+delete {len(del_ids)}.")
        return
    if not del_ids:
        print("\n  nothing to purge."); return
    # archive then delete, in batches
    archived = 0
    for i in range(0, len(del_ids), BATCH):
        chunk = del_ids[i:i+BATCH]
        docs = list(db["bot_trades"].find({"_id": {"$in": chunk}}))
        if docs:
            db[arch_name].insert_many(docs, ordered=False)
            archived += len(docs)
    arch_cnt = db[arch_name].count_documents({})
    print(f"\n  archived {archived} → {arch_name} (archive now {arch_cnt})")
    if arch_cnt < len(del_ids):
        print(f"  ❌ archive {arch_cnt} < delete {len(del_ids)} — NOT deleting. Investigate."); return
    res = db["bot_trades"].delete_many({"_id": {"$in": del_ids}})
    remaining_genuine = db["bot_trades"].count_documents(
        {"_id": {"$in": genuine_ids}}) if genuine_ids else 0
    print(f"  deleted {res.deleted_count} garbage from bot_trades")
    print(f"  genuine survivors still present: {remaining_genuine}/{kept_genuine}  "
          f"({'✅ intact' if remaining_genuine == kept_genuine else '⚠ MISMATCH'})")
    print(f"\n  Done. Reversible via --rollback. Archive: {arch_name} (drop manually when satisfied).")


if __name__ == "__main__":
    main()
