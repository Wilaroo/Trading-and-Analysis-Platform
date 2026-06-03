#!/usr/bin/env python3
"""Builder: emits deploy_v19_34_240.py with all v240 files embedded as
gzip+base64 blobs. Upload the OUTPUT to paste.rs."""
import base64
import gzip
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
FILES = [
    "backend/services/trade_outcome_hygiene.py",
    "backend/services/pnl_compute.py",
    "backend/services/gameplan_edge_ranker.py",
    "backend/scripts/backfill_v19_34_240_hygiene.py",
    "backend/tests/test_v19_34_240_outcome_hygiene.py",
]


def blob(rel):
    with open(os.path.join(ROOT, rel), "rb") as f:
        return base64.b64encode(gzip.compress(f.read(), 9)).decode()


payload = {rel: blob(rel) for rel in FILES}

L = []
L.append('#!/usr/bin/env python3')
L.append('"""')
L.append('DGX DEPLOY v19.34.241 — hygiene: also reject reconciliation/import setup_types.')
L.append('')
L.append('Idempotent: rewrites the embedded files, runs the v240 pytest under .venv,')
L.append('then git commit && git push (REQUIRED — the .bat restart runs `git checkout -- .`')
L.append('which wipes uncommitted work), then ./start_backend.sh --force.')
L.append('')
L.append('Does NOT run the data backfill — run that separately AFTER deploy:')
L.append('  .venv/bin/python backend/scripts/backfill_v19_34_240_hygiene.py --dry-run')
L.append('  .venv/bin/python backend/scripts/backfill_v19_34_240_hygiene.py')
L.append('')
L.append('Run on the DGX repo root:  .venv/bin/python /tmp/deploy_v19_34_240.py')
L.append('"""')
L.append('import base64, gzip, os, subprocess, sys')
L.append('')
L.append('FILES = {')
for rel, b in payload.items():
    L.append(f'    {rel!r}: {b!r},')
L.append('}')
L.append('')
L.append('REPO = os.getcwd()')
L.append('')
L.append('def main():')
L.append('    if not os.path.isdir(os.path.join(REPO, "backend", "services")):')
L.append('        print(f"[FATAL] not a repo root (no backend/services): {REPO}")')
L.append('        sys.exit(1)')
L.append('    for rel, b in FILES.items():')
L.append('        dst = os.path.join(REPO, rel)')
L.append('        os.makedirs(os.path.dirname(dst), exist_ok=True)')
L.append('        data = gzip.decompress(base64.b64decode(b))')
L.append('        with open(dst, "wb") as f:')
L.append('            f.write(data)')
L.append('        print(f"[WROTE] {rel} ({len(data)} bytes)")')
L.append('')
L.append('    print("[TEST] running v240 + v239 pytest ...")')
L.append('    r = subprocess.run(')
L.append('        [sys.executable, "-m", "pytest",')
L.append('         "backend/tests/test_v19_34_240_outcome_hygiene.py",')
L.append('         "backend/tests/test_v19_34_233_gameplan_edge_rank.py", "-q"],')
L.append('        cwd=REPO)')
L.append('    if r.returncode != 0:')
L.append('        print("[FATAL] pytest failed — aborting BEFORE commit/restart.")')
L.append('        sys.exit(2)')
L.append('')
L.append('    subprocess.run(["git", "add"] + list(FILES.keys()), cwd=REPO)')
L.append('    c = subprocess.run(')
L.append('        ["git", "commit", "-m",')
L.append('         "v19.34.241 — hygiene: reject reconciliation/import setup_types (reconciled_*, imported_from_ib)"],')
L.append('        cwd=REPO)')
L.append('    if c.returncode != 0:')
L.append('        print("[INFO] git commit no-op (already committed) — continuing.")')
L.append('    p = subprocess.run(["git", "push"], cwd=REPO)')
L.append('    if p.returncode != 0:')
L.append('        print("[WARN] git push failed — commit is LOCAL; push manually.")')
L.append('')
L.append('    print("[RESTART] ./start_backend.sh --force")')
L.append('    subprocess.run(["./start_backend.sh", "--force"], cwd=REPO)')
L.append('    print("[DONE] v19.34.241 deployed. Re-run the backfill --dry-run to confirm reconciled_* are gone, then commit it.")')
L.append('')
L.append('if __name__ == "__main__":')
L.append('    main()')

out = os.path.join(ROOT, "deploy_v19_34_241.py")
with open(out, "w") as f:
    f.write("\n".join(L) + "\n")
print(f"[BUILT] {out}")
