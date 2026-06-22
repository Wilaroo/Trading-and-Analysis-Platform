#!/usr/bin/env python3
"""Generate scripts/patch_a2j_carryforward_pillar_backfill.py — chunk patcher
pinned to the CURRENT live backend/services/enhanced_scanner.py (A2h-applied,
sha 77956844…), held locally at /tmp/es_dgx_patched.

Edit: in _hydrate_carry_forward_alerts_from_mongo(), backfill the 5-pillar TQS
breakdown for hydrated carry-forward alerts that restore WITHOUT
tqs_pillar_grades (every cf_* gameplan card was ringless), then re-persist so
future restarts restore it directly (self-healing). _enrich_alert_with_tqs is
try/except-safe and lazily loads the TQS engine, so it's safe at start()-time.
"""
import base64
import hashlib

DGX = "/tmp/es_dgx_patched"
REL = "backend/services/enhanced_scanner.py"

# OLD chunk = the hydration loop + its summary log, lines 7833-7850 (1-indexed).
lines = open(DGX, encoding="utf-8").read().splitlines(keepends=True)
OLD = "".join(lines[7832:7850])  # 0-indexed slice -> lines 7833..7850

ENRICH_BLOCK = (
    "                        # v19.34.283 (A2j) — carry-forwards persisted before the\n"
    "                        # alert object carried a pillar breakdown (or before A2h)\n"
    "                        # restore WITHOUT tqs_pillar_grades, so the Provenance Ring\n"
    "                        # never renders for the morning gameplan watchlist (every\n"
    "                        # cf_* card was ringless). Backfill the 5-pillar breakdown on\n"
    "                        # hydration when missing, then re-persist so future restarts\n"
    "                        # restore it directly (self-healing, one-time per alert).\n"
    "                        if not (getattr(alert, \"tqs_pillar_grades\", None) or {}):\n"
    "                            try:\n"
    "                                await self._enrich_alert_with_tqs(alert)\n"
    "                                if getattr(alert, \"tqs_pillar_grades\", None):\n"
    "                                    self._persist_carry_forward_alert(alert)\n"
    "                                    backfilled += 1\n"
    "                            except Exception as _bf_err:\n"
    "                                logger.debug(\n"
    "                                    f\"A2j pillar backfill skipped for \"\n"
    "                                    f\"{getattr(alert, 'id', '?')}: {_bf_err}\"\n"
    "                                )\n"
)

