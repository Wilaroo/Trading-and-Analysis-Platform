#!/usr/bin/env python3
"""patch_v379_smartfilter_grade_gate.py
=========================================
Fix the smart_filter borderline-band QUALITY gate (operator audit 2026-06,
diags v378b/v378c/v379).

ROOT CAUSE (proven by diag_v379 on live DGX data — 49/49 joinable drops):
  The borderline-win-rate band (0.45 <= win_rate < normal_threshold) was
  comparing `quality_score` against an absolute `high_tqs_requirement = 75`,
  while the MAIN bot loop feeds `quality_score = alert['score'] =
  trigger_probability * 100` (trading_bot_service.py builds that dict), NOT the
  TQS. Worse, even the real TQS can never reach 75 — it is a 5-pillar AVERAGE
  crushed into ~48-68 (see services/tqs/grade_calibration.py). Net effect: every
  borderline setup (SNDK/UMC/rs_leader_break/…) was permanently hard-blocked,
  and the reject string mislabeled trigger_probability as "TQS".

FIX (2 files, fully reversible):
  O1  opportunity_evaluator.py — feed smart_filter the REAL TQS
      (`quality_score = int(alert.get('tqs_score') or alert.get('score') or 70)`),
      mirroring the confidence-gate GAP-1 fix; the auto-execute path already
      passes the TQS, so both entry paths become consistent.
  S1  smart_filter.py — add `import os`, a `_GRADE_RANK` ladder, and a new
      env-tunable `borderline_min_grade` (SMART_FILTER_BORDERLINE_MIN_GRADE,
      default "B") to DEFAULT_CONFIG.
  S2  smart_filter.py — the borderline band now PROCEEDs when the CALIBRATED
      grade (services.tqs.grade_calibration.calibrate_grade) clears the floor,
      instead of the unreachable absolute 75. `high_tqs_requirement` is kept ONLY
      as a crash / no-reference fallback. Self-adapts if the TQS scale is later
      de-compressed (Path B).

REVERSIBLE: --rollback restores the .bak.v379 backups. Loosen/tighten live with
SMART_FILTER_BORDERLINE_MIN_GRADE=C|B|A (no redeploy).

NOTHING SAFETY-CRITICAL TOUCHED (no close_trade / bracket / kill-switch paths).

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/patch_v379_smartfilter_grade_gate.py --check
  .venv/bin/python backend/scripts/patch_v379_smartfilter_grade_gate.py --apply
  .venv/bin/python backend/scripts/patch_v379_smartfilter_grade_gate.py --rollback
"""
import base64
import hashlib
import os
import sys
import py_compile

BAK_SUFFIX = ".bak.v379"

# ── O1 — opportunity_evaluator.py : feed the real TQS into smart_filter ──
O1_OLD_B64 = "ICAgICAgICAgICAgc3RyYXRlZ3lfZmlsdGVyID0gYm90Ll9ldmFsdWF0ZV9zdHJhdGVneV9maWx0ZXIoCiAgICAgICAgICAgICAgICBzZXR1cF90eXBlPXNldHVwX3R5cGUsCiAgICAgICAgICAgICAgICBxdWFsaXR5X3Njb3JlPWFsZXJ0LmdldCgnc2NvcmUnLCA3MCksCiAgICAgICAgICAgICAgICBzeW1ib2w9c3ltYm9sCiAgICAgICAgICAgICkK"
O1_NEW_B64 = "ICAgICAgICAgICAgc3RyYXRlZ3lfZmlsdGVyID0gYm90Ll9ldmFsdWF0ZV9zdHJhdGVneV9maWx0ZXIoCiAgICAgICAgICAgICAgICBzZXR1cF90eXBlPXNldHVwX3R5cGUsCiAgICAgICAgICAgICAgICBxdWFsaXR5X3Njb3JlPWludChhbGVydC5nZXQoJ3Rxc19zY29yZScpIG9yIGFsZXJ0LmdldCgnc2NvcmUnKSBvciA3MCksCiAgICAgICAgICAgICAgICBzeW1ib2w9c3ltYm9sCiAgICAgICAgICAgICkK"

