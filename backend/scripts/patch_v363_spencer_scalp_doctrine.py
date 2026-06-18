#!/usr/bin/env python3
# patch_v363_spencer_scalp_doctrine.py
# ---------------------------------------------------------------------------
# v363 — REWRITE `_check_spencer_scalp` to the SMB cheat-sheet DOCTRINE, LONG-ONLY (was a loose near-HOD proxy).
#
# DOCTRINE (1-min): a >=20-min tight consolidation (band < 15% of the day's range) in the UPPER 1/3
# of the day range, then a VOLUME SURGE break of the range HIGH (institutional accumulation) ->
# ENTER on the range-high break, STOP .02 below the range LOW, fixed 2.0R target. All-day (RTH).
#
# EVIDENCE (diag_v363_spencer_scalp_doctrine.py, 180d / 300-sym, 1-min):
#   doctrine LONG, band<0.15*dayRange + vol-surge 1.3x, scaled exit : n=17729 win 52% winsorAvg +0.063
#   doctrine LONG, fixed 2.0R target                               : ~+0.043R (detector-only, SHIPPED)
#   SHORT side ~0 (+0.012..0.021) -> dropped (kept LONG-only). Morning-only was -EV -> kept all-day.
#   Ground truth: 0 real fills (9 simulated) -> the prior loose near-HOD code never traded live and
#   modeled none of the 20-min-range / range-stop / measured-move structure.
#   NOTE: scaled 1R/2R/3R exit needs position-mgmt work -> shipped a detector-only fixed 2.0R target.
#
# The new detector fetches 1-min bars via ts._get_intraday_bars_from_db(symbol, "1 min", 60)
# (same pattern as the live vwap_fade detector) and is DETECTOR-ONLY (no exit-management changes).
#
# Anchored-chunk patcher (AGENTS.md §2): whole-file PRE-SHA guard + exact OLD-bytes match
# (count MUST be 1) + post-write self-verify + py_compile. ABORTS before writing on ANY drift.
# Auto-backup. Supports --check dry-run.
#
# Deploy (DGX, repo root):
#   curl -sS -o /tmp/patch_v363.py https://paste.rs/<id>
#   .venv/bin/python /tmp/patch_v363.py --check
#   .venv/bin/python /tmp/patch_v363.py
#   .venv/bin/python -m pytest backend/tests/test_v363_spencer_scalp_doctrine.py -q
#   git add backend/ memory/ && git commit -m "v363: rewrite spencer_scalp to SMB doctrine (LONG-only, range-break, 2R)" && git push origin main
#   git status --short
#   ./start_backend.sh --force
# ---------------------------------------------------------------------------
import base64
import hashlib
import py_compile
import shutil
import sys
import tempfile

FILE = "backend/services/enhanced_scanner.py"
PRE_FILE_SHA = "e77006287b3ce31c327f41c6bb5dd7dfedd72cdb4388f98d9826433736c55692"

OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfc3BlbmNlcl9zY2FscChzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIlNwZW5jZXIgU2NhbHAgLSBUaWdodCBjb25zb2xpZGF0aW9uIG5lYXIgSE9EIiIiCiAgICAgICAgZGlzdF9mcm9tX2hvZCA9ICgoc25hcHNob3QuaGlnaF9vZl9kYXkgLSBzbmFwc2hvdC5jdXJyZW50X3ByaWNlKSAvIHNuYXBzaG90LmN1cnJlbnRfcHJpY2UpICogMTAwCiAgICAgICAgCiAgICAgICAgaWYgZGlzdF9mcm9tX2hvZCA8IDEuMCBhbmQgc25hcHNob3QuZGFpbHlfcmFuZ2VfcGN0IDwgMy4wIGFuZCBzbmFwc2hvdC5ydm9sID49IDEuNToKICAgICAgICAgICAgcHJpb3JpdHkgPSBBbGVydFByaW9yaXR5LkhJR0ggaWYgdGFwZS5jb25maXJtYXRpb25fZm9yX2xvbmcgZWxzZSBBbGVydFByaW9yaXR5Lk1FRElVTQogICAgICAgICAgICAKICAgICAgICAgICAgcmV0dXJuIExpdmVBbGVydCgKICAgICAgICAgICAgICAgIGlkPWYic3BlbmNlcl97c3ltYm9sfV97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVIJU0lUycpfSIsCiAgICAgICAgICAgICAgICBzeW1ib2w9c3ltYm9sLAogICAgICAgICAgICAgICAgc2V0dXBfdHlwZT0ic3BlbmNlcl9zY2FscCIsCiAgICAgICAgICAgICAgICBzdHJhdGVneV9uYW1lPSJTcGVuY2VyIFNjYWxwIChJTlQtMjIpIiwKICAgICAgICAgICAgICAgIGRpcmVjdGlvbj0ibG9uZyIsCiAgICAgICAgICAgICAgICBwcmlvcml0eT1wcmlvcml0eSwKICAgICAgICAgICAgICAgIGN1cnJlbnRfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgIHRyaWdnZXJfcHJpY2U9c25hcHNob3QuaGlnaF9vZl9kYXksCiAgICAgICAgICAgICAgICBzdG9wX2xvc3M9cm91bmQoc25hcHNob3QuY3VycmVudF9wcmljZSAtIChzbmFwc2hvdC5hdHIgKiAwLjUpLCAyKSwKICAgICAgICAgICAgICAgIHRhcmdldD1yb3VuZChzbmFwc2hvdC5oaWdoX29mX2RheSArIChzbmFwc2hvdC5hdHIgKiAxLjUpLCAyKSwKICAgICAgICAgICAgICAgIHJpc2tfcmV3YXJkPTMuMCwKICAgICAgICAgICAgICAgIHRyaWdnZXJfcHJvYmFiaWxpdHk9MC41NSwKICAgICAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjU1LAogICAgICAgICAgICAgICAgbWludXRlc190b190cmlnZ2VyPTE1LAogICAgICAgICAgICAgICAgaGVhZGxpbmU9ZiLwn5OKIHtzeW1ib2x9IFNwZW5jZXIgU2NhbHAgLSBOZWFyIEhPRCB7J+KckyBUQVBFJyBpZiB0YXBlLmNvbmZpcm1hdGlvbl9mb3JfbG9uZyBlbHNlICcnfSIsCiAgICAgICAgICAgICAgICByZWFzb25pbmc9WwogICAgICAgICAgICAgICAgICAgIGYiUHJpY2Uge2Rpc3RfZnJvbV9ob2Q6LjFmfSUgZnJvbSBIT0QgJHtzbmFwc2hvdC5oaWdoX29mX2RheTouMmZ9IiwKICAgICAgICAgICAgICAgICAgICBmIlRpZ2h0IGNvbnNvbGlkYXRpb24gKHJhbmdlOiB7c25hcHNob3QuZGFpbHlfcmFuZ2VfcGN0Oi4xZn0lKSIsCiAgICAgICAgICAgICAgICAgICAgZiJSVk9MOiB7c25hcHNob3QucnZvbDouMWZ9eCIsCiAgICAgICAgICAgICAgICAgICAgZiJUYXBlOiB7dGFwZS5vdmVyYWxsX3NpZ25hbC52YWx1ZX0iLAogICAgICAgICAgICAgICAgICAgICJFbnRyeTogQnJlYWsgb2YgY29uc29saWRhdGlvbiBoaWdoIgogICAgICAgICAgICAgICAgXSwKICAgICAgICAgICAgICAgIHRpbWVfd2luZG93PXNlbGYuX2dldF9jdXJyZW50X3RpbWVfd2luZG93KCkudmFsdWUsCiAgICAgICAgICAgICAgICBtYXJrZXRfcmVnaW1lPXNlbGYuX21hcmtldF9yZWdpbWUudmFsdWUsCiAgICAgICAgICAgICAgICBleHBpcmVzX2F0PShkYXRldGltZS5ub3codGltZXpvbmUudXRjKSArIHRpbWVkZWx0YShob3Vycz0yKSkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgKQogICAgICAgIHJldHVybiBOb25lCiAgICAK"

