#!/usr/bin/env python3
"""patch_v320_daily_bar_premarket_gate.py  —  v19.34.320 patcher  (2026-06-16)

AGENTS.md §2.2-COMPLIANT anchored-chunk patcher:
  • base64 (old, new) chunk pair
  • per-file SHA256 PRE + POST hash guards
  • ABORTS on drift (pre-mismatch OR post-mismatch)
  • supports --check / --apply / --rollback / --status
  • backs up original on every write

Target: backend/services/opportunity_evaluator.py

Effect: inserts a daily-bar premarket gate immediately BEFORE the
v19.34.173 F-gate block. Suppresses entries whose trade_style is
multi_day/swing/position/investment OR whose setup_type is in the
daily-bar list, when local ET time < V320_DAILY_BAR_CUTOFF_ET (default
10:00). Policy controlled by V320_DAILY_BAR_GATE_POLICY:
  block (default) | observe | off
"""
import argparse
import base64
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path.home() / "Trading-and-Analysis-Platform"
TARGET = REPO_ROOT / "backend" / "services" / "opportunity_evaluator.py"

EXPECTED_PRE_SHA = "ce3624c52cb6c03fd7475a11478b33c6478963fa08c9bc46dd215afcf1e8d120"
EXPECTED_POST_SHA = "886bb28761779e61e4dfb5d8737cf0231a8f52f57199bab4c842fa6222f40a2b"

