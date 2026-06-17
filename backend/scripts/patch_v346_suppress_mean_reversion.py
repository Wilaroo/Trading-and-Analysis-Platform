#!/usr/bin/env python3
"""
patch_v346_suppress_mean_reversion.py  (AGENTS.md §2.2 — line-anchored, unique+compile guarded)

WHAT: removes "mean_reversion" from trading_bot_service._enabled_setups so it stops trading
      (routes to the setup_disabled gate, same as `breakdown`). One-line edit.
WHY : v345 EMA20-snapback replay — mean_reversion is ~97% a DUPLICATE of the now-live vwap_fade
      (UNIQUE vs vwap_fade: 1/25 short, 2/35 long; the rest OVERLAP and already fire vwap_fade).
      SHORT side is breakeven (medR -0.06); the +EV LONG edge is already captured by vwap_fade.
      Keeping it only creates CORRELATED double-fires (2x sizing on the same signal) — bad for
      unmanaged paper trading — with zero incremental edge. So suppress, let vwap_fade own it.
SAFETY: trading-eligibility only (removes one enum entry). No close/bracket/EOD/scoring change.
        Reversible via --rollback or by re-adding the entry. Uses ANCHOR-uniqueness + py_compile +
        backup + reverse-anchor rollback (no whole-file SHA: this large file drifts vs sandbox and
        the edit is a single unambiguous enum line).

Usage (repo root, DGX):
  .venv/bin/python /tmp/patch_v346_suppress_mean_reversion.py --check
  .venv/bin/python /tmp/patch_v346_suppress_mean_reversion.py --apply
  .venv/bin/python /tmp/patch_v346_suppress_mean_reversion.py --rollback
Then: commit ; ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os, py_compile, tempfile

FILE = "backend/services/trading_bot_service.py"
# OLD: the enabled-setups line that includes mean_reversion
OLD_B64 = "ICAgICAgICAgICAgIm1lYW5fcmV2ZXJzaW9uIiwgImdhcF9mYWRlIiwgImNoYXJ0X3BhdHRlcm4iLA=="
# NEW: mean_reversion removed (suppressed); note appended
NEW_B64 = "ICAgICAgICAgICAgImdhcF9mYWRlIiwgImNoYXJ0X3BhdHRlcm4iLCAgIyBtZWFuX3JldmVyc2lvbiBzdXBwcmVzc2VkIHYxOS4zNC4zMjcgKDk3JSB2d2FwX2ZhZGUgZHVwbGljYXRlLCB2MzQ1KQ=="
BACKUP = FILE + ".bak_v346"


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
    src = _read(); old = _old()
    print(f"file        : {FILE}")
    print(f"whole SHA   : {_sha(src)}")
    print(f"OLD anchor  : present={old in src} count={src.count(old)}")
    print(f"NEW present : {_new() in src}")
    if _new() in src:
        print("state       : ALREADY PATCHED (mean_reversion already suppressed)"); return True
    if src.count(old) != 1:
        print("\nAnchor missing/ambiguous — abort (send me the live _enabled_setups block)."); return False
    print("\nREADY: --apply removes mean_reversion from _enabled_setups.")
    return True


def apply():
    src = _read(); old, new = _old(), _new()
    if new in src: print("Already patched. No-op."); return
    if src.count(old) != 1:
        print(f"ABORT: anchor count={src.count(old)} (need 1)."); sys.exit(3)
    patched = src.replace(old, new, 1)
    _blk = patched.split("_enabled_setups = [", 1)[1].split("]", 1)[0] if "_enabled_setups = [" in patched else ""
    if '"mean_reversion"' in _blk:
        # defensive: ensure no other mean_reversion ENUM entry remains in the SAME list block
        print("NOTE: mean_reversion still present elsewhere in the enabled list — verify manually.")
    if not _compiles(patched):
        print("ABORT: patched file does not compile. No write."); sys.exit(3)
    shutil.copy2(FILE, BACKUP)
    with open(FILE, "w", encoding="utf-8") as f: f.write(patched)
    print(f"APPLIED. backup -> {BACKUP}")
    print(f"new whole SHA : {_sha(patched)}")
    print("commit ; ./start_backend.sh --force")


def rollback():
    src = _read(); old, new = _old(), _new()
    if old in src and new not in src:
        print("Already at baseline. No-op."); return
    if new in src and src.count(new) == 1:
        restored = src.replace(new, old, 1)
        shutil.copy2(FILE, FILE + ".bak_pre_rollback")
        with open(FILE, "w", encoding="utf-8") as f: f.write(restored)
        print("ROLLED BACK (mean_reversion re-enabled)."); return
    if os.path.exists(BACKUP):
        shutil.copy2(BACKUP, FILE); print(f"ROLLED BACK from {BACKUP}."); return
    print("ABORT: could not safely roll back."); sys.exit(4)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    {"--check": check, "--apply": apply, "--rollback": rollback}.get(arg, lambda: print("usage: --check | --apply | --rollback"))()
