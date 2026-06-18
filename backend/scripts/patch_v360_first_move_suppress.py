#!/usr/bin/env python3
# patch_v360_first_move_suppress.py
# ---------------------------------------------------------------------------
# v360 — SUPPRESS both _check_first_move_up and _check_first_move_down (return None).
#
# EVIDENCE (diag_v360_first_move_replay.py, 180d / 300-sym, 5-min intraday):
#   first_move_up   (SHORT fade): n=2392 win 27% winsorAvg -0.106 (tightened: -0.101)
#   first_move_down (LONG  fade): n=2274 win 24% winsorAvg -0.176 (tightened: -0.188)
#   medR -1.0 on both (>50% hit the full stop). Tightening push/RSI did not help.
#   Counter-trend morning fades of volume-confirmed momentum are structurally -EV.
#   (Ground truth too thin to use: first_move_up n=0, first_move_down n=2.)
#
# Dual anchored-chunk patcher (AGENTS.md §2): whole-file PRE-SHA guard + BOTH OLD-bytes match
# (each count MUST be 1) + post-write self-verify. ABORTS before writing on ANY drift. Auto-backup.
# Supports --check dry-run.
#
# Deploy (DGX, repo root):
#   curl -sS -o /tmp/patch_v360.py https://paste.rs/<id>
#   .venv/bin/python /tmp/patch_v360.py --check
#   .venv/bin/python /tmp/patch_v360.py
#   .venv/bin/python -m pytest backend/tests/test_v360_first_move_suppress.py -q
#   git add backend/ memory/ && git commit -m "v360: suppress first_move_up/down (negative-EV morning fades)" && git push origin main
#   git status --short   # must be clean
#   ./start_backend.sh --force
# ---------------------------------------------------------------------------
import base64
import hashlib
import shutil
import sys

FILE = "backend/services/enhanced_scanner.py"
PRE_FILE_SHA = "8ff8213235dd51887ce9218b0985fb1f9a7ee9d9ce1b97edf13cf6733318af92"

