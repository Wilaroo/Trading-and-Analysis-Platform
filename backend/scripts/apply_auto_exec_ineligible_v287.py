#!/usr/bin/env python3
"""
apply_auto_exec_ineligible_v287.py  (SentCom v19.34.287)

Idempotent applier — make the auto-execute INTAKE drop visible in symbol-trace.

WHAT IT DOES
  backend/services/enhanced_scanner.py
    - adds _auto_exec_fail_reasons() (static, pure) + _record_auto_exec_ineligible()
    - when a surfaced alert FAILS the auto-execute eligibility gate (priority<high
      / tape unconfirmed / win-rate<floor) AND auto-exec is enabled, records a
      `trade_drop` (gate=auto_exec_ineligible) with the precise reason + margins,
      deduped per (symbol,setup)/5min. Previously skipped silently (0 drops),
      which is why symbol-trace showed "NO gate-drop logged".
  backend/services/trade_drop_recorder.py
    - registers `auto_exec_ineligible` in KNOWN_GATES (no WARN spam).
  backend/tests/test_auto_exec_ineligible_v287.py : 8 unit tests.

SAFETY
  - Idempotent: no-op once 'v19.34.287' present.
  - Each hunk must match its DGX anchor exactly once or the file is skipped clean.
  - Timestamped .bak per file + py_compile w/ auto-restore.
  - Pure-additive observability: NO change to what actually trades.

USAGE
  python3 apply_auto_exec_ineligible_v287.py --dry-run --repo ~/Trading-and-Analysis-Platform
  python3 apply_auto_exec_ineligible_v287.py --repo ~/Trading-and-Analysis-Platform
"""
import argparse, base64, os, py_compile, shutil, sys, time
MARKER="v19.34.287"
_B64={
    "A_OLD": "ICAgIGFzeW5jIGRlZiBfYXV0b19leGVjdXRlX2FsZXJ0KHNlbGYsIGFsZXJ0OiBMaXZlQWxlcnQpOgo=",
    "A_NEW": "ICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBfYXV0b19leGVjX2ZhaWxfcmVhc29ucyhwcmlvcml0eV92YWx1ZSwgdGFwZV9jb25maXJtYXRpb24sIHdpbl9yYXRlLCBtaW5fd2luX3JhdGUpOgogICAgICAgICIiInYxOS4zNC4yODcg4oCUIHdoaWNoIGF1dG8tZXhlY3V0ZSBlbGlnaWJpbGl0eSBjb25kaXRpb25zIGFuIGFsZXJ0IEZBSUxFRC4KICAgICAgICBQdXJlICsgdW5pdC10ZXN0YWJsZTsgbWlycm9ycyB0aGUgZ2F0ZSBzdGFtcGVkIGluIF9zY2FuX3N5bWJvbF9hbGxfc2V0dXBzCiAgICAgICAgKHByaW9yaXR5IGluIHtjcml0aWNhbCxoaWdofSBBTkQgdGFwZV9jb25maXJtYXRpb24gQU5EIHdpbl9yYXRlID49IGZsb29yKS4iIiIKICAgICAgICBmYWlsZWQgPSBbXQogICAgICAgIGlmIHN0cihwcmlvcml0eV92YWx1ZSkubG93ZXIoKSBub3QgaW4gKCJjcml0aWNhbCIsICJoaWdoIik6CiAgICAgICAgICAgIGZhaWxlZC5hcHBlbmQoZiJwcmlvcml0eT17cHJpb3JpdHlfdmFsdWV9PGhpZ2giKQogICAgICAgIGlmIG5vdCB0YXBlX2NvbmZpcm1hdGlvbjoKICAgICAgICAgICAgZmFpbGVkLmFwcGVuZCgidGFwZV91bmNvbmZpcm1lZCIpCiAgICAgICAgZGVmIF9udW0odik6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJldHVybiBmbG9hdCh2KQogICAgICAgICAgICBleGNlcHQgKFR5cGVFcnJvciwgVmFsdWVFcnJvcik6CiAgICAgICAgICAgICAgICByZXR1cm4gMC4wCiAgICAgICAgd3IsIG1uID0gX251bSh3aW5fcmF0ZSksIF9udW0obWluX3dpbl9yYXRlKQogICAgICAgIGlmIHdyIDwgbW46CiAgICAgICAgICAgIGZhaWxlZC5hcHBlbmQoZiJ3aW4tcmF0ZSB7d3IgKiAxMDA6LjBmfSU8e21uICogMTAwOi4wZn0lIikKICAgICAgICByZXR1cm4gZmFpbGVkCgogICAgZGVmIF9yZWNvcmRfYXV0b19leGVjX2luZWxpZ2libGUoc2VsZiwgYWxlcnQpOgogICAgICAgICIiInYxOS4zNC4yODcg4oCUIGludGFrZSB2aXNpYmlsaXR5OiByZWNvcmQgV0hZIGEgc3VyZmFjZWQgYWxlcnQgZmFpbGVkIHRoZQogICAgICAgIGF1dG8tZXhlY3V0ZSBlbGlnaWJpbGl0eSBnYXRlLCBzbyBzeW1ib2wtdHJhY2UncyBnYXRlIGZ1bm5lbCBzdG9wcyBzaG93aW5nCiAgICAgICAgJ05PIGdhdGUtZHJvcCBsb2dnZWQnIGZvciBhbGVydHMgdGhhdCBuZXZlciBhdXRvLXRyYWRlLiBEZWR1cGVkIHBlcgogICAgICAgIChzeW1ib2wsIHNldHVwKSAvIDUgbWluIHNvIGl0IGNhbid0IGZsb29kIGB0cmFkZV9kcm9wc2AuIE5ldmVyIHJhaXNlcy4iIiIKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydCB0aW1lIGFzIF90CiAgICAgICAgICAgIHNlZW4gPSBnZXRhdHRyKHNlbGYsICJfYXV0b19leGVjX2Ryb3Bfc2VlbiIsIE5vbmUpCiAgICAgICAgICAgIGlmIHNlZW4gaXMgTm9uZToKICAgICAgICAgICAgICAgIHNlZW4gPSBzZWxmLl9hdXRvX2V4ZWNfZHJvcF9zZWVuID0ge30KICAgICAgICAgICAga2V5ID0gKGdldGF0dHIoYWxlcnQsICJzeW1ib2wiLCAiPyIpLCBnZXRhdHRyKGFsZXJ0LCAic2V0dXBfdHlwZSIsICI/IikpCiAgICAgICAgICAgIG5vd190ID0gX3QudGltZSgpCiAgICAgICAgICAgIGlmIG5vd190IC0gc2Vlbi5nZXQoa2V5LCAwLjApIDwgMzAwOgogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgIHNlZW5ba2V5XSA9IG5vd190CiAgICAgICAgICAgIHByID0gYWxlcnQucHJpb3JpdHkudmFsdWUgaWYgZ2V0YXR0cihhbGVydCwgInByaW9yaXR5IiwgTm9uZSkgZWxzZSAiPyIKICAgICAgICAgICAgd3IgPSBmbG9hdChnZXRhdHRyKGFsZXJ0LCAic3RyYXRlZ3lfd2luX3JhdGUiLCAwLjApIG9yIDAuMCkKICAgICAgICAgICAgbW4gPSBmbG9hdChzZWxmLl9hdXRvX2V4ZWN1dGVfbWluX3dpbl9yYXRlKQogICAgICAgICAgICB0YXBlX29rID0gYm9vbChnZXRhdHRyKGFsZXJ0LCAidGFwZV9jb25maXJtYXRpb24iLCBGYWxzZSkpCiAgICAgICAgICAgIGZhaWxlZCA9IHNlbGYuX2F1dG9fZXhlY19mYWlsX3JlYXNvbnMocHIsIHRhcGVfb2ssIHdyLCBtbikKICAgICAgICAgICAgZnJvbSBzZXJ2aWNlcy50cmFkZV9kcm9wX3JlY29yZGVyIGltcG9ydCByZWNvcmRfdHJhZGVfZHJvcAogICAgICAgICAgICByZWNvcmRfdHJhZGVfZHJvcCgKICAgICAgICAgICAgICAgIGdldGF0dHIoc2VsZiwgImRiIiwgTm9uZSksCiAgICAgICAgICAgICAgICBnYXRlPSJhdXRvX2V4ZWNfaW5lbGlnaWJsZSIsCiAgICAgICAgICAgICAgICBzeW1ib2w9Z2V0YXR0cihhbGVydCwgInN5bWJvbCIsIE5vbmUpLAogICAgICAgICAgICAgICAgc2V0dXBfdHlwZT1nZXRhdHRyKGFsZXJ0LCAic2V0dXBfdHlwZSIsIE5vbmUpLAogICAgICAgICAgICAgICAgZGlyZWN0aW9uPWdldGF0dHIoYWxlcnQsICJkaXJlY3Rpb24iLCAibG9uZyIpIG9yICJsb25nIiwKICAgICAgICAgICAgICAgIHJlYXNvbj0iYXV0by1leGVjIGluZWxpZ2libGU6ICIgKyAoIiwgIi5qb2luKGZhaWxlZCkgb3IgInVua25vd24iKSwKICAgICAgICAgICAgICAgIGNvbnRleHQ9eyJwcmlvcml0eSI6IHByLCAidGFwZV9jb25maXJtYXRpb24iOiB0YXBlX29rLAogICAgICAgICAgICAgICAgICAgICAgICAgIndpbl9yYXRlIjogd3IsICJtaW5fd2luX3JhdGUiOiBtbiwgImZhaWxlZCI6IGZhaWxlZH0sCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgYXN5bmMgZGVmIF9hdXRvX2V4ZWN1dGVfYWxlcnQoc2VsZiwgYWxlcnQ6IExpdmVBbGVydCk6Cg==",
    "B_OLD": "ICAgICAgICAgICAgICAgICMgQXV0by1leGVjdXRlIGlmIGVsaWdpYmxlCiAgICAgICAgICAgICAgICBpZiBhbGVydC5hdXRvX2V4ZWN1dGVfZWxpZ2libGU6CiAgICAgICAgICAgICAgICAgICAgYXdhaXQgc2VsZi5fYXV0b19leGVjdXRlX2FsZXJ0KGFsZXJ0KQo=",
    "B_NEW": "ICAgICAgICAgICAgICAgICMgQXV0by1leGVjdXRlIGlmIGVsaWdpYmxlCiAgICAgICAgICAgICAgICBpZiBhbGVydC5hdXRvX2V4ZWN1dGVfZWxpZ2libGU6CiAgICAgICAgICAgICAgICAgICAgYXdhaXQgc2VsZi5fYXV0b19leGVjdXRlX2FsZXJ0KGFsZXJ0KQogICAgICAgICAgICAgICAgIyB2MTkuMzQuMjg3IOKAlCByZWNvcmQgV0hZIGFuIG90aGVyd2lzZS1zdXJmYWNlZCBhbGVydCB3b24ndAogICAgICAgICAgICAgICAgIyBhdXRvLXRyYWRlIChpbnRha2UgdmlzaWJpbGl0eSBmb3Igc3ltYm9sLXRyYWNlJ3MgZ2F0ZSBmdW5uZWwpLgogICAgICAgICAgICAgICAgZWxpZiBzZWxmLl9hdXRvX2V4ZWN1dGVfZW5hYmxlZDoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRfYXV0b19leGVjX2luZWxpZ2libGUoYWxlcnQpCg==",
    "C_OLD": "ICAgICJzY2FubmVyX3BhdXNlZCIsICAgICAgICAgICAjIHNjYW5uZXIgZ2xvYmFsbHkgcGF1c2VkIHZpYSBndWFyZHJhaWxzCn0=",
    "C_NEW": "ICAgICJzY2FubmVyX3BhdXNlZCIsICAgICAgICAgICAjIHNjYW5uZXIgZ2xvYmFsbHkgcGF1c2VkIHZpYSBndWFyZHJhaWxzCiAgICAiYXV0b19leGVjX2luZWxpZ2libGUiLCAgICAgIyB2MTkuMzQuMjg3IHNjYW5uZXIgYXV0by1leGVjdXRlIGVsaWdpYmlsaXR5IGdhdGUgKHByaW9yaXR5L3RhcGUvd2luLXJhdGUpCn0=",
    "TEST": "IiIiCnRlc3RfYXV0b19leGVjX2luZWxpZ2libGVfdjI4Ny5weSDigJQgZ3VhcmRzIHRoZSBhdXRvLWV4ZWMgZWxpZ2liaWxpdHkgaW50YWtlIHRyYWNlLgoKQWxlcnRzIHRoYXQgc3VyZmFjZSBidXQgZmFpbCB0aGUgc2Nhbm5lcidzIGF1dG8tZXhlY3V0ZSBnYXRlIChwcmlvcml0eTxoaWdoIC8KdGFwZSB1bmNvbmZpcm1lZCAvIHdpbi1yYXRlPGZsb29yKSB3ZXJlIHNpbGVudGx5IHNraXBwZWQgKDAgdHJhZGVfZHJvcHMpLCBzbwpzeW1ib2wtdHJhY2Ugc2hvd2VkICJOTyBnYXRlLWRyb3AgbG9nZ2VkIi4gVGhpcyB0ZXN0cyB0aGUgcHVyZSByZWFzb24tZGVjb2Rlcgp0aGF0IG5vdyBmZWVkcyB0aGUgcmVjb3JkZWQgYGF1dG9fZXhlY19pbmVsaWdpYmxlYCBkcm9wLgoiIiIKaW1wb3J0IG9zCmltcG9ydCBzeXMKCnN5cy5wYXRoLmluc2VydCgwLCBvcy5wYXRoLmRpcm5hbWUob3MucGF0aC5kaXJuYW1lKG9zLnBhdGguYWJzcGF0aChfX2ZpbGVfXykpKSkKCmZyb20gc2VydmljZXMuZW5oYW5jZWRfc2Nhbm5lciBpbXBvcnQgRW5oYW5jZWRCYWNrZ3JvdW5kU2Nhbm5lciAgIyBub3FhOiBFNDAyCgpyZWFzb25zID0gRW5oYW5jZWRCYWNrZ3JvdW5kU2Nhbm5lci5fYXV0b19leGVjX2ZhaWxfcmVhc29ucwoKCmNsYXNzIFRlc3RGYWlsUmVhc29uczoKICAgIGRlZiB0ZXN0X2FsbF9wYXNzX3JldHVybnNfZW1wdHkoc2VsZik6CiAgICAgICAgYXNzZXJ0IHJlYXNvbnMoImhpZ2giLCBUcnVlLCAwLjYwLCAwLjU1KSA9PSBbXQogICAgICAgIGFzc2VydCByZWFzb25zKCJjcml0aWNhbCIsIFRydWUsIDAuNTUsIDAuNTUpID09IFtdCgogICAgZGVmIHRlc3RfcHJpb3JpdHlfdG9vX2xvdyhzZWxmKToKICAgICAgICByID0gcmVhc29ucygibWVkaXVtIiwgVHJ1ZSwgMC42MCwgMC41NSkKICAgICAgICBhc3NlcnQgciA9PSBbInByaW9yaXR5PW1lZGl1bTxoaWdoIl0KCiAgICBkZWYgdGVzdF90YXBlX3VuY29uZmlybWVkKHNlbGYpOgogICAgICAgIHIgPSByZWFzb25zKCJoaWdoIiwgRmFsc2UsIDAuNjAsIDAuNTUpCiAgICAgICAgYXNzZXJ0IHIgPT0gWyJ0YXBlX3VuY29uZmlybWVkIl0KCiAgICBkZWYgdGVzdF93aW5fcmF0ZV9iZWxvd19mbG9vcihzZWxmKToKICAgICAgICByID0gcmVhc29ucygiaGlnaCIsIFRydWUsIDAuNTAsIDAuNTUpCiAgICAgICAgYXNzZXJ0IHIgPT0gWyJ3aW4tcmF0ZSA1MCU8NTUlIl0KCiAgICBkZWYgdGVzdF9tdWx0aXBsZV9mYWlsdXJlc19vcmRlcmVkKHNlbGYpOgogICAgICAgIHIgPSByZWFzb25zKCJtZWRpdW0iLCBGYWxzZSwgMC40MCwgMC41NSkKICAgICAgICBhc3NlcnQgciA9PSBbInByaW9yaXR5PW1lZGl1bTxoaWdoIiwgInRhcGVfdW5jb25maXJtZWQiLCAid2luLXJhdGUgNDAlPDU1JSJdCgogICAgZGVmIHRlc3RfY3JpdGljYWxfcHJpb3JpdHlfcGFzc2VzX3ByaW9yaXR5X2NoZWNrKHNlbGYpOgogICAgICAgIGFzc2VydCAicHJpb3JpdHkiIG5vdCBpbiAiICIuam9pbihyZWFzb25zKCJjcml0aWNhbCIsIFRydWUsIDAuNjAsIDAuNTUpKQoKICAgIGRlZiB0ZXN0X2JhZF93aW5yYXRlX3ZhbHVlc19kb250X3JhaXNlKHNlbGYpOgogICAgICAgICMgTm9uZS9nYXJiYWdlIHdpbl9yYXRlIG11c3Qgbm90IHRocm93OyB0cmVhdGVkIGFzIDAg4oaSIGJlbG93IGFueSBmbG9vcgogICAgICAgIGFzc2VydCAid2luLXJhdGUiIGluICIgIi5qb2luKHJlYXNvbnMoImhpZ2giLCBUcnVlLCBOb25lLCAwLjU1KSkKICAgICAgICBhc3NlcnQgcmVhc29ucygiaGlnaCIsIFRydWUsICJ4IiwgMC41NSkgPT0gWyJ3aW4tcmF0ZSAwJTw1NSUiXQoKICAgIGRlZiB0ZXN0X3ByaW9yaXR5X2Nhc2VfaW5zZW5zaXRpdmUoc2VsZik6CiAgICAgICAgYXNzZXJ0IHJlYXNvbnMoIkhJR0giLCBUcnVlLCAwLjYwLCAwLjU1KSA9PSBbXQo=",
}
def _d(k): return base64.b64decode(_B64[k]).decode("utf-8")
def log(m): print(f"[v287-applier] {m}", flush=True)