OLD_B64 = "ICAgICAgICAgICAgZGlyZWN0aW9uID0gVHJhZGVEaXJlY3Rpb24uTE9ORyBpZiBkaXJlY3Rpb25fc3RyID09ICdsb25nJyBlbHNlIFRyYWRlRGlyZWN0aW9uLlNIT1JUCgogICAgICAgICAgICAjIOKUgOKUgCB2MTkuMzQuMTczIOKAlCBTZXR1cC1ncmFkZSBGLWdhdGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACg=="
NEW_B64 = "ICAgICAgICAgICAgZGlyZWN0aW9uID0gVHJhZGVEaXJlY3Rpb24uTE9ORyBpZiBkaXJlY3Rpb25fc3RyID09ICdsb25nJyBlbHNlIFRyYWRlRGlyZWN0aW9uLlNIT1JUCgoKICAgICAgICAgICAgIyDilIDilIAgdjE5LjM0LjMyMCDigJQgRGFpbHktYmFyIHByZW1hcmtldCBnYXRlIOKUgOKUgCBCRUdJTiDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgIyBTdXBwcmVzcyBkYWlseS1iYXItY29uc3VtaW5nIHNldHVwcyBiZWZvcmUgdGhlIGN1dG9mZiBFVAogICAgICAgICAgICAjIHRpbWUuIFRvZGF5J3MgZGFpbHkgYmFyIGlzbid0IG1hdHVyZSB1bnRpbCB0aGUgZmlyc3QgMzAKICAgICAgICAgICAgIyBtaW4gb2YgUlRIIGhhdmUgcGFzc2VkICh+MTA6MDAgRVQpLiBTZXR1cHMgd2hvc2UKICAgICAgICAgICAgIyB0cmFkZV9zdHlsZSBpbiBtdWx0aV9kYXkvc3dpbmcvcG9zaXRpb24vaW52ZXN0bWVudCBPUgogICAgICAgICAgICAjIHNldHVwX3R5cGUgaW4gZGFpbHktYmFyIGxpc3QgcmVhZCBUT0RBWSdzIGRhaWx5IE9ITENWIC0+CiAgICAgICAgICAgICMgcHJlLWN1dG9mZiBmaXJlcyBjb25zdW1lIGluY29tcGxldGUvd2hpcHB5IGRhdGEuCiAgICAgICAgICAgICMKICAgICAgICAgICAgIyBFbnY6IFYzMjBfREFJTFlfQkFSX0dBVEVfUE9MSUNZIGluIHtibG9jayxvYnNlcnZlLG9mZn0KICAgICAgICAgICAgIyAgICAgIFYzMjBfREFJTFlfQkFSX0NVVE9GRl9FVCAoSEg6TU0gQW1lcmljYS9OZXdfWW9yaykKICAgICAgICAgICAgIyAgICAgIFYzMjBfREFJTFlfQkFSX1NUWUxFUyAgIChjb21tYSBsaXN0KQogICAgICAgICAgICAjICAgICAgVjMyMF9EQUlMWV9CQVJfU0VUVVBTICAgKGNvbW1hIGxpc3QpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGltcG9ydCBvcyBhcyBfb3NfdjMyMAogICAgICAgICAgICAgICAgX3YzMjBfcG9saWN5ID0gKF9vc192MzIwLmVudmlyb24uZ2V0KAogICAgICAgICAgICAgICAgICAgICJWMzIwX0RBSUxZX0JBUl9HQVRFX1BPTElDWSIsICJibG9jayIpCiAgICAgICAgICAgICAgICAgICAgb3IgImJsb2NrIikubG93ZXIoKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpZiBfdjMyMF9wb2xpY3kgbm90IGluICgiYmxvY2siLCAib2JzZXJ2ZSIsICJvZmYiKToKICAgICAgICAgICAgICAgICAgICBfdjMyMF9wb2xpY3kgPSAiYmxvY2siCiAgICAgICAgICAgICAgICBpZiBfdjMyMF9wb2xpY3kgIT0gIm9mZiI6CiAgICAgICAgICAgICAgICAgICAgZnJvbSB6b25laW5mbyBpbXBvcnQgWm9uZUluZm8gYXMgX1pJX3YzMjAKICAgICAgICAgICAgICAgICAgICBfdjMyMF9jdXRvZmYgPSAoX29zX3YzMjAuZW52aXJvbi5nZXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJWMzIwX0RBSUxZX0JBUl9DVVRPRkZfRVQiLCAiMTA6MDAiKSBvciAiMTA6MDAiKQogICAgICAgICAgICAgICAgICAgIF9oLCBfbSA9IF92MzIwX2N1dG9mZi5zcGxpdCgiOiIpCiAgICAgICAgICAgICAgICAgICAgX2N1dG9mZl9taW4gPSBpbnQoX2gpICogNjAgKyBpbnQoX20pCiAgICAgICAgICAgICAgICAgICAgX25vd19ldCA9IGRhdGV0aW1lLm5vdyhfWklfdjMyMCgiQW1lcmljYS9OZXdfWW9yayIpKQogICAgICAgICAgICAgICAgICAgIF9ub3dfbWluID0gX25vd19ldC5ob3VyICogNjAgKyBfbm93X2V0Lm1pbnV0ZQogICAgICAgICAgICAgICAgICAgIGlmIF9ub3dfbWluIDwgX2N1dG9mZl9taW46CiAgICAgICAgICAgICAgICAgICAgICAgIF9zdHlsZXNfZW52ID0gX29zX3YzMjAuZW52aXJvbi5nZXQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAiVjMyMF9EQUlMWV9CQVJfU1RZTEVTIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICJtdWx0aV9kYXksc3dpbmcscG9zaXRpb24saW52ZXN0bWVudCIpCiAgICAgICAgICAgICAgICAgICAgICAgIF9zZXR1cHNfZW52ID0gX29zX3YzMjAuZW52aXJvbi5nZXQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAiVjMyMF9EQUlMWV9CQVJfU0VUVVBTIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICJkYWlseV9icmVha291dCxyc19sZWFkZXJfYnJlYWssIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgInN0YWdlXzJfYnJlYWtvdXQscG93ZXJfdHJlbmRfc3RhY2ssIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgInBvY2tldF9waXZvdCx0aHJlZV93ZWVrX3RpZ2h0LCIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICJhY2N1bXVsYXRpb25fZW50cnksZGFpbHlfc3F1ZWV6ZSIpCiAgICAgICAgICAgICAgICAgICAgICAgIF92MzIwX3N0eWxlcyA9IHtzLnN0cmlwKCkubG93ZXIoKSBmb3IgcyBpbiBfc3R5bGVzX2Vudi5zcGxpdCgiLCIpIGlmIHMuc3RyaXAoKX0KICAgICAgICAgICAgICAgICAgICAgICAgX3YzMjBfc2V0dXBzID0ge3Muc3RyaXAoKS5sb3dlcigpIGZvciBzIGluIF9zZXR1cHNfZW52LnNwbGl0KCIsIikgaWYgcy5zdHJpcCgpfQogICAgICAgICAgICAgICAgICAgICAgICBfYWxlcnRfc3R5bGUgPSAoYWxlcnQuZ2V0KCJ0cmFkZV9zdHlsZSIpIG9yICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICAgICAgX2FsZXJ0X3NldHVwID0gKHNldHVwX3R5cGUgb3IgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBfaGl0X3N0eWxlID0gX2FsZXJ0X3N0eWxlIGluIF92MzIwX3N0eWxlcwogICAgICAgICAgICAgICAgICAgICAgICBfaGl0X3NldHVwID0gX2FsZXJ0X3NldHVwIGluIF92MzIwX3NldHVwcwogICAgICAgICAgICAgICAgICAgICAgICBpZiBfaGl0X3N0eWxlIG9yIF9oaXRfc2V0dXA6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBfdjMyMF9wb2xpY3kgPT0gImJsb2NrIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGJvdC5yZWNvcmRfcmVqZWN0aW9uKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgc3ltYm9sPXN5bWJvbCwgc2V0dXBfdHlwZT1zZXR1cF90eXBlLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZGlyZWN0aW9uPWRpcmVjdGlvbl9zdHIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICByZWFzb25fY29kZT0idjMyMF9kYWlseV9iYXJfcHJlbWFya2V0X2dhdGUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgY29udGV4dD17CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgInBvbGljeSI6ICJ2MTkuMzQuMzIwX3ByZW1hcmtldF9nYXRlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiY3V0b2ZmX2V0IjogX3YzMjBfY3V0b2ZmLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJub3dfZXQiOiBfbm93X2V0LnN0cmZ0aW1lKCIlSDolTSIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJtYXRjaGVkX3N0eWxlIjogX2FsZXJ0X3N0eWxlIGlmIF9oaXRfc3R5bGUgZWxzZSBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJtYXRjaGVkX3NldHVwIjogX2FsZXJ0X3NldHVwIGlmIF9oaXRfc2V0dXAgZWxzZSBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgfSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBsb2dnZXIuaW5mbygKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlxVMDAwMWY2YWIgW3YxOS4zNC4zMjBdIGRhaWx5LWJhciBnYXRlIEJMT0NLICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIiVzLyVzIChzdHlsZT0lcywgc2V0dXA9JXMsIG5vdz0lcyBFVCwgY3V0b2ZmPSVzIEVUKSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHN5bWJvbCwgc2V0dXBfdHlwZSwgX2FsZXJ0X3N0eWxlIG9yICItIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2FsZXJ0X3NldHVwIG9yICItIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX25vd19ldC5zdHJmdGltZSgiJUg6JU0iKSwgX3YzMjBfY3V0b2ZmLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgZWxpZiBfdjMyMF9wb2xpY3kgPT0gIm9ic2VydmUiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGxvZ2dlci5pbmZvKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiXFUwMDAxZjQ0MVx1ZmUwZiBbdjE5LjM0LjMyMCBPQlNFUlZFXSBkYWlseS1iYXIgZ2F0ZSB3b3VsZCBCTE9DSyAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICIlcy8lcyAoc3R5bGU9JXMsIHNldHVwPSVzLCBub3c9JXMgRVQpIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgc3ltYm9sLCBzZXR1cF90eXBlLCBfYWxlcnRfc3R5bGUgb3IgIi0iLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfYWxlcnRfc2V0dXAgb3IgIi0iLCBfbm93X2V0LnN0cmZ0aW1lKCIlSDolTSIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBfdjMyMF9lcnI6CiAgICAgICAgICAgICAgICBsb2dnZXIuZGVidWcoInYzMjAgZGFpbHktYmFyIGdhdGUgdGhyZXcgKGFsbG93aW5nIHRocm91Z2gpOiAlcyIsIF92MzIwX2VycikKICAgICAgICAgICAgIyDilIDilIAgdjE5LjM0LjMyMCDigJQgRGFpbHktYmFyIHByZW1hcmtldCBnYXRlIOKUgOKUgCBFTkQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACgogICAgICAgICAgICAjIOKUgOKUgCB2MTkuMzQuMTczIOKAlCBTZXR1cC1ncmFkZSBGLWdhdGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACg=="