# --- first_move_up: OLD (verbatim from extract_func) -> NEW (suppressed) ---
UP_OLD = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfZmlyc3RfbW92ZV91cChzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIkZpcnN0IE1vdmUgVXAg4oCUIFNIT1JUIChmYWRlIGZpcnN0IG1vcm5pbmcgcHVzaCB0byBIT0QpLgoKICAgICAgICBUcmlnZ2VyOiBwcmljZSBoYXMgcHVzaGVkIHVwIG1ha2luZyBhIGZyZXNoIEhPRCBvZmYgdGhlIG9wZW4sIFJTSSBpcwogICAgICAgIG92ZXJib3VnaHQsIHRhcGUgc2hvd3MgZXhoYXVzdGlvbiAvIHN0cm9uZy1hc2ssIHJlYWR5IHRvIGZhZGUgYmFjayB0bwogICAgICAgIFZXQVAgb3IgdGhlIG9wZW4uCiAgICAgICAgIiIiCiAgICAgICAgaWYgc25hcHNob3QuaGlnaF9vZl9kYXkgPD0gMCBvciBzbmFwc2hvdC5hdHIgPD0gMDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAjIFB1c2ggbXVzdCBiZSBtZWFuaW5nZnVsOiA+IDEuNSUgZnJvbSBvcGVuIEFORCBwcmljZSB3aXRoaW4gMC41JSBvZiBIT0QKICAgICAgICBwdXNoX3BjdCA9ICgoc25hcHNob3QuaGlnaF9vZl9kYXkgLSBzbmFwc2hvdC5vcGVuKSAvIHNuYXBzaG90Lm9wZW4pICogMTAwIGlmIHNuYXBzaG90Lm9wZW4gPiAwIGVsc2UgMAogICAgICAgIGRpc3RfZnJvbV9ob2RfcGN0ID0gKChzbmFwc2hvdC5oaWdoX29mX2RheSAtIHNuYXBzaG90LmN1cnJlbnRfcHJpY2UpIC8gc25hcHNob3QuY3VycmVudF9wcmljZSkgKiAxMDAKICAgICAgICBpZiAocHVzaF9wY3QgPj0gMS41IGFuZAogICAgICAgICAgICBkaXN0X2Zyb21faG9kX3BjdCA8PSAwLjUgYW5kCiAgICAgICAgICAgIHNuYXBzaG90LnJzaV8xNCA+PSA2OCBhbmQKICAgICAgICAgICAgc25hcHNob3QuZGlzdF9mcm9tX3Z3YXAgPj0gMS4wIGFuZAogICAgICAgICAgICBzbmFwc2hvdC5ydm9sID49IDEuNSk6CiAgICAgICAgICAgIHRhcmdldF9wcmljZSA9IG1heChzbmFwc2hvdC52d2FwLCBzbmFwc2hvdC5vcGVuKQogICAgICAgICAgICBzdG9wID0gcm91bmQoc25hcHNob3QuaGlnaF9vZl9kYXkgKyAoc25hcHNob3QuYXRyICogMC4yNSksIDIpCiAgICAgICAgICAgIHJpc2sgPSBhYnMoc3RvcCAtIHNuYXBzaG90LmN1cnJlbnRfcHJpY2UpCiAgICAgICAgICAgIHJld2FyZCA9IGFicyhzbmFwc2hvdC5jdXJyZW50X3ByaWNlIC0gdGFyZ2V0X3ByaWNlKQogICAgICAgICAgICByciA9IChyZXdhcmQgLyByaXNrKSBpZiByaXNrID4gMCBlbHNlIDEuNQogICAgICAgICAgICByZXR1cm4gTGl2ZUFsZXJ0KAogICAgICAgICAgICAgICAgaWQ9ZiJmaXJzdF9tb3ZlX3VwX3tzeW1ib2x9X3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJUglTSVTJyl9IiwKICAgICAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgICAgICBzZXR1cF90eXBlPSJmaXJzdF9tb3ZlX3VwIiwKICAgICAgICAgICAgICAgIHN0cmF0ZWd5X25hbWU9IkZpcnN0IE1vdmUgVXAgRmFkZSAoTU9STi0wMSkiLAogICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJzaG9ydCIsCiAgICAgICAgICAgICAgICBwcmlvcml0eT1BbGVydFByaW9yaXR5LkhJR0ggaWYgdGFwZS5jb25maXJtYXRpb25fZm9yX3Nob3J0IGVsc2UgQWxlcnRQcmlvcml0eS5NRURJVU0sCiAgICAgICAgICAgICAgICBjdXJyZW50X3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICBzdG9wX2xvc3M9c3RvcCwKICAgICAgICAgICAgICAgIHRhcmdldD1yb3VuZCh0YXJnZXRfcHJpY2UsIDIpLAogICAgICAgICAgICAgICAgcmlza19yZXdhcmQ9cm91bmQocnIsIDIpLAogICAgICAgICAgICAgICAgdHJpZ2dlcl9wcm9iYWJpbGl0eT0wLjU1LAogICAgICAgICAgICAgICAgd2luX3Byb2JhYmlsaXR5PTAuNTUsCiAgICAgICAgICAgICAgICBtaW51dGVzX3RvX3RyaWdnZXI9MTAsCiAgICAgICAgICAgICAgICBoZWFkbGluZT1mIvCfqoIge3N5bWJvbH0gRmlyc3QtTW92ZS1VcCBGYWRlIOKAlCBIT0QgcHVzaCAre3B1c2hfcGN0Oi4xZn0lIiwKICAgICAgICAgICAgICAgIHJlYXNvbmluZz1bCiAgICAgICAgICAgICAgICAgICAgZiJQdXNoIGZyb20gb3BlbjogK3twdXNoX3BjdDouMWZ9JSB0byBIT0QgJHtzbmFwc2hvdC5oaWdoX29mX2RheTouMmZ9IiwKICAgICAgICAgICAgICAgICAgICBmIldpdGhpbiB7ZGlzdF9mcm9tX2hvZF9wY3Q6LjJmfSUgb2YgSE9EIiwKICAgICAgICAgICAgICAgICAgICBmIlJTSSBvdmVyYm91Z2h0OiB7c25hcHNob3QucnNpXzE0Oi4wZn0iLAogICAgICAgICAgICAgICAgICAgIGYie3NuYXBzaG90LmRpc3RfZnJvbV92d2FwOisuMWZ9JSBleHRlbmRlZCBhYm92ZSBWV0FQIiwKICAgICAgICAgICAgICAgICAgICBmIlRhcmdldDogVldBUC9vcGVuICR7dGFyZ2V0X3ByaWNlOi4yZn0iLAogICAgICAgICAgICAgICAgXSwKICAgICAgICAgICAgICAgIHRpbWVfd2luZG93PXNlbGYuX2dldF9jdXJyZW50X3RpbWVfd2luZG93KCkudmFsdWUsCiAgICAgICAgICAgICAgICBtYXJrZXRfcmVnaW1lPXNlbGYuX21hcmtldF9yZWdpbWUudmFsdWUsCiAgICAgICAgICAgICAgICBleHBpcmVzX2F0PShkYXRldGltZS5ub3codGltZXpvbmUudXRjKSArIHRpbWVkZWx0YShtaW51dGVzPTQ1KSkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gTm9uZQoK"
UP_NEW = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfZmlyc3RfbW92ZV91cChzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIkZpcnN0IE1vdmUgVXAg4oCUIFNVUFBSRVNTRUQgdjM2MCAocmV0dXJucyBOb25lKS4KICAgICAgICBJbnRyYWRheSByZXBsYXkgKDE4MGQgLyAzMDAtc3ltLCA1LW1pbikgcHJvdmVkIHRoaXMgbW9ybmluZyBTSE9SVCBmYWRlIGlzIG5lZ2F0aXZlLUVWOgogICAgICAgIHdpbiAyNyUsIHdpbnNvckF2ZyAtMC4xMDYgUi90cmFkZSAoPjUwJSBoaXQgdGhlIGZ1bGwgc3RvcCkuIFRpZ2h0ZXIgZ2F0ZXMgKHB1c2ggMi4wLAogICAgICAgIFJTSSA3MikgZGlkIG5vdCBoZWxwLiBGYWRpbmcgYSB2b2x1bWUtY29uZmlybWVkIGZyZXNoLUhPRCBwdXNoIGZpZ2h0cyB0aGUgbW9tZW50dW0gdGhlCiAgICAgICAgdmFsaWRhdGVkIHNldHVwcyB0cmFkZS4gU3VwcHJlc3NlZCBsaWtlIHZ3YXBfYm91bmNlICh2MzU0KS4gU2VlIG1lbW9yeS92MzYwX2ZpcnN0X21vdmVfYnVpbGQubWQuIiIiCiAgICAgICAgcmV0dXJuIE5vbmUKCg=="

