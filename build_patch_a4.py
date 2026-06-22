#!/usr/bin/env python3
"""Generate scripts/patch_a4_ev_proxy_verdict.py — anchored-chunk multi-file patcher
for Track A4 (honest EV "Est. (R:R)" verdict instead of "No data").

4 files, each a whole-file PRE/POST SHA256 guard + N anchored (old,new) chunks
(each asserted to appear exactly once). Two-pass: validate ALL, then apply ALL
(no partial application). Pinned to LIVE DGX bytes in /tmp/dgx_a4/.

Behaviour change: the R:R-derived EV proxy stops being labeled "No data" and gets
the distinct verdict "Est. (R:R)". /api/tqs/coverage reports it as a 3rd state
(proxy) — real_pct / coverage_pct are UNCHANGED (proxy was already excluded from
'real'); only the "No data" bucket splits into proxy + truly-absent.
"""
import base64
import gzip
import hashlib

DGX = "/tmp/dgx_a4"

# ---- per-file (old -> new) anchored replacements, applied to LIVE bytes ----
EDITS = {
    "backend/services/tqs/descriptors.py": [
        (
            'def verdict_for(score: Optional[float], absent: bool = False) -> str:\n'
            '    """Score band \u2192 plain verdict. `absent=True` overrides to \'No data\'."""\n'
            '    if absent:\n'
            '        return "No data"\n',
            'def verdict_for(score: Optional[float], absent: bool = False, proxy: bool = False) -> str:\n'
            '    """Score band \u2192 plain verdict. `absent=True` overrides to \'No data\';\n'
            '    `proxy=True` marks a data-derived estimate (e.g. EV from R:R) as \'Est. (R:R)\'."""\n'
            '    if absent:\n'
            '        return "No data"\n'
            '    if proxy:\n'
            '        return "Est. (R:R)"\n',
        ),
        (
            'def disp(label: str, score: Optional[float], reading: str,\n'
            '         absent: bool = False) -> Dict[str, str]:\n'
            '    """Build one sub-score display block."""\n'
            '    return {\n'
            '        "label": label,\n'
            '        "verdict": verdict_for(score, absent),\n'
            '        "reading": reading,\n'
            '    }\n',
            'def disp(label: str, score: Optional[float], reading: str,\n'
            '         absent: bool = False, proxy: bool = False) -> Dict[str, str]:\n'
            '    """Build one sub-score display block."""\n'
            '    return {\n'
            '        "label": label,\n'
            '        "verdict": verdict_for(score, absent, proxy),\n'
            '        "reading": reading,\n'
            '    }\n',
        ),
    ],
    "backend/services/tqs/setup_quality.py": [
        (
            '            "expected_value": disp("Expected Value", self.ev_score, ev_read,\n'
            '                                   absent=c.get("ev_is_proxy")),\n',
            '            "expected_value": disp("Expected Value", self.ev_score, ev_read,\n'
            '                                   proxy=c.get("ev_is_proxy")),\n',
        ),
    ],
    "backend/routers/data_diagnostics.py": [
        (
            'NO_DATA = "No data"\n'
            'PILLARS = ["setup", "technical", "fundamental", "context", "execution"]\n',
            'NO_DATA = "No data"\n'
            'PROXY = "Est. (R:R)"\n'
            'PILLARS = ["setup", "technical", "fundamental", "context", "execution"]\n',
        ),
        (
            '    comp = defaultdict(lambda: defaultdict(lambda: {"label": "", "total": 0, "no_data": 0}))\n'
            '    pillar_tot = defaultdict(lambda: {"t": 0, "nd": 0})\n',
            '    comp = defaultdict(lambda: defaultdict(lambda: {"label": "", "total": 0, "no_data": 0, "proxy": 0}))\n'
            '    pillar_tot = defaultdict(lambda: {"t": 0, "nd": 0, "px": 0})\n',
        ),
        (
            '                nd = (blk.get("verdict") == NO_DATA)\n'
            '                rec["no_data"] += 1 if nd else 0\n'
            '                pillar_tot[p]["t"] += 1\n'
            '                pillar_tot[p]["nd"] += 1 if nd else 0\n',
            '                nd = (blk.get("verdict") == NO_DATA)\n'
            '                px = (blk.get("verdict") == PROXY)\n'
            '                rec["no_data"] += 1 if nd else 0\n'
            '                rec["proxy"] += 1 if px else 0\n'
            '                pillar_tot[p]["t"] += 1\n'
            '                pillar_tot[p]["nd"] += 1 if nd else 0\n'
            '                pillar_tot[p]["px"] += 1 if px else 0\n',
        ),
        (
            '    pillars = []\n'
            '    g_t = g_nd = 0\n'
            '    for p in PILLARS:\n',
            '    pillars = []\n'
            '    g_t = g_nd = g_px = 0\n'
            '    for p in PILLARS:\n',
        ),
        (
            '        pt = pillar_tot[p]\n'
            '        g_t += pt["t"]\n'
            '        g_nd += pt["nd"]\n',
            '        pt = pillar_tot[p]\n'
            '        g_t += pt["t"]\n'
            '        g_nd += pt["nd"]\n'
            '        g_px += pt["px"]\n',
        ),
        (
            '                "real_pct": round(100.0 * (tot - rec["no_data"]) / tot, 1) if tot else 0,\n'
            '                "no_data_pct": round(100.0 * rec["no_data"] / tot, 1) if tot else 0,\n'
            '            })\n',
            '                "real_pct": round(100.0 * (tot - rec["no_data"] - rec["proxy"]) / tot, 1) if tot else 0,\n'
            '                "proxy_pct": round(100.0 * rec["proxy"] / tot, 1) if tot else 0,\n'
            '                "no_data_pct": round(100.0 * rec["no_data"] / tot, 1) if tot else 0,\n'
            '            })\n',
        ),
        (
            '            "coverage_pct": round(100.0 * (1 - pt["nd"] / pt["t"]), 1) if pt["t"] else 0,\n'
            '            "components": components,\n',
            '            "coverage_pct": round(100.0 * (1 - (pt["nd"] + pt["px"]) / pt["t"]), 1) if pt["t"] else 0,\n'
            '            "proxy_pct": round(100.0 * pt["px"] / pt["t"], 1) if pt["t"] else 0,\n'
            '            "components": components,\n',
        ),
        (
            '        "overall_coverage_pct": round(100.0 * (1 - g_nd / g_t), 1) if g_t else 0,\n'
            '        "real_subscores": g_t - g_nd,\n'
            '        "total_subscores": g_t,\n',
            '        "overall_coverage_pct": round(100.0 * (1 - (g_nd + g_px) / g_t), 1) if g_t else 0,\n'
            '        "real_subscores": g_t - g_nd - g_px,\n'
            '        "proxy_subscores": g_px,\n'
            '        "total_subscores": g_t,\n',
        ),
    ],
    "frontend/src/components/sentcom/v5/TqsCoveragePanel.jsx": [
        (
            '          <span className="text-[13px] text-zinc-500">real vs "No data" default</span>\n',
            '          <span className="text-[13px] text-zinc-500">real \u00b7 est (R:R) \u00b7 no-data</span>\n',
        ),
        (
            '              {data.real_subscores}/{data.total_subscores} sub-scores real \u00b7{\' \'}\n'
            '              <span className="text-zinc-400">{data.with_display}</span> alerts w/ descriptors \u00b7{\' \'}\n',
            '              {data.real_subscores}/{data.total_subscores} sub-scores real \u00b7{\' \'}\n'
            '              {data.proxy_subscores ? (<><span className="text-sky-400">{data.proxy_subscores} est</span> \u00b7{\' \'}</>) : null}\n'
            '              <span className="text-zinc-400">{data.with_display}</span> alerts w/ descriptors \u00b7{\' \'}\n',
        ),
        (
            '                      {c.no_data_pct > 0 && (\n'
            '                        <span className="v5-mono text-zinc-500">{c.no_data_pct}% no-data</span>\n'
            '                      )}\n',
            '                      {c.proxy_pct > 0 && (\n'
            '                        <span className="v5-mono text-sky-400" title="Estimated from R:R \u2014 no live expectancy yet">{c.proxy_pct}% est</span>\n'
            '                      )}\n'
            '                      {c.no_data_pct > 0 && (\n'
            '                        <span className="v5-mono text-zinc-500">{c.no_data_pct}% no-data</span>\n'
            '                      )}\n',
        ),
        (
            '            real% = data-backed sub-scores; no-data% = scored from absent data (descriptor verdict "No data").\n',
            '            real% = measured data; est% = data-derived estimate (e.g. EV from R:R, verdict "Est. (R:R)"); no-data% = absent.\n',
        ),
    ],
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    files = []
    for path, edits in EDITS.items():
        pre_b = open(f"{DGX}/{path}", "rb").read()
        text = pre_b.decode("utf-8")
        chunks = []
        for old, new in edits:
            cnt = text.count(old)
            assert cnt == 1, f"{path}: OLD anchor count={cnt} (must be 1)\n---\n{old[:120]}"
            text = text.replace(old, new, 1)
            chunks.append({
                "old": base64.b64encode(old.encode("utf-8")).decode(),
                "new": base64.b64encode(new.encode("utf-8")).decode(),
            })
        post_b = text.encode("utf-8")
        if path.endswith(".py"):
            compile(post_b, path, "exec")  # syntax gate
        files.append({
            "path": path, "pre": sha(pre_b), "post": sha(post_b),
            "chunks": chunks, "nchunks": len(chunks),
        })
        print(f"  {path}\n    pre={sha(pre_b)[:12]} post={sha(post_b)[:12]} chunks={len(chunks)}")

    files_lit = "[\n" + "".join(
        "    {{'path': {p!r}, 'pre': {pre!r}, 'post': {post!r}, 'chunks': {ch!r}}},\n".format(
            p=f["path"], pre=f["pre"], post=f["post"], ch=f["chunks"])
        for f in files
    ) + "]"

    patcher = '''#!/usr/bin/env python3
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
FILES = __FILES__


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
        print(f"\\n  [CHECK OK] {len(todo)} file(s) to patch, {len(plan)-len(todo)} already applied. Re-run without --check.")
        return
    if not todo:
        print("\\n  Nothing to do — all files already applied.")
        return
    for f, path, status, new_bytes in plan:
        if status != "PATCH":
            continue
        bak = path + ".a4bak"
        if not os.path.exists(bak):
            open(bak, "wb").write(open(path, "rb").read())
        open(path, "wb").write(new_bytes)
        print(f"  [PATCHED] {path} -> {sha(new_bytes)[:12]}")
    print("\\n  APPLY complete. NEXT: cd frontend && yarn build && cd .. ; ./start_backend.sh --force ; commit.")


if __name__ == "__main__":
    main()
'''
    patcher = patcher.replace("__FILES__", files_lit)
    out = "/app/scripts/patch_a4_ev_proxy_verdict.py"
    open(out, "w", encoding="utf-8").write(patcher)
    print("wrote", out, len(patcher), "bytes")


if __name__ == "__main__":
    main()
