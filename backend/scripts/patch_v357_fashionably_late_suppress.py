#!/usr/bin/env python3
# patch_v357_fashionably_late_suppress.py
# ---------------------------------------------------------------------------
# v357 — SUPPRESS `_check_fashionably_late` (return None), mirroring the
# vwap_bounce v354 suppression.
#
# EVIDENCE (diag_v357_fashionably_late_replay.py, 120d / 300-sym IB intraday):
#   • SMB-doctrine measured-move 3:1 exits  : ALL win 31%, winsorAvg -0.149
#   • current LIVE ATR-floored-stop exits    : ALL win 23%, winsorAvg -0.265 (WORST)
#   • best quality subset (loose + vol-conv + fast-turn): win 54% but winsorAvg
#     -0.018 R/trade BEFORE costs (avgRR collapses to 0.67) -> negative after costs.
#   No tested geometry or quality gate produced a tradeable +EV subset.
#
# Anchored-chunk patcher (AGENTS.md §2 convention): whole-file PRE-SHA guard +
# exact OLD-bytes match (count MUST be 1) + post-write self-verify. ABORTS before
# writing on ANY drift. Backs up the original. Supports --check dry-run.
#
# Deploy (DGX, repo root):
#   curl -sS -o /tmp/patch_v357.py https://paste.rs/<id>
#   .venv/bin/python /tmp/patch_v357.py --check     # dry-run: hash + anchor guards
#   .venv/bin/python /tmp/patch_v357.py             # apply (auto-backup .bak)
#   .venv/bin/python -m pytest backend/tests/test_v357_fashionably_late_suppress.py -q
#   # COMMIT BEFORE ANY RESTART (StartTrading.bat git-wipes uncommitted code):
#   git add backend/ && git commit -m "v357: suppress fashionably_late (negative-EV)" && git push origin main
#   ./start_backend.sh --force
# ---------------------------------------------------------------------------
import base64
import hashlib
import shutil
import sys

FILE = "backend/services/enhanced_scanner.py"

# whole-file SHA256 of the LIVE DGX enhanced_scanner.py this patch was built against
PRE_FILE_SHA = "30eba7d1faf17f1c4fa0794c564e5790b73e4baf0b35f04095a1cbc16d03b1ac"