ESCAN_HUNKS=[("A (recorder methods)",_d("A_OLD"),_d("A_NEW")),
             ("B (elif intake record)",_d("B_OLD"),_d("B_NEW"))]
DROPS_HUNKS=[("C (KNOWN_GATES)",_d("C_OLD"),_d("C_NEW"))]

def find_repo(x):
    if x: return x
    here=os.path.abspath(os.path.dirname(__file__))
    for b in (here,os.getcwd(),os.path.expanduser("~/Trading-and-Analysis-Platform")):
        c=b
        for _ in range(6):
            if os.path.isfile(os.path.join(c,"backend","services","enhanced_scanner.py")): return c
            p=os.path.dirname(c)
            if p==c: break
            c=p
    return None

def patch(path, hunks, dry):
    with open(path,encoding="utf-8") as fh: content=fh.read()
    if MARKER in content:
        log(f"already patched: {os.path.basename(path)}"); return True
    for n,o,_nw in hunks:
        cnt=content.count(o)
        if cnt!=1:
            log(f"ERROR: {os.path.basename(path)} hunk {n} matched {cnt} (expected 1). Aborting file."); return False
    for n,o,nw in hunks: content=content.replace(o,nw,1)
    if dry:
        log(f"DRY-RUN ok: {os.path.basename(path)} ({len(hunks)} hunk(s) match)"); return True
    bak=f"{path}.bak.v287.{time.strftime('%Y%m%d-%H%M%S')}"; shutil.copy2(path,bak); log(f"backup: {bak}")
    with open(path,"w",encoding="utf-8") as fh: fh.write(content)
    try: py_compile.compile(path,doraise=True); log(f"py_compile OK: {os.path.basename(path)}")
    except py_compile.PyCompileError as e:
        log(f"ERROR py_compile {os.path.basename(path)}: {e}; restoring"); shutil.copy2(bak,path); return False
    return True