APPLIED_STAMP = "/tmp/v320_gate.applied"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _read_target() -> str:
    if not TARGET.exists():
        print(f"ERROR: target missing: {TARGET}")
        sys.exit(1)
    return TARGET.read_text(encoding="utf-8")


def _decode_chunks():
    return (base64.b64decode(OLD_B64).decode("utf-8"),
            base64.b64decode(NEW_B64).decode("utf-8"))


def cmd_check():
    body = _read_target()
    cur_sha = _sha(body)
    OLD, NEW = _decode_chunks()
    print(f"  target:     {TARGET}")
    print(f"  size:       {len(body):,} chars")
    print(f"  current sha:  {cur_sha}")
    print(f"  expected pre: {EXPECTED_PRE_SHA}")
    print(f"  expected post:{EXPECTED_POST_SHA}")
    print()

    if cur_sha == EXPECTED_POST_SHA:
        print("  ✅ ALREADY APPLIED — file matches POST hash. Nothing to do.")
        sys.exit(0)
    if cur_sha != EXPECTED_PRE_SHA:
        print("  ❌ PRE-HASH MISMATCH — DGX file has drifted from the tested baseline.")
        print("     Per AGENTS.md §2.2: upload your file and ask agent to rebase.")
        print(f"     curl -sS --data-binary @{TARGET} https://paste.rs/")
        sys.exit(2)
    cnt = body.count(OLD)
    if cnt != 1:
        print(f"  ❌ OLD chunk count != 1 (got {cnt}). Refusing to write.")
        sys.exit(3)
    projected = body.replace(OLD, NEW, 1)
    proj_sha = _sha(projected)
    if proj_sha != EXPECTED_POST_SHA:
        print(f"  ❌ PROJECTED POST-HASH MISMATCH: {proj_sha} vs {EXPECTED_POST_SHA}")
        print("     Refusing to write.")
        sys.exit(4)
    print(f"  ✓ pre-hash matches baseline")
    print(f"  ✓ OLD chunk found exactly 1x ({len(OLD)} chars)")
    print(f"  ✓ projected post-hash matches expected ({EXPECTED_POST_SHA[:16]}...)")
    print(f"  ✓ chunk insert is {len(NEW)-len(OLD):,} chars (gate code)")
    print()
    print("  re-run with --apply to write.")