# (OLD, NEW) base64 chunk pair. OLD = exact live bytes from extract_func.py.
OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfZmFzaGlvbmFibHlfbGF0ZShzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIkZhc2hpb25hYmx5IExhdGUgLSA5LUVNQSBjcm9zc2VzIFZXQVAiIiIKICAgICAgICBpZiAoc25hcHNob3QuYWJvdmVfZW1hOSBhbmQgCiAgICAgICAgICAgIHNuYXBzaG90LmVtYV85ID4gc25hcHNob3QudndhcCBhbmQKICAgICAgICAgICAgKHNuYXBzaG90LmVtYV85IC0gc25hcHNob3QudndhcCkgLyBzbmFwc2hvdC52d2FwICogMTAwIDwgMC41IGFuZAogICAgICAgICAgICBzbmFwc2hvdC50cmVuZCA9PSAidXB0cmVuZCIgYW5kCiAgICAgICAgICAgIHNuYXBzaG90LnJ2b2wgPj0gMS4yKToKICAgICAgICAgICAgCiAgICAgICAgICAgIHJldHVybiBMaXZlQWxlcnQoCiAgICAgICAgICAgICAgICBpZD1mImZhc2hpb25hYmx5X2xhdGVfe3N5bWJvbH1fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclSCVNJVMnKX0iLAogICAgICAgICAgICAgICAgc3ltYm9sPXN5bWJvbCwKICAgICAgICAgICAgICAgIHNldHVwX3R5cGU9ImZhc2hpb25hYmx5X2xhdGUiLAogICAgICAgICAgICAgICAgc3RyYXRlZ3lfbmFtZT0iRmFzaGlvbmFibHkgTGF0ZSAoSU5ULTI2KSIsCiAgICAgICAgICAgICAgICBkaXJlY3Rpb249ImxvbmciLAogICAgICAgICAgICAgICAgIyB2MTkuMzQuMzIwciDigJQgdGFwZS1nYXRlZCBISUdIIGJyYW5jaCAod2FzIGhhcmRjb2RlZCBNRURJVU0sIHdoaWNoIGNhcHBlZAogICAgICAgICAgICAgICAgIyB0aGlzIGludHJhZGF5IHNjYWxwIGJlbG93IHRoZSBhdXRvLWZpcmUgYmFyIHJlZ2FyZGxlc3Mgb2Ygc2lnbmFsCiAgICAgICAgICAgICAgICAjIHF1YWxpdHk7IHNlZSB2MzIwcSArIHYzMjByLXByZWNoZWNrKS4gT25seSB0aGUgdGFwZS1jb25maXJtZWQKICAgICAgICAgICAgICAgICMgc3Vic2V0IHByb21vdGVzOyBFVi93aW4tcmF0ZSBnYXRlIHN0aWxsIGdvdmVybnMgYXV0by1maXJlLgogICAgICAgICAgICAgICAgcHJpb3JpdHk9QWxlcnRQcmlvcml0eS5ISUdIIGlmIHRhcGUuY29uZmlybWF0aW9uX2Zvcl9sb25nIGVsc2UgQWxlcnRQcmlvcml0eS5NRURJVU0sCiAgICAgICAgICAgICAgICBjdXJyZW50X3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICBzdG9wX2xvc3M9c2VsZi5fYXRyX2Zsb29yZWRfc3RvcCggICMgdjE5LjM0LjUwCiAgICAgICAgICAgICAgICAgICAgZW50cnlfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgICAgICByYXdfc3RvcD1zbmFwc2hvdC52d2FwIC0gKHNuYXBzaG90LmF0ciAqIDAuMzMpLAogICAgICAgICAgICAgICAgICAgIGF0cj1nZXRhdHRyKHNuYXBzaG90LCAiYXRyIiwgTm9uZSksCiAgICAgICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJsb25nIiwKICAgICAgICAgICAgICAgICAgICBtaW5fYXRyX211bHQ9MC41LAogICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgIHRhcmdldD1yb3VuZChzbmFwc2hvdC52d2FwICsgKHNuYXBzaG90LnZ3YXAgLSBzbmFwc2hvdC5sb3dfb2ZfZGF5KSwgMiksCiAgICAgICAgICAgICAgICByaXNrX3Jld2FyZD0zLjAsCiAgICAgICAgICAgICAgICB0cmlnZ2VyX3Byb2JhYmlsaXR5PTAuNTUsCiAgICAgICAgICAgICAgICB3aW5fcHJvYmFiaWxpdHk9MC42MCwKICAgICAgICAgICAgICAgIG1pbnV0ZXNfdG9fdHJpZ2dlcj0xNSwKICAgICAgICAgICAgICAgIGhlYWRsaW5lPWYi4o+wIHtzeW1ib2x9IEZhc2hpb25hYmx5IExhdGUgLSA5LUVNQSBjcm9zc2luZyBWV0FQIiwKICAgICAgICAgICAgICAgIHJlYXNvbmluZz1bCiAgICAgICAgICAgICAgICAgICAgIjktRU1BIGp1c3QgY3Jvc3NlZCBWV0FQIiwKICAgICAgICAgICAgICAgICAgICAiTW9tZW50dW0gYnVpbGRpbmciLAogICAgICAgICAgICAgICAgICAgIGYiVGFwZToge3RhcGUub3ZlcmFsbF9zaWduYWwudmFsdWV9IgogICAgICAgICAgICAgICAgXSwKICAgICAgICAgICAgICAgIHRpbWVfd2luZG93PXNlbGYuX2dldF9jdXJyZW50X3RpbWVfd2luZG93KCkudmFsdWUsCiAgICAgICAgICAgICAgICBtYXJrZXRfcmVnaW1lPXNlbGYuX21hcmtldF9yZWdpbWUudmFsdWUsCiAgICAgICAgICAgICAgICBleHBpcmVzX2F0PShkYXRldGltZS5ub3codGltZXpvbmUudXRjKSArIHRpbWVkZWx0YShob3Vycz0xKSkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgKQogICAgICAgIHJldHVybiBOb25lCiAgICAK"

