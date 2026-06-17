#!/usr/bin/env python3
"""Builder (sandbox-only) — emits patch_v341_vwap_fade_snapback.py.
Extracts the live _check_vwap_fade bytes from enhanced_scanner.py (sandbox==DGX,
sha b92ccff3), pairs with the validated rewrite in _v341_new_func.txt, and writes
a function-anchored §2.2 patcher (mirror of patch_v330)."""
import base64, hashlib, re

FILE = "backend/services/enhanced_scanner.py"
DGX_WHOLE_PRE = "bc674f2688e9983edc3e7cad385a3463fe04d75ebc8dd927975154018b4b37cf"
EXPECT_PRE_FUNC = "b92ccff3de6deaaafa19d46bce4052e2fa1dce3dfa70863caae04af350aa9c7c"
NAME = "_check_vwap_fade"


def extract_old():
    lines = open(FILE, encoding="utf-8").read().split("\n")
    start = next(i for i, l in enumerate(lines) if l.lstrip().startswith(f"async def {NAME}"))
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        l = lines[j]
        if l.strip() and (len(l) - len(l.lstrip())) <= indent and re.match(r"\s*(async\s+)?def ", l):
            end = j
            break
    return "\n".join(lines[start:end])


def main():
    old = extract_old()
    pre = hashlib.sha256(old.encode()).hexdigest()
    assert pre == EXPECT_PRE_FUNC, f"OLD func sha {pre} != {EXPECT_PRE_FUNC}"
    trailing = old[len(old.rstrip()):]              # "\n    " (4-space next-def prefix)
    new_body = open("backend/scripts/_v341_new_func.txt", encoding="utf-8").read().rstrip()
    new = new_body + trailing
    post = hashlib.sha256(new.encode()).hexdigest()

    # sanity: the new block, dropped into the file, must compile
    src = open(FILE, encoding="utf-8").read()
    assert src.count(old) == 1, f"anchor count={src.count(old)}"
    import tempfile, py_compile, os
    patched = src.replace(old, new, 1)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(patched); tmp = tf.name
    py_compile.compile(tmp, doraise=True); os.unlink(tmp)

    old_b64 = base64.b64encode(old.encode()).decode()
    new_b64 = base64.b64encode(new.encode()).decode()

    patcher = '''#!/usr/bin/env python3
"""
patch_v341_vwap_fade_snapback.py  (AGENTS.md §2.2 — function-anchored patcher)

WHAT: replaces enhanced_scanner._check_vwap_fade (a dist_from_vwap STATE check at a
      2.5%% dead-zone threshold, no trigger) with a VWAP-anchored SMB SNAPBACK detector:
      extension into the [1.0%%, 3.0%%) band from session VWAP + a 1-min double-bar-break
      snapback within +1..+4 bars of the extreme + accel(1.3x) + RVOL>=1.5 + stop>=1.0%%
      of entry + 2 fires/day per (symbol, side). Long AND short.
WHY : v340b risk-controlled 14d native-1min replay validated +EV BOTH sides
      (LONG 1-2%% win73%%/+0.19R, SHORT 1-2%% win73%%/+0.21R; >=3%% no edge, hard-excluded).
      The 1.0%% stop floor gates the tiny-stop R-explosions that inflated v340's raw means.
      1-min bars come from ib_historical_data (IB-only) via
      self.technical_service._get_intraday_bars_from_db(sym,"1 min",60).

DRIFT NOTE: FUNCTION-ANCHORED. Asserts live whole-file SHA == DGX baseline AND the exact
      _check_vwap_fade bytes present (count==1), replaces, asserts new func SHA, then
      py_compiles the whole file before writing. (452KB file > paste limit → no precomputed
      whole-file POST_SHA; compile + func-SHA guards + backup cover it.)

§2.2: PRE whole-file SHA + function PRE/POST SHA + anchor-uniqueness + compile guard +
      auto-backup + --check/--apply/--rollback.

Usage (repo root, DGX):
  .venv/bin/python /tmp/patch_v341_vwap_fade_snapback.py --check
  .venv/bin/python /tmp/patch_v341_vwap_fade_snapback.py --apply
  .venv/bin/python /tmp/patch_v341_vwap_fade_snapback.py --rollback
Then: pytest backend/tests/test_v341_vwap_fade.py -q ; commit ; ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os, py_compile, tempfile

FILE = "backend/services/enhanced_scanner.py"
DGX_WHOLE_PRE = "%(whole)s"
PRE_FUNC_SHA  = "%(pre)s"
POST_FUNC_SHA = "%(post)s"
OLD_B64 = "%(old)s"
NEW_B64 = "%(new)s"
BACKUP = FILE + ".bak_v341"


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
        print("POST-PATCH COMPILE FAILED:\\n", e); return False
    finally:
        os.unlink(tmp)


def check():
    src = _read(); cur = _sha(src); old = _old()
    print(f"file            : {FILE}")
    print(f"whole-file SHA  : {cur}")
    print(f"expected (DGX)  : {DGX_WHOLE_PRE}  {'OK' if cur == DGX_WHOLE_PRE else 'DRIFT!'}")
    print(f"func anchor     : present={old in src} count={src.count(old)}")
    print(f"func PRE sha    : {_sha(old)}  {'OK' if _sha(old) == PRE_FUNC_SHA else 'MISMATCH'}")
    if _new() in src: print("state           : ALREADY PATCHED")
    if cur != DGX_WHOLE_PRE:
        print("\\nDRIFT: live file != DGX baseline. Re-extract the function and rebuild.")
        return False
    if src.count(old) != 1:
        print("\\nAnchor missing/ambiguous — abort."); return False
    print("\\nREADY: --apply installs the VWAP-fade SMB snapback detector (long+short).")
    return True


def apply():
    src = _read(); old, new = _old(), _new()
    if new in src: print("Already patched. No-op."); return
    if _sha(src) != DGX_WHOLE_PRE:
        print(f"ABORT: whole-file SHA {_sha(src)} != DGX baseline. See --check."); sys.exit(3)
    if src.count(old) != 1:
        print(f"ABORT: anchor count={src.count(old)} (need 1)."); sys.exit(3)
    if _sha(old) != PRE_FUNC_SHA:
        print("ABORT: function PRE sha mismatch."); sys.exit(3)
    if _sha(new) != POST_FUNC_SHA:
        print("ABORT: embedded NEW function sha mismatch (corrupt patcher)."); sys.exit(3)
    patched = src.replace(old, new, 1)
    if not _compiles(patched):
        print("ABORT: patched file does not compile. No write."); sys.exit(3)
    shutil.copy2(FILE, BACKUP)
    with open(FILE, "w", encoding="utf-8") as f: f.write(patched)
    print(f"APPLIED. backup -> {BACKUP}")
    print(f"new whole-file SHA : {_sha(patched)}  (record this)")
    print("Verify: pytest backend/tests/test_v341_vwap_fade.py -q ; commit BEFORE restart ; ./start_backend.sh --force")


def rollback():
    src = _read(); old, new = _old(), _new()
    if old in src and _sha(src) == DGX_WHOLE_PRE:
        print("Already at baseline (unpatched). No-op."); return
    if new in src and src.count(new) == 1:
        restored = src.replace(new, old, 1)
        shutil.copy2(FILE, FILE + ".bak_pre_rollback")
        with open(FILE, "w", encoding="utf-8") as f: f.write(restored)
        print(f"ROLLED BACK via reverse-anchor. whole-file SHA == DGX baseline: {_sha(restored) == DGX_WHOLE_PRE}")
        return
    if os.path.exists(BACKUP):
        bsrc = open(BACKUP, encoding="utf-8").read()
        if _sha(bsrc) == DGX_WHOLE_PRE:
            shutil.copy2(BACKUP, FILE); print(f"ROLLED BACK from {BACKUP} (== DGX baseline)."); return
    print("ABORT: could not safely roll back."); sys.exit(4)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    {"--check": check, "--apply": apply, "--rollback": rollback}.get(arg, lambda: print("usage: --check | --apply | --rollback"))()
''' % {"whole": DGX_WHOLE_PRE, "pre": pre, "post": post, "old": old_b64, "new": new_b64}

    with open("backend/scripts/patch_v341_vwap_fade_snapback.py", "w", encoding="utf-8") as f:
        f.write(patcher)
    print(f"PRE_FUNC_SHA  = {pre}")
    print(f"POST_FUNC_SHA = {post}")
    print(f"trailing repr = {trailing!r}")
    print("wrote backend/scripts/patch_v341_vwap_fade_snapback.py")


if __name__ == "__main__":
    main()