def cmd_apply():
    body = _read_target()
    cur_sha = _sha(body)
    OLD, NEW = _decode_chunks()

    if cur_sha == EXPECTED_POST_SHA:
        print("  ALREADY APPLIED. No-op.")
        return
    if cur_sha != EXPECTED_PRE_SHA:
        print(f"  ABORT: pre-hash drift ({cur_sha[:16]}... vs expected "
              f"{EXPECTED_PRE_SHA[:16]}...).")
        sys.exit(2)
    if body.count(OLD) != 1:
        print(f"  ABORT: OLD chunk count != 1.")
        sys.exit(3)

    new_body = body.replace(OLD, NEW, 1)
    new_sha = _sha(new_body)
    if new_sha != EXPECTED_POST_SHA:
        print(f"  ABORT: post-hash mismatch ({new_sha[:16]}... vs expected "
              f"{EXPECTED_POST_SHA[:16]}...). NO WRITE.")
        sys.exit(4)

    # Backup, then atomic write
    bak = TARGET.with_suffix(
        TARGET.suffix + ".bak." +
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new_body, encoding="utf-8")

    # Verify on-disk hash
    on_disk = _sha(TARGET.read_text(encoding="utf-8"))
    if on_disk != EXPECTED_POST_SHA:
        # Restore from backup
        TARGET.unlink()
        bak.rename(TARGET)
        print(f"  ABORT: on-disk hash {on_disk[:16]}... mismatch after write.")
        print(f"  Restored from backup. No change applied.")
        sys.exit(5)

    Path(APPLIED_STAMP).write_text(
        f"pre_sha={EXPECTED_PRE_SHA}\n"
        f"post_sha={EXPECTED_POST_SHA}\n"
        f"applied_at={datetime.now(timezone.utc).isoformat()}\n"
        f"backup={bak}\n")
    print(f"  ✓ wrote {TARGET}")
    print(f"  ✓ post-hash verified: {on_disk[:16]}...")
    print(f"  ✓ backup at {bak.name}")
    print(f"  ✓ stamp at {APPLIED_STAMP}")
    print()
    print("  NEXT STEPS (per AGENTS.md §2.4):")
    print("    1) set policy (observe-mode for safe rollout):")
    print("       grep -q '^V320_DAILY_BAR_GATE_POLICY=' backend/.env || \\")
    print("         echo 'V320_DAILY_BAR_GATE_POLICY=observe' >> backend/.env")
    print("    2) restart backend (MUST use --force):")
    print("       ./start_backend.sh --force")
    print("    3) watch for gate fires:")
    print("       tail -f /tmp/backend.log | grep -E '(v19.34.320|OBSERVE)'")