NEW_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfZmFzaGlvbmFibHlfbGF0ZShzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIkZhc2hpb25hYmx5IExhdGUg4oCUIFNVUFBSRVNTRUQgdjM1NyAocmV0dXJucyBOb25lKS4KICAgICAgICBSZXBsYXkgYWNyb3NzIDEyMGQgLyAzMDAtc3ltYm9sIElCIGludHJhZGF5IGJhcnMgcHJvdmVkIHRoZSA5LUVNQcOXVldBUCBjcm9zcyBpcwogICAgICAgIHN1Yi1jb3N0IG5lZ2F0aXZlLUVWIHVuZGVyIEVWRVJZIHRlc3RlZCBnZW9tZXRyeTogU01CLWRvY3RyaW5lIG1lYXN1cmVkLW1vdmUgMzoxCiAgICAgICAgYmVzdCBzdWJzZXQgPSAtMC4wMTggUi90cmFkZSBCRUZPUkUgY29tbWlzc2lvbnMvc2xpcHBhZ2UgKHdpbiA1NCUsIGF2Z1JSIDAuNjcpOwogICAgICAgIHRoZSBwcmV2aW91cyBsaXZlIEFUUi1mbG9vcmVkLXN0b3AgZ2VvbWV0cnkgd2FzIHRoZSB3b3JzdCB2YXJpYW50IGF0IC0wLjI3IHRvCiAgICAgICAgLTAuNTMgUi90cmFkZSAod2luIDEzLTIzJSkuIE5vIHF1YWxpdHkgZ2F0ZSAodm9sLWNvbnZlcmdlbmNlIC8gZmFzdC10dXJuIC8KICAgICAgICB0aW1lLXdpbmRvdykgaXNvbGF0ZWQgYSB0cmFkZWFibGUgK0VWIHN1YnNldC4gU3VwcHJlc3NlZCBsaWtlIHZ3YXBfYm91bmNlICh2MzU0KS4KICAgICAgICBTZWUgbWVtb3J5L3YzNTdfZmFzaGlvbmFibHlfbGF0ZV9idWlsZC5tZCBmb3IgdGhlIGZ1bGwgcmVwbGF5IGV2aWRlbmNlLiIiIgogICAgICAgIHJldHVybiBOb25lCiAgICAK"


def main():
    check = "--check" in sys.argv
    src = open(FILE, encoding="utf-8").read()
    cur_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
    print(f"file            : {FILE}")
    print(f"live SHA        : {cur_sha}")
    print(f"expected SHA    : {PRE_FILE_SHA}")
    if cur_sha != PRE_FILE_SHA:
        print("\nABORT: live file SHA != expected baseline. The DGX file has DRIFTED.")
        print("Re-run extract_func.py _check_fashionably_late and upload the live file so the")
        print("patch can be rebased. NOTHING was written.")
        sys.exit(2)

    old = base64.b64decode(OLD_B64).decode("utf-8")
    new = base64.b64decode(NEW_B64).decode("utf-8")
    n = src.count(old)
    print(f"OLD anchor count: {n}  (MUST be 1)")
    if n != 1:
        print("\nABORT: OLD anchor not uniquely found. NOTHING was written.")
        sys.exit(3)

    patched = src.replace(old, new, 1)
    post_sha = hashlib.sha256(patched.encode("utf-8")).hexdigest()
    # self-verify the result
    if patched.count(new) != 1 or old in patched:
        print("\nABORT: post-replace self-check failed. NOTHING was written.")
        sys.exit(4)
    print(f"POST SHA        : {post_sha}")

    if check:
        print("\n--check OK: guards pass, OLD found exactly once, replacement is clean.")
        print("Run without --check to apply.")
        return

    bak = FILE + ".v357.bak"
    shutil.copy2(FILE, bak)
    with open(FILE, "w", encoding="utf-8") as f:
        f.write(patched)
    verify = hashlib.sha256(open(FILE, encoding="utf-8").read().encode("utf-8")).hexdigest()
    if verify != post_sha:
        print(f"\nABORT: post-write verify mismatch ({verify} != {post_sha}).")
        sys.exit(5)
    print(f"\nAPPLIED. backup -> {bak}")
    print(f"new live SHA    : {verify}")
    print("Next: pytest -> commit -> ./start_backend.sh --force")


if __name__ == "__main__":
    main()
