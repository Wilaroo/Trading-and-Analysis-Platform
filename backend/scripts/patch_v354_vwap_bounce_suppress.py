#!/usr/bin/env python3
"""
patch_v354_vwap_bounce_suppress.py  (AGENTS.md 2.2 -- function-anchored patcher)

WHAT: SUPPRESSES enhanced_scanner._check_vwap_bounce (rewrites it to `return None`).
WHY : audit found the shipped near-VWAP-STATE rule (dist_from_vwap in (-0.8%,+0.3%), uptrend,
      above 9-EMA, rvol>=1.5; stop=VWAP-0.5*ATR, target=VWAP+1.5*ATR, R:R 3.0) is NEGATIVE-EV.
      14d native-1min replay (diag_v354_vwap_bounce): winsorAvg -0.101R over 2,387 fires
      (-242R total) -- 59% win but broken geometry (avg R:R 0.85). A doctrine rewrite (SMB
      First VWAP Pullback) was swept across legmult 0.5/0.75/1.0, minleg 0.5/0.75/1.0, single-
      attempt and RR caps 2.0-2.5: EVERY band stayed negative (best -0.049R). No validated +EV
      config exists in IB data, so this high-fire setup is disabled to stop the bleed.
DRIFT NOTE: FUNCTION-ANCHORED. Asserts live whole-file SHA == DGX baseline AND the exact live
      _check_vwap_bounce bytes present (count==1; the anchor ENDS before the _atr_floored_stop
      helper, which is preserved), replaces, asserts embedded NEW func SHA, py_compiles the
      whole file before writing.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/patch_v354_vwap_bounce_suppress.py --check
  .venv/bin/python backend/scripts/patch_v354_vwap_bounce_suppress.py --apply
  .venv/bin/python backend/scripts/patch_v354_vwap_bounce_suppress.py --rollback
Then: pytest backend/tests/test_v354_vwap_bounce.py -q ; commit ; ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os, py_compile, tempfile

FILE = "backend/services/enhanced_scanner.py"
DGX_WHOLE_PRE = "3611da4854a7fff120793d4c882de141c3e1a663cd08bd9ba8cc25928635d0af"
PRE_FUNC_SHA  = "31de305d0cae62d395e228f2d38dfe846886a08ddc2775a1b9a96186853857a6"
POST_FUNC_SHA = "31514bf95f71512c07e5e2dfa23780ca28515c1f3712926eab12b9d61ec1e5c7"
OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfdndhcF9ib3VuY2Uoc2VsZiwgc3ltYm9sOiBzdHIsIHNuYXBzaG90LCB0YXBlOiBUYXBlUmVhZGluZykgLT4gT3B0aW9uYWxbTGl2ZUFsZXJ0XToKICAgICAgICAiIiJWV0FQIEJvdW5jZSAtIFB1bGxiYWNrIHRvIFZXQVAgaW4gdXB0cmVuZCIiIgogICAgICAgIGlmICgtMC44IDwgc25hcHNob3QuZGlzdF9mcm9tX3Z3YXAgPCAwLjMgYW5kIAogICAgICAgICAgICBzbmFwc2hvdC50cmVuZCA9PSAidXB0cmVuZCIgYW5kIAogICAgICAgICAgICBzbmFwc2hvdC5hYm92ZV9lbWE5IGFuZAogICAgICAgICAgICBzbmFwc2hvdC5ydm9sID49IDEuNSk6CiAgICAgICAgICAgIAogICAgICAgICAgICBkaXN0ID0gYWJzKHNuYXBzaG90LmRpc3RfZnJvbV92d2FwKQogICAgICAgICAgICBwcmlvcml0eSA9IEFsZXJ0UHJpb3JpdHkuSElHSCBpZiBkaXN0IDwgMC4zIGFuZCB0YXBlLmNvbmZpcm1hdGlvbl9mb3JfbG9uZyBlbHNlIEFsZXJ0UHJpb3JpdHkuTUVESVVNCiAgICAgICAgICAgIAogICAgICAgICAgICByZXR1cm4gTGl2ZUFsZXJ0KAogICAgICAgICAgICAgICAgaWQ9ZiJ2d2FwX2JvdW5jZV97c3ltYm9sfV97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVIJU0lUycpfSIsCiAgICAgICAgICAgICAgICBzeW1ib2w9c3ltYm9sLAogICAgICAgICAgICAgICAgc2V0dXBfdHlwZT0idndhcF9ib3VuY2UiLAogICAgICAgICAgICAgICAgc3RyYXRlZ3lfbmFtZT0iVldBUCBCb3VuY2UgKElOVC0wNikiLAogICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJsb25nIiwKICAgICAgICAgICAgICAgIHByaW9yaXR5PXByaW9yaXR5LAogICAgICAgICAgICAgICAgY3VycmVudF9wcmljZT1zbmFwc2hvdC5jdXJyZW50X3ByaWNlLAogICAgICAgICAgICAgICAgdHJpZ2dlcl9wcmljZT1zbmFwc2hvdC52d2FwLAogICAgICAgICAgICAgICAgc3RvcF9sb3NzPXJvdW5kKHNuYXBzaG90LnZ3YXAgLSAoc25hcHNob3QuYXRyICogMC41KSwgMiksCiAgICAgICAgICAgICAgICB0YXJnZXQ9cm91bmQoc25hcHNob3QudndhcCArIChzbmFwc2hvdC5hdHIgKiAxLjUpLCAyKSwKICAgICAgICAgICAgICAgIHJpc2tfcmV3YXJkPTMuMCwKICAgICAgICAgICAgICAgIHRyaWdnZXJfcHJvYmFiaWxpdHk9MC42MCwKICAgICAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjYwLAogICAgICAgICAgICAgICAgbWludXRlc190b190cmlnZ2VyPTEwLAogICAgICAgICAgICAgICAgaGVhZGxpbmU9ZiLwn5ONIHtzeW1ib2x9IFZXQVAgQm91bmNlIC0gJHtzbmFwc2hvdC52d2FwOi4yZn0geyfinJMgVEFQRScgaWYgdGFwZS5jb25maXJtYXRpb25fZm9yX2xvbmcgZWxzZSAnJ30iLAogICAgICAgICAgICAgICAgcmVhc29uaW5nPVsKICAgICAgICAgICAgICAgICAgICBmIlByaWNlIHtzbmFwc2hvdC5kaXN0X2Zyb21fdndhcDorLjFmfSUgZnJvbSBWV0FQIiwKICAgICAgICAgICAgICAgICAgICAiVXB0cmVuZCBpbnRhY3QgLSBhYm92ZSA5LUVNQSBhbmQgMjAtRU1BIiwKICAgICAgICAgICAgICAgICAgICBmIlJWT0w6IHtzbmFwc2hvdC5ydm9sOi4xZn14IiwKICAgICAgICAgICAgICAgICAgICBmIlRhcGU6IHt0YXBlLm92ZXJhbGxfc2lnbmFsLnZhbHVlfSIsCiAgICAgICAgICAgICAgICAgICAgIkVudHJ5OiBSZWplY3Rpb24gd2ljayArIGJ1bGxpc2ggY2FuZGxlIGF0IFZXQVAiCiAgICAgICAgICAgICAgICBdLAogICAgICAgICAgICAgICAgdGltZV93aW5kb3c9c2VsZi5fZ2V0X2N1cnJlbnRfdGltZV93aW5kb3coKS52YWx1ZSwKICAgICAgICAgICAgICAgIG1hcmtldF9yZWdpbWU9c2VsZi5fbWFya2V0X3JlZ2ltZS52YWx1ZSwKICAgICAgICAgICAgICAgIGV4cGlyZXNfYXQ9KGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpICsgdGltZWRlbHRhKGhvdXJzPTEpKS5pc29mb3JtYXQoKQogICAgICAgICAgICApCiAgICAgICAgcmV0dXJuIE5vbmUKICAgIAo="
NEW_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfdndhcF9ib3VuY2Uoc2VsZiwgc3ltYm9sOiBzdHIsIHNuYXBzaG90LCB0YXBlOiBUYXBlUmVhZGluZykgLT4gT3B0aW9uYWxbTGl2ZUFsZXJ0XToKICAgICAgICAiIiJWV0FQIEJvdW5jZSBcdTIwMTQgRElTQUJMRUQgKHYxOS4zNC4zNTQsIGF1ZGl0IHN1cHByZXNzaW9uKS4KCiAgICAgICAgQXVkaXQgZmluZGluZzogdGhlIHNoaXBwZWQgbmVhci1WV0FQLVNUQVRFIHJ1bGUgKGRpc3RfZnJvbV92d2FwIGluICgtMC44JSwgKzAuMyUpLAogICAgICAgIHRyZW5kPT11cHRyZW5kLCBhYm92ZSA5LUVNQSwgcnZvbD49MS41OyBzdG9wPVZXQVAtMC41KkFUUiwgdGFyZ2V0PVZXQVArMS41KkFUUiwKICAgICAgICBSOlIgaGFyZC1jb2RlZCAzLjApIGlzIE5FR0FUSVZFLUVWLiAxNGQgbmF0aXZlLTFtaW4gcmVwbGF5IChkaWFnX3YzNTRfdndhcF9ib3VuY2UpOgogICAgICAgIHdpbnNvckF2ZyAtMC4xMDFSIG92ZXIgMiwzODcgZmlyZXMgKC0yNDJSIHRvdGFsKSBcdTIwMTQgNTklJSB3aW4gYnV0IEJST0tFTiBnZW9tZXRyeQogICAgICAgIChyZWFsaXplZCBhdmcgUjpSIDAuODUpLiBBIGRvY3RyaW5lIHJld3JpdGUgKFNNQiAiRmlyc3QgVldBUCBQdWxsYmFjayI6IG9wZW5pbmctZHJpdmUKICAgICAgICB1cC1sZWcgLT4gcHVsbGJhY2sgdGhhdCBIT0xEUyBhYm92ZSByaXNpbmcgVldBUCAtPiBjb25maXJtYXRpb24gYm91bmNlOyBzdG9wIGp1c3QgYmVsb3cKICAgICAgICBWV0FQLCB0YXJnZXQgPSBtZWFzdXJlZCBtb3ZlIG9mIHRoZSBmaXJzdCBsZWcpIHdhcyB0ZXN0ZWQgYWNyb3NzIGxlZ211bHQgMC41LzAuNzUvMS4wLAogICAgICAgIG1pbmxlZyAwLjUvMC43NS8xLjAsIHNpbmdsZS1hdHRlbXB0IGFuZCBSUiBjYXBzIDIuMC0yLjU6IEVWRVJZIFI6UiBiYW5kIHN0YXllZCBuZWdhdGl2ZQogICAgICAgIChkb2N0cmluZSBlbnRyeSBvbmx5IDMwLTQzJSUgd2luOyBiZXN0IGJhbmQgLTAuMDQ5UikuIE5vIHZhbGlkYXRlZCArRVYgY29uZmlndXJhdGlvbgogICAgICAgIGV4aXN0cyBpbiB0aGUgSUIgZGF0YSwgc28gdGhpcyBoaWdoLWZpcmUgc2V0dXAgaXMgU1VQUFJFU1NFRCB0byBzdG9wIHRoZSBibGVlZCBvbiB0aGUKICAgICAgICB1bm1hbmFnZWQgcGFwZXIgYWNjb3VudC4gUmUtZW5hYmxlIG9ubHkgYWZ0ZXIgYSByZXBsYXkgc3VyZmFjZXMgYSBiYW5kIHdpdGgKICAgICAgICB3aW5zb3JBdmcgPiAwLiAtLXJvbGxiYWNrIHJlc3RvcmVzIHRoZSBwcmlvciBuZWFyLVZXQVAgcnVsZS4KICAgICAgICAiIiIKICAgICAgICByZXR1cm4gTm9uZQogICAgCg=="
BACKUP = FILE + ".bak_v354"


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
    print(f"file            : {FILE}")
    print(f"whole-file SHA  : {cur}")
    print(f"expected (DGX)  : {DGX_WHOLE_PRE}  {'OK' if cur == DGX_WHOLE_PRE else 'DRIFT!'}")
    print(f"func anchor     : present={old in src} count={src.count(old)}")
    print(f"func PRE sha    : {_sha(old)}  {'OK' if _sha(old) == PRE_FUNC_SHA else 'MISMATCH'}")
    print(f"func POST sha   : {_sha(_new())}  {'OK' if _sha(_new()) == POST_FUNC_SHA else 'MISMATCH'}")
    if _new() in src: print("state           : ALREADY PATCHED")
    if cur != DGX_WHOLE_PRE:
        print("\nDRIFT: live file != DGX baseline (benign if already applied; else re-extract)."); return False
    if src.count(old) != 1:
        print("\nAnchor missing/ambiguous -- abort."); return False
    print("\nREADY: --apply suppresses vwap_bounce (return None); _atr_floored_stop preserved.")
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
    print("Verify: pytest backend/tests/test_v354_vwap_bounce.py -q ; commit BEFORE restart ; ./start_backend.sh --force")


def rollback():
    src = _read(); old, new = _old(), _new()
    if old in src and _sha(src) == DGX_WHOLE_PRE:
        print("Already at baseline. No-op."); return
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