def main():
    a=argparse.ArgumentParser(); a.add_argument("--repo",default=None); a.add_argument("--dry-run",action="store_true")
    args=a.parse_args()
    repo=find_repo(args.repo)
    if not repo: log("ERROR: repo root not found. Pass --repo."); return 2
    log(f"repo: {repo}")
    escan=os.path.join(repo,"backend","services","enhanced_scanner.py")
    drops=os.path.join(repo,"backend","services","trade_drop_recorder.py")
    test=os.path.join(repo,"backend","tests","test_auto_exec_ineligible_v287.py")
    if not patch(escan,ESCAN_HUNKS,args.dry_run): return 3
    if not patch(drops,DROPS_HUNKS,args.dry_run): return 4
    if args.dry_run:
        log("DRY-RUN: all hunks match + test would be written. Nothing changed."); return 0
    os.makedirs(os.path.dirname(test),exist_ok=True)
    with open(test,"w",encoding="utf-8") as fh: fh.write(_d("TEST"))
    try: py_compile.compile(test,doraise=True); log(f"wrote + compiled: {test}")
    except py_compile.PyCompileError as e: log(f"ERROR test py_compile: {e}"); return 5
    log("SUCCESS - v19.34.287 auto-exec intake trace applied.")
    log("Tests:  .venv/bin/python -m pytest backend/tests/test_auto_exec_ineligible_v287.py -q")
    log("Then ./start_backend.sh --force and re-probe: probe_symbol_day.py NVDA")
    return 0
if __name__=="__main__": sys.exit(main())
