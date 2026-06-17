#!/usr/bin/env python3
"""
patch_v322_ev_aware_meta.py  (AGENTS.md §2.2 anchored-chunk patcher)

WHAT: replaces the meta-labeler's flat `p_win < 0.50` force-skip in
      confidence_gate.py with an EV-AWARE veto.
WHY : v321g proved the flat 0.50 wall causes 86% of all gate SKIPs and
      force-skips 24% of high-score GO-eligible setups — EV-blind (a 2:1
      setup is breakeven at p_win=0.33). New rule:
        floor = 1/(1+RR_assumed=2.0) + margin(0.05)  = ~0.383
        per-setup realized expectancy (setup_regime_expectancy cells) override:
            weighted_mean_r > 0      -> floor = min(floor, 0.30)   (proven +EV)
            weighted_mean_r <= hard_r-> floor = 0.50               (proven -EV)
        force_skip = p_win < floor
ROLLOUT: ACTIVE (paper-only env; zero financial risk). Fully reversible.

§2.2: PRE+POST SHA256 guards, base64 anchored chunk, --check/--apply/--rollback,
      backs up the original, refuses to write on drift or wrong post-hash.

Usage (from repo root, DGX):
  .venv/bin/python /tmp/patch_v322_ev_aware_meta.py --check
  .venv/bin/python /tmp/patch_v322_ev_aware_meta.py --apply
  .venv/bin/python /tmp/patch_v322_ev_aware_meta.py --rollback
Then: ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os

FILE = "backend/services/ai_modules/confidence_gate.py"
PRE_SHA  = "454318302b85bfd17f6e2b789221c074bfa08b30d30c4b8f28828ed9cb35193a"
POST_SHA = "de14fd64b4887c15494726f0bc60a250e75a1fe01c8fb05c1ea3c7f379835709"
OLD_B64 = "ICAgICAgICAgICAgZWxpZiBwX3dpbiA+PSAwLjUwOgogICAgICAgICAgICAgICAgIyBCb3JkZXJsaW5lIOKAlCBubyBzY29yZSBib29zdCwgYnV0IGtlZXAgdHJhZGUgYXQgaGFsZiBzaXplCiAgICAgICAgICAgICAgICByZWFzb25pbmcuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiRW5zZW1ibGUgbWV0YS1sYWJlbGVyIHtlbnNfbmFtZX06IFAod2luKT17cF93aW46LjAlfSBib3JkZXJsaW5lIOKAlCBoYWxmIHNpemUiCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAjIE1ldGEtbGFiZWxlciBzYXlzIG5vIGVkZ2Ug4oCUIEZPUkNFIFNLSVAKICAgICAgICAgICAgICAgIGZvcmNlX3NraXAgPSBUcnVlCiAgICAgICAgICAgICAgICByZWFzb25pbmcuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiRW5zZW1ibGUgbWV0YS1sYWJlbGVyIHtlbnNfbmFtZX06IFAod2luKT17cF93aW46LjAlfSA8IDUwJSDigJQgTk8gRURHRSwgc2tpcHBpbmcgdHJhZGUiCiAgICAgICAgICAgICAgICAp"
NEW_B64 = "ICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICMgdjMyMiBFVi1BV0FSRSBNRVRBIFZFVE8g4oCUIHJlcGxhY2VzIHRoZSBmbGF0IHBfd2luPDAuNTAgZm9yY2Utc2tpcC4KICAgICAgICAgICAgICAgICMgQSBmbGF0IDAuNTAgd2FsbCBpcyBFVi1ibGluZDogYSAyOjEgc2V0dXAgaXMgYnJlYWtldmVuIGF0IHBfd2luPTAuMzMsCiAgICAgICAgICAgICAgICAjIHNvIHBvc2l0aXZlLUVWIHNldHVwcyB3ZXJlIGZvcmNlLXNraXBwZWQgKDg2JSBvZiBhbGwgZ2F0ZSBTS0lQcywgdjMyMWcpLgogICAgICAgICAgICAgICAgIyBmbG9vciA9IGJyZWFrZXZlbihhc3N1bWVkIFJSKSArIG1hcmdpbjsgcGVyLXNldHVwIFJFQUxJWkVEIGV4cGVjdGFuY3kKICAgICAgICAgICAgICAgICMgKHNldHVwX3JlZ2ltZV9leHBlY3RhbmN5IGNlbGxzKSBvdmVycmlkZXMgdGhlIGZsb29yIHdoZXJlIHJlYWwgZGF0YSBleGlzdHMuCiAgICAgICAgICAgICAgICBfcnJfYXNzdW1lZCA9IDIuMAogICAgICAgICAgICAgICAgX21hcmdpbiA9IDAuMDUKICAgICAgICAgICAgICAgIF9ldl9mbG9vciA9ICgxLjAgLyAoMS4wICsgX3JyX2Fzc3VtZWQpKSArIF9tYXJnaW4gICMgfjAuMzgzCiAgICAgICAgICAgICAgICBfZXZfciA9IE5vbmUKICAgICAgICAgICAgICAgIF9ldl9uID0gMC4wCiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgaWYgc2VsZi5fcmVnaW1lX2V4cGVjdGFuY3kgYW5kIHNlbGYuX3JlZ2ltZV9leHBlY3RhbmN5LmdldCgiY2VsbHMiKToKICAgICAgICAgICAgICAgICAgICAgICAgZnJvbSBzZXJ2aWNlcy5haV9tb2R1bGVzLnJlZ2ltZV9leHBlY3RhbmN5X2NhbGlicmF0b3IgaW1wb3J0IGJhbmRfb2YgYXMgX2V2X2JhbmRfb2YKICAgICAgICAgICAgICAgICAgICAgICAgZnJvbSBzZXJ2aWNlcy5zZXR1cF90YXhvbm9teSBpbXBvcnQgY2Fub25pY2FsaXplIGFzIF9ldl9jYW5vbgogICAgICAgICAgICAgICAgICAgICAgICBfZXZfY2VsbHMgPSBzZWxmLl9yZWdpbWVfZXhwZWN0YW5jeVsiY2VsbHMiXQogICAgICAgICAgICAgICAgICAgICAgICBfZXZfcGFyYW1zID0gc2VsZi5fcmVnaW1lX2V4cGVjdGFuY3kuZ2V0KCJwYXJhbXMiLCB7fSkKICAgICAgICAgICAgICAgICAgICAgICAgX2V2X21pbl9uID0gX2V2X3BhcmFtcy5nZXQoIm1pbl9lZmZfbiIsIDApCiAgICAgICAgICAgICAgICAgICAgICAgIF9ldl9oYXJkX3IgPSBfZXZfcGFyYW1zLmdldCgiaGFyZF9yIiwgLTAuMzApCiAgICAgICAgICAgICAgICAgICAgICAgIF9ldl9iYW5kID0gX2V2X2JhbmRfb2YocmVnaW1lX3Njb3JlKQogICAgICAgICAgICAgICAgICAgICAgICBfZXZfc2V0dXAgPSBfZXZfY2Fub24oc2V0dXBfdHlwZSkKICAgICAgICAgICAgICAgICAgICAgICAgX2V2X2RpciA9ICJsb25nIiBpZiBzdHIoZGlyZWN0aW9uKS5sb3dlcigpLnN0YXJ0c3dpdGgoImwiKSBlbHNlICJzaG9ydCIKICAgICAgICAgICAgICAgICAgICAgICAgaWYgX2V2X2JhbmQ6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmb3IgX2V2X2tleSBpbiAoZiJ7X2V2X3NldHVwfXx7X2V2X2Rpcn18e19ldl9iYW5kfSIsIGYie19ldl9zZXR1cH18e19ldl9iYW5kfSIpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9ldl9jZWxsID0gX2V2X2NlbGxzLmdldChfZXZfa2V5KQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIChfZXZfY2VsbCBhbmQgKF9ldl9jZWxsLmdldCgiZWZmX24iKSBvciAwLjApID49IF9ldl9taW5fbgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYW5kIF9ldl9jZWxsLmdldCgid2VpZ2h0ZWRfbWVhbl9yIikgaXMgbm90IE5vbmUpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfZXZfciA9IF9ldl9jZWxsWyJ3ZWlnaHRlZF9tZWFuX3IiXQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfZXZfbiA9IF9ldl9jZWxsWyJlZmZfbiJdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIF9ldl9yIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgX2V2X3IgPiAwOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9ldl9mbG9vciA9IG1pbihfZXZfZmxvb3IsIDAuMzApCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBlbGlmIF9ldl9yIDw9IF9ldl9oYXJkX3I6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2V2X2Zsb29yID0gMC41MAogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBfZXZfciA9IE5vbmUKICAgICAgICAgICAgICAgIF9ldl9ub3RlID0gKGYiLCByZWFsaXplZCBFViB7X2V2X3I6Ky4yZn1SIG49e19ldl9uOi4wZn0iIGlmIF9ldl9yIGlzIG5vdCBOb25lIGVsc2UgIiIpCiAgICAgICAgICAgICAgICBpZiBwX3dpbiA8IF9ldl9mbG9vcjoKICAgICAgICAgICAgICAgICAgICBmb3JjZV9za2lwID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIHJlYXNvbmluZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgIGYiRW5zZW1ibGUgbWV0YS1sYWJlbGVyIHtlbnNfbmFtZX06IFAod2luKT17cF93aW46LjAlfSA8IEVWLWZsb29yICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJ7X2V2X2Zsb29yOi4wJX0gKFJSfntfcnJfYXNzdW1lZDouMGZ9OjF7X2V2X25vdGV9KSDigJQgTk8gRURHRSwgc2tpcHBpbmcgdHJhZGUiCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICByZWFzb25pbmcuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgICAgICBmIkVuc2VtYmxlIG1ldGEtbGFiZWxlciB7ZW5zX25hbWV9OiBQKHdpbik9e3Bfd2luOi4wJX0gPj0gRVYtZmxvb3IgIgogICAgICAgICAgICAgICAgICAgICAgICBmIntfZXZfZmxvb3I6LjAlfSDigJQgdjMyMiBFVi1hd2FyZSBBTExPV3tfZXZfbm90ZX0iCiAgICAgICAgICAgICAgICAgICAgKQ=="
BACKUP = FILE + ".bak_v322"


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _read():
    if not os.path.exists(FILE):
        print(f"ERROR: {FILE} not found (run from repo root)"); sys.exit(2)
    return open(FILE, encoding="utf-8").read()


def _old():
    return base64.b64decode(OLD_B64).decode("utf-8")


def _new():
    return base64.b64decode(NEW_B64).decode("utf-8")


def check():
    src = _read(); cur = _sha(src); old = _old()
    print(f"file        : {FILE}")
    print(f"current SHA : {cur}")
    print(f"expected PRE: {PRE_SHA}  {'OK' if cur == PRE_SHA else 'DRIFT!'}")
    print(f"anchor found: {old in src}  (count={src.count(old)})")
    if _new() in src:
        print("state       : ALREADY PATCHED (new block present)")
    if cur != PRE_SHA:
        print("\nDRIFT: live file differs from the tested baseline. Do NOT --apply.")
        print("Upload your copy:  curl --data-binary @%s https://paste.rs/" % FILE)
        return False
    if old not in src or src.count(old) != 1:
        print("\nAnchor missing/ambiguous — abort."); return False
    print("\nREADY: --apply will replace the flat 0.50 force-skip with the EV-aware veto.")
    print(f"post-apply SHA will be: {POST_SHA}")
    return True


def apply():
    src = _read()
    if _sha(src) == POST_SHA and _new() in src:
        print("Already patched (POST_SHA matches). No-op."); return
    if _sha(src) != PRE_SHA:
        print(f"ABORT: PRE_SHA mismatch (got {_sha(src)}). File drifted — see --check."); sys.exit(3)
    old, new = _old(), _new()
    if src.count(old) != 1:
        print(f"ABORT: anchor count={src.count(old)} (need 1)."); sys.exit(3)
    patched = src.replace(old, new, 1)
    if _sha(patched) != POST_SHA:
        print(f"ABORT: POST_SHA mismatch (got {_sha(patched)}, want {POST_SHA})."); sys.exit(3)
    shutil.copy2(FILE, BACKUP)
    with open(FILE, "w", encoding="utf-8") as f:
        f.write(patched)
    print(f"APPLIED. backup -> {BACKUP}")
    print(f"new SHA : {_sha(patched)}  (== POST_SHA: {_sha(patched) == POST_SHA})")
    print("Restart: ./start_backend.sh --force")


def rollback():
    src = _read()
    if _sha(src) == PRE_SHA:
        print("Already at PRE_SHA (unpatched). No-op."); return
    old, new = _old(), _new()
    if new in src and src.count(new) == 1:
        restored = src.replace(new, old, 1)
        if _sha(restored) == PRE_SHA:
            shutil.copy2(FILE, FILE + ".bak_pre_rollback")
            with open(FILE, "w", encoding="utf-8") as f:
                f.write(restored)
            print(f"ROLLED BACK via reverse-anchor. SHA: {_sha(restored)} (== PRE: True)")
            return
        print("WARN: reverse-anchor did not reproduce PRE_SHA.")
    if os.path.exists(BACKUP):
        bsrc = open(BACKUP, encoding="utf-8").read()
        if _sha(bsrc) == PRE_SHA:
            shutil.copy2(BACKUP, FILE)
            print(f"ROLLED BACK from {BACKUP}. SHA: {_sha(bsrc)} (== PRE: True)")
            return
        print("WARN: backup SHA != PRE_SHA.")
    print("ABORT: could not safely roll back."); sys.exit(4)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if arg == "--check":
        check()
    elif arg == "--apply":
        apply()
    elif arg == "--rollback":
        rollback()
    else:
        print("usage: --check | --apply | --rollback")
