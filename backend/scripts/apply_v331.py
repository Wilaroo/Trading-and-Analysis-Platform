#!/usr/bin/env python3
"""
apply_v331.py — manual universe pin + SPCX onboarding
======================================================
Operator: "$SPCX just IPO'd today — does our system automatically add
IPOs to our scans?"

ANSWER — No. The scan universe is `symbol_adv_cache` rows with
avg_dollar_volume >= $50M, rebuilt nightly FROM STORED DAILY BARS. A
day-one IPO has no bars in our DB, so it never gets an ADV row — and
collection only targets symbols ALREADY in the cache, so its bars never
get collected either. Chicken-and-egg: IPOs are invisible forever
unless something seeds them.

v331 adds the missing mechanism — `manual_universe_pin`:
  • pinned symbols are ALWAYS in every scan universe (any tier),
    regardless of ADV;
  • immune to `unqualifiable` promotion (fresh listings often fail IB
    qualification transiently in their first sessions);
  • automatically included in the pusher L1 priority stream (live
    ticks are the only data a bar-less symbol has);
  • once its first daily bars are collected, the nightly ADV rebuild
    fills in real tier/ADV ($set-only — the pin flag survives);
  • helpers: pin_symbol(db, sym, reason) / unpin_symbol(db, sym).

DB phase:
  1. pins SPCX (reason: "IPO 2026-06-12 — operator preferred");
  2. queues IB backfill requests for SPCX (1 day / 1 hour / 15 mins /
     5 mins / 1 min, 5-day lookback) so history starts building the
     moment the pusher serves them (short durations — NOT held by the
     v328 RTH gate).

SAFE TO RUN MULTIPLE TIMES (idempotent — re-pin is a no-op upsert,
queue requests dedup via skip_if_pending).
Run from repo root:   .venv/bin/python /tmp/apply_v331.py
Files-only (no DB):   .venv/bin/python /tmp/apply_v331.py --files-only
Then: git add -A && git commit -m "v331: manual universe pin + SPCX" && git push
Then restart the backend (scanner watchlist refresh picks up the pin).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CHUNKS = [
    ('backend/services/symbol_universe.py',
     '\n    Excludes `unqualifiable=true` symbols by default. Set\n    `include_unqualifiable=True` only for diagnostics.\n    """\n    if db is None:\n        return set()\n',
     '\n    Excludes `unqualifiable=true` symbols by default. Set\n    `include_unqualifiable=True` only for diagnostics.\n\n    v331 — rows with `manual_universe_pin: true` are ALWAYS included\n    regardless of ADV (operator pins, e.g. day-one IPOs like SPCX that\n    have no daily bars yet so no avg_dollar_volume).\n    """\n    if db is None:\n        return set()\n'),
    ('backend/services/symbol_universe.py',
     '    if tier_key not in DOLLAR_VOL_THRESHOLDS:\n        raise ValueError(f"Unknown tier: {tier!r}; must be one of "\n                         f"{list(DOLLAR_VOL_THRESHOLDS) + [\'all\']}")\n    threshold = DOLLAR_VOL_THRESHOLDS[tier_key]\n\n    query: Dict[str, Any] = {"avg_dollar_volume": {"$gte": threshold}}\n    if not include_unqualifiable:\n        query["unqualifiable"] = {"$ne": True}\n\n    cursor = db["symbol_adv_cache"].find(query, {"symbol": 1, "_id": 0})\n    return {d["symbol"] for d in cursor if d.get("symbol")}\n',
     '    if tier_key not in DOLLAR_VOL_THRESHOLDS:\n        raise ValueError(f"Unknown tier: {tier!r}; must be one of "\n                         f"{list(DOLLAR_VOL_THRESHOLDS) + [\'all\']}")\n    threshold = DOLLAR_VOL_THRESHOLDS[tier_key]\n\n    query: Dict[str, Any] = {"$or": [\n        {"avg_dollar_volume": {"$gte": threshold}},\n        {"manual_universe_pin": True},\n    ]}\n    if not include_unqualifiable:\n        query["unqualifiable"] = {"$ne": True}\n\n    cursor = db["symbol_adv_cache"].find(query, {"symbol": 1, "_id": 0})\n    return {d["symbol"] for d in cursor if d.get("symbol")}\n'),
    ('backend/services/symbol_universe.py',
     '    if tier_key not in DOLLAR_VOL_THRESHOLDS:\n        raise ValueError(f"Unknown tier: {tier!r}; must be one of "\n                         f"{list(DOLLAR_VOL_THRESHOLDS) + [\'all\']}")\n    threshold = DOLLAR_VOL_THRESHOLDS[tier_key]\n\n    query: Dict[str, Any] = {"avg_dollar_volume": {"$gte": threshold}}\n    if not include_unqualifiable:\n        query["unqualifiable"] = {"$ne": True}\n\n    cursor = (db["symbol_adv_cache"]\n              .find(query, {"symbol": 1, "_id": 0})\n',
     '    if tier_key not in DOLLAR_VOL_THRESHOLDS:\n        raise ValueError(f"Unknown tier: {tier!r}; must be one of "\n                         f"{list(DOLLAR_VOL_THRESHOLDS) + [\'all\']}")\n    threshold = DOLLAR_VOL_THRESHOLDS[tier_key]\n\n    # v331 — manual pins always included (sort by ADV puts no-ADV pins last).\n    query: Dict[str, Any] = {"$or": [\n        {"avg_dollar_volume": {"$gte": threshold}},\n        {"manual_universe_pin": True},\n    ]}\n    if not include_unqualifiable:\n        query["unqualifiable"] = {"$ne": True}\n\n    cursor = (db["symbol_adv_cache"]\n              .find(query, {"symbol": 1, "_id": 0})\n'),
    ('backend/services/symbol_universe.py',
     '        ]\n\n    extra_priority = extra_priority or []\n\n    # Pull top-N by avg_dollar_volume (qualified + non-unqualifiable only).\n    # v322n — over-fetch then drop bond/cash, income, index clones and\n',
     '        ]\n\n    extra_priority = extra_priority or []\n\n    # v331 — operator-pinned symbols (manual_universe_pin, e.g. day-one\n    # IPOs) are always L1-streamed: a pinned name has no Mongo bar depth\n    # yet, so live ticks are the only way the scanner can see it.\n    try:\n        pinned = [d["symbol"] for d in db["symbol_adv_cache"].find(\n            {"manual_universe_pin": True, "unqualifiable": {"$ne": True}},\n            {"_id": 0, "symbol": 1})]\n        extra_priority = list(extra_priority) + [\n            p for p in pinned if p not in extra_priority]\n    except Exception as e:\n        logger.debug(f"pin lookup failed: {e}")\n\n    # Pull top-N by avg_dollar_volume (qualified + non-unqualifiable only).\n    # v322n — over-fetch then drop bond/cash, income, index clones and\n'),
    ('backend/services/symbol_universe.py',
     '    doc = adv.find_one(\n        {"symbol": sym},\n        {"_id": 0, "unqualifiable_failure_count": 1, "unqualifiable": 1,\n         "avg_dollar_volume": 1},\n    ) or {}\n    count = doc.get("unqualifiable_failure_count", 0)\n    already = bool(doc.get("unqualifiable"))\n    adv_value = float(doc.get("avg_dollar_volume") or 0.0)\n\n    # ---- Layer 1: mega-cap immunity (v19.34.140) -----------------------\n    # Imported lazily to avoid a circular import between symbol_universe\n',
     '    doc = adv.find_one(\n        {"symbol": sym},\n        {"_id": 0, "unqualifiable_failure_count": 1, "unqualifiable": 1,\n         "avg_dollar_volume": 1, "manual_universe_pin": 1},\n    ) or {}\n    count = doc.get("unqualifiable_failure_count", 0)\n    already = bool(doc.get("unqualifiable"))\n    adv_value = float(doc.get("avg_dollar_volume") or 0.0)\n\n    # ---- Layer 0: manual-pin immunity (v331) ----------------------------\n    # Operator-pinned symbols (fresh IPOs etc.) often fail IB qualification\n    # transiently in their first sessions — never auto-promote them.\n    if doc.get("manual_universe_pin"):\n        if not already:\n            logger.warning(\n                f"🛡️ {sym} would have been promoted to unqualifiable after "\n                f"{count} failures (reason={reason!r}) — BLOCKED by "\n                "manual_universe_pin (operator pin)."\n            )\n        return {\n            "success": True,\n            "symbol": sym,\n            "failure_count": count,\n            "unqualifiable": False,\n            "promoted_now": False,\n            "protected_by": "manual_universe_pin",\n        }\n\n    # ---- Layer 1: mega-cap immunity (v19.34.140) -----------------------\n    # Imported lazily to avoid a circular import between symbol_universe\n'),
    ('backend/services/symbol_universe.py',
     '    }\n\n\ndef reset_unqualifiable(db, symbol: str) -> bool:\n    """Operator escape hatch — clear the unqualifiable flag. Used after\n    a manual symbol-list correction or an IB Gateway re-sync."""\n',
     '    }\n\n\ndef pin_symbol(db, symbol: str, reason: str = "operator pin") -> Dict[str, Any]:\n    """v331 — operator pin: force `symbol` into every scan universe and\n    the pusher L1 priority list regardless of ADV. Use for day-one IPOs\n    (no daily bars → no avg_dollar_volume → otherwise invisible until\n    the nightly ADV rebuild AFTER its first collected daily bar — which\n    itself never happens because collection only targets cached symbols:\n    chicken-and-egg). The pin also grants unqualifiable immunity. The\n    nightly rebuild will fill in real ADV/tier once bars exist; the pin\n    flag survives because rebuild upserts with $set (doesn\'t clear it).\n    """\n    if db is None or not symbol:\n        return {"success": False, "error": "missing db or symbol"}\n    sym = symbol.upper()\n    now_iso = datetime.now(timezone.utc).isoformat()\n    db["symbol_adv_cache"].update_one(\n        {"symbol": sym},\n        {"$set": {\n            "manual_universe_pin": True,\n            "pinned_at": now_iso,\n            "pinned_reason": reason,\n            "unqualifiable": False,\n        },\n         "$setOnInsert": {"symbol": sym, "tier": "intraday",\n                          "first_seen_at": now_iso}},\n        upsert=True,\n    )\n    logger.info(f"📌 {sym} pinned into the scan universe ({reason})")\n    return {"success": True, "symbol": sym, "pinned": True}\n\n\ndef unpin_symbol(db, symbol: str) -> bool:\n    """v331 — remove an operator pin (symbol reverts to ADV-based rules)."""\n    if db is None or not symbol:\n        return False\n    res = db["symbol_adv_cache"].update_one(\n        {"symbol": symbol.upper()},\n        {"$unset": {"manual_universe_pin": "", "pinned_at": "",\n                    "pinned_reason": ""}},\n    )\n    return res.modified_count > 0\n\n\ndef reset_unqualifiable(db, symbol: str) -> bool:\n    """Operator escape hatch — clear the unqualifiable flag. Used after\n    a manual symbol-list correction or an IB Gateway re-sync."""\n'),
]

