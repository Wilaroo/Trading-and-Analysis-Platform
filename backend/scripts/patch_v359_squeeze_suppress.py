#!/usr/bin/env python3
# patch_v359_squeeze_suppress.py
# ---------------------------------------------------------------------------
# v359 — SUPPRESS `_check_squeeze` (return None), dedup of the daily-compression edge.
#
# EVIDENCE:
#   • GROUND TRUTH (diag_v359b, 473 closed bot_trades, synthetic excluded): negative-EV on
#     every cut — ALL winsorAvg -0.158 (31% win, totR -128.8), LONG -0.080 (n=285),
#     SHORT -0.277 (n=188).
#   • SIM (diag_v359, market-order fill = its real execution): -0.475 R/trade.
#   • STRUCTURAL: the "intraday" squeeze is actually a DAILY-bar signal (squeeze_on / bb_width /
#     atr / rvol all built from daily bars), fires ~46k/yr with NO tightness gate, and fully
#     overlaps daily_squeeze — which after v358 is long-only and already harvests the genuine
#     +EV daily-compression LONG edge with sound geometry. squeeze is a duplicate bleeder.
#
# Anchored-chunk patcher (AGENTS.md §2): whole-file PRE-SHA guard + exact OLD-bytes match
# (count MUST be 1) + post-write self-verify. ABORTS before writing on ANY drift. Auto-backup.
# Supports --check dry-run.
#
# Deploy (DGX, repo root):
#   curl -sS -o /tmp/patch_v359.py https://paste.rs/<id>
#   .venv/bin/python /tmp/patch_v359.py --check
#   .venv/bin/python /tmp/patch_v359.py
#   .venv/bin/python -m pytest backend/tests/test_v359_squeeze_suppress.py -q
#   git add backend/ memory/ && git commit -m "v359: suppress squeeze (negative-EV daily-compression duplicate)" && git push origin main
#   ./start_backend.sh --force
# ---------------------------------------------------------------------------
import base64
import hashlib
import shutil
import sys

FILE = "backend/services/enhanced_scanner.py"

PRE_FILE_SHA = "dbe2a191fca7cca6e4e83e3b18c003b6bb839f042ce7dc266841b10ccfcfc9a1"

OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfc3F1ZWV6ZShzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIlNxdWVlemUgRGV0ZWN0aW9uOiBCb2xsaW5nZXIgQmFuZHMgaW5zaWRlIEtlbHRuZXIgQ2hhbm5lbHMgPSB2b2xhdGlsaXR5IGNvbXByZXNzaW9uIiIiCiAgICAgICAgaWYgbm90IGhhc2F0dHIoc25hcHNob3QsICdzcXVlZXplX29uJykgb3Igbm90IHNuYXBzaG90LnNxdWVlemVfb246CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgaWYgc25hcHNob3QucnZvbCA8IDEuMDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAKICAgICAgICBkaXJlY3Rpb24gPSAibG9uZyIgaWYgc25hcHNob3Quc3F1ZWV6ZV9maXJlID4gMCBlbHNlICJzaG9ydCIKICAgICAgICAKICAgICAgICAjIFRpZ2h0ZXIgQkIgd2lkdGggPSBtb3JlIGV4cGxvc2l2ZQogICAgICAgIGlmIHNuYXBzaG90LmJiX3dpZHRoIDwgMy4wOgogICAgICAgICAgICBwcmlvcml0eSA9IEFsZXJ0UHJpb3JpdHkuQ1JJVElDQUwKICAgICAgICBlbGlmIHNuYXBzaG90LmJiX3dpZHRoIDwgNS4wOgogICAgICAgICAgICBwcmlvcml0eSA9IEFsZXJ0UHJpb3JpdHkuSElHSAogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHByaW9yaXR5ID0gQWxlcnRQcmlvcml0eS5NRURJVU0KICAgICAgICAKICAgICAgICAjIFRhcGUgY29uZmlybWF0aW9uIHVwZ3JhZGVzIHByaW9yaXR5CiAgICAgICAgaWYgZGlyZWN0aW9uID09ICJsb25nIiBhbmQgdGFwZS5jb25maXJtYXRpb25fZm9yX2xvbmcgYW5kIHByaW9yaXR5ICE9IEFsZXJ0UHJpb3JpdHkuQ1JJVElDQUw6CiAgICAgICAgICAgIHByaW9yaXR5ID0gQWxlcnRQcmlvcml0eS5ISUdICiAgICAgICAgZWxpZiBkaXJlY3Rpb24gPT0gInNob3J0IiBhbmQgdGFwZS5jb25maXJtYXRpb25fZm9yX3Nob3J0IGFuZCBwcmlvcml0eSAhPSBBbGVydFByaW9yaXR5LkNSSVRJQ0FMOgogICAgICAgICAgICBwcmlvcml0eSA9IEFsZXJ0UHJpb3JpdHkuSElHSAogICAgICAgIAogICAgICAgICMgMjAyNi0wNS0wMSB2MTkuMjAg4oCUIEJvdW5kZWQgU3F1ZWV6ZSBzdG9wIHNvIFI6UiBzdGF5cyB2aWFibGUgb24KICAgICAgICAjIG1lZ2EtY2Fwcy4gUHJldmlvdXNseSBgc3RvcCA9IGJiX2xvd2VyYCBjb3VsZCBiZSA+MS41IEFUUiBhd2F5IG9uCiAgICAgICAgIyB3aWRlLUJCIG5hbWVzIChLTywgUEcsIExJTiksIHdoaWNoIHB1c2hlZCBSOlIgYmVsb3cgdGhlIDEuNSBnYXRlCiAgICAgICAgIyBldmVyeSBjeWNsZSBhbmQgdGhlIHNldHVwIHdhcyBlZmZlY3RpdmVseSBkZWFkLiBDbGFtcGluZyB0aGUgc3RvcAogICAgICAgICMgdG8gd2l0aGluIDEuMCBBVFIgb2YgdGhlIGN1cnJlbnQgcHJpY2UgY2FwcyBkb3duc2lkZSB3aGlsZSBzdGlsbAogICAgICAgICMgaG9ub3VyaW5nIHRoZSBCQiBiYW5kIHN0cnVjdHVyZSDigJQgd2hpY2hldmVyIGlzIFRJR0hURVIgKGNsb3NlciB0bwogICAgICAgICMgcHJpY2UpIHdpbnMsIHNvIHRoZSBCQiBzdGlsbCBnb3Zlcm5zIHdoZW4gaXQncyB0aWdodCBlbm91Z2guCiAgICAgICAgIwogICAgICAgICMgdjE5LjM0LjE4MyDigJQgQW5jaG9yIHRoZSBFTlRSWSB0byB3aGVyZSB0aGUgdHJhZGUgYWN0dWFsbHkgZW50ZXJzLgogICAgICAgICMgVGhlIGJyZWFrb3V0IHRyaWdnZXIgaXMgYmJfdXBwZXIgKGxvbmcpIC8gYmJfbG93ZXIgKHNob3J0KSwgYnV0IG9uY2UKICAgICAgICAjIHByaWNlIGhhcyBBTFJFQURZIGJyb2tlbiBvdXQgYW5kIHJ1biBwYXN0IHRoZSBiYW5kLCB0aGF0IGxldmVsIGlzCiAgICAgICAgIyBzdGFsZSBhbmQgc2l0cyBvbiB0aGUgV1JPTkcgc2lkZSBvZiBhbiBBVFIgc3RvcCBhbmNob3JlZCB0byBjdXJyZW50CiAgICAgICAgIyBwcmljZSAoZS5nLiBESUE6IHRyaWdnZXIgNTAxLjYzIDwgc3RvcCA1MDUuODIgZm9yIGEgImxvbmciKS4gQ2xhbXAKICAgICAgICAjIHRoZSBlbnRyeSB0byBjdXJyZW50IHByaWNlIGluIHRoYXQgY2FzZSBzbyBlbnRyeS9zdG9wL3RhcmdldCBnZW9tZXRyeQogICAgICAgICMgaXMgYWx3YXlzIGludGVybmFsbHkgY29uc2lzdGVudCwgdGhlbiBhbmNob3Igc3RvcCArIHRhcmdldCB0byBgZW50cnlgLgogICAgICAgIGNwID0gc25hcHNob3QuY3VycmVudF9wcmljZQogICAgICAgIGlmIGRpcmVjdGlvbiA9PSAibG9uZyI6CiAgICAgICAgICAgIGVudHJ5ID0gbWF4KHNuYXBzaG90LmJiX3VwcGVyLCBjcCkKICAgICAgICAgICAgcmF3X3N0b3AgPSBzbmFwc2hvdC5iYl9sb3dlcgogICAgICAgICAgICBhdHJfZmxvb3IgPSBlbnRyeSAtIChzbmFwc2hvdC5hdHIgKiAxLjApCiAgICAgICAgICAgIHN0b3AgPSBtYXgocmF3X3N0b3AsIGF0cl9mbG9vcikgICMgTE9ORzogaGlnaGVyIHN0b3AgPSB0aWdodGVyIChhbHdheXMgPCBlbnRyeSkKICAgICAgICAgICAgdGFyZ2V0ID0gZW50cnkgKyAoc25hcHNob3QuYXRyICogMi41KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGVudHJ5ID0gbWluKHNuYXBzaG90LmJiX2xvd2VyLCBjcCkKICAgICAgICAgICAgcmF3X3N0b3AgPSBzbmFwc2hvdC5iYl91cHBlcgogICAgICAgICAgICBhdHJfY2VpbCA9IGVudHJ5ICsgKHNuYXBzaG90LmF0ciAqIDEuMCkKICAgICAgICAgICAgc3RvcCA9IG1pbihyYXdfc3RvcCwgYXRyX2NlaWwpICAjIFNIT1JUOiBsb3dlciBzdG9wID0gdGlnaHRlciAoYWx3YXlzID4gZW50cnkpCiAgICAgICAgICAgIHRhcmdldCA9IGVudHJ5IC0gKHNuYXBzaG90LmF0ciAqIDIuNSkKICAgICAgICByaXNrID0gYWJzKGVudHJ5IC0gc3RvcCkKICAgICAgICByciA9IGFicyh0YXJnZXQgLSBlbnRyeSkgLyByaXNrIGlmIHJpc2sgPiAwIGVsc2UgMQogICAgICAgIAogICAgICAgIHJldHVybiBMaXZlQWxlcnQoCiAgICAgICAgICAgIGlkPWYic3F1ZWV6ZV97c3ltYm9sfV97ZGlyZWN0aW9ufV97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVIJU0lUycpfSIsCiAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgIHNldHVwX3R5cGU9InNxdWVlemUiLAogICAgICAgICAgICBzdHJhdGVneV9uYW1lPWYiU3F1ZWV6ZSBGaXJlIHtkaXJlY3Rpb24udXBwZXIoKX0iLAogICAgICAgICAgICBkaXJlY3Rpb249ZGlyZWN0aW9uLAogICAgICAgICAgICBwcmlvcml0eT1wcmlvcml0eSwKICAgICAgICAgICAgY3VycmVudF9wcmljZT1zbmFwc2hvdC5jdXJyZW50X3ByaWNlLAogICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPXJvdW5kKGVudHJ5LCAyKSwgICMgdjE5LjM0LjE4MyDigJQgY29uc2lzdGVudCBlbnRyeSBhbmNob3IKICAgICAgICAgICAgc3RvcF9sb3NzPXJvdW5kKHN0b3AsIDIpLAogICAgICAgICAgICB0YXJnZXQ9cm91bmQodGFyZ2V0LCAyKSwKICAgICAgICAgICAgcmlza19yZXdhcmQ9cm91bmQocnIsIDIpLAogICAgICAgICAgICB0cmlnZ2VyX3Byb2JhYmlsaXR5PTAuNjgsCiAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjYyLAogICAgICAgICAgICBtaW51dGVzX3RvX3RyaWdnZXI9MTAsCiAgICAgICAgICAgIGhlYWRsaW5lPWYiU1FVRUVaRSB7c3ltYm9sfSB7ZGlyZWN0aW9uLnVwcGVyKCl9IC0gQkIgV2lkdGgge3NuYXBzaG90LmJiX3dpZHRoOi4xZn0lIHsnKyBUQVBFJyBpZiAodGFwZS5jb25maXJtYXRpb25fZm9yX2xvbmcgaWYgZGlyZWN0aW9uID09ICdsb25nJyBlbHNlIHRhcGUuY29uZmlybWF0aW9uX2Zvcl9zaG9ydCkgZWxzZSAnJ30iLAogICAgICAgICAgICByZWFzb25pbmc9WwogICAgICAgICAgICAgICAgIkJvbGxpbmdlciBCYW5kcyBJTlNJREUgS2VsdG5lciBDaGFubmVscyA9IHZvbGF0aWxpdHkgc3F1ZWV6ZSIsCiAgICAgICAgICAgICAgICBmIkJCIFdpZHRoOiB7c25hcHNob3QuYmJfd2lkdGg6LjFmfSUgKHRpZ2h0ID0gZXhwbG9zaXZlIGJyZWFrb3V0IGltbWluZW50KSIsCiAgICAgICAgICAgICAgICBmIk1vbWVudHVtOiB7c25hcHNob3Quc3F1ZWV6ZV9maXJlOisuMmZ9ICh7J2J1bGxpc2gnIGlmIGRpcmVjdGlvbiA9PSAnbG9uZycgZWxzZSAnYmVhcmlzaCd9KSIsCiAgICAgICAgICAgICAgICBmIlJWT0w6IHtzbmFwc2hvdC5ydm9sOi4xZn14IHwgUlNJOiB7c25hcHNob3QucnNpXzE0Oi4wZn0iLAogICAgICAgICAgICAgICAgZiJUYXBlOiB7dGFwZS5vdmVyYWxsX3NpZ25hbC52YWx1ZX0gKHNjb3JlOiB7dGFwZS50YXBlX3Njb3JlOi4yZn0pIgogICAgICAgICAgICBdLAogICAgICAgICAgICB0aW1lX3dpbmRvdz1zZWxmLl9nZXRfY3VycmVudF90aW1lX3dpbmRvdygpLnZhbHVlLAogICAgICAgICAgICBtYXJrZXRfcmVnaW1lPXNlbGYuX21hcmtldF9yZWdpbWUudmFsdWUsCiAgICAgICAgICAgIGV4cGlyZXNfYXQ9KGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpICsgdGltZWRlbHRhKGhvdXJzPTIpKS5pc29mb3JtYXQoKQogICAgICAgICkKICAgIAo="