# --- first_move_down: OLD (verbatim from extract_func) -> NEW (suppressed) ---
DN_OLD = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfZmlyc3RfbW92ZV9kb3duKHNlbGYsIHN5bWJvbDogc3RyLCBzbmFwc2hvdCwgdGFwZTogVGFwZVJlYWRpbmcpIC0+IE9wdGlvbmFsW0xpdmVBbGVydF06CiAgICAgICAgIiIiRmlyc3QgTW92ZSBEb3duIOKAlCBMT05HIChmYWRlIGZpcnN0IG1vcm5pbmcgZmx1c2ggdG8gTE9EKS4iIiIKICAgICAgICBpZiBzbmFwc2hvdC5sb3dfb2ZfZGF5IDw9IDAgb3Igc25hcHNob3QuYXRyIDw9IDA6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgZmx1c2hfcGN0ID0gKChzbmFwc2hvdC5vcGVuIC0gc25hcHNob3QubG93X29mX2RheSkgLyBzbmFwc2hvdC5vcGVuKSAqIDEwMCBpZiBzbmFwc2hvdC5vcGVuID4gMCBlbHNlIDAKICAgICAgICBkaXN0X2Zyb21fbG9kX3BjdCA9ICgoc25hcHNob3QuY3VycmVudF9wcmljZSAtIHNuYXBzaG90Lmxvd19vZl9kYXkpIC8gc25hcHNob3QuY3VycmVudF9wcmljZSkgKiAxMDAKICAgICAgICBpZiAoZmx1c2hfcGN0ID49IDEuNSBhbmQKICAgICAgICAgICAgZGlzdF9mcm9tX2xvZF9wY3QgPD0gMC41IGFuZAogICAgICAgICAgICBzbmFwc2hvdC5yc2lfMTQgPD0gMzIgYW5kCiAgICAgICAgICAgIHNuYXBzaG90LmRpc3RfZnJvbV92d2FwIDw9IC0xLjAgYW5kCiAgICAgICAgICAgIHNuYXBzaG90LnJ2b2wgPj0gMS41KToKICAgICAgICAgICAgdGFyZ2V0X3ByaWNlID0gbWluKHNuYXBzaG90LnZ3YXAsIHNuYXBzaG90Lm9wZW4pCiAgICAgICAgICAgIHN0b3AgPSByb3VuZChzbmFwc2hvdC5sb3dfb2ZfZGF5IC0gKHNuYXBzaG90LmF0ciAqIDAuMjUpLCAyKQogICAgICAgICAgICByaXNrID0gYWJzKHNuYXBzaG90LmN1cnJlbnRfcHJpY2UgLSBzdG9wKQogICAgICAgICAgICByZXdhcmQgPSBhYnModGFyZ2V0X3ByaWNlIC0gc25hcHNob3QuY3VycmVudF9wcmljZSkKICAgICAgICAgICAgcnIgPSAocmV3YXJkIC8gcmlzaykgaWYgcmlzayA+IDAgZWxzZSAxLjUKICAgICAgICAgICAgcmV0dXJuIExpdmVBbGVydCgKICAgICAgICAgICAgICAgIGlkPWYiZmlyc3RfbW92ZV9kb3duX3tzeW1ib2x9X3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJUglTSVTJyl9IiwKICAgICAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgICAgICBzZXR1cF90eXBlPSJmaXJzdF9tb3ZlX2Rvd24iLAogICAgICAgICAgICAgICAgc3RyYXRlZ3lfbmFtZT0iRmlyc3QgTW92ZSBEb3duIFJldmVyc2FsIChNT1JOLTAyKSIsCiAgICAgICAgICAgICAgICBkaXJlY3Rpb249ImxvbmciLAogICAgICAgICAgICAgICAgcHJpb3JpdHk9QWxlcnRQcmlvcml0eS5ISUdIIGlmIHRhcGUuY29uZmlybWF0aW9uX2Zvcl9sb25nIGVsc2UgQWxlcnRQcmlvcml0eS5NRURJVU0sCiAgICAgICAgICAgICAgICBjdXJyZW50X3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICBzdG9wX2xvc3M9c3RvcCwKICAgICAgICAgICAgICAgIHRhcmdldD1yb3VuZCh0YXJnZXRfcHJpY2UsIDIpLAogICAgICAgICAgICAgICAgcmlza19yZXdhcmQ9cm91bmQocnIsIDIpLAogICAgICAgICAgICAgICAgdHJpZ2dlcl9wcm9iYWJpbGl0eT0wLjU1LAogICAgICAgICAgICAgICAgd2luX3Byb2JhYmlsaXR5PTAuNTUsCiAgICAgICAgICAgICAgICBtaW51dGVzX3RvX3RyaWdnZXI9MTAsCiAgICAgICAgICAgICAgICBoZWFkbGluZT1mIvCfqoMge3N5bWJvbH0gRmlyc3QtTW92ZS1Eb3duIFJldmVyc2FsIOKAlCBMT0QgZmx1c2gg4oiSe2ZsdXNoX3BjdDouMWZ9JSIsCiAgICAgICAgICAgICAgICByZWFzb25pbmc9WwogICAgICAgICAgICAgICAgICAgIGYiRmx1c2ggZnJvbSBvcGVuOiDiiJJ7Zmx1c2hfcGN0Oi4xZn0lIHRvIExPRCAke3NuYXBzaG90Lmxvd19vZl9kYXk6LjJmfSIsCiAgICAgICAgICAgICAgICAgICAgZiJXaXRoaW4ge2Rpc3RfZnJvbV9sb2RfcGN0Oi4yZn0lIG9mIExPRCIsCiAgICAgICAgICAgICAgICAgICAgZiJSU0kgb3ZlcnNvbGQ6IHtzbmFwc2hvdC5yc2lfMTQ6LjBmfSIsCiAgICAgICAgICAgICAgICAgICAgZiJ7c25hcHNob3QuZGlzdF9mcm9tX3Z3YXA6Ky4xZn0lIGJlbG93IFZXQVAiLAogICAgICAgICAgICAgICAgICAgIGYiVGFyZ2V0OiBWV0FQL29wZW4gJHt0YXJnZXRfcHJpY2U6LjJmfSIsCiAgICAgICAgICAgICAgICBdLAogICAgICAgICAgICAgICAgdGltZV93aW5kb3c9c2VsZi5fZ2V0X2N1cnJlbnRfdGltZV93aW5kb3coKS52YWx1ZSwKICAgICAgICAgICAgICAgIG1hcmtldF9yZWdpbWU9c2VsZi5fbWFya2V0X3JlZ2ltZS52YWx1ZSwKICAgICAgICAgICAgICAgIGV4cGlyZXNfYXQ9KGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpICsgdGltZWRlbHRhKG1pbnV0ZXM9NDUpKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgKQogICAgICAgIHJldHVybiBOb25lCgo="
DN_NEW = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfZmlyc3RfbW92ZV9kb3duKHNlbGYsIHN5bWJvbDogc3RyLCBzbmFwc2hvdCwgdGFwZTogVGFwZVJlYWRpbmcpIC0+IE9wdGlvbmFsW0xpdmVBbGVydF06CiAgICAgICAgIiIiRmlyc3QgTW92ZSBEb3duIOKAlCBTVVBQUkVTU0VEIHYzNjAgKHJldHVybnMgTm9uZSkuCiAgICAgICAgSW50cmFkYXkgcmVwbGF5ICgxODBkIC8gMzAwLXN5bSwgNS1taW4pIHByb3ZlZCB0aGlzIG1vcm5pbmcgTE9ORyBmYWRlIGlzIG5lZ2F0aXZlLUVWOgogICAgICAgIHdpbiAyNCUsIHdpbnNvckF2ZyAtMC4xNzYgUi90cmFkZSAoPjUwJSBoaXQgdGhlIGZ1bGwgc3RvcCkuIFRpZ2h0ZXIgZ2F0ZXMgZGlkIG5vdCBoZWxwLgogICAgICAgIEZhZGluZyBhIHZvbHVtZS1jb25maXJtZWQgZmx1c2ggZmlnaHRzIG1vbWVudHVtLiBTdXBwcmVzc2VkIGxpa2UgdndhcF9ib3VuY2UgKHYzNTQpLgogICAgICAgIFNlZSBtZW1vcnkvdjM2MF9maXJzdF9tb3ZlX2J1aWxkLm1kLiIiIgogICAgICAgIHJldHVybiBOb25lCgo="