# ── S1 — smart_filter.py : imports + DEFAULT_CONFIG ──
S1_OLD_B64 = "aW1wb3J0IGxvZ2dpbmcKZnJvbSBkYXRldGltZSBpbXBvcnQgZGF0ZXRpbWUsIHRpbWV6b25lCmZyb20gdHlwaW5nIGltcG9ydCBEaWN0LCBBbnksIExpc3QKCmxvZ2dlciA9IGxvZ2dpbmcuZ2V0TG9nZ2VyKF9fbmFtZV9fKQoKREVGQVVMVF9DT05GSUcgPSB7CiAgICAiZW5hYmxlZCI6IFRydWUsCiAgICAibWluX3NhbXBsZV9zaXplIjogNSwKICAgICJza2lwX3dpbl9yYXRlX3RocmVzaG9sZCI6IDAuMzUsCiAgICAicmVkdWNlX3NpemVfdGhyZXNob2xkIjogMC40NSwKICAgICJyZXF1aXJlX2hpZ2hlcl90cXNfdGhyZXNob2xkIjogMC41MCwKICAgICJub3JtYWxfdGhyZXNob2xkIjogMC41NSwKICAgICJzaXplX3JlZHVjdGlvbl9wY3QiOiAwLjUsCiAgICAiaGlnaF90cXNfcmVxdWlyZW1lbnQiOiA3NSwKfQo="
S1_NEW_B64 = "aW1wb3J0IGxvZ2dpbmcKaW1wb3J0IG9zCmZyb20gZGF0ZXRpbWUgaW1wb3J0IGRhdGV0aW1lLCB0aW1lem9uZQpmcm9tIHR5cGluZyBpbXBvcnQgRGljdCwgQW55LCBMaXN0Cgpsb2dnZXIgPSBsb2dnaW5nLmdldExvZ2dlcihfX25hbWVfXykKCiMgdjM3OSDigJQgZ3JhZGUtcmFuayBsYWRkZXIgZm9yIHRoZSBib3JkZXJsaW5lLWJhbmQgcXVhbGl0eSBnYXRlLiBDb3ZlcnMgYm90aAojIHRoZSBwZXJjZW50aWxlLWNhbGlicmF0ZWQgZ3JhZGVzIChBL0IvQy9EL0YgZnJvbQojIGdyYWRlX2NhbGlicmF0aW9uLmNhbGlicmF0ZV9ncmFkZSkgYW5kIHRoZSBsZWdhY3kgc3RhdGljICIrIiBncmFkZXMsIHNvIHRoZQojIGNvbXBhcmlzb24gaXMgcm9idXN0IHRvIHdoaWNoZXZlciBwYXRoIGNhbGlicmF0ZV9ncmFkZSByZXR1cm5zLgpfR1JBREVfUkFOSyA9IHsiQSsiOiA3LCAiQSI6IDYsICJCKyI6IDUsICJCIjogNCwgIkMrIjogMywgIkMiOiAyLCAiRCI6IDEsICJGIjogMH0KCkRFRkFVTFRfQ09ORklHID0gewogICAgImVuYWJsZWQiOiBUcnVlLAogICAgIm1pbl9zYW1wbGVfc2l6ZSI6IDUsCiAgICAic2tpcF93aW5fcmF0ZV90aHJlc2hvbGQiOiAwLjM1LAogICAgInJlZHVjZV9zaXplX3RocmVzaG9sZCI6IDAuNDUsCiAgICAicmVxdWlyZV9oaWdoZXJfdHFzX3RocmVzaG9sZCI6IDAuNTAsCiAgICAibm9ybWFsX3RocmVzaG9sZCI6IDAuNTUsCiAgICAic2l6ZV9yZWR1Y3Rpb25fcGN0IjogMC41LAogICAgIyB2Mzc5IOKAlCBib3JkZXJsaW5lLWJhbmQgc2V0dXBzICgwLjQ1PD13aW5fcmF0ZTxub3JtYWwpIG5vdyBmaXJlIHdoZW4gdGhlCiAgICAjIGFsZXJ0J3MgQ0FMSUJSQVRFRCBUUVMgR1JBREUgY2xlYXJzIHRoaXMgZmxvb3IgKGRlZmF1bHQgIkIiKSwgaW5zdGVhZCBvZgogICAgIyBjb21wYXJpbmcgdGhlIHJhdyBjb21wb3NpdGUgVFFTIHRvIGFuIGFic29sdXRlIDc1IGl0IGNhbiBuZXZlciByZWFjaCAodGhlCiAgICAjIGNvbXBvc2l0ZSBpcyBhIDUtcGlsbGFyIGF2ZXJhZ2UgY2FwcGVkIH42ODsgc2VlIGdyYWRlX2NhbGlicmF0aW9uLnB5KS4KICAgICMgRW52LXR1bmFibGUgKyByZXZlcnNpYmxlLiBgaGlnaF90cXNfcmVxdWlyZW1lbnRgIGlzIGtlcHQgT05MWSBhcyBhCiAgICAjIGNyYXNoIC8gbm8tcmVmZXJlbmNlIGZhbGxiYWNrIGluc2lkZSB0aGUgYm9yZGVybGluZSBicmFuY2guCiAgICAiYm9yZGVybGluZV9taW5fZ3JhZGUiOiBvcy5lbnZpcm9uLmdldCgiU01BUlRfRklMVEVSX0JPUkRFUkxJTkVfTUlOX0dSQURFIiwgIkIiKSwKICAgICJoaWdoX3Rxc19yZXF1aXJlbWVudCI6IDc1LAp9Cg=="

