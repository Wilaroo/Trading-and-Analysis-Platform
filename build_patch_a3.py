#!/usr/bin/env python3
"""Generate scripts/patch_a3_why_trace_modal.py — bundled multi-file FRONTEND
patcher for Track A3 (Why-Trace modal). 1 new file + 3 whole-file edits, each
gzip+b64 with PRE/POST SHA256 guards. Two-pass: validate ALL, then apply ALL
(no partial application). Pinned to live DGX bytes from /tmp/dgx_v5/.
"""
import base64
import gzip
import hashlib
import os

V5 = "frontend/src/components/sentcom/v5"
SB = f"/app/{V5}"          # my edited (POST)
DGX = "/tmp/dgx_v5"        # live (PRE) for edited files

EDITS = ["tqsDrawerBus.js", "ScannerCardsV5.jsx", "TqsDrillDownDrawer.jsx"]
NEWF = ["WhyTraceModal.jsx"]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    files = []
    # new file(s)
    for name in NEWF:
        post_b = open(f"{SB}/{name}", "rb").read()
        files.append({
            "path": f"{V5}/{name}", "kind": "new",
            "pre": None, "post": sha(post_b),
            "b64": base64.b64encode(gzip.compress(post_b, 9)).decode(),
        })
    # whole-file edits
    for name in EDITS:
        pre_b = open(f"{DGX}/{V5}/{name}", "rb").read()
        post_b = open(f"{SB}/{name}", "rb").read()
        files.append({
            "path": f"{V5}/{name}", "kind": "edit",
            "pre": sha(pre_b), "post": sha(post_b),
            "b64": base64.b64encode(gzip.compress(post_b, 9)).decode(),
        })
    for f in files:
        print(f"  {f['kind']:5} {f['path']}  pre={ (f['pre'] or '-')[:12] } post={f['post'][:12]}")

    files_lit = "[\n" + "".join(
        f"    {{'path': {f['path']!r}, 'kind': {f['kind']!r}, 'pre': {f['pre']!r}, 'post': {f['post']!r}, 'b64': {f['b64']!r}}},\n"
        for f in files
    ) + "]"

    patcher = '''#!/usr/bin/env python3
"""
patch_a3_why_trace_modal.py  —  v19.34.285 (UI Track A · A3)
"Why-Trace modal — plain-language 7-stage trade trace"

Adds a Why-Trace modal opened from the TQS drill-down drawer header. It renders
the trade's life as 7 sequential, plain-language stages — scan -> setup -> grade
-> gate -> size -> manage -> exit — each with a DONE / NOW / NEXT / STOOD-DOWN
status and a one-line human explanation, built from the card object (now passed
through tqsDrawerBus) + the card-detail payload the drawer already fetched.

FRONTEND change. 1 new file + 3 whole-file edits, each gzip+b64 with PRE/POST
SHA256 guards. Two-pass: validates ALL files first and aborts on ANY drift
before writing anything (no partial apply). Per-file .a3bak backups.
REQUIRES a frontend rebuild.

FILES:
  NEW  frontend/src/components/sentcom/v5/WhyTraceModal.jsx
  EDIT frontend/src/components/sentcom/v5/tqsDrawerBus.js        (bus carries card)
  EDIT frontend/src/components/sentcom/v5/ScannerCardsV5.jsx     (pass card on click)
  EDIT frontend/src/components/sentcom/v5/TqsDrillDownDrawer.jsx (Why-Trace button + modal)

USAGE (repo root):
  .venv/bin/python scripts/patch_a3_why_trace_modal.py --check
  .venv/bin/python scripts/patch_a3_why_trace_modal.py
  cd frontend && yarn build && cd ..
  git add frontend/ scripts/ && git commit -m "v19.34.285 (A3): Why-Trace modal" && git push origin main
Then hard-reload. Rollback: restore the three *.a3bak files and rm WhyTraceModal.jsx, then rebuild.
"""
import base64
import gzip
import hashlib
import os
import sys

CHECK = "--check" in sys.argv
FILES = __FILES__


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    plan = []
    for f in FILES:
        path, kind, pre, post = f["path"], f["kind"], f["pre"], f["post"]
        new_bytes = gzip.decompress(base64.b64decode(f["b64"]))
        if sha(new_bytes) != post:
            print(f"  [CORRUPT] {path}: embedded payload sha != POST — ABORT."); sys.exit(5)
        exists = os.path.exists(path)
        cur = open(path, "rb").read() if exists else b""
        cur_sha = sha(cur) if exists else None

        if exists and cur_sha == post:
            status = "ALREADY"
        elif kind == "new":
            if exists:
                print(f"  [CONFLICT] {path} already exists with unexpected content (sha={cur_sha[:12]}) — ABORT.")
                sys.exit(3)
            status = "CREATE"
        else:  # edit
            if not exists:
                print(f"  [MISSING] {path} — run from repo root. ABORT."); sys.exit(2)
            if cur_sha != pre:
                print(f"  [DRIFT] {path}")
                print(f"    expected PRE  {pre}")
                print(f"    found on disk {cur_sha}")
                print(f"    rebase: tar czf - {path} | curl -sS --data-binary @- https://paste.rs/  (and the other two)")
                sys.exit(4)
            status = "PATCH"
        plan.append((f, path, kind, post, new_bytes, status))
        tag = f"pre {pre[:12]} -> " if pre else ""
        print(f"  [{status:7}] {path}  {tag}post {post[:12]}")

    todo = [p for p in plan if p[5] in ("CREATE", "PATCH")]
    if CHECK:
        print(f"\\n  [CHECK OK] {len(todo)} file(s) to write, {len(plan)-len(todo)} already applied. Re-run without --check.")
        return
    if not todo:
        print("\\n  Nothing to do — all files already applied.")
        return
    for f, path, kind, post, new_bytes, status in plan:
        if status not in ("CREATE", "PATCH"):
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if status == "PATCH":
            bak = path + ".a3bak"
            if not os.path.exists(bak):
                open(bak, "wb").write(open(path, "rb").read())
        open(path, "wb").write(new_bytes)
        print(f"  [{'CREATED' if status=='CREATE' else 'PATCHED'}] {path} -> {post[:12]}")
    print("\\n  APPLY complete. NEXT: cd frontend && yarn build && cd .. ; commit; hard-reload the UI.")


if __name__ == "__main__":
    main()
'''
    patcher = patcher.replace("__FILES__", files_lit)
    out = "/app/scripts/patch_a3_why_trace_modal.py"
    open(out, "w", encoding="utf-8").write(patcher)
    print("wrote", out, len(patcher), "bytes")


if __name__ == "__main__":
    main()
