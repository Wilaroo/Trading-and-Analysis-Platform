#!/usr/bin/env python3
"""Generator: builds the DGX deploy script for v19.34.249 (F1 reconciler + F3
canonical strategy_stats EV). Ships code only — the one-time historical backfill
is a separate manual step (dry-run first) the operator runs afterwards."""
import base64
import gzip
import os

REPO = "/app"
FILES = [
    "backend/services/pnl_compute.py",
    "backend/services/learning_reconciler.py",
    "backend/services/trading_scheduler.py",
    "backend/scripts/backfill_v19_34_249_learning_coverage.py",
    "backend/scripts/diag_learning_loop_audit_v19_34_248.py",
    "backend/scripts/diag_learning_loop_audit_v19_34_248b.py",
    "backend/tests/test_v19_34_249_learning_reconciler.py",
]

blobs = {}
for rel in FILES:
    with open(os.path.join(REPO, rel), "rb") as fh:
        blobs[rel] = base64.b64encode(gzip.compress(fh.read())).decode("ascii")

header = '''#!/usr/bin/env python3
"""
v19.34.249 — Learning-loop COVERAGE RECONCILER (F1) + canonical genuine
strategy_stats EV (F3). DGX deploy script.

WHY: the audit proved the loop saw only ~17% of closed trades — the OCA-external
sweep / EOD auto-close / operator close-panel / consolidation paths set status
inline and skip record_trade_outcome + alert_outcomes, so 238 genuine wins/losses
(mostly bracket target/stop fills) never reached the learning sinks. And the v216
strategy_stats counter double-counted scale-out partials, inflating EV/win-rate
(accumulation_entry read 52%/+0.62R vs the realized 11%/-0.43R).

F1: new services/learning_reconciler.py + a nightly reconcile hook in the
    learning_stats rebuild (ingests missing closes post-close, stored entry-time
    context, GENUINE-only into trade_outcomes; zero close-path risk).
F3: pnl_compute now RECOMPUTES strategy_stats whole-trade/genuine from
    alert_outcomes (win_rate + EV share one sample) — kills the partial inflation.

This deploy ships CODE ONLY. After it, repair the historical backlog manually:
    .venv/bin/python backend/scripts/backfill_v19_34_249_learning_coverage.py          # DRY RUN — review
    .venv/bin/python backend/scripts/backfill_v19_34_249_learning_coverage.py --commit  # apply
    ./start_backend.sh --force   # so TQS reloads strategy_stats

Idempotent. Commits+pushes BEFORE restart (the .bat does `git checkout -- .`).
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
    if not os.path.isdir(REPO):
        sys.exit(f"[FATAL] repo not found: {REPO}")
    os.chdir(REPO)
    for rel, b64 in FILES.items():
        data = gzip.decompress(base64.b64decode(b64))
        path = os.path.join(REPO, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        print(f"[WROTE] {rel} ({len(data)} bytes)")

    print("[TEST] pytest v249 + v247 ...")
    r = subprocess.run(
        [PY, "-m", "pytest",
         "backend/tests/test_v19_34_249_learning_reconciler.py",
         "backend/tests/test_v19_34_247_eod_aware_thresholds.py", "-q"],
        cwd=REPO,
    )
    if r.returncode != 0:
        sys.exit("[FATAL] tests failed — NOT committing/restarting.")

    subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode == 0:
        print("[GIT] no changes (already up to date).")
    else:
        subprocess.run(
            ["git", "commit", "-m",
             "v19.34.249 — learning-loop coverage reconciler (F1) + canonical "
             "genuine whole-trade strategy_stats EV (F3): fix ~17% outcome "
             "coverage leak + scale-out EV inflation"],
            cwd=REPO, check=True)
        subprocess.run(["git", "push"], cwd=REPO, check=True)
        print("[GIT] committed + pushed.")

    print("[RESTART] ./start_backend.sh --force")
    subprocess.run(["./start_backend.sh", "--force"], cwd=REPO, check=False)
    print("[DONE] v19.34.249 code deployed. Next: run the backfill (dry-run first):")
    print("  .venv/bin/python backend/scripts/backfill_v19_34_249_learning_coverage.py")


if __name__ == "__main__":
    main()
'''

out = "/tmp/deploy_v19_34_249.py"
with open(out, "w") as fh:
    fh.write(body)
print(f"wrote {out} ({len(body)} bytes)")