# ── S2 — smart_filter.py : grade-calibrated borderline band ──
S2_OLD_B64 = "ICAgICAgICAjIFJFUVVJUkVfSElHSEVSX1RRUzogQm9yZGVybGluZQogICAgICAgIGlmIHdpbl9yYXRlIDwgY29uZmlnWyJub3JtYWxfdGhyZXNob2xkIl06CiAgICAgICAgICAgIGlmIHF1YWxpdHlfc2NvcmUgPCBjb25maWdbImhpZ2hfdHFzX3JlcXVpcmVtZW50Il06CiAgICAgICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgICAgICJhY3Rpb24iOiAiU0tJUCIsCiAgICAgICAgICAgICAgICAgICAgInJlYXNvbmluZyI6ICgKICAgICAgICAgICAgICAgICAgICAgICAgZiJQYXNzaW5nIG9uIHtzeW1ib2x9IHtzZXR1cF90eXBlfSAtICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJ3ZSdyZSB7d2luX3JhdGU6LjAlfSBvbiB0aGlzIHNldHVwIGFuZCBUUVMgKHtxdWFsaXR5X3Njb3JlfSkgIgogICAgICAgICAgICAgICAgICAgICAgICBmImRvZXNuJ3QgbWVldCB0aHJlc2hvbGQgKHtjb25maWdbJ2hpZ2hfdHFzX3JlcXVpcmVtZW50J119KSIKICAgICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgICJhZGp1c3RtZW50X3BjdCI6IDAsCiAgICAgICAgICAgICAgICAgICAgInN0YXRzIjogc3RhdHMsCiAgICAgICAgICAgICAgICAgICAgIndpbl9yYXRlIjogd2luX3JhdGUsCiAgICAgICAgICAgICAgICAgICAgInRxc19yZXF1aXJlZCI6IGNvbmZpZ1siaGlnaF90cXNfcmVxdWlyZW1lbnQiXSwKICAgICAgICAgICAgICAgIH0KICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAgICAgImFjdGlvbiI6ICJQUk9DRUVEIiwKICAgICAgICAgICAgICAgICAgICAicmVhc29uaW5nIjogKAogICAgICAgICAgICAgICAgICAgICAgICBmIlRha2luZyB7c3ltYm9sfSB7c2V0dXBfdHlwZX0gLSAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVybGluZSB3aW4gcmF0ZSAoe3dpbl9yYXRlOi4wJX0pIGJ1dCBUUVMgaXMgc3Ryb25nICh7cXVhbGl0eV9zY29yZX0pIgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgImFkanVzdG1lbnRfcGN0IjogMS4wLAogICAgICAgICAgICAgICAgICAgICJzdGF0cyI6IHN0YXRzLAogICAgICAgICAgICAgICAgICAgICJ3aW5fcmF0ZSI6IHdpbl9yYXRlLAogICAgICAgICAgICAgICAgfQo="
S2_NEW_B64 = "ICAgICAgICAjIFJFUVVJUkVfSElHSEVSX1RRUzogQm9yZGVybGluZQogICAgICAgICMgdjM3OSDigJQganVkZ2UgVEhJUyBpbnN0YW5jZSdzIHF1YWxpdHkgYnkgdGhlIENBTElCUkFURUQgR1JBREUKICAgICAgICAjIChjb25zaXN0ZW50IHdpdGggdGhlIGdyYWRlIHN5c3RlbSksIG5vdCB0aGUgcmF3IGNvbXBvc2l0ZSBUUVMuIFRoZQogICAgICAgICMgY29tcG9zaXRlIGlzIGEgNS1waWxsYXIgYXZlcmFnZSBjcnVzaGVkIGludG8gfjQ4LTY4CiAgICAgICAgIyAoZ3JhZGVfY2FsaWJyYXRpb24ucHkpLCBzbyB0aGUgbGVnYWN5IGFic29sdXRlCiAgICAgICAgIyBgcXVhbGl0eV9zY29yZSA8IGhpZ2hfdHFzX3JlcXVpcmVtZW50ICg3NSlgIHRlc3Qgd2FzIHVucmVhY2hhYmxlIGFuZAogICAgICAgICMgaGFyZC1ibG9ja2VkIEVWRVJZIGJvcmRlcmxpbmUgc2V0dXAuIFBST0NFRUQgd2hlbiB0aGUgY2FsaWJyYXRlZCBncmFkZQogICAgICAgICMgY2xlYXJzIGBib3JkZXJsaW5lX21pbl9ncmFkZWAgKGRlZmF1bHQgIkIiKS4gRmFsbHMgYmFjayB0byB0aGUKICAgICAgICAjIGFic29sdXRlIGhpZ2hfdHFzX3JlcXVpcmVtZW50IG9ubHkgaWYgY2FsaWJyYXRpb24gaXMgdW5hdmFpbGFibGUuCiAgICAgICAgaWYgd2luX3JhdGUgPCBjb25maWdbIm5vcm1hbF90aHJlc2hvbGQiXToKICAgICAgICAgICAgbWluX2dyYWRlID0gY29uZmlnLmdldCgiYm9yZGVybGluZV9taW5fZ3JhZGUiLCAiQiIpCiAgICAgICAgICAgIGdyYWRlID0gTm9uZQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBmcm9tIHNlcnZpY2VzLnRxcy5ncmFkZV9jYWxpYnJhdGlvbiBpbXBvcnQgY2FsaWJyYXRlX2dyYWRlCiAgICAgICAgICAgICAgICBncmFkZSA9IGNhbGlicmF0ZV9ncmFkZShxdWFsaXR5X3Njb3JlKQogICAgICAgICAgICAgICAgcXVhbGl0eV9vayA9IF9HUkFERV9SQU5LLmdldChncmFkZSwgLTEpID49IF9HUkFERV9SQU5LLmdldChtaW5fZ3JhZGUsIDQpCiAgICAgICAgICAgICAgICBnYXRlX2Rlc2MgPSBmImdyYWRlIHtncmFkZX0gdnMge21pbl9ncmFkZX0gZmxvb3IiCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgX2dyYWRlX2VycjoKICAgICAgICAgICAgICAgIGxvZ2dlci53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgICJbc21hcnRfZmlsdGVyXSBjYWxpYnJhdGVfZ3JhZGUgZmFpbGVkICglcykg4oCUIGFic29sdXRlIFRRUyBmYWxsYmFjayIsCiAgICAgICAgICAgICAgICAgICAgX2dyYWRlX2VyciwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHF1YWxpdHlfb2sgPSBxdWFsaXR5X3Njb3JlID49IGNvbmZpZ1siaGlnaF90cXNfcmVxdWlyZW1lbnQiXQogICAgICAgICAgICAgICAgZ2F0ZV9kZXNjID0gZiJUUVMge3F1YWxpdHlfc2NvcmV9IHZzIHtjb25maWdbJ2hpZ2hfdHFzX3JlcXVpcmVtZW50J119IGZsb29yIgogICAgICAgICAgICBpZiBub3QgcXVhbGl0eV9vazoKICAgICAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAgICAgImFjdGlvbiI6ICJTS0lQIiwKICAgICAgICAgICAgICAgICAgICAicmVhc29uaW5nIjogKAogICAgICAgICAgICAgICAgICAgICAgICBmIlBhc3Npbmcgb24ge3N5bWJvbH0ge3NldHVwX3R5cGV9IC0gIgogICAgICAgICAgICAgICAgICAgICAgICBmIndlJ3JlIHt3aW5fcmF0ZTouMCV9IG9uIHRoaXMgc2V0dXAgYW5kIGl0cyBxdWFsaXR5ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiIoe2dhdGVfZGVzY30pIGlzIGJlbG93IHRoZSBiYXIgZm9yIGJvcmRlcmxpbmUgc2V0dXBzIgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgImFkanVzdG1lbnRfcGN0IjogMCwKICAgICAgICAgICAgICAgICAgICAic3RhdHMiOiBzdGF0cywKICAgICAgICAgICAgICAgICAgICAid2luX3JhdGUiOiB3aW5fcmF0ZSwKICAgICAgICAgICAgICAgICAgICAidHFzX2dyYWRlIjogZ3JhZGUsCiAgICAgICAgICAgICAgICAgICAgIm1pbl9ncmFkZSI6IG1pbl9ncmFkZSwKICAgICAgICAgICAgICAgIH0KICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAgICAgImFjdGlvbiI6ICJQUk9DRUVEIiwKICAgICAgICAgICAgICAgICAgICAicmVhc29uaW5nIjogKAogICAgICAgICAgICAgICAgICAgICAgICBmIlRha2luZyB7c3ltYm9sfSB7c2V0dXBfdHlwZX0gLSAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVybGluZSB3aW4gcmF0ZSAoe3dpbl9yYXRlOi4wJX0pIGJ1dCBxdWFsaXR5IGlzIHN0cm9uZyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiKHtnYXRlX2Rlc2N9KSIKICAgICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgICJhZGp1c3RtZW50X3BjdCI6IDEuMCwKICAgICAgICAgICAgICAgICAgICAic3RhdHMiOiBzdGF0cywKICAgICAgICAgICAgICAgICAgICAid2luX3JhdGUiOiB3aW5fcmF0ZSwKICAgICAgICAgICAgICAgICAgICAidHFzX2dyYWRlIjogZ3JhZGUsCiAgICAgICAgICAgICAgICB9Cg=="


