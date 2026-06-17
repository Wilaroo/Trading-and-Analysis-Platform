#!/usr/bin/env python3
"""
patch_v328_anchor_aware_mixed_mode.py  (AGENTS.md §2.2 anchored-chunk patcher)

WHAT: makes multi_tf_regime.mode_for_direction's MIXED/UNKNOWN branch ANCHOR-AWARE.
WHY : v326 (DGX) showed the regime classifier is NOT stuck — it varies day to day.
      The 100%-CAUTIOUS posture (2026-06-16/17) was caused by SPY context flipping to
      MIXED when the DAILY ANCHOR was strongly UP (long lane 91) but the INTRADAY lane
      drifted to NEUTRAL (43-46). classify_context only recognizes (UP,UP)=ALIGNED_UP
      and (UP,DOWN)=PULLBACK; (UP,NEUTRAL) falls through to MIXED, which flattened BOTH
      long & short to 'cautious' — raising the GO bar 38->50 (confidence_gate L1026-31)
      and starving execution. v327 unlock-sim: 85 decisions WOULD GO at the NORMAL bar
      (vs current 8, ~10x), all 85 in cautious, ZERO hard-blocked by active suppression
      (suppression only REDUCEs 58, never SKIPs — the safety net stays intact).
NEW RULE (mode_for_direction MIXED/UNKNOWN branch):
        long_anchor bias UP   -> long: normal,    short: defensive
        long_anchor bias DOWN -> long: defensive, short: normal
        anchor NEUTRAL/UNKNOWN-> both cautious (unchanged; truly no directional read)
      This unlocks WITH-trend entries in a decisive trend while making COUNTER-trend
      entries MORE conservative (defensive, GO bar 60) than the old blanket cautious(50).
ROLLOUT: paper-only; fully reversible. active-REDUCE regime suppression still trims
      negative-EV cells, so newly-admitted trades remain EV-screened.

§2.2: PRE+POST SHA256 guards, base64 anchored chunk, --check/--apply/--rollback,
      backs up the original, refuses to write on drift or wrong post-hash.

Usage (from repo root, DGX):
  .venv/bin/python /tmp/patch_v328_anchor_aware_mixed_mode.py --check
  .venv/bin/python /tmp/patch_v328_anchor_aware_mixed_mode.py --apply
  .venv/bin/python /tmp/patch_v328_anchor_aware_mixed_mode.py --rollback
Then: ./start_backend.sh --force

POST-DEPLOY VERIFY (wall-clock, MIXED-context session):
  diag_v327_mode_unlock_sim.py  → GO should rise from ~8 toward the WOULD-GO count;
                                   trading_mode mix should show 'normal' for longs.
  diag_v326_regime_mtf_timeline → modes(long) on UP-anchor MIXED days now 'normal'.
  Watch newly-admitted LONGs' sanitized avgR (diag_v321b) stays >=0; if bleeding,
  --rollback or tighten via the regime-suppression EV table.
"""
import base64, hashlib, sys, shutil, os

FILE = "backend/services/multi_tf_regime.py"
PRE_SHA  = "ae994e646b85e1eeac8a65a28994d5eec883dd8dc927c61b13753f030f67e1ea"
POST_SHA = "8954243629a4d4633a0c1a1dcbbcfc54addf8f784e5a73bce142bce79999ebc1"
OLD_B64 = "ICAgICMgTUlYRUQgLyBVTktOT1dOCiAgICByZXR1cm4gImNhdXRpb3VzIgo="
NEW_B64 = "ICAgICMgTUlYRUQgLyBVTktOT1dOIOKAlCBhbmNob3ItYXdhcmUgKHYxOS4zNC4zMjEpLiBBIGRlY2lzaXZlIGRhaWx5IGFuY2hvcgogICAgIyB3aXRoIGEgbWVyZWx5LU5FVVRSQUwgKG5vbi1vcHBvc2luZykgaW50cmFkYXkgaXMgYSB0cmVuZCBjb25zb2xpZGF0aW5nLAogICAgIyBOT1QgYSBuby1yZWFkLiB2MzI2L3YzMjcgKDIwMjYtMDYpOiBTUFkgKFVQLWFuY2hvciwgTkVVVFJBTC1pbnRyYWRheSkgZmVsbAogICAgIyBoZXJlIGFuZCBmbGF0dGVuZWQgQk9USCBkaXJlY3Rpb25zIHRvICdjYXV0aW91cycsIHJhaXNpbmcgdGhlIEdPIGJhciAzOC0+NTAKICAgICMgYW5kIHN0YXJ2aW5nIEdPICh+MTB4IGZld2VyIEdPcykuIEtlZXAgdGhlIFdJVEgtdHJlbmQgc2lkZSB0cmFkZWFibGUKICAgICMgKG5vcm1hbCkgYW5kIHRoZSBDT1VOVEVSLXRyZW5kIHNpZGUgZGVmZW5zaXZlOyBvbmx5IGEgdHJ1bHkgbmV1dHJhbC91bmtub3duCiAgICAjIGFuY2hvciBjYXBzIGJvdGguIFN5bW1ldHJpYyBmb3IgYSBkZWNpc2l2ZS1ET1dOIGFuY2hvci4KICAgIGxiID0gbGFuZV9iaWFzKGxvbmdfc2NvcmUpCiAgICBpZiBsYiA9PSAiVVAiOgogICAgICAgIHJldHVybiAibm9ybWFsIiBpZiBkID09ICJsb25nIiBlbHNlICJkZWZlbnNpdmUiCiAgICBpZiBsYiA9PSAiRE9XTiI6CiAgICAgICAgcmV0dXJuICJkZWZlbnNpdmUiIGlmIGQgPT0gImxvbmciIGVsc2UgIm5vcm1hbCIKICAgIHJldHVybiAiY2F1dGlvdXMiCg=="
BACKUP = FILE + ".bak_v328"


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
    print("\nREADY: --apply will make the MIXED/UNKNOWN mode branch anchor-aware.")
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
