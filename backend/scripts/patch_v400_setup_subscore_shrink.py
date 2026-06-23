#!/usr/bin/env python3
r"""
patch_v400_setup_subscore_shrink.py — TQS Track · TQS4 (v400).

Env-gated, DORMANT-by-default neutralization of two SETUP-pillar sub-scores the
read-only diag_setup_pillar_probe flagged on sanitized bot-own closed trades
(14/21/30d windows, joined to tqs_breakdown):

  • setup.pattern  (0.20 wt) — the 75-90 score bucket LOSES every window (0% win,
    avgR -0.34..-0.36; opening_drive=85 -> 0% win) while low-scored setups
    (fashionably_late 51, vwap_continuation 54) WIN. The hand-tuned SMB tier
    ranking is mildly ANTI-predictive (corr -0.08/-0.13/-0.14). Fix = shrink the
    static ranking toward neutral (NOT invert) to de-emphasize the over-rewarded
    high tier.  Dial: TQS_SETUP_PATTERN_SHRINK

  • setup.win_rate (0.15 wt, v305) — DEGENERATE: raw historical WR pinned ~0.55
    for ~95% of the book (score stuck ~62), carries ~no signal (the -0.62 14d
    blip was a single-outlier artifact). Dial provided for completeness / live
    A-B; shrinking a near-constant ~62 toward 50 is nearly a no-op in practice.
    Dial: TQS_SETUP_WR_SHRINK

Mechanism (per sub-score):  s -> 50 + (s - 50) * k , clamped [0,100].
  k = 1.0  → byte-identical no-op (DEFAULT, DORMANT)
  k = 0.5  → halve the deviation from neutral
  k = 0.0  → fully neutralize to 50
Both read from env at scoring time → tunable + instantly reversible (unset/=1.0),
no restart-of-logic needed beyond the normal env reload. Composite grade is
unchanged in the default path; only changes when a dial is set < 1.0.

1 anchored, idempotent edit to ONE file (.v400bak backup, reversible).
  EDIT backend/services/tqs/setup_quality.py  (SetupQualityService.calculate_score,
        inserted just before the "# Calculate weighted total" block)

HASH GUARDS (v322t+ convention — built against live DGX bytes):
  PRE_SHA256  = 9026c9ac1757666afd097a14c6b857b37fa86547a41d030892fd1c1507611c06
  POST_SHA256 = 24fc9dcfa4677754f660b76f6752a525e532634e5ecd4e7be05975bc39199a15

Usage (repo root, DGX):
    .venv/bin/python backend/scripts/patch_v400_setup_subscore_shrink.py --check
    .venv/bin/python backend/scripts/patch_v400_setup_subscore_shrink.py --apply
    .venv/bin/python backend/scripts/patch_v400_setup_subscore_shrink.py --rollback
After --apply (dial stays OFF until you set it):
    git add -A && git commit -m "v400: TQS4 env-gated setup pattern/win_rate shrink (dormant)" && git push origin main
    ./start_backend.sh --force      # backend-only; no yarn build
To A/B live later (example):  set TQS_SETUP_PATTERN_SHRINK=0.5 in backend env, restart, observe.
Revert anytime: unset (or =1.0) + restart, or --rollback.
⚠️ COMMIT BEFORE ANY RESTART (StartTrading.bat git-wipes uncommitted code).

On a PRE_SHA mismatch (DGX drift), DO NOT --force. Upload your live copy:
  curl --data-binary @backend/services/tqs/setup_quality.py https://paste.rs/
and send the link so the edit can be rebased onto the canonical baseline.
"""
import os
import sys
import base64
import shutil
import hashlib
import argparse
import py_compile

BAK = ".v400bak"
TARGET = "backend/services/tqs/setup_quality.py"
PRE_SHA = "9026c9ac1757666afd097a14c6b857b37fa86547a41d030892fd1c1507611c06"
POST_SHA = "24fc9dcfa4677754f660b76f6752a525e532634e5ecd4e7be05975bc39199a15"