def _d(b64):
    return base64.b64decode(b64).decode("utf-8")


FILES = [
    {
        "path": "backend/services/opportunity_evaluator.py",
        "pre_sha": "eecb760f6ef2aafc6c2690a225d0ff2d522163d3f086eecfc70a7ad6378700ce",
        "edits": [("O1 feed real TQS", _d(O1_OLD_B64), _d(O1_NEW_B64))],
    },
    {
        "path": "backend/services/smart_filter.py",
        "pre_sha": "86fd6ac41539f734586529e2118597ddff4aa7816d57f5882639d50f1fb4d6fe",
        "edits": [
            ("S1 config + _GRADE_RANK", _d(S1_OLD_B64), _d(S1_NEW_B64)),
            ("S2 grade-calibrated band", _d(S2_OLD_B64), _d(S2_NEW_B64)),
        ],
    },
]


def _resolve(path):
    if os.path.exists(path):
        return path
    alt = path.replace("backend/", "")
    if os.path.exists(alt):
        return alt
    sys.exit(f"ERROR: cannot find {path}")


def rollback():
    any_done = False
    for spec in FILES:
        path = _resolve(spec["path"])
        bak = path + BAK_SUFFIX
        if os.path.exists(bak):
            open(path, "w", encoding="utf-8").write(open(bak, encoding="utf-8").read())
            print(f"restored {path} from {bak}")
            any_done = True
        else:
            print(f"no backup for {path} ({bak} missing) — skipped")
    if not any_done:
        print("nothing to roll back.")