TEST_FILE_REL = 'backend/tests/test_v331_universe_pin.py'
TEST_FILE_CONTENT = '"""v331 — manual universe pin (operator-pinned symbols, e.g. day-one IPOs).\n\n`symbol_adv_cache.manual_universe_pin: true` rows are:\n  1. always in get_universe / get_universe_ranked regardless of ADV;\n  2. immune to unqualifiable promotion (Layer 0, before mega-cap check);\n  3. auto-included in the pusher L1 priority list.\n`pin_symbol(db, sym, reason)` / `unpin_symbol(db, sym)` manage the flag.\nFirst use: SPCX (IPO\'d 2026-06-12) — no daily bars → no ADV row → was\ninvisible to every scan (chicken-and-egg: collection only targets cached\nsymbols).\n"""\nimport py_compile\nfrom pathlib import Path\n\n\ndef _repo_root():\n    for c in Path(__file__).resolve().parents:\n        if (c / "backend" / "services" / "symbol_universe.py").exists():\n            return c\n    raise AssertionError("repo root not found")\n\n\nROOT = _repo_root()\nSRC = (ROOT / "backend" / "services" / "symbol_universe.py").read_text()\n\n\ndef test_pin_clause_in_get_universe():\n    i = SRC.index("def get_universe(")\n    block = SRC[i:SRC.index("def get_universe_ranked(")]\n    assert \'{"manual_universe_pin": True}\' in block\n    assert \'"$or"\' in block\n\n\ndef test_pin_clause_in_get_universe_ranked():\n    i = SRC.index("def get_universe_ranked(")\n    block = SRC[i:SRC.index("def get_universe_for_bar_size(")]\n    assert \'{"manual_universe_pin": True}\' in block\n\n\ndef test_pin_immunity_in_mark_unqualifiable():\n    i = SRC.index("def mark_unqualifiable(")\n    block = SRC[i:SRC.index("def reset_unqualifiable(")]\n    assert \'doc.get("manual_universe_pin")\' in block\n    assert \'"protected_by": "manual_universe_pin"\' in block\n\n\ndef test_pin_flows_to_pusher_l1():\n    i = SRC.index("def get_pusher_l1_recommendations(")\n    block = SRC[i:SRC.index("def get_universe_stats(")]\n    assert \'"manual_universe_pin": True\' in block\n\n\ndef test_pin_helpers_exist():\n    assert "def pin_symbol(" in SRC\n    assert "def unpin_symbol(" in SRC\n\n\ndef test_file_compiles():\n    py_compile.compile(str(ROOT / "backend" / "services" / "symbol_universe.py"),\n                       doraise=True)\n'