NEW_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfc3BlbmNlcl9zY2FscChzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIlNwZW5jZXIgU2NhbHAgKElOVC0yMikgLSBET0NUUklORSByZXdyaXRlICh2MzYzLCBMT05HLW9ubHkpLgogICAgICAgIFNNQiBjaGVhdC1zaGVldDogYSA+PTIwLW1pbiB0aWdodCBjb25zb2xpZGF0aW9uIChiYW5kIDwgMTUlIG9mIHRoZSBkYXkncyByYW5nZSkgaW4gdGhlIFVQUEVSCiAgICAgICAgMS8zIG9mIHRoZSBkYXkgcmFuZ2UsIHRoZW4gYSBWT0xVTUUgU1VSR0UgYnJlYWsgb2YgdGhlIHJhbmdlIGhpZ2ggKGEgbWV0aG9kaWNhbCBpbnN0aXR1dGlvbmFsCiAgICAgICAgYWNjdW11bGF0aW9uIHByb2dyYW0pLiBFTlRFUiBvbiB0aGUgcmFuZ2UtaGlnaCBicmVhaywgU1RPUCAuMDIgYmVsb3cgdGhlIHJhbmdlIGxvdywgZml4ZWQgMi4wUgogICAgICAgIHRhcmdldC4gMTgwZC8zMDAtc3ltIDEtbWluIHJlcGxheTogTE9ORyArMC4wNC0wLjA2UjsgU0hPUlQgfjAgKGRyb3BwZWQpOyBtb3JuaW5nLW9ubHkgd2FzIC1FVgogICAgICAgIHNvIGtlcHQgYWxsLWRheS4gU2VlIG1lbW9yeS92MzYzX3NwZW5jZXJfc2NhbHBfYnVpbGQubWQuIiIiCiAgICAgICAgQ09OU19MRU4gPSAyMAogICAgICAgIENPTlNfRlJBQyA9IDAuMTUgICAgICAgICMgY29uc29saWRhdGlvbiBiYW5kIDwgMTUlIG9mIHRoZSBkYXkgcmFuZ2UKICAgICAgICBVUFBFUl9USElSRCA9IDAuNjY3ICAgICAjIGNvbnNvbGlkYXRpb24gbXVzdCBzaXQgaW4gdGhlIHVwcGVyIDEvMyBvZiB0aGUgZGF5IHJhbmdlCiAgICAgICAgVk9MX1NVUkdFID0gMS4zICAgICAgICAgIyBicmVhay1iYXIgdm9sdW1lID49IDEuM3ggdGhlIGNvbnNvbGlkYXRpb24gYXZnCiAgICAgICAgVEFSR0VUX1JNVUxUID0gMi4wCgogICAgICAgIGhvZCA9IGZsb2F0KGdldGF0dHIoc25hcHNob3QsICJoaWdoX29mX2RheSIsIDAuMCkgb3IgMC4wKQogICAgICAgIGxvZCA9IGZsb2F0KGdldGF0dHIoc25hcHNob3QsICJsb3dfb2ZfZGF5IiwgMC4wKSBvciAwLjApCiAgICAgICAgY3AgPSBmbG9hdChnZXRhdHRyKHNuYXBzaG90LCAiY3VycmVudF9wcmljZSIsIDAuMCkgb3IgMC4wKQogICAgICAgIGRheV9yYW5nZSA9IGhvZCAtIGxvZAogICAgICAgIGlmIGNwIDw9IDAgb3IgZGF5X3JhbmdlIDw9IDA6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIHRzID0gZ2V0YXR0cihzZWxmLCAidGVjaG5pY2FsX3NlcnZpY2UiLCBOb25lKQogICAgICAgIGlmIHRzIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgYmFycyA9IHRzLl9nZXRfaW50cmFkYXlfYmFyc19mcm9tX2RiKHN5bWJvbCwgIjEgbWluIiwgNjApCiAgICAgICAgaWYgbm90IGJhcnMgb3IgbGVuKGJhcnMpIDwgQ09OU19MRU4gKyAyOgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAgICBpID0gbGVuKGJhcnMpIC0gMSAgICAgICAgICAgICAgICAgICAgICAgICAgIyBtb3N0LXJlY2VudCBiYXIgPSB0aGUgcmFuZ2UtYnJlYWsgYmFyCiAgICAgICAgd2luID0gYmFyc1tpIC0gQ09OU19MRU46aV0gICAgICAgICAgICAgICAgICAjIHRoZSBjb25zb2xpZGF0aW9uID0gcHJpb3IgQ09OU19MRU4gYmFycwogICAgICAgIHRyeToKICAgICAgICAgICAgd2ggPSBtYXgoYlsiaGlnaCJdIGZvciBiIGluIHdpbikKICAgICAgICAgICAgd2wgPSBtaW4oYlsibG93Il0gZm9yIGIgaW4gd2luKQogICAgICAgICAgICBicmVha192b2wgPSBiYXJzW2ldLmdldCgidm9sdW1lIikgb3IgMAogICAgICAgICAgICBicmVha19oaWdoID0gYmFyc1tpXVsiaGlnaCJdCiAgICAgICAgZXhjZXB0IChLZXlFcnJvciwgVHlwZUVycm9yLCBWYWx1ZUVycm9yKToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBiYW5kID0gd2ggLSB3bAogICAgICAgIGlmIGJhbmQgPD0gMCBvciBiYW5kID4gQ09OU19GUkFDICogZGF5X3JhbmdlOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIHdsIDwgbG9kICsgVVBQRVJfVEhJUkQgKiBkYXlfcmFuZ2U6ICAgICAgIyBjb25zb2xpZGF0aW9uIG11c3QgYmUgaW4gdGhlIHVwcGVyIDEvMwogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHd2ID0gW2JbInZvbHVtZSJdIGZvciBiIGluIHdpbiBpZiAoYi5nZXQoInZvbHVtZSIpIG9yIDApID4gMF0KICAgICAgICBpZiB3diBhbmQgYnJlYWtfdm9sIDwgVk9MX1NVUkdFICogKHN1bSh3dikgLyBsZW4od3YpKTogICAjIHZvbHVtZSBzdXJnZSBjb25maXJtcyB0aGUgYnJlYWsKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBlbnRyeSA9IHJvdW5kKHdoICsgMC4wMSwgMikKICAgICAgICBpZiBub3QgKGNwID49IGVudHJ5IG9yIGJyZWFrX2hpZ2ggPj0gZW50cnkpOiAgICAgICAgICAgICMgcmFuZ2UgYnJlYWsgbXVzdCBiZSBwcmludGluZwogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHN0b3AgPSByb3VuZCh3bCAtIDAuMDIsIDIpCiAgICAgICAgcmlzayA9IGVudHJ5IC0gc3RvcAogICAgICAgIGlmIHJpc2sgPD0gMDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICB0YXJnZXQgPSByb3VuZChlbnRyeSArIFRBUkdFVF9STVVMVCAqIHJpc2ssIDIpCgogICAgICAgIHByaW9yaXR5ID0gQWxlcnRQcmlvcml0eS5ISUdIIGlmIHRhcGUuY29uZmlybWF0aW9uX2Zvcl9sb25nIGVsc2UgQWxlcnRQcmlvcml0eS5NRURJVU0KICAgICAgICByZXR1cm4gTGl2ZUFsZXJ0KAogICAgICAgICAgICBpZD1mInNwZW5jZXJfe3N5bWJvbH1fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclSCVNJVMnKX0iLAogICAgICAgICAgICBzeW1ib2w9c3ltYm9sLAogICAgICAgICAgICBzZXR1cF90eXBlPSJzcGVuY2VyX3NjYWxwIiwKICAgICAgICAgICAgc3RyYXRlZ3lfbmFtZT0iU3BlbmNlciBTY2FscCAoSU5ULTIyKSIsCiAgICAgICAgICAgIGRpcmVjdGlvbj0ibG9uZyIsCiAgICAgICAgICAgIHByaW9yaXR5PXByaW9yaXR5LAogICAgICAgICAgICBjdXJyZW50X3ByaWNlPWNwLAogICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPWVudHJ5LAogICAgICAgICAgICBzdG9wX2xvc3M9c3RvcCwKICAgICAgICAgICAgdGFyZ2V0PXRhcmdldCwKICAgICAgICAgICAgcmlza19yZXdhcmQ9VEFSR0VUX1JNVUxULAogICAgICAgICAgICB0cmlnZ2VyX3Byb2JhYmlsaXR5PTAuNTUsCiAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjUyLAogICAgICAgICAgICBtaW51dGVzX3RvX3RyaWdnZXI9NSwKICAgICAgICAgICAgaGVhZGxpbmU9ZiLwn5OKIHtzeW1ib2x9IFNwZW5jZXIgU2NhbHAgLSByYW5nZSBicmVhayB7J+KckyBUQVBFJyBpZiB0YXBlLmNvbmZpcm1hdGlvbl9mb3JfbG9uZyBlbHNlICcnfSIsCiAgICAgICAgICAgIHJlYXNvbmluZz1bCiAgICAgICAgICAgICAgICBmIjIwLW1pbiBjb25zb2xpZGF0aW9uIHt3bDouMmZ9LXt3aDouMmZ9ICg8MTUlIG9mIGRheSByYW5nZSkgaW4gdXBwZXIgMS8zIiwKICAgICAgICAgICAgICAgIGYiVm9sdW1lIHN1cmdlIG9uIGJyZWFrICg+PXtWT0xfU1VSR0U6Z314IHJhbmdlIGF2ZykiLAogICAgICAgICAgICAgICAgZiJCcmVhayBlbnRyeSB7ZW50cnk6LjJmfSwgc3RvcCB7c3RvcDouMmZ9IChyYW5nZSBsb3cpLCAyUiB0YXJnZXQge3RhcmdldDouMmZ9IiwKICAgICAgICAgICAgICAgIGYiVGFwZToge3RhcGUub3ZlcmFsbF9zaWduYWwudmFsdWV9IgogICAgICAgICAgICBdLAogICAgICAgICAgICB0aW1lX3dpbmRvdz1zZWxmLl9nZXRfY3VycmVudF90aW1lX3dpbmRvdygpLnZhbHVlLAogICAgICAgICAgICBtYXJrZXRfcmVnaW1lPXNlbGYuX21hcmtldF9yZWdpbWUudmFsdWUsCiAgICAgICAgICAgIGV4cGlyZXNfYXQ9KGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpICsgdGltZWRlbHRhKGhvdXJzPTIpKS5pc29mb3JtYXQoKQogICAgICAgICkKICAgIAo="


