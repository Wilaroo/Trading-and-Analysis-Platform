#!/usr/bin/env python3
r"""
patch_a2b_position_pillar_grades.py — UI Track A · A2b (v19.34.275).

Makes the provenance ring render on OPEN POSITION scanner cards (not just live
scanner alerts). The per-pillar TQS grades are already captured at fill time in
`entry_context.tqs.pillar_grades` (opportunity_evaluator.py ~3011/3022), but the
`/api/sentcom/positions` serializer in `sentcom_service.py` never emitted them —
so position cards showed a TQS badge but no ring (most visible PRE-MARKET, when
only open positions render and no live scanner alerts exist).

Fix (BACKEND-ONLY, additive read-only field): emit `tqs_pillar_grades` on both
position serializers, sourced from `entry_context.tqs.pillar_grades`. The V5
ScannerCardsV5 position branch already reads `p.tqs_pillar_grades`.

2 anchored, idempotent edits to ONE file (.a2bbak backup, reversible).
  EDIT backend/services/sentcom_service.py

HASH GUARDS (v322t+ convention):
  PRE_SHA256  = f7d2cd93e499a654374f22de4ac6206465c75549e1a735c934c68204d1b4f551
  POST_SHA256 = 0ef6e9f6add4b48cdac8119daa31580db555a92ec31dfdf78170e3aa51b25be8

Usage (repo root):
    python3 backend/scripts/patch_a2b_position_pillar_grades.py --check
    python3 backend/scripts/patch_a2b_position_pillar_grades.py --apply
    python3 backend/scripts/patch_a2b_position_pillar_grades.py --rollback
After --apply:  ./start_backend.sh --force   (backend-only; no yarn build needed)

On a PRE_SHA mismatch (DGX drift), DO NOT --force. Upload your live copy:
  curl --data-binary @backend/services/sentcom_service.py https://paste.rs/
and send the link so the edits can be rebased onto the canonical baseline.
"""
import os
import sys
import shutil
import hashlib
import argparse

BAK = ".a2bbak"
TARGET = "backend/services/sentcom_service.py"
PRE_SHA = "f7d2cd93e499a654374f22de4ac6206465c75549e1a735c934c68204d1b4f551"
POST_SHA = "0ef6e9f6add4b48cdac8119daa31580db555a92ec31dfdf78170e3aa51b25be8"

EDITS = [
    {
        "id": "1-open-position serializer +tqs_pillar_grades",
        "old": "                            # v19.34.258 — TQS as the single trusted UI score.\n                            \"tqs_score\": trade.get(\"tqs_score\", 0),\n                            \"tqs_grade\": trade.get(\"tqs_grade\", \"\"),",
        "new": "                            # v19.34.258 — TQS as the single trusted UI score.\n                            \"tqs_score\": trade.get(\"tqs_score\", 0),\n                            \"tqs_grade\": trade.get(\"tqs_grade\", \"\"),\n                            # v19.34.275 (UI Track A / A2b) — per-pillar grades captured at\n                            # fill time so the scanner-card provenance ring renders on open\n                            # positions, not just live scanner alerts.\n                            \"tqs_pillar_grades\": (trade.get(\"entry_context\") or {}).get(\"tqs\", {}).get(\"pillar_grades\") or {},",
        "applied_marker": "(trade.get(\"entry_context\") or {}).get(\"tqs\", {}).get(\"pillar_grades\")",
    },
    {
        "id": "2-lazy-orphan serializer +tqs_pillar_grades",
        "old": "                        # v19.34.258 — TQS as the single trusted UI score.\n                        \"tqs_score\": (enrich_trade or {}).get(\"tqs_score\", 0),\n                        \"tqs_grade\": (enrich_trade or {}).get(\"tqs_grade\", \"\"),",
        "new": "                        # v19.34.258 — TQS as the single trusted UI score.\n                        \"tqs_score\": (enrich_trade or {}).get(\"tqs_score\", 0),\n                        \"tqs_grade\": (enrich_trade or {}).get(\"tqs_grade\", \"\"),\n                        # v19.34.275 (UI Track A / A2b) — per-pillar grades for the\n                        # provenance ring on lazy-reconciled / IB-orphan positions.\n                        \"tqs_pillar_grades\": ((enrich_trade or {}).get(\"entry_context\") or {}).get(\"tqs\", {}).get(\"pillar_grades\") or {},",
        "applied_marker": "((enrich_trade or {}).get(\"entry_context\") or {}).get(\"tqs\", {}).get(\"pillar_grades\")",
    },
]