def find_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / "backend" / "services" / "symbol_universe.py").exists():
            return cand
    print("FATAL: run from repo root")
    sys.exit(1)


def _load_env(root: Path) -> None:
    p = root / "backend" / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))


def apply_chunks(root: Path) -> int:
    applied = 0
    for rel, old, new in CHUNKS:
        path = root / rel
        text = path.read_text()
        if new in text:
            print(f"[SKIP] {rel} — chunk already applied")
            continue
        n = text.count(old)
        if n != 1:
            print(f"[FAIL] {rel} — anchor found {n}x (expected 1). File drifted. ABORTING.")
            sys.exit(2)
        path.write_text(text.replace(old, new, 1))
        applied += 1
        print(f"[OK]   {rel} — chunk applied")
    tp = root / TEST_FILE_REL
    if tp.exists() and tp.read_text() == TEST_FILE_CONTENT:
        print(f"[SKIP] {TEST_FILE_REL} — already present")
    else:
        tp.write_text(TEST_FILE_CONTENT)
        print(f"[OK]   {TEST_FILE_REL} — written")
    return applied


def db_phase(root: Path) -> None:
    from pymongo import MongoClient
    _load_env(root)
    url = os.environ.get("MONGO_URL")
    if not url:
        print("[WARN] MONGO_URL not found — skipping DB phase")
        return
    db = MongoClient(url)[os.environ.get("DB_NAME", "tradecommand")]
    sys.path.insert(0, str(root / "backend"))

    # 1. pin SPCX using the freshly-patched helper
    import importlib
    import services.symbol_universe as su
    importlib.reload(su)
    r = su.pin_symbol(db, "SPCX", "IPO 2026-06-12 — operator preferred")
    print(f"[DB]   SPCX pinned: {r}")
    in_universe = "SPCX" in su.get_universe(db, "intraday")
    print(f"[DB]   SPCX in intraday scan universe: {in_universe}")
    if not in_universe:
        print("[FAIL] pin did not take effect")
        sys.exit(3)

    # 2. queue IB backfill so SPCX history starts building
    try:
        from services.historical_data_queue_service import HistoricalDataQueueService
        svc = HistoricalDataQueueService(db)
        queued = []
        for bar_size, duration in [("1 day", "5 D"), ("1 hour", "5 D"),
                                   ("15 mins", "5 D"), ("5 mins", "5 D"),
                                   ("1 min", "2 D")]:
            rid = svc.create_request(symbol="SPCX", duration=duration,
                                     bar_size=bar_size)
            queued.append(f"{bar_size}→{rid}")
        print(f"[DB]   SPCX backfill queued: {len(queued)} requests")
        for q in queued:
            print(f"       {q}")
    except Exception as e:
        print(f"[WARN] backfill queue failed (pin still active): {e}")