OLD_B64 = (
    "ICAgICAgICAjIENhbGN1bGF0ZSB3ZWlnaHRlZCB0b3RhbAogICAgICAgICMgdjE5LjM0LjMwNSDi"
    "gJQgcmViYWxhbmNlIHN1Yi13ZWlnaHRzIHNvIHJlYWxpemVkIEVYUEVDVEFOQ1kgKEVWKSBjYXJy"
    "aWVzCiAgICAgICAgIyB0aGUgbW9zdCBhdXRob3JpdHkgYW5kIHJhdyB3aW4tcmF0ZSBjYXJyaWVz"
    "IGxlc3MuIFdpbiByYXRlIGFsb25lIGlzbid0Cg=="
)
NEW_B64 = (
    "ICAgICAgICAjIHY0MDAgKFRRUzQpIOKAlCBlbnYtZ2F0ZWQgbmV1dHJhbGl6YXRpb24gb2YgdHdv"
    "IGZsYWdnZWQgc2V0dXAgc3ViLXNjb3JlcywKICAgICAgICAjIHByb3ZlbiBieSBkaWFnX3NldHVw"
    "X3BpbGxhcl9wcm9iZSAocmVhZC1vbmx5LCAxNC8yMS8zMGQgd2luZG93cyk6CiAgICAgICAgIyAg"
    "IHBhdHRlcm4gOiB0aGUgNzUtOTAgc2NvcmUgYnVja2V0IExPU0VTIGV2ZXJ5IHdpbmRvdyAoMCUg"
    "d2luLCBhdmdSCiAgICAgICAgIyAgICAgICAgICAgICAtMC4zNC4uLTAuMzY7IG9wZW5pbmdfZHJp"
    "dmU9ODUgLT4gMCUgd2luKSB3aGlsZSBsb3ctc2NvcmVkCiAgICAgICAgIyAgICAgICAgICAgICBz"
    "ZXR1cHMgKGZhc2hpb25hYmx5X2xhdGUgNTEsIHZ3YXBfY29udGludWF0aW9uIDU0KSB3aW4uIFRo"
    "ZQogICAgICAgICMgICAgICAgICAgICAgc3RhdGljIFNNQiB0aWVyIHJhbmtpbmcgaXMgbWlsZGx5"
    "IEFOVEktcHJlZGljdGl2ZSAoLTAuMDguLi0wLjE0KS4KICAgICAgICAjICAgd2luX3JhdGU6IERF"
    "R0VORVJBVEUg4oCUIHJhdyBoaXN0b3JpY2FsIFdSIHBpbm5lZCB+MC41NSBmb3Igfjk1JSBvZiB0"
    "aGUKICAgICAgICAjICAgICAgICAgICAgIGJvb2sgKHNjb3JlIHN0dWNrIH42Mik7IH5ubyBzaWdu"
    "YWwgKHRoZSAtMC42MiAxNGQgYmxpcCB3YXMgYQogICAgICAgICMgICAgICAgICAgICAgMS1vdXRs"
    "aWVyIGFydGlmYWN0KS4gRGlhbCBwcm92aWRlZCBmb3IgY29tcGxldGVuZXNzL0EtQi4KICAgICAg"
    "ICAjIEVhY2ggc2hyaW5rcyB0b3dhcmQgbmV1dHJhbCA1MDogcyAtPiA1MCArIChzLTUwKSprLiBE"
    "ZWZhdWx0IGs9MS4wID0gYnl0ZS0KICAgICAgICAjIGlkZW50aWNhbCBuby1vcCAoRE9STUFOVCku"
    "IFR1bmFibGUgKyByZXZlcnNpYmxlIHZpYSBlbnY7IEEvQiBsaXZlIGxpa2UgVFFTMi4KICAgICAg"
    "ICBpbXBvcnQgb3MgYXMgX29zCiAgICAgICAgZGVmIF9zaHJpbmtfayhfa2V5KToKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgcmV0dXJuIGZsb2F0KF9vcy5lbnZpcm9uLmdldChfa2V5"
    "LCAiMS4wIikpCiAgICAgICAgICAgIGV4Y2VwdCAoVHlwZUVycm9yLCBWYWx1ZUVycm9yKToKICAg"
    "ICAgICAgICAgICAgIHJldHVybiAxLjAKICAgICAgICBfcGF0X2sgPSBfc2hyaW5rX2soIlRRU19T"
    "RVRVUF9QQVRURVJOX1NIUklOSyIpCiAgICAgICAgaWYgX3BhdF9rICE9IDEuMDoKICAgICAgICAg"
    "ICAgX3BhdF9vbGQgPSByZXN1bHQucGF0dGVybl9zY29yZQogICAgICAgICAgICByZXN1bHQucGF0"
    "dGVybl9zY29yZSA9IG1heCgwLjAsIG1pbigxMDAuMCwgNTAuMCArIChyZXN1bHQucGF0dGVybl9z"
    "Y29yZSAtIDUwLjApICogX3BhdF9rKSkKICAgICAgICAgICAgcmVzdWx0LmZhY3RvcnMuYXBwZW5k"
    "KGYiUGF0dGVybiByYW5raW5nIHNocnVuayB7X3BhdF9vbGQ6LjBmfS0+e3Jlc3VsdC5wYXR0ZXJu"
    "X3Njb3JlOi4wZn0gKFRRU19TRVRVUF9QQVRURVJOX1NIUklOSz17X3BhdF9rOi4yZn0pIikKICAg"
    "ICAgICBfd3JfayA9IF9zaHJpbmtfaygiVFFTX1NFVFVQX1dSX1NIUklOSyIpCiAgICAgICAgaWYg"
    "X3dyX2sgIT0gMS4wOgogICAgICAgICAgICBfd3Jfb2xkID0gcmVzdWx0Lndpbl9yYXRlX3Njb3Jl"
    "CiAgICAgICAgICAgIHJlc3VsdC53aW5fcmF0ZV9zY29yZSA9IG1heCgwLjAsIG1pbigxMDAuMCwg"
    "NTAuMCArIChyZXN1bHQud2luX3JhdGVfc2NvcmUgLSA1MC4wKSAqIF93cl9rKSkKICAgICAgICAg"
    "ICAgcmVzdWx0LmZhY3RvcnMuYXBwZW5kKGYiV2luLXJhdGUgc2NvcmUgc2hydW5rIHtfd3Jfb2xk"
    "Oi4wZn0tPntyZXN1bHQud2luX3JhdGVfc2NvcmU6LjBmfSAoVFFTX1NFVFVQX1dSX1NIUklOSz17"
    "X3dyX2s6LjJmfSkiKQoKICAgICAgICAjIENhbGN1bGF0ZSB3ZWlnaHRlZCB0b3RhbAogICAgICAg"
    "ICMgdjE5LjM0LjMwNSDigJQgcmViYWxhbmNlIHN1Yi13ZWlnaHRzIHNvIHJlYWxpemVkIEVYUEVD"
    "VEFOQ1kgKEVWKSBjYXJyaWVzCiAgICAgICAgIyB0aGUgbW9zdCBhdXRob3JpdHkgYW5kIHJhdyB3"
    "aW4tcmF0ZSBjYXJyaWVzIGxlc3MuIFdpbiByYXRlIGFsb25lIGlzbid0Cg=="
)
APPLIED_MARKER = "TQS_SETUP_PATTERN_SHRINK"