def main():
    check = "--check" in sys.argv
    src = open(FILE, encoding="utf-8").read()
    cur_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
    print(f"file            : {FILE}")
    print(f"live SHA        : {cur_sha}")
    print(f"expected SHA    : {PRE_FILE_SHA}")
    if cur_sha != PRE_FILE_SHA:
        print("\nABORT: live file SHA != expected baseline. The DGX file has DRIFTED.")
        print("Re-run extract_func.py _check_spencer_scalp and rebase. NOTHING was written.")
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

    # compile the patched content before touching disk
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(patched); tmp = tf.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        print(f"\nABORT: patched file fails to compile: {e}. NOTHING was written.")
        sys.exit(5)
    print(f"POST SHA        : {post_sha}")
    print("py_compile      : OK")

    if check:
        print("\n--check OK: guards pass, OLD found exactly once, patched compiles cleanly.")
        print("Run without --check to apply.")
        return

    bak = FILE + ".v363.bak"
    shutil.copy2(FILE, bak)
    with open(FILE, "w", encoding="utf-8") as f:
        f.write(patched)
    verify = hashlib.sha256(open(FILE, encoding="utf-8").read().encode("utf-8")).hexdigest()
    if verify != post_sha:
        print(f"\nABORT: post-write verify mismatch ({verify} != {post_sha}).")
        sys.exit(6)
    print(f"\nAPPLIED. backup -> {bak}")
    print(f"new live SHA    : {verify}")
    print("Next: pytest -> commit -> ./start_backend.sh --force")


if __name__ == "__main__":
    main()
