#!/usr/bin/env python3
# patch_v361_big_dog_gates.py
# ---------------------------------------------------------------------------
# v361 — TIGHTEN `_check_big_dog`: add a $10 min-price gate + a 1.0% min-stop gate.
# (NOT a suppress — big_dog has a real edge once the slippage tail is cut.)
#
# EVIDENCE (diag_v361_big_dog_replay.py, 180d / 300-sym, 5-min intraday):
#   baseline LIVE trigger@HOD : n=38166 win 46% winsorAvg -0.009 medR +0.000  (breakeven)
#   + min-stop>=1% + price>=$10: n=268  win 53% winsorAvg +0.097 medR +0.132  (+EV, healthy n)
#   tighter coil alone (range<1.5%, distHOD<0.5%) did NOT help (-0.013) -> the lever is the
#   stop/price floor, not the coil. GROUND TRUTH (5 real fills): avgR -2.0 -- every loss was a
#   sub-1% stop on a <$30 name (KRG $25.86 stop 25.74 -> gapped to 25.53) blowing through.
#   So big_dog bleeds ONLY on tight-stop/illiquid fires; gating those out makes it +EV.
#
# Anchored-chunk patcher (AGENTS.md §2): whole-file PRE-SHA guard + exact OLD-bytes match
# (count MUST be 1) + post-write self-verify. ABORTS before writing on ANY drift. Auto-backup.
# Supports --check dry-run.
#
# Deploy (DGX, repo root):
#   curl -sS -o /tmp/patch_v361.py https://paste.rs/<id>
#   .venv/bin/python /tmp/patch_v361.py --check
#   .venv/bin/python /tmp/patch_v361.py
#   .venv/bin/python -m pytest backend/tests/test_v361_big_dog_gates.py -q
#   git add backend/ memory/ && git commit -m "v361: big_dog +$10 min-price +1% min-stop gates (cut slippage tail)" && git push origin main
#   git status --short   # must be clean
#   ./start_backend.sh --force
# ---------------------------------------------------------------------------
import base64
import hashlib
import shutil
import sys

FILE = "backend/services/enhanced_scanner.py"
PRE_FILE_SHA = "0569a72496a91696dffc954223197f5d32ae2a10c9205a510743a38f50de6314"

OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfYmlnX2RvZyhzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIkJpZyBEb2cgQ29uc29saWRhdGlvbiAtIFRpZ2h0IHdlZGdlIDE1KyBtaW4iIiIKICAgICAgICBpZiAoc25hcHNob3QuZGFpbHlfcmFuZ2VfcGN0IDwgMi4wIGFuZAogICAgICAgICAgICBzbmFwc2hvdC5hYm92ZV92d2FwIGFuZAogICAgICAgICAgICBzbmFwc2hvdC5hYm92ZV9lbWE5IGFuZAogICAgICAgICAgICBzbmFwc2hvdC5ydm9sID49IDEuMik6CiAgICAgICAgICAgIAogICAgICAgICAgICBkaXN0X2Zyb21faG9kID0gKChzbmFwc2hvdC5oaWdoX29mX2RheSAtIHNuYXBzaG90LmN1cnJlbnRfcHJpY2UpIC8gc25hcHNob3QuY3VycmVudF9wcmljZSkgKiAxMDAKICAgICAgICAgICAgCiAgICAgICAgICAgIGlmIGRpc3RfZnJvbV9ob2QgPCAxLjA6CiAgICAgICAgICAgICAgICBwcmlvcml0eSA9IEFsZXJ0UHJpb3JpdHkuTUVESVVNCiAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgIHJldHVybiBMaXZlQWxlcnQoCiAgICAgICAgICAgICAgICAgICAgaWQ9ZiJiaWdfZG9nX3tzeW1ib2x9X3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJUglTSVTJyl9IiwKICAgICAgICAgICAgICAgICAgICBzeW1ib2w9c3ltYm9sLAogICAgICAgICAgICAgICAgICAgIHNldHVwX3R5cGU9ImJpZ19kb2ciLAogICAgICAgICAgICAgICAgICAgIHN0cmF0ZWd5X25hbWU9IkJpZyBEb2cgQ29uc29saWRhdGlvbiAoSU5ULTQ0KSIsCiAgICAgICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJsb25nIiwKICAgICAgICAgICAgICAgICAgICBwcmlvcml0eT1wcmlvcml0eSwKICAgICAgICAgICAgICAgICAgICBjdXJyZW50X3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICAgICAgdHJpZ2dlcl9wcmljZT1zbmFwc2hvdC5oaWdoX29mX2RheSwKICAgICAgICAgICAgICAgICAgICBzdG9wX2xvc3M9c2VsZi5fYXRyX2Zsb29yZWRfc3RvcCgKICAgICAgICAgICAgICAgICAgICAgICAgZW50cnlfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgICAgICAgICAgcmF3X3N0b3A9c25hcHNob3QuZW1hXzkgLSAwLjAyLAogICAgICAgICAgICAgICAgICAgICAgICBhdHI9Z2V0YXR0cihzbmFwc2hvdCwgImF0ciIsIE5vbmUpLAogICAgICAgICAgICAgICAgICAgICAgICBkaXJlY3Rpb249ImxvbmciLAogICAgICAgICAgICAgICAgICAgICAgICBtaW5fYXRyX211bHQ9MC41LAogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgdGFyZ2V0PXJvdW5kKHNuYXBzaG90LmhpZ2hfb2ZfZGF5ICsgKHNuYXBzaG90LmF0ciAqIDEuNSksIDIpLAogICAgICAgICAgICAgICAgICAgIHJpc2tfcmV3YXJkPTIuMCwKICAgICAgICAgICAgICAgICAgICB0cmlnZ2VyX3Byb2JhYmlsaXR5PTAuNTUsCiAgICAgICAgICAgICAgICAgICAgd2luX3Byb2JhYmlsaXR5PTAuNTUsCiAgICAgICAgICAgICAgICAgICAgbWludXRlc190b190cmlnZ2VyPTE1LAogICAgICAgICAgICAgICAgICAgIGhlYWRsaW5lPWYi8J+QlSB7c3ltYm9sfSBCaWcgRG9nIC0gVGlnaHQgY29uc29saWRhdGlvbiIsCiAgICAgICAgICAgICAgICAgICAgcmVhc29uaW5nPVsKICAgICAgICAgICAgICAgICAgICAgICAgIlRpZ2h0IHJhbmdlIG5lYXIgSE9EIiwKICAgICAgICAgICAgICAgICAgICAgICAgIkFib3ZlIFZXQVAgYW5kIDktRU1BIiwKICAgICAgICAgICAgICAgICAgICAgICAgZiJUYXBlOiB7dGFwZS5vdmVyYWxsX3NpZ25hbC52YWx1ZX0iCiAgICAgICAgICAgICAgICAgICAgXSwKICAgICAgICAgICAgICAgICAgICB0aW1lX3dpbmRvdz1zZWxmLl9nZXRfY3VycmVudF90aW1lX3dpbmRvdygpLnZhbHVlLAogICAgICAgICAgICAgICAgICAgIG1hcmtldF9yZWdpbWU9c2VsZi5fbWFya2V0X3JlZ2ltZS52YWx1ZSwKICAgICAgICAgICAgICAgICAgICBleHBpcmVzX2F0PShkYXRldGltZS5ub3codGltZXpvbmUudXRjKSArIHRpbWVkZWx0YShob3Vycz0xKSkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gTm9uZQogICAgCg=="