def cmd_rollback():
    body = _read_target()
    cur_sha = _sha(body)
    OLD, NEW = _decode_chunks()
    if cur_sha == EXPECTED_PRE_SHA:
        print("  Not applied (file matches PRE hash). Nothing to roll back.")
        return
    if cur_sha != EXPECTED_POST_SHA:
        print(f"  ABORT: file hash {cur_sha[:16]}... matches neither PRE nor POST.")
        print(f"  Manual recovery needed.")
        sys.exit(2)
    if body.count(NEW) != 1:
        print(f"  ABORT: NEW chunk count != 1.")
        sys.exit(3)
    reverted = body.replace(NEW, OLD, 1)
    rev_sha = _sha(reverted)
    if rev_sha != EXPECTED_PRE_SHA:
        print(f"  ABORT: revert hash mismatch.")
        sys.exit(4)
    bak = TARGET.with_suffix(
        TARGET.suffix + ".bak_rollback." +
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(reverted, encoding="utf-8")
    try:
        os.remove(APPLIED_STAMP)
    except FileNotFoundError:
        pass
    print(f"  ✓ rolled back. Patched copy backed up at {bak.name}")
    print(f"  Run ./start_backend.sh --force to reload.")


def cmd_status():
    body = _read_target()
    cur_sha = _sha(body)
    print(f"  current sha:    {cur_sha}")
    print(f"  pre  baseline:  {EXPECTED_PRE_SHA}")
    print(f"  post baseline:  {EXPECTED_POST_SHA}")
    if cur_sha == EXPECTED_POST_SHA:
        print("  state: ✅ APPLIED")
    elif cur_sha == EXPECTED_PRE_SHA:
        print("  state: ⚪ NOT APPLIED (clean baseline)")
    else:
        print("  state: ⚠️  DRIFT (hash matches neither baseline)")
    if os.path.exists(APPLIED_STAMP):
        print(f"  stamp:\n{Path(APPLIED_STAMP).read_text()}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.check: cmd_check()
    elif args.apply: cmd_apply()
    elif args.rollback: cmd_rollback()
    elif args.status: cmd_status()


if __name__ == "__main__":
    main()
