#!/usr/bin/env python3
"""Builder (sandbox-only) — emits patch_v343_gap_fade_snapback.py.
Extracts live _check_gap_fade bytes (unchanged by v341), pairs with the validated
rewrite in _v343_new_func.txt, writes a function-anchored §2.2 patcher anchored on the
post-v341 DGX whole-file baseline 45db2e66."""
import base64, hashlib, re, tempfile, py_compile, os

FILE = "backend/services/enhanced_scanner.py"
DGX_WHOLE_PRE = "45db2e66d028625d96ec6a97ea78afcca032e4f8beda557b8de58303e988b296"
NAME = "_check_gap_fade"


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
    trailing = old[len(old.rstrip()):]
    new = open("backend/scripts/_v343_new_func.txt", encoding="utf-8").read().rstrip() + trailing
    post = hashlib.sha256(new.encode()).hexdigest()

    src = open(FILE, encoding="utf-8").read()
    assert src.count(old) == 1, f"anchor count={src.count(old)}"
    patched = src.replace(old, new, 1)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(patched); tmp = tf.name
    py_compile.compile(tmp, doraise=True); os.unlink(tmp)

    old_b64 = base64.b64encode(old.encode()).decode()
    new_b64 = base64.b64encode(new.encode()).decode()

    patcher = '''#!/usr/bin/env python3
"""
patch_v343_gap_fade_snapback.py  (AGENTS.md §2.2 — function-anchored patcher)

WHAT: replaces enhanced_scanner._check_gap_fade (a fade-to-full-prior-close on a raw
      VWAP-cross — NEGATIVE-EV per v342: -0.11R short / -0.07R long, n=1080) with a
      gap-gated v341 SNAPBACK: 1-min double-bar-break after the post-gap HOD/LOD extreme,
      stop = HOD/LOD +/- 0.02, target = session VWAP (1R floor). COMPLEMENTARITY gate:
      only fires when entry is WITHIN 1%% of VWAP — the low-extension gap reversals the
      live vwap_fade MISSES (v342c UNIQUE 54%%: SHORT win69%%/+0.11R, LONG win71%%/+0.13R),
      so gap_fade and vwap_fade never double-fire. Keeps |gap|>=2%% + RVOL>=1.3 + 2/day cap.
WHY : v342/v342b/v342c replays — the full-fill target was the bleed; snapback + VWAP target +
      complementarity zone is +EV and non-redundant.

DRIFT NOTE: FUNCTION-ANCHORED on the post-v341 baseline. Asserts whole-file SHA == %(whole)s
      AND the exact _check_gap_fade bytes present (count==1), replaces, asserts new func SHA,
      py_compiles before writing.

§2.2: PRE whole-file SHA + function PRE/POST SHA + anchor-uniqueness + compile guard +
      auto-backup + --check/--apply/--rollback.

Usage (repo root, DGX):
  .venv/bin/python /tmp/patch_v343_gap_fade_snapback.py --check
  .venv/bin/python /tmp/patch_v343_gap_fade_snapback.py --apply
  .venv/bin/python /tmp/patch_v343_gap_fade_snapback.py --rollback
Then: pytest backend/tests/test_v343_gap_fade.py -q ; commit ; ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os, py_compile, tempfile

FILE = "backend/services/enhanced_scanner.py"
DGX_WHOLE_PRE = "%(whole)s"
PRE_FUNC_SHA  = "%(pre)s"
POST_FUNC_SHA = "%(post)s"
OLD_B64 = "%(old)s"
NEW_B64 = "%(new)s"
BACKUP = FILE + ".bak_v343"


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
        print("\\nDRIFT: live file != post-v341 baseline. Re-extract the function and rebuild."); return False
    if src.count(old) != 1:
        print("\\nAnchor missing/ambiguous — abort."); return False
    print("\\nREADY: --apply installs the gap-gated gap_fade SMB snapback (long+short).")
    return True


def apply():
    src = _read(); old, new = _old(), _new()
    if new in src: print("Already patched. No-op."); return
    if _sha(src) != DGX_WHOLE_PRE:
        print(f"ABORT: whole-file SHA {_sha(src)} != baseline. See --check."); sys.exit(3)
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
    print("Verify: pytest backend/tests/test_v343_gap_fade.py -q ; commit BEFORE restart ; ./start_backend.sh --force")


def rollback():
    src = _read(); old, new = _old(), _new()
    if old in src and _sha(src) == DGX_WHOLE_PRE:
        print("Already at baseline (unpatched). No-op."); return
    if new in src and src.count(new) == 1:
        restored = src.replace(new, old, 1)
        shutil.copy2(FILE, FILE + ".bak_pre_rollback")
        with open(FILE, "w", encoding="utf-8") as f: f.write(restored)
        print(f"ROLLED BACK via reverse-anchor. whole-file SHA == baseline: {_sha(restored) == DGX_WHOLE_PRE}")
        return
    if os.path.exists(BACKUP):
        bsrc = open(BACKUP, encoding="utf-8").read()
        if _sha(bsrc) == DGX_WHOLE_PRE:
            shutil.copy2(BACKUP, FILE); print(f"ROLLED BACK from {BACKUP} (== baseline)."); return
    print("ABORT: could not safely roll back."); sys.exit(4)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    {"--check": check, "--apply": apply, "--rollback": rollback}.get(arg, lambda: print("usage: --check | --apply | --rollback"))()
''' % {"whole": DGX_WHOLE_PRE, "pre": pre, "post": post, "old": old_b64, "new": new_b64}

    with open("backend/scripts/patch_v343_gap_fade_snapback.py", "w", encoding="utf-8") as f:
        f.write(patcher)
    print(f"PRE_FUNC_SHA  = {pre}")
    print(f"POST_FUNC_SHA = {post}")
    print("wrote backend/scripts/patch_v343_gap_fade_snapback.py")


if __name__ == "__main__":
    main()