NEW = OLD
# 1) declare the backfilled counter alongside hydrated
a = "            hydrated = 0\n            for doc in docs:\n"
assert OLD.count(a) == 1, "anchor #1 (hydrated=0/for) not unique"
NEW = NEW.replace(a, "            hydrated = 0\n            backfilled = 0\n            for doc in docs:\n", 1)
# 2) insert the enrich/backfill block right after `hydrated += 1`
b = "                        hydrated += 1\n                except Exception as e:\n"
assert OLD.count(b) == 1, "anchor #2 (hydrated+=1/except) not unique"
NEW = NEW.replace(b, "                        hydrated += 1\n" + ENRICH_BLOCK + "                except Exception as e:\n", 1)
# 3) extend the summary log to report backfilled count
c = "                    f\"(survived backend restart)\"\n                )\n"
assert OLD.count(c) == 1, "anchor #3 (log tail) not unique"
NEW = NEW.replace(
    c,
    "                    f\"(survived backend restart); A2j pillar-backfilled \"\n"
    "                    f\"{backfilled}\"\n                )\n",
    1,
)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    pristine = open(DGX, "rb").read()
    ob, nb = OLD.encode(), NEW.encode()
    assert pristine.count(ob) == 1, f"OLD not unique in DGX file ({pristine.count(ob)})"
    assert nb not in pristine, "NEW already present"
    patched = pristine.replace(ob, nb, 1)
    compile(patched.decode(), REL, "exec")
    pre, post = sha(pristine), sha(patched)
    print("PRE :", pre)
    print("POST:", post)

    patcher = f'''#!/usr/bin/env python3
"""
patch_a2j_carryforward_pillar_backfill.py  —  v19.34.283 (UI Track A · A2j)
"Provenance Rings on the carry-forward gameplan watchlist"

DIAGNOSIS (operator curl /api/live-scanner/alerts): 146/146 ringless alerts were
carry-forwards (id prefix cf_*, setup carry_forward_watch/day_2_continuation,
trade_style multi_day, scan_tier swing, time_window CLOSED), all with tqs_score>0
but NO tqs_pillar_grades. They are HYDRATED from Mongo at scanner start() via
_hydrate_carry_forward_alerts_from_mongo() -> _inflate_live_alert_from_mongo(),
which BYPASSES _process_new_alert — so A2h's chokepoint backfill never ran on them,
and they were persisted (pre-A2h) without a pillar breakdown. Result: every cf_*
gameplan card rendered without a Provenance Ring.

FIX (backend-only, additive, 1 chunk on services/enhanced_scanner.py): in the
hydration loop, when an inflated carry-forward lacks tqs_pillar_grades, call
_enrich_alert_with_tqs (computes the 5-pillar breakdown from the alert's own
attributes — no live tape/IB fetch needed; try/except-safe; lazily loads the TQS
engine) and re-persist it so subsequent restarts restore the pillars directly
(self-healing, one-time cost per alert). A new `backfilled` counter is reported in
the existing hydrate log. Companion to A2h (creation-path) + A2i (/setups feed).

PRE+POST SHA256 hard-guarded; aborts on drift; --check dry-run; .a2jbak backup.

USAGE (repo root):
  .venv/bin/python scripts/patch_a2j_carryforward_pillar_backfill.py --check
  .venv/bin/python scripts/patch_a2j_carryforward_pillar_backfill.py
  git add backend/ scripts/ && git commit -m "v19.34.283 (A2j): backfill pillar grades for hydrated carry-forwards" && git push origin main
  ./start_backend.sh --force
After restart, watch the boot log for: 'A2j pillar-backfilled N', then the cf_*
gameplan cards should all render rings. Verify:
  curl -s http://localhost:8001/api/live-scanner/alerts | python3 -c "import sys,json;a=json.load(sys.stdin)['alerts'];print(sum(1 for x in a if x.get('tqs_pillar_grades')),'/',len(a),'carry pillars')"
"""
import base64
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
PATH = {REL!r}
PRE = {pre!r}
POST = {post!r}
OLD_B64 = {base64.b64encode(ob).decode()!r}
NEW_B64 = {base64.b64encode(nb).decode()!r}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.exists(PATH):
        print(f"  [MISSING!] {{PATH}} — run from the repo root."); sys.exit(2)
    cur = open(PATH, "rb").read()
    cur_sha = sha(cur)
    old = base64.b64decode(OLD_B64)
    new = base64.b64decode(NEW_B64)

    if cur_sha == POST or new in cur:
        print(f"  [ALREADY-APPLIED] {{PATH}} sha={{cur_sha[:12]}} — nothing to do.")
        return
    if cur_sha != PRE:
        print(f"  [DRIFT] {{PATH}}")
        print(f"    expected PRE  {{PRE}}")
        print(f"    found on disk {{cur_sha}}")
        print("    ABORT (no write). Send me your copy to rebase:")
        print(f"      gzip -c -9 {{PATH}} | curl -sS --data-binary @- https://paste.rs/")
        sys.exit(3)
    n = cur.count(old)
    if n != 1:
        print(f"  [ANCHOR x{{n}}] OLD chunk not uniquely found — ABORT (no write)."); sys.exit(4)
    out = cur.replace(old, new, 1)
    out_sha = sha(out)
    if out_sha != POST:
        print(f"  [POST-MISMATCH] would produce {{out_sha}} != {{POST}} — ABORT."); sys.exit(5)
    if CHECK:
        print(f"  [CHECK OK] {{PATH}} sha={{cur_sha[:12]}} -> POST {{POST[:12]}} (1 chunk). Re-run without --check.")
        return
    bak = PATH + ".a2jbak"
    if not os.path.exists(bak):
        open(bak, "wb").write(cur)
    open(PATH, "wb").write(out)
    print(f"  [APPLIED] {{PATH}}  {{PRE[:12]}} -> {{POST[:12]}}  (.a2jbak saved)")
    print("  NEXT: commit (before any restart), then ./start_backend.sh --force")


if __name__ == "__main__":
    main()
'''
    out_path = "/app/scripts/patch_a2j_carryforward_pillar_backfill.py"
    open(out_path, "w", encoding="utf-8").write(patcher)
    print("wrote", out_path, len(patcher), "bytes")
    # also write the patched file so we can sync the sandbox mirror
    open("/tmp/es_dgx_patched_a2j", "wb").write(patched)


if __name__ == "__main__":
    main()
