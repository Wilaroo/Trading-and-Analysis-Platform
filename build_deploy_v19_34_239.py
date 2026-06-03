#!/usr/bin/env python3
"""
Builder: emits deploy_v19_34_239.py with the two changed files embedded as
gzip+base64 blobs. Run locally; upload the OUTPUT to paste.rs.

v19.34.239 — dynamic trigger_probability wired into the _apply_setup_context
enrichment chokepoint (always-on). Treats each detector's hardcoded
trigger_probability as a calibrated base; live distance-to-trigger + RVOL
move it, clamped [0.15, 0.90].
"""
import base64
import gzip
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

FILES = [
    "backend/services/enhanced_scanner.py",
    "backend/tests/test_v19_34_239_dynamic_trigger_prob.py",
]


def blob(rel):
    with open(os.path.join(ROOT, rel), "rb") as f:
        return base64.b64encode(gzip.compress(f.read(), 9)).decode()


payload = {rel: blob(rel) for rel in FILES}

lines = []
lines.append('#!/usr/bin/env python3')
lines.append('"""')
lines.append('DGX DEPLOY v19.34.239 — dynamic trigger_probability (always-on).')
lines.append('')
lines.append('Idempotent: rewrites the two files from embedded gzip+base64 blobs,')
lines.append('runs the v239 pytest under .venv, then git commit && git push (REQUIRED —')
lines.append('the .bat restart runs `git checkout -- .` which wipes uncommitted work),')
lines.append('then restarts the backend via ./start_backend.sh --force.')
lines.append('')
lines.append('Run on the DGX repo root:  .venv/bin/python /tmp/deploy_v19_34_239.py')
lines.append('"""')
lines.append('import base64, gzip, os, subprocess, sys')
lines.append('')
lines.append('FILES = {')
for rel, b in payload.items():
    lines.append(f'    {rel!r}: {b!r},')
lines.append('}')
lines.append('')
lines.append('ROOT = os.path.dirname(os.path.abspath(__file__))')
lines.append('# When run from /tmp, fall back to CWD as the repo root.')
lines.append('REPO = os.getcwd()')
lines.append('')
lines.append('def main():')
lines.append('    if not os.path.isdir(os.path.join(REPO, "backend", "services")):')
lines.append('        print(f"[FATAL] not a repo root (no backend/services): {REPO}")')
lines.append('        sys.exit(1)')
lines.append('    for rel, b in FILES.items():')
lines.append('        dst = os.path.join(REPO, rel)')
lines.append('        os.makedirs(os.path.dirname(dst), exist_ok=True)')
lines.append('        data = gzip.decompress(base64.b64decode(b))')
lines.append('        with open(dst, "wb") as f:')
lines.append('            f.write(data)')
lines.append('        print(f"[WROTE] {rel} ({len(data)} bytes)")')
lines.append('')
lines.append('    # Verify with pytest under the venv python actually running this.')
lines.append('    print("[TEST] running v239 pytest ...")')
lines.append('    r = subprocess.run(')
lines.append('        [sys.executable, "-m", "pytest",')
lines.append('         "backend/tests/test_v19_34_239_dynamic_trigger_prob.py", "-q"],')
lines.append('        cwd=REPO)')
lines.append('    if r.returncode != 0:')
lines.append('        print("[FATAL] pytest failed — aborting BEFORE commit/restart.")')
lines.append('        sys.exit(2)')
lines.append('')
lines.append('    # Commit + push BEFORE restart (the .bat does git checkout -- .).')
lines.append('    subprocess.run(["git", "add",')
lines.append('                    "backend/services/enhanced_scanner.py",')
lines.append('                    "backend/tests/test_v19_34_239_dynamic_trigger_prob.py"],')
lines.append('                   cwd=REPO)')
lines.append('    c = subprocess.run(')
lines.append('        ["git", "commit", "-m",')
lines.append('         "v19.34.239 — dynamic trigger_probability via _apply_setup_context chokepoint"],')
lines.append('        cwd=REPO)')
lines.append('    if c.returncode != 0:')
lines.append('        print("[INFO] git commit no-op (already committed / clean) — continuing.")')
lines.append('    p = subprocess.run(["git", "push"], cwd=REPO)')
lines.append('    if p.returncode != 0:')
lines.append('        print("[WARN] git push failed — commit is LOCAL; push manually.")')
lines.append('')
lines.append('    print("[RESTART] ./start_backend.sh --force")')
lines.append('    subprocess.run(["./start_backend.sh", "--force"], cwd=REPO)')
lines.append('    print("[DONE] v19.34.239 deployed.")')
lines.append('')
lines.append('if __name__ == "__main__":')
lines.append('    main()')

out = os.path.join(ROOT, "deploy_v19_34_239.py")
with open(out, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"[BUILT] {out}")