def self_test(root: Path) -> None:
    print()
    print("── self-test: pytest ──")
    tests = ["tests/test_v331_universe_pin.py"]
    existing = [t for t in tests if (root / "backend" / t).exists()]
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *existing],
        cwd=str(root / "backend"), capture_output=True, text=True, timeout=180,
    )
    for line in (r.stdout or "").strip().splitlines()[-3:]:
        print("   " + line)
    if r.returncode != 0:
        print("[FAIL] self-test failed — see above.")
        print((r.stdout or "")[-1500:])
        sys.exit(3)
    print("[OK]   self-test PASSED")


def main():
    root = find_root()
    print(f"repo root: {root}")
    applied = apply_chunks(root)
    if "--files-only" in sys.argv:
        print("[SKIP] DB phase (--files-only)")
    else:
        db_phase(root)
    self_test(root)
    print()
    print(f"v331 done — {applied} chunk(s) newly applied.")
    print("Next:")
    print("  git add -A && git commit -m 'v331: manual universe pin + SPCX' && git push")
    print("  then RESTART the backend. SPCX appears in scans immediately;")
    print("  bars build as the pusher serves the queued requests; tonight's")
    print("  ADV rebuild assigns its real tier (pin keeps it in regardless).")
    print("  Future IPOs: .venv/bin/python -c \"")
    print("    import sys; sys.path.insert(0,'backend'); ...pin_symbol(db,'SYM','reason')\"")
    print("  (or ask me for a one-liner / UI button).")


if __name__ == "__main__":
    main()