def main():
    if "--rollback" in sys.argv:
        rollback()
        return
    apply_mode = "--apply" in sys.argv
    force = "--force" in sys.argv

    # 1) validate every file's PRE-SHA + anchor counts BEFORE writing anything
    plans = []
    all_ok = True
    for spec in FILES:
        path = _resolve(spec["path"])
        src = open(path, encoding="utf-8").read()
        cur = hashlib.sha256(src.encode("utf-8")).hexdigest()
        sha_ok = (cur == spec["pre_sha"])
        print(f"\ntarget        : {path}")
        print(f"whole-file SHA: {cur}")
        print(f"expected PRE  : {spec['pre_sha']}  {'OK' if sha_ok else 'MISMATCH'}")
        if not sha_ok and not force:
            all_ok = False
            print("  (PRE-SHA mismatch — anchors still checked below; pass --force "
                  "to proceed if anchor counts are all 1)")
        out = src
        for tag, old, new in spec["edits"]:
            n = src.count(old)
            flag = "OK" if n == 1 else "FAIL"
            if n != 1:
                all_ok = False
            print(f"  [{flag}] {tag:<26} anchor count = {n} (need 1)")
            if n == 1:
                out = out.replace(old, new, 1)
        try:
            compile(out, path, "exec")
            comp = "compile OK"
        except SyntaxError as e:
            comp = f"COMPILE ERROR: {e}"
            all_ok = False
        post = hashlib.sha256(out.encode("utf-8")).hexdigest()
        print(f"  would-be POST SHA: {post}")
        print(f"  patched syntax   : {comp}")
        plans.append((path, src, out))

    if not all_ok and not force:
        sys.exit("\nABORT: not all checks passed. No file written. "
                 "(Use --force only if PRE-SHA drifted but every anchor count is 1.)")

    if not apply_mode:
        print("\n--check complete. Re-run with --apply to write (creates "
              f"{BAK_SUFFIX} backups + py_compile, auto-restore on failure).")
        return

    # 2) apply: write backups + patched content, then py_compile each
    written = []
    for path, src, out in plans:
        bak = path + BAK_SUFFIX
        open(bak, "w", encoding="utf-8").write(src)
        open(path, "w", encoding="utf-8").write(out)
        written.append((path, src, bak))
        print(f"\nAPPLIED {path}  (backup: {bak})")
        print(f"  POST SHA: {hashlib.sha256(out.encode()).hexdigest()}")

    failed = None
    for path, _, _ in written:
        try:
            py_compile.compile(path, doraise=True)
            print(f"py_compile {path}: OK")
        except py_compile.PyCompileError as e:
            print(f"py_compile {path}: FAILED\n{e}")
            failed = path
            break
    if failed:
        print("\nROLLING BACK all files (a patched file failed to compile)…")
        for path, src, _ in written:
            open(path, "w", encoding="utf-8").write(src)
            print(f"  restored {path}")
        sys.exit("ABORT: restored originals; patch produced invalid syntax.")

    print("\n✅ v379 applied to BOTH files. Restart backend/scanner to load.")
    print("   Tune live (no redeploy): SMART_FILTER_BORDERLINE_MIN_GRADE=C|B|A")
    print("   Rollback: --rollback")


if __name__ == "__main__":
    main()
