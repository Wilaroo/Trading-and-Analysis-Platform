#!/usr/bin/env python3
"""
patch_a4_ev_proxy_verdict.py  —  v19.34.286 (UI Track A · A4)
"Honest EV verdict — 'Est. (R:R)' instead of 'No data' for the R:R proxy"

The Setup pillar's Expected-Value sub-score falls back to an R:R-derived PROXY
when a setup lacks a >=5-sample realized EV (diag A4/A4b proved this gap is
genuine, not a plumbing bug). That proxy was mislabeled with the descriptor
verdict "No data", so /api/tqs/coverage reported it as missing data. This patch
gives the proxy the distinct verdict "Est. (R:R)" and reports it as a 3rd
coverage state. NO scoring math changes: real_pct / coverage_pct are identical;
the "No data" bucket simply splits into proxy + truly-absent.

4 files, anchored (old->new) chunks, each whole-file PRE/POST SHA256-guarded.
Two-pass: validates ALL files first and ABORTS on ANY drift before writing
anything (no partial apply). Per-file .a4bak backups.
2 backend files hot-reload; the frontend file REQUIRES `cd frontend && yarn build`.

USAGE (repo root):
  .venv/bin/python scripts/patch_a4_ev_proxy_verdict.py --check
  .venv/bin/python scripts/patch_a4_ev_proxy_verdict.py
  cd frontend && yarn build && cd ..
  ./start_backend.sh --force
  git add backend/ frontend/ scripts/ memory/ && git commit -m "v19.34.286 (A4): honest EV 'Est. (R:R)' verdict" && git push origin main
Rollback: restore the four *.a4bak files (+ rebuild frontend).
"""
import base64
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
FILES = [
    {'path': 'backend/services/tqs/descriptors.py', 'pre': '365fb732b8afde85a2af9891955281b7e31a28257e3a7077b5a164d4781aa09b', 'post': 'b9308d46f4e252e18885678a60b0fa02a175e11fff9e9af03c742b34759a54a9', 'chunks': [{'old': 'ZGVmIHZlcmRpY3RfZm9yKHNjb3JlOiBPcHRpb25hbFtmbG9hdF0sIGFic2VudDogYm9vbCA9IEZhbHNlKSAtPiBzdHI6CiAgICAiIiJTY29yZSBiYW5kIOKGkiBwbGFpbiB2ZXJkaWN0LiBgYWJzZW50PVRydWVgIG92ZXJyaWRlcyB0byAnTm8gZGF0YScuIiIiCiAgICBpZiBhYnNlbnQ6CiAgICAgICAgcmV0dXJuICJObyBkYXRhIgo=', 'new': 'ZGVmIHZlcmRpY3RfZm9yKHNjb3JlOiBPcHRpb25hbFtmbG9hdF0sIGFic2VudDogYm9vbCA9IEZhbHNlLCBwcm94eTogYm9vbCA9IEZhbHNlKSAtPiBzdHI6CiAgICAiIiJTY29yZSBiYW5kIOKGkiBwbGFpbiB2ZXJkaWN0LiBgYWJzZW50PVRydWVgIG92ZXJyaWRlcyB0byAnTm8gZGF0YSc7CiAgICBgcHJveHk9VHJ1ZWAgbWFya3MgYSBkYXRhLWRlcml2ZWQgZXN0aW1hdGUgKGUuZy4gRVYgZnJvbSBSOlIpIGFzICdFc3QuIChSOlIpJy4iIiIKICAgIGlmIGFic2VudDoKICAgICAgICByZXR1cm4gIk5vIGRhdGEiCiAgICBpZiBwcm94eToKICAgICAgICByZXR1cm4gIkVzdC4gKFI6UikiCg=='}, {'old': 'ZGVmIGRpc3AobGFiZWw6IHN0ciwgc2NvcmU6IE9wdGlvbmFsW2Zsb2F0XSwgcmVhZGluZzogc3RyLAogICAgICAgICBhYnNlbnQ6IGJvb2wgPSBGYWxzZSkgLT4gRGljdFtzdHIsIHN0cl06CiAgICAiIiJCdWlsZCBvbmUgc3ViLXNjb3JlIGRpc3BsYXkgYmxvY2suIiIiCiAgICByZXR1cm4gewogICAgICAgICJsYWJlbCI6IGxhYmVsLAogICAgICAgICJ2ZXJkaWN0IjogdmVyZGljdF9mb3Ioc2NvcmUsIGFic2VudCksCiAgICAgICAgInJlYWRpbmciOiByZWFkaW5nLAogICAgfQo=', 'new': 'ZGVmIGRpc3AobGFiZWw6IHN0ciwgc2NvcmU6IE9wdGlvbmFsW2Zsb2F0XSwgcmVhZGluZzogc3RyLAogICAgICAgICBhYnNlbnQ6IGJvb2wgPSBGYWxzZSwgcHJveHk6IGJvb2wgPSBGYWxzZSkgLT4gRGljdFtzdHIsIHN0cl06CiAgICAiIiJCdWlsZCBvbmUgc3ViLXNjb3JlIGRpc3BsYXkgYmxvY2suIiIiCiAgICByZXR1cm4gewogICAgICAgICJsYWJlbCI6IGxhYmVsLAogICAgICAgICJ2ZXJkaWN0IjogdmVyZGljdF9mb3Ioc2NvcmUsIGFic2VudCwgcHJveHkpLAogICAgICAgICJyZWFkaW5nIjogcmVhZGluZywKICAgIH0K'}]},
    {'path': 'backend/services/tqs/setup_quality.py', 'pre': 'dfc16585849894bff667e219c54c77e922a34662ea2a919db8ae53ba7cf43cbe', 'post': '9026c9ac1757666afd097a14c6b857b37fa86547a41d030892fd1c1507611c06', 'chunks': [{'old': 'ICAgICAgICAgICAgImV4cGVjdGVkX3ZhbHVlIjogZGlzcCgiRXhwZWN0ZWQgVmFsdWUiLCBzZWxmLmV2X3Njb3JlLCBldl9yZWFkLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGFic2VudD1jLmdldCgiZXZfaXNfcHJveHkiKSksCg==', 'new': 'ICAgICAgICAgICAgImV4cGVjdGVkX3ZhbHVlIjogZGlzcCgiRXhwZWN0ZWQgVmFsdWUiLCBzZWxmLmV2X3Njb3JlLCBldl9yZWFkLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHByb3h5PWMuZ2V0KCJldl9pc19wcm94eSIpKSwK'}]},
    {'path': 'backend/routers/data_diagnostics.py', 'pre': 'bee27de64fd7230ec2932d64e6dbfcbc3a4487fb4a9c346c61ed3bf233d6db2e', 'post': 'df383f6eaa2eca50210ef9269731cfdb658a8c632e509360cd71f13e09d8e4e9', 'chunks': [{'old': 'Tk9fREFUQSA9ICJObyBkYXRhIgpQSUxMQVJTID0gWyJzZXR1cCIsICJ0ZWNobmljYWwiLCAiZnVuZGFtZW50YWwiLCAiY29udGV4dCIsICJleGVjdXRpb24iXQo=', 'new': 'Tk9fREFUQSA9ICJObyBkYXRhIgpQUk9YWSA9ICJFc3QuIChSOlIpIgpQSUxMQVJTID0gWyJzZXR1cCIsICJ0ZWNobmljYWwiLCAiZnVuZGFtZW50YWwiLCAiY29udGV4dCIsICJleGVjdXRpb24iXQo='}, {'old': 'ICAgIGNvbXAgPSBkZWZhdWx0ZGljdChsYW1iZGE6IGRlZmF1bHRkaWN0KGxhbWJkYTogeyJsYWJlbCI6ICIiLCAidG90YWwiOiAwLCAibm9fZGF0YSI6IDB9KSkKICAgIHBpbGxhcl90b3QgPSBkZWZhdWx0ZGljdChsYW1iZGE6IHsidCI6IDAsICJuZCI6IDB9KQo=', 'new': 'ICAgIGNvbXAgPSBkZWZhdWx0ZGljdChsYW1iZGE6IGRlZmF1bHRkaWN0KGxhbWJkYTogeyJsYWJlbCI6ICIiLCAidG90YWwiOiAwLCAibm9fZGF0YSI6IDAsICJwcm94eSI6IDB9KSkKICAgIHBpbGxhcl90b3QgPSBkZWZhdWx0ZGljdChsYW1iZGE6IHsidCI6IDAsICJuZCI6IDAsICJweCI6IDB9KQo='}, {'old': 'ICAgICAgICAgICAgICAgIG5kID0gKGJsay5nZXQoInZlcmRpY3QiKSA9PSBOT19EQVRBKQogICAgICAgICAgICAgICAgcmVjWyJub19kYXRhIl0gKz0gMSBpZiBuZCBlbHNlIDAKICAgICAgICAgICAgICAgIHBpbGxhcl90b3RbcF1bInQiXSArPSAxCiAgICAgICAgICAgICAgICBwaWxsYXJfdG90W3BdWyJuZCJdICs9IDEgaWYgbmQgZWxzZSAwCg==', 'new': 'ICAgICAgICAgICAgICAgIG5kID0gKGJsay5nZXQoInZlcmRpY3QiKSA9PSBOT19EQVRBKQogICAgICAgICAgICAgICAgcHggPSAoYmxrLmdldCgidmVyZGljdCIpID09IFBST1hZKQogICAgICAgICAgICAgICAgcmVjWyJub19kYXRhIl0gKz0gMSBpZiBuZCBlbHNlIDAKICAgICAgICAgICAgICAgIHJlY1sicHJveHkiXSArPSAxIGlmIHB4IGVsc2UgMAogICAgICAgICAgICAgICAgcGlsbGFyX3RvdFtwXVsidCJdICs9IDEKICAgICAgICAgICAgICAgIHBpbGxhcl90b3RbcF1bIm5kIl0gKz0gMSBpZiBuZCBlbHNlIDAKICAgICAgICAgICAgICAgIHBpbGxhcl90b3RbcF1bInB4Il0gKz0gMSBpZiBweCBlbHNlIDAK'}, {'old': 'ICAgIHBpbGxhcnMgPSBbXQogICAgZ190ID0gZ19uZCA9IDAKICAgIGZvciBwIGluIFBJTExBUlM6Cg==', 'new': 'ICAgIHBpbGxhcnMgPSBbXQogICAgZ190ID0gZ19uZCA9IGdfcHggPSAwCiAgICBmb3IgcCBpbiBQSUxMQVJTOgo='}, {'old': 'ICAgICAgICBwdCA9IHBpbGxhcl90b3RbcF0KICAgICAgICBnX3QgKz0gcHRbInQiXQogICAgICAgIGdfbmQgKz0gcHRbIm5kIl0K', 'new': 'ICAgICAgICBwdCA9IHBpbGxhcl90b3RbcF0KICAgICAgICBnX3QgKz0gcHRbInQiXQogICAgICAgIGdfbmQgKz0gcHRbIm5kIl0KICAgICAgICBnX3B4ICs9IHB0WyJweCJdCg=='}, {'old': 'ICAgICAgICAgICAgICAgICJyZWFsX3BjdCI6IHJvdW5kKDEwMC4wICogKHRvdCAtIHJlY1sibm9fZGF0YSJdKSAvIHRvdCwgMSkgaWYgdG90IGVsc2UgMCwKICAgICAgICAgICAgICAgICJub19kYXRhX3BjdCI6IHJvdW5kKDEwMC4wICogcmVjWyJub19kYXRhIl0gLyB0b3QsIDEpIGlmIHRvdCBlbHNlIDAsCiAgICAgICAgICAgIH0pCg==', 'new': 'ICAgICAgICAgICAgICAgICJyZWFsX3BjdCI6IHJvdW5kKDEwMC4wICogKHRvdCAtIHJlY1sibm9fZGF0YSJdIC0gcmVjWyJwcm94eSJdKSAvIHRvdCwgMSkgaWYgdG90IGVsc2UgMCwKICAgICAgICAgICAgICAgICJwcm94eV9wY3QiOiByb3VuZCgxMDAuMCAqIHJlY1sicHJveHkiXSAvIHRvdCwgMSkgaWYgdG90IGVsc2UgMCwKICAgICAgICAgICAgICAgICJub19kYXRhX3BjdCI6IHJvdW5kKDEwMC4wICogcmVjWyJub19kYXRhIl0gLyB0b3QsIDEpIGlmIHRvdCBlbHNlIDAsCiAgICAgICAgICAgIH0pCg=='}, {'old': 'ICAgICAgICAgICAgImNvdmVyYWdlX3BjdCI6IHJvdW5kKDEwMC4wICogKDEgLSBwdFsibmQiXSAvIHB0WyJ0Il0pLCAxKSBpZiBwdFsidCJdIGVsc2UgMCwKICAgICAgICAgICAgImNvbXBvbmVudHMiOiBjb21wb25lbnRzLAo=', 'new': 'ICAgICAgICAgICAgImNvdmVyYWdlX3BjdCI6IHJvdW5kKDEwMC4wICogKDEgLSAocHRbIm5kIl0gKyBwdFsicHgiXSkgLyBwdFsidCJdKSwgMSkgaWYgcHRbInQiXSBlbHNlIDAsCiAgICAgICAgICAgICJwcm94eV9wY3QiOiByb3VuZCgxMDAuMCAqIHB0WyJweCJdIC8gcHRbInQiXSwgMSkgaWYgcHRbInQiXSBlbHNlIDAsCiAgICAgICAgICAgICJjb21wb25lbnRzIjogY29tcG9uZW50cywK'}, {'old': 'ICAgICAgICAib3ZlcmFsbF9jb3ZlcmFnZV9wY3QiOiByb3VuZCgxMDAuMCAqICgxIC0gZ19uZCAvIGdfdCksIDEpIGlmIGdfdCBlbHNlIDAsCiAgICAgICAgInJlYWxfc3Vic2NvcmVzIjogZ190IC0gZ19uZCwKICAgICAgICAidG90YWxfc3Vic2NvcmVzIjogZ190LAo=', 'new': 'ICAgICAgICAib3ZlcmFsbF9jb3ZlcmFnZV9wY3QiOiByb3VuZCgxMDAuMCAqICgxIC0gKGdfbmQgKyBnX3B4KSAvIGdfdCksIDEpIGlmIGdfdCBlbHNlIDAsCiAgICAgICAgInJlYWxfc3Vic2NvcmVzIjogZ190IC0gZ19uZCAtIGdfcHgsCiAgICAgICAgInByb3h5X3N1YnNjb3JlcyI6IGdfcHgsCiAgICAgICAgInRvdGFsX3N1YnNjb3JlcyI6IGdfdCwK'}]},
    {'path': 'frontend/src/components/sentcom/v5/TqsCoveragePanel.jsx', 'pre': '066f7d7a312bd87c1604ecc376f254f1ba34403f6a4b162f6eb429fad7bff98d', 'post': '574f23cc467eccd40ac92c383ebc458b4651be62333ff6f039c558b9208053cc', 'chunks': [{'old': 'ICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0idGV4dC1bMTNweF0gdGV4dC16aW5jLTUwMCI+cmVhbCB2cyAiTm8gZGF0YSIgZGVmYXVsdDwvc3Bhbj4K', 'new': 'ICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0idGV4dC1bMTNweF0gdGV4dC16aW5jLTUwMCI+cmVhbCDCtyBlc3QgKFI6Uikgwrcgbm8tZGF0YTwvc3Bhbj4K'}, {'old': 'ICAgICAgICAgICAgICB7ZGF0YS5yZWFsX3N1YnNjb3Jlc30ve2RhdGEudG90YWxfc3Vic2NvcmVzfSBzdWItc2NvcmVzIHJlYWwgwrd7JyAnfQogICAgICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0idGV4dC16aW5jLTQwMCI+e2RhdGEud2l0aF9kaXNwbGF5fTwvc3Bhbj4gYWxlcnRzIHcvIGRlc2NyaXB0b3JzIMK3eycgJ30K', 'new': 'ICAgICAgICAgICAgICB7ZGF0YS5yZWFsX3N1YnNjb3Jlc30ve2RhdGEudG90YWxfc3Vic2NvcmVzfSBzdWItc2NvcmVzIHJlYWwgwrd7JyAnfQogICAgICAgICAgICAgIHtkYXRhLnByb3h5X3N1YnNjb3JlcyA/ICg8PjxzcGFuIGNsYXNzTmFtZT0idGV4dC1za3ktNDAwIj57ZGF0YS5wcm94eV9zdWJzY29yZXN9IGVzdDwvc3Bhbj4gwrd7JyAnfTwvPikgOiBudWxsfQogICAgICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0idGV4dC16aW5jLTQwMCI+e2RhdGEud2l0aF9kaXNwbGF5fTwvc3Bhbj4gYWxlcnRzIHcvIGRlc2NyaXB0b3JzIMK3eycgJ30K'}, {'old': 'ICAgICAgICAgICAgICAgICAgICAgIHtjLm5vX2RhdGFfcGN0ID4gMCAmJiAoCiAgICAgICAgICAgICAgICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0idjUtbW9ubyB0ZXh0LXppbmMtNTAwIj57Yy5ub19kYXRhX3BjdH0lIG5vLWRhdGE8L3NwYW4+CiAgICAgICAgICAgICAgICAgICAgICApfQo=', 'new': 'ICAgICAgICAgICAgICAgICAgICAgIHtjLnByb3h5X3BjdCA+IDAgJiYgKAogICAgICAgICAgICAgICAgICAgICAgICA8c3BhbiBjbGFzc05hbWU9InY1LW1vbm8gdGV4dC1za3ktNDAwIiB0aXRsZT0iRXN0aW1hdGVkIGZyb20gUjpSIOKAlCBubyBsaXZlIGV4cGVjdGFuY3kgeWV0Ij57Yy5wcm94eV9wY3R9JSBlc3Q8L3NwYW4+CiAgICAgICAgICAgICAgICAgICAgICApfQogICAgICAgICAgICAgICAgICAgICAge2Mubm9fZGF0YV9wY3QgPiAwICYmICgKICAgICAgICAgICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJ2NS1tb25vIHRleHQtemluYy01MDAiPntjLm5vX2RhdGFfcGN0fSUgbm8tZGF0YTwvc3Bhbj4KICAgICAgICAgICAgICAgICAgICAgICl9Cg=='}, {'old': 'ICAgICAgICAgICAgcmVhbCUgPSBkYXRhLWJhY2tlZCBzdWItc2NvcmVzOyBuby1kYXRhJSA9IHNjb3JlZCBmcm9tIGFic2VudCBkYXRhIChkZXNjcmlwdG9yIHZlcmRpY3QgIk5vIGRhdGEiKS4K', 'new': 'ICAgICAgICAgICAgcmVhbCUgPSBtZWFzdXJlZCBkYXRhOyBlc3QlID0gZGF0YS1kZXJpdmVkIGVzdGltYXRlIChlLmcuIEVWIGZyb20gUjpSLCB2ZXJkaWN0ICJFc3QuIChSOlIpIik7IG5vLWRhdGElID0gYWJzZW50Lgo='}]},
]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    plan = []
    for f in FILES:
        path, pre, post, chunks = f["path"], f["pre"], f["post"], f["chunks"]
        if not os.path.exists(path):
            print(f"  [MISSING] {path} — run from repo root. ABORT."); sys.exit(2)
        cur = open(path, "rb").read()
        cur_sha = sha(cur)
        if cur_sha == post:
            print(f"  [ALREADY] {path}  post {post[:12]}")
            plan.append((f, path, "ALREADY", None)); continue
        if cur_sha != pre:
            print(f"  [DRIFT] {path}")
            print(f"    expected PRE  {pre}")
            print(f"    found on disk {cur_sha}")
            print(f"    rebase: tar czf - {path} | curl -sS --data-binary @- https://paste.rs/")
            sys.exit(4)
        text = cur.decode("utf-8")
        for ch in chunks:
            old = base64.b64decode(ch["old"]).decode("utf-8")
            new = base64.b64decode(ch["new"]).decode("utf-8")
            c = text.count(old)
            if c != 1:
                print(f"  [ANCHOR] {path}: a chunk matched {c} times (need 1) — ABORT."); sys.exit(3)
            text = text.replace(old, new, 1)
        new_bytes = text.encode("utf-8")
        if sha(new_bytes) != post:
            print(f"  [POSTHASH] {path}: rebuilt sha != expected POST — ABORT."); sys.exit(5)
        print(f"  [PATCH  ] {path}  pre {pre[:12]} -> post {post[:12]}  ({f['nchunks'] if 'nchunks' in f else len(chunks)} chunks)")
        plan.append((f, path, "PATCH", new_bytes))

    todo = [p for p in plan if p[2] == "PATCH"]
    if CHECK:
        print(f"\n  [CHECK OK] {len(todo)} file(s) to patch, {len(plan)-len(todo)} already applied. Re-run without --check.")
        return
    if not todo:
        print("\n  Nothing to do — all files already applied.")
        return
    for f, path, status, new_bytes in plan:
        if status != "PATCH":
            continue
        bak = path + ".a4bak"
        if not os.path.exists(bak):
            open(bak, "wb").write(open(path, "rb").read())
        open(path, "wb").write(new_bytes)
        print(f"  [PATCHED] {path} -> {sha(new_bytes)[:12]}")
    print("\n  APPLY complete. NEXT: cd frontend && yarn build && cd .. ; ./start_backend.sh --force ; commit.")


if __name__ == "__main__":
    main()