OLD = base64.b64decode(OLD_B64).decode("utf-8")
NEW = base64.b64decode(NEW_B64).decode("utf-8")


def sha_full(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..", "..")):
        c = os.path.abspath(os.path.join(base, path))
        if os.path.exists(c):
            return c
    return os.path.abspath(os.path.join(".", path))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    print("=" * 84)
    print("  v400 / TQS4 — env-gated setup pattern/win_rate shrink (setup_quality.py)")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    p = resolve(TARGET)
    if not os.path.exists(p):
        print(f"  \u274c MISSING FILE: {TARGET}")
        sys.exit(2)

    if args.rollback:
        bak = p + BAK
        if os.path.exists(bak):
            shutil.copy2(bak, p)
            ok = "\u2705 matches PRE_SHA" if sha_full(p) == PRE_SHA else "\u26a0\ufe0f sha unexpected"
            print(f"  restored {TARGET}  sha={sha_full(p)[:12]}  {ok}")
        else:
            print(f"  no backup found ({BAK}); nothing to restore.")
        print("\n  ROLLBACK complete.  NEXT: ./start_backend.sh --force")
        return

    cur_sha = sha_full(p)
    if cur_sha == POST_SHA:
        file_state = "ALREADY-APPLIED"
    elif cur_sha == PRE_SHA:
        file_state = "READY"
    else:
        file_state = "DRIFT"

    print(f"\n  file   : {TARGET}")
    print(f"    sha     : {cur_sha[:12]}")
    print(f"    PRE_SHA : {PRE_SHA[:12]}  POST_SHA: {POST_SHA[:12]}")
    print(f"    state   : {file_state}")

    if file_state == "DRIFT":
        print("\n  \u274c DRIFT: live file matches neither PRE nor POST hash. Do NOT --force.")
        print(f"     Upload your live copy:  curl --data-binary @{TARGET} https://paste.rs/")
        sys.exit(3)

    src = open(p, encoding="utf-8").read()
    applied = APPLIED_MARKER in src
    n = src.count(OLD)
    status = "ALREADY-APPLIED" if applied else ("READY" if n == 1 else f"ANCHOR x{n}")
    print(f"\n  [calculate_score +pattern/win_rate shrink dials]\n    status : {status}")
    if not applied and n != 1:
        print("    \u274c anchor not uniquely found — ABORT (no files changed).")
        sys.exit(3)

    if args.check:
        nready = 0 if applied else 1
        print(f"\n  CHECK ok. {nready} change(s) ready. Re-run with --apply.")
        return

    if file_state == "ALREADY-APPLIED" or applied:
        print("\n  Nothing to do — file already at POST_SHA.")
        return

    bak = p + BAK
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    out = src.replace(OLD, NEW, 1)
    open(p, "w", encoding="utf-8").write(out)

    try:
        py_compile.compile(p, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, p)
        print(f"  \u274c py_compile FAILED — reverted from {BAK}.\n     {e}")
        sys.exit(6)

    post = sha_full(p)
    print(f"\n  patched {TARGET}  sha={post[:12]}  ({BAK} saved)")
    if post == POST_SHA:
        print("  \u2705 POST_SHA verified — result is byte-identical to the tested build.")
    else:
        shutil.copy2(bak, p)
        print(f"  \u26a0\ufe0f  POST_SHA MISMATCH — expected {POST_SHA[:12]} got {post[:12]}. Reverted.")
        sys.exit(5)
    print("\n  APPLY complete. 1 change. Dials default OFF (k=1.0) — behavior unchanged.")
    print("  NEXT (commit BEFORE restart):")
    print("    git add -A && git commit -m 'v400: TQS4 env-gated setup pattern/win_rate shrink (dormant)' && git push origin main")
    print("    ./start_backend.sh --force")
    print("  A/B later:  export TQS_SETUP_PATTERN_SHRINK=0.5  (or 0.0) ; restart ; observe.")


if __name__ == "__main__":
    main()