CHUNKS = [("first_move_up", UP_OLD, UP_NEW), ("first_move_down", DN_OLD, DN_NEW)]


def main():
    check = "--check" in sys.argv
    src = open(FILE, encoding="utf-8").read()
    cur_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
    print(f"file            : {FILE}")
    print(f"live SHA        : {cur_sha}")
    print(f"expected SHA    : {PRE_FILE_SHA}")
    if cur_sha != PRE_FILE_SHA:
        print("\nABORT: live file SHA != expected baseline. DRIFTED. Re-extract + rebase. NOTHING written.")
        sys.exit(2)

    patched = src
    for name, ob, nb in CHUNKS:
        old = base64.b64decode(ob).decode("utf-8")
        new = base64.b64decode(nb).decode("utf-8")
        n = patched.count(old)
        print(f"OLD anchor [{name}] count: {n}  (MUST be 1)")
        if n != 1:
            print(f"\nABORT: {name} anchor not uniquely found. NOTHING was written.")
            sys.exit(3)
        patched = patched.replace(old, new, 1)
        if patched.count(new) != 1 or old in patched:
            print(f"\nABORT: {name} post-replace self-check failed. NOTHING was written.")
            sys.exit(4)

    post_sha = hashlib.sha256(patched.encode("utf-8")).hexdigest()
    print(f"POST SHA        : {post_sha}")
    if check:
        print("\n--check OK: guards pass, both anchors found exactly once, replacements clean.")
        return

    bak = FILE + ".v360.bak"
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
