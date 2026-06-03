#!/usr/bin/env python3
"""Generator: DGX deploy for v19.34.249b — reconciler fixes (force _AO_DB so
standalone alert_outcomes/strategy_stats writes persist; reconstruct exit_price
from realized_pnl/shares so OCA-external bracket fills are ingested)."""
import base64
import gzip
import os

REPO = "/app"
FILES = [
    "backend/services/learning_reconciler.py",
    "backend/tests/test_v19_34_249_learning_reconciler.py",
]
blobs = {}
for rel in FILES:
    with open(os.path.join(REPO, rel), "rb") as fh:
        blobs[rel] = base64.b64encode(gzip.compress(fh.read())).decode("ascii")

header = '''#!/usr/bin/env python3
"""
v19.34.249b — learning reconciler FIXES (after the first --commit revealed 2 bugs).

(1) alert_outcomes wrote 0 + strategy_stats never recomputed: pnl_compute._AO_DB is
    None in a standalone script (no MONGO_URL in-env), so the canonical writers
    silently no-op'd. reconcile() now points _AO_DB at the passed db when None.
(2) OCA-external / EOD sweeps persist realized_pnl but NOT exit_price, so the 186
    bracket target/stop fills (the most important wins/losses) landed in
    skipped_no_prices. reconcile() now reconstructs exit_price from
    realized_pnl/shares.

After deploy, RE-RUN the backfill (idempotent — only adds what's still missing):
    .venv/bin/python backend/scripts/backfill_v19_34_249_learning_coverage.py            # dry-run
    .venv/bin/python backend/scripts/backfill_v19_34_249_learning_coverage.py --commit
    ./start_backend.sh --force
    .venv/bin/python backend/scripts/diag_learning_loop_audit_v19_34_248b.py --days 14
"""
import base64
import gzip
import os
import subprocess
import sys

REPO = os.path.expanduser("~/Trading-and-Analysis-Platform")
PY = os.path.join(REPO, ".venv/bin/python")

FILES = {
'''
body = header
for rel, b64 in blobs.items():
    body += f'    {rel!r}: "{b64}",\n'
body += '''}


def main():
    os.chdir(REPO)
    for rel, b64 in FILES.items():
        data = gzip.decompress(base64.b64decode(b64))
        with open(os.path.join(REPO, rel), "wb") as fh:
            fh.write(data)
        print(f"[WROTE] {rel} ({len(data)} bytes)")
    r = subprocess.run([PY, "-m", "pytest",
                        "backend/tests/test_v19_34_249_learning_reconciler.py", "-q"], cwd=REPO)
    if r.returncode != 0:
        sys.exit("[FATAL] tests failed — NOT committing.")
    subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode != 0:
        subprocess.run(["git", "commit", "-m",
                        "v19.34.249b — reconciler: force _AO_DB for standalone writes + "
                        "reconstruct exit_price from realized_pnl (ingest OCA-external fills)"],
                       cwd=REPO, check=True)
        subprocess.run(["git", "push"], cwd=REPO, check=True)
        print("[GIT] committed + pushed.")
    else:
        print("[GIT] no changes.")
    print("[DONE] v249b deployed. Re-run the backfill (dry-run first), then restart + audit.")
    print("  NOTE: no backend restart needed yet — restart AFTER the --commit backfill.")


if __name__ == "__main__":
    main()
'''
out = "/tmp/deploy_v19_34_249b.py"
with open(out, "w") as fh:
    fh.write(body)
print(f"wrote {out} ({len(body)} bytes)")