NEW_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfc3F1ZWV6ZShzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIlNxdWVlemUg4oCUIFNVUFBSRVNTRUQgdjM1OSAocmV0dXJucyBOb25lKS4KICAgICAgICBUaGlzICJpbnRyYWRheSIgZGV0ZWN0b3IgaXMgYWN0dWFsbHkgYSBEQUlMWS1iYXIgc2lnbmFsIChzcXVlZXplX29uIC8gYmJfd2lkdGggLyBhdHIgLwogICAgICAgIHJ2b2wgYWxsIGNvbWUgZnJvbSBkYWlseSBiYXJzIGluIHJlYWx0aW1lX3RlY2huaWNhbF9zZXJ2aWNlKSBhbmQgZnVsbHkgb3ZlcmxhcHMKICAgICAgICBkYWlseV9zcXVlZXplLiBHcm91bmQgdHJ1dGggZnJvbSA0NzMgY2xvc2VkIGJvdF90cmFkZXM6IG5lZ2F0aXZlLUVWIG9uIGV2ZXJ5IGN1dCDigJQKICAgICAgICBBTEwgd2luc29yQXZnIC0wLjE1OCAoMzElIHdpbiwgdG90UiAtMTI4LjgpLCBMT05HIC0wLjA4MCAobj0yODUpLCBTSE9SVCAtMC4yNzcgKG49MTg4KS4KICAgICAgICBJdHMgbWFya2V0LW9yZGVyIGZpbGwgZ2VvbWV0cnkgcmVwbGF5cyB0byAtMC40NzUgUi90cmFkZS4gVGhlIGdlbnVpbmUgZGFpbHktY29tcHJlc3Npb24KICAgICAgICBMT05HIGVkZ2UgaXMgYWxyZWFkeSBjYXB0dXJlZCBieSBkYWlseV9zcXVlZXplIChsb25nLW9ubHksIHYzNTgpLiBTdXBwcmVzc2VkIHRvIGRlZHVwZSBhCiAgICAgICAgaGlnaC1mcmVxdWVuY3kgKH40NmsgZmlyZXMveXIpIG5lZ2F0aXZlLUVWIGR1cGxpY2F0ZS4gU2VlIG1lbW9yeS92MzU5X3NxdWVlemVfYnVpbGQubWQuIiIiCiAgICAgICAgcmV0dXJuIE5vbmUKICAgIAo="


def main():
    check = "--check" in sys.argv
    src = open(FILE, encoding="utf-8").read()
    cur_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
    print(f"file            : {FILE}")
    print(f"live SHA        : {cur_sha}")
    print(f"expected SHA    : {PRE_FILE_SHA}")
    if cur_sha != PRE_FILE_SHA:
        print("\nABORT: live file SHA != expected baseline. The DGX file has DRIFTED.")
        print("Re-run extract_func.py _check_squeeze and rebase. NOTHING was written.")
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

    bak = FILE + ".v359.bak"
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