def sha_full(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..", "..")):
        c = os.path.abspath(os.path.join(base, path))
        if os.path.exists(c):
            return c
    return os.path.abspath(os.path.join(".", path))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    print("=" * 84)
    print("  A2b PATCH — open-position provenance-ring grades (sentcom_service.py)")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    p = resolve(TARGET)
    if not os.path.exists(p):
        print(f"  \u274c MISSING FILE: {TARGET}")
        sys.exit(2)

    if args.rollback:
        bak = p + BAK
        if os.path.exists(bak):
            shutil.copy2(bak, p)
            ok = "\u2705 matches PRE_SHA" if sha_full(p) == PRE_SHA else "\u26a0\ufe0f sha unexpected"
            print(f"  restored {TARGET}  sha={sha_full(p)[:12]}  {ok}")
        else:
            print(f"  no backup found ({BAK}); nothing to restore.")
        print("\n  ROLLBACK complete.  NEXT: ./start_backend.sh --force")
        return

    cur_sha = sha_full(p)
    if cur_sha == POST_SHA:
        file_state = "ALREADY-APPLIED"
    elif cur_sha == PRE_SHA:
        file_state = "READY"
    else:
        file_state = "DRIFT"

    print(f"\n  file   : {TARGET}")
    print(f"    sha     : {cur_sha[:12]}")
    print(f"    PRE_SHA : {PRE_SHA[:12]}  POST_SHA: {POST_SHA[:12]}")
    print(f"    state   : {file_state}")

    if file_state == "DRIFT":
        print("\n  \u274c DRIFT: live file matches neither PRE nor POST hash. Do NOT --force.")
        print(f"     Upload your live copy:  curl --data-binary @{TARGET} https://paste.rs/")
        sys.exit(3)

    src = open(p, encoding="utf-8").read()
    ed_plan = []
    for e in EDITS:
        applied = e["applied_marker"] in src
        n = src.count(e["old"])
        status = "ALREADY-APPLIED" if applied else ("READY" if n == 1 else f"ANCHOR x{n}")
        print(f"\n  [{e['id']}]\n    status : {status}")
        if not applied and n != 1:
            print("    \u274c anchor not uniquely found — ABORT (no files changed).")
            sys.exit(3)
        ed_plan.append((e, applied))

    if args.check:
        nready = sum(1 for _, a in ed_plan if not a)
        print(f"\n  CHECK ok. {nready} change(s) ready. Re-run with --apply.")
        return

    if file_state == "ALREADY-APPLIED":
        print("\n  Nothing to do — file already at POST_SHA.")
        return

    bak = p + BAK
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    cur = src
    changed = 0
    for e, applied in ed_plan:
        if applied:
            print(f"  skip (applied): {e['id']}")
            continue
        if e["old"] not in cur:
            print(f"  \u274c anchor vanished at apply for {e['id']} — ABORT.")
            sys.exit(4)
        cur = cur.replace(e["old"], e["new"], 1)
        changed += 1
    open(p, "w", encoding="utf-8").write(cur)
    post = sha_full(p)
    print(f"\n  patched {TARGET}  sha={post[:12]}  ({BAK} saved)")
    if post == POST_SHA:
        print("  \u2705 POST_SHA verified — result is byte-identical to the tested build.")
    else:
        print(f"  \u26a0\ufe0f  POST_SHA MISMATCH — expected {POST_SHA[:12]} got {post[:12]}.")
        sys.exit(5)
    print(f"\n  APPLY complete. {changed} change(s).")
    print("  NEXT: ./start_backend.sh --force   (backend-only)")


if __name__ == "__main__":
    main()
