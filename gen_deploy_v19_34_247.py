#!/usr/bin/env python3
"""Generator: builds the self-contained DGX deploy script for v19.34.247.

Reads the changed files from this fork, gzip+base64 encodes them, and emits
/tmp/deploy_v19_34_247.py which the operator runs on the DGX. The deploy
script writes the files, runs pytest under .venv, commits+pushes BEFORE
restart (so the .bat `git checkout -- .` can't wipe it), then restarts.
"""
import base64
import gzip
import os

REPO = "/app"
FILES = [
    "backend/services/opportunity_evaluator.py",
    "backend/routers/ib.py",
    "backend/services/trading_rules.py",
    "backend/tests/test_v19_34_247_eod_aware_thresholds.py",
    "frontend/src/components/sentcom/v5/EodCountdownBannerV5.jsx",
    "frontend/src/components/sentcom/v5/EodPreviewBanner.jsx",
]

blobs = {}
for rel in FILES:
    with open(os.path.join(REPO, rel), "rb") as fh:
        raw = fh.read()
    blobs[rel] = base64.b64encode(gzip.compress(raw)).decode("ascii")

header = '''#!/usr/bin/env python3
"""
v19.34.247 — EOD-aware thresholds (DGX deploy script).

Two related fixes for the run into the close:
  (1) FALSE "IB PUSHER DEAD" banner near EOD — the hard 30s dead threshold
      tripped during the natural EOD push slowdown (thin ticks + the
      serialized 15:45 flatten loop lagging the push-data handler). The
      pusher-dead threshold is now relaxed (default 120s) inside the
      15:40-16:05 ET window via `_resolve_pusher_dead_threshold`.
  (2) STALE "EOD fires at 3:55pm" gate text — the no-new-entries gate
      hardcoded HARD_CUT=15:55 while the EOD-flatten loop moved to 15:45 ET
      in v19.34.154. HARD cut is now pinned to the bot's ACTUAL flatten
      time (`_eod_cut_times`), and all operator-facing strings are derived
      from it. Closes the 15:45-15:55 hole where a fresh entry could be
      opened *while the flatten loop was already running*.

Idempotent: re-running writes identical bytes and is a no-op for git.
Frontend changes are COMMENT-ONLY — no `yarn build` required.
All knobs env-tunable: PUSHER_DEAD_THRESHOLD_S, PUSHER_DEAD_EOD_THRESHOLD_S,
PUSHER_DEAD_EOD_WINDOW_{START,END}_MIN, EOD_NO_ENTRY_GRACE_MIN.
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

    # ── Run the v247 regression test under the venv ──────────────────
    print("[TEST] pytest v247 ...")
    r = subprocess.run(
        [PY, "-m", "pytest",
         "backend/tests/test_v19_34_247_eod_aware_thresholds.py", "-q"],
        cwd=REPO,
    )
    if r.returncode != 0:
        sys.exit("[FATAL] v247 tests failed — NOT committing/restarting.")

    # ── Commit + push BEFORE restart (the .bat does `git checkout -- .`) ─
    subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO)
    if diff.returncode == 0:
        print("[GIT] no changes to commit (already up to date).")
    else:
        subprocess.run(
            ["git", "commit", "-m",
             "v19.34.247 — EOD-aware thresholds: kill false pusher-dead "
             "banner near EOD + re-pin no-new-entries gate to real 15:45 "
             "flatten time (no more stale 3:55pm text)"],
            cwd=REPO, check=True,
        )
        subprocess.run(["git", "push"], cwd=REPO, check=True)
        print("[GIT] committed + pushed.")

    # ── Restart backend ──────────────────────────────────────────────
    print("[RESTART] ./start_backend.sh --force")
    subprocess.run(["./start_backend.sh", "--force"], cwd=REPO, check=False)
    print("[DONE] v19.34.247 deployed. Verify via:")
    print("  curl -s localhost:8001/api/ib/pusher-health | python3 -m json.tool | grep -E 'dead|eod'")


if __name__ == "__main__":
    main()
'''

out = "/tmp/deploy_v19_34_247.py"
with open(out, "w") as fh:
    fh.write(body)
print(f"wrote {out} ({len(body)} bytes)")