NEW_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfYmlnX2RvZyhzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIkJpZyBEb2cgQ29uc29saWRhdGlvbiAtIFRpZ2h0IHdlZGdlIDE1KyBtaW4gKExPTkcsIEhPRCBicmVha291dCkuCiAgICAgICAgdjM2MSDigJQgKyBtaW4tcHJpY2UgJDEwICsgbWluLXN0b3AgMS4wJSBnYXRlcy4gMTgwZC8zMDAtc3ltIDUtbWluIHJlcGxheTogdGhlCiAgICAgICAgYmFzZWxpbmUgdHJpZ2dlckBIT0QgbW9kZWwgaXMgYnJlYWtldmVuICh3aW5zb3JBdmcgLTAuMDA5UikgYnV0IGZsaXBzIHRvICswLjA5N1IKICAgICAgICAod2luIDUzJSwgbWVkUiArMC4xMzIsIG49MjY4KSBvbmNlIHRpZ2h0LXN0b3AgYmxvdy10aHJvdWdocyBvbiBsb3ctcHJpY2VkL2lsbGlxdWlkCiAgICAgICAgbmFtZXMgYXJlIGV4Y2x1ZGVkLiBHcm91bmQgdHJ1dGggKG49NSByZWFsIGZpbGxzKSB3YXMgYXZnUiAtMi4wIOKAlCBhbGwgc3ViLTElIHN0b3BzCiAgICAgICAgb24gPCQzMCBuYW1lcyB0aGF0IGdhcHBlZCB0aHJvdWdoIHRoZSBzdG9wLiBTZWUgbWVtb3J5L3YzNjFfYmlnX2RvZ19idWlsZC5tZC4iIiIKICAgICAgICBpZiAoc25hcHNob3QuZGFpbHlfcmFuZ2VfcGN0IDwgMi4wIGFuZAogICAgICAgICAgICBzbmFwc2hvdC5hYm92ZV92d2FwIGFuZAogICAgICAgICAgICBzbmFwc2hvdC5hYm92ZV9lbWE5IGFuZAogICAgICAgICAgICBzbmFwc2hvdC5ydm9sID49IDEuMiBhbmQKICAgICAgICAgICAgc25hcHNob3QuY3VycmVudF9wcmljZSA+PSAxMC4wKTogICMgdjM2MSBwcmljZSBmbG9vciAoZHJvcCBpbGxpcXVpZCkKICAgICAgICAgICAgCiAgICAgICAgICAgIGRpc3RfZnJvbV9ob2QgPSAoKHNuYXBzaG90LmhpZ2hfb2ZfZGF5IC0gc25hcHNob3QuY3VycmVudF9wcmljZSkgLyBzbmFwc2hvdC5jdXJyZW50X3ByaWNlKSAqIDEwMAogICAgICAgICAgICAKICAgICAgICAgICAgaWYgZGlzdF9mcm9tX2hvZCA8IDEuMDoKICAgICAgICAgICAgICAgICMgdjM2MSBtaW4tc3RvcCBmbG9vciDigJQgcmVqZWN0IHRpZ2h0LXN0b3AgYmxvdy10aHJvdWdocyAodGhlIGdyb3VuZC10cnV0aAogICAgICAgICAgICAgICAgIyBibGVlZDogbj01IGF2Z1IgLTIuMCwgYWxsIHN1Yi0xJSBzdG9wcyBvbiA8JDMwIG5hbWVzIHRoYXQgZ2FwcGVkIHRocm91Z2gpLgogICAgICAgICAgICAgICAgc3RvcCA9IHNlbGYuX2F0cl9mbG9vcmVkX3N0b3AoCiAgICAgICAgICAgICAgICAgICAgZW50cnlfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgICAgICByYXdfc3RvcD1zbmFwc2hvdC5lbWFfOSAtIDAuMDIsCiAgICAgICAgICAgICAgICAgICAgYXRyPWdldGF0dHIoc25hcHNob3QsICJhdHIiLCBOb25lKSwKICAgICAgICAgICAgICAgICAgICBkaXJlY3Rpb249ImxvbmciLAogICAgICAgICAgICAgICAgICAgIG1pbl9hdHJfbXVsdD0wLjUsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiBzbmFwc2hvdC5jdXJyZW50X3ByaWNlIDw9IDAgb3IgKHNuYXBzaG90LmN1cnJlbnRfcHJpY2UgLSBzdG9wKSAvIHNuYXBzaG90LmN1cnJlbnRfcHJpY2UgKiAxMDAgPCAxLjA6CiAgICAgICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgICAgIHByaW9yaXR5ID0gQWxlcnRQcmlvcml0eS5NRURJVU0KICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAgcmV0dXJuIExpdmVBbGVydCgKICAgICAgICAgICAgICAgICAgICBpZD1mImJpZ19kb2dfe3N5bWJvbH1fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclSCVNJVMnKX0iLAogICAgICAgICAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgICAgICAgICAgc2V0dXBfdHlwZT0iYmlnX2RvZyIsCiAgICAgICAgICAgICAgICAgICAgc3RyYXRlZ3lfbmFtZT0iQmlnIERvZyBDb25zb2xpZGF0aW9uIChJTlQtNDQpIiwKICAgICAgICAgICAgICAgICAgICBkaXJlY3Rpb249ImxvbmciLAogICAgICAgICAgICAgICAgICAgIHByaW9yaXR5PXByaW9yaXR5LAogICAgICAgICAgICAgICAgICAgIGN1cnJlbnRfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPXNuYXBzaG90LmhpZ2hfb2ZfZGF5LAogICAgICAgICAgICAgICAgICAgIHN0b3BfbG9zcz1zdG9wLAogICAgICAgICAgICAgICAgICAgIHRhcmdldD1yb3VuZChzbmFwc2hvdC5oaWdoX29mX2RheSArIChzbmFwc2hvdC5hdHIgKiAxLjUpLCAyKSwKICAgICAgICAgICAgICAgICAgICByaXNrX3Jld2FyZD0yLjAsCiAgICAgICAgICAgICAgICAgICAgdHJpZ2dlcl9wcm9iYWJpbGl0eT0wLjU1LAogICAgICAgICAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjU1LAogICAgICAgICAgICAgICAgICAgIG1pbnV0ZXNfdG9fdHJpZ2dlcj0xNSwKICAgICAgICAgICAgICAgICAgICBoZWFkbGluZT1mIvCfkJUge3N5bWJvbH0gQmlnIERvZyAtIFRpZ2h0IGNvbnNvbGlkYXRpb24iLAogICAgICAgICAgICAgICAgICAgIHJlYXNvbmluZz1bCiAgICAgICAgICAgICAgICAgICAgICAgICJUaWdodCByYW5nZSBuZWFyIEhPRCIsCiAgICAgICAgICAgICAgICAgICAgICAgICJBYm92ZSBWV0FQIGFuZCA5LUVNQSIsCiAgICAgICAgICAgICAgICAgICAgICAgIGYiVGFwZToge3RhcGUub3ZlcmFsbF9zaWduYWwudmFsdWV9IgogICAgICAgICAgICAgICAgICAgIF0sCiAgICAgICAgICAgICAgICAgICAgdGltZV93aW5kb3c9c2VsZi5fZ2V0X2N1cnJlbnRfdGltZV93aW5kb3coKS52YWx1ZSwKICAgICAgICAgICAgICAgICAgICBtYXJrZXRfcmVnaW1lPXNlbGYuX21hcmtldF9yZWdpbWUudmFsdWUsCiAgICAgICAgICAgICAgICAgICAgZXhwaXJlc19hdD0oZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykgKyB0aW1lZGVsdGEoaG91cnM9MSkpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgcmV0dXJuIE5vbmUKICAgIAo="


def main():
    check = "--check" in sys.argv
    src = open(FILE, encoding="utf-8").read()
    cur_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
    print(f"file            : {FILE}")
    print(f"live SHA        : {cur_sha}")
    print(f"expected SHA    : {PRE_FILE_SHA}")
    if cur_sha != PRE_FILE_SHA:
        print("\nABORT: live file SHA != expected baseline. The DGX file has DRIFTED.")
        print("Re-run extract_func.py _check_big_dog and rebase. NOTHING was written.")
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
    if patched.count(new) != 1 or old in patched:
        print("\nABORT: post-replace self-check failed. NOTHING was written.")
        sys.exit(4)
    print(f"POST SHA        : {post_sha}")

    if check:
        print("\n--check OK: guards pass, OLD found exactly once, replacement is clean.")
        print("Run without --check to apply.")
        return

    bak = FILE + ".v361.bak"
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
