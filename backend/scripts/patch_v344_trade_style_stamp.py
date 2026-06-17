#!/usr/bin/env python3
"""
patch_v344_trade_style_stamp.py  (AGENTS.md §2.2 — line-anchored, whole-file-SHA-guarded)

WHAT: at BotTrade creation (OpportunityEvaluator.evaluate_opportunity) stamp the CANONICAL
      resolved trade_style via self._resolve_geometry_style(alert, setup_type) instead of the
      legacy literal default "trade_2_hold". _resolve_geometry_style already defers the generic
      trade_2_hold to the setup-derived horizon (scalp/intraday/multi_day/swing/...) and maps
      unknown->intraday — the SAME logic the policy/EOD layer (v245) uses at runtime.
WHY : v332/v333/v338 — 528/586 genuine closes were stamped with the meaningless 'trade_2_hold'
      default, polluting per-setup EV / meta-labeler / analytics bucketing. EOD policy already
      compensated at runtime; this aligns the PERSISTED style so analytics are trustworthy.
      Behaviour only changes for previously-defaulted rows (real styles pass through unchanged).
SAFETY: analytics/hygiene only — does NOT alter close_trade / submit_with_bracket / EOD logic.

§2.2: whole-file PRE/POST SHA + unique-anchor + py_compile guard + backup + --check/--apply/--rollback.

Usage (repo root, DGX):
  .venv/bin/python /tmp/patch_v344_trade_style_stamp.py --check
  .venv/bin/python /tmp/patch_v344_trade_style_stamp.py --apply
  .venv/bin/python /tmp/patch_v344_trade_style_stamp.py --rollback
Then: commit ; ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os, py_compile, tempfile

FILE = "backend/services/opportunity_evaluator.py"
PRE_SHA  = "ce3624c52cb6c03fd7475a11478b33c6478963fa08c9bc46dd215afcf1e8d120"
POST_SHA = "b34dc9177ee029ead90d54a85a26b534e3634c57e2e0b2a7fb247afd5c4586a9"
OLD_B64 = "ICAgICAgICAgICAgICAgIHRyYWRlX3N0eWxlPWFsZXJ0LmdldCgidHJhZGVfc3R5bGUiLCAidHJhZGVfMl9ob2xkIiks"
NEW_B64 = "ICAgICAgICAgICAgICAgIHRyYWRlX3N0eWxlPXNlbGYuX3Jlc29sdmVfZ2VvbWV0cnlfc3R5bGUoYWxlcnQsIHNldHVwX3R5cGUpLA=="
BACKUP = FILE + ".bak_v344"


def _sha(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()
def _read():
    if not os.path.exists(FILE):
        print(f"ERROR: {FILE} not found (run from repo root)"); sys.exit(2)
    return open(FILE, encoding="utf-8").read()
def _old(): return base64.b64decode(OLD_B64).decode("utf-8")
def _new(): return base64.b64decode(NEW_B64).decode("utf-8")
def _compiles(text):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(text); tmp = tf.name
    try:
        py_compile.compile(tmp, doraise=True); return True
    except py_compile.PyCompileError as e:
        print("POST-PATCH COMPILE FAILED:\n", e); return False
    finally:
        os.unlink(tmp)


def check():
    src = _read(); cur = _sha(src); old = _old()
    print(f"file           : {FILE}")
    print(f"whole-file SHA : {cur}")
    print(f"expected (PRE) : {PRE_SHA}  {'OK' if cur == PRE_SHA else 'DRIFT!'}")
    print(f"anchor         : present={old in src} count={src.count(old)}")
    if _new() in src: print("state          : ALREADY PATCHED")
    if cur != PRE_SHA:
        print("\nDRIFT: live opportunity_evaluator.py != expected baseline. Send me the live SHA to rebuild.")
        return False
    if src.count(old) != 1:
        print("\nAnchor missing/ambiguous — abort."); return False
    print("\nREADY: --apply stamps the canonical resolved trade_style on new trades.")
    return True


def apply():
    src = _read(); old, new = _old(), _new()
    if new in src: print("Already patched. No-op."); return
    if _sha(src) != PRE_SHA:
        print(f"ABORT: whole-file SHA {_sha(src)} != PRE. See --check."); sys.exit(3)
    if src.count(old) != 1:
        print(f"ABORT: anchor count={src.count(old)} (need 1)."); sys.exit(3)
    patched = src.replace(old, new, 1)
    if _sha(patched) != POST_SHA:
        print("ABORT: POST sha mismatch (corrupt patcher)."); sys.exit(3)
    if not _compiles(patched):
        print("ABORT: patched file does not compile. No write."); sys.exit(3)
    shutil.copy2(FILE, BACKUP)
    with open(FILE, "w", encoding="utf-8") as f: f.write(patched)
    print(f"APPLIED. backup -> {BACKUP}")
    print(f"new whole-file SHA : {_sha(patched)}")
    print("commit ; ./start_backend.sh --force")


def rollback():
    src = _read(); old, new = _old(), _new()
    if old in src and _sha(src) == PRE_SHA:
        print("Already at baseline. No-op."); return
    if new in src and src.count(new) == 1:
        restored = src.replace(new, old, 1)
        shutil.copy2(FILE, FILE + ".bak_pre_rollback")
        with open(FILE, "w", encoding="utf-8") as f: f.write(restored)
        print(f"ROLLED BACK. whole-file SHA == PRE: {_sha(restored) == PRE_SHA}"); return
    if os.path.exists(BACKUP) and _sha(open(BACKUP, encoding='utf-8').read()) == PRE_SHA:
        shutil.copy2(BACKUP, FILE); print(f"ROLLED BACK from {BACKUP}."); return
    print("ABORT: could not safely roll back."); sys.exit(4)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    {"--check": check, "--apply": apply, "--rollback": rollback}.get(arg, lambda: print("usage: --check | --apply | --rollback"))()
