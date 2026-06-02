#!/usr/bin/env python3
"""Generator: writes /app/deploy_v19_34_230_pillar_decompress.py with the
base64 payload embedded. Run once locally; the OUTPUT is what goes to paste.rs."""
import json

with open("/tmp/v230_payload.json") as f:
    payload = json.load(f)

HEADER = '''#!/usr/bin/env python3
"""
deploy_v19_34_230_pillar_decompress.py

v19.34.230 — TQS pillar DE-COMPRESSION (durable follow-up to v228/v229).

Widens the raw TQS composite so the v228 percentile calibration auto-respreads
(no redeploy). Three changes, all env-gated + reversible:

  A1 (setup) — EV-from-R:R when no live EV data: replaces the flat ev_score=30
       pin with clamp(25 + (RR-1)*22, 10, 95). Real per-alert variance + ceiling.
  A2 (setup) — missing/uninformative SMB -> neutral 50 (not punitive C/35).
  B3 (exec)  — history_score per-setup_type from a 15-min-cached trade_outcomes
       aggregation, shrunk toward 60 by sample size (replaces the pinned-60).

Env flags (default ON in code; set to 0 to revert instantly, no redeploy):
  TQS_SETUP_DECOMPRESS=1   TQS_EXEC_DECOMPRESS=1
Tunables: TQS_EXEC_HIST_TTL_SEC=900  TQS_EXEC_HIST_WINDOW_DAYS=30  TQS_EXEC_HIST_SHRINK_K=10

SAFE DELIVERY: full-file replace of two pillar modules + a new pytest file, via
base64 (downloaded by curl, never pasted -> no terminal corruption).
  * IDEMPOTENT: if a file already contains the v19.34.230 marker, it is skipped.
  * ANCHOR-GUARDED: a file is only overwritten if it still contains its expected
    pre-patch anchor strings; otherwise the script ABORTS (won't clobber a
    diverged file). Nothing is committed if any file aborts.
  * Prints `git diff --stat` before committing so you see exactly what changed.
  * Auto-commits + pushes so the `.bat` `git checkout -- .` cannot wipe it.

USAGE on the DGX:
    curl -s https://paste.rs/XXXX -o /tmp/deploy_v230.py
    python3 /tmp/deploy_v230.py            # auto-detects repo root
    # then run the pytest + RESTART the backend (see printed instructions).
"""
import base64
import json
import os
import subprocess
import sys

MARKER = "v19.34.230"

# path -> {"b64":..., "anchors":[...], "new_file":bool}
PAYLOAD = json.loads(r"""'''

FOOTER = '''

def find_repo_root() -> str:
    candidates = []
    if len(sys.argv) > 1:
        candidates.append(os.path.abspath(sys.argv[1]))
    candidates.append(os.getcwd())
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    seen = set()
    for start in candidates:
        cur = start
        for _ in range(8):
            if cur in seen:
                break
            seen.add(cur)
            if os.path.isfile(os.path.join(cur, "backend", "server.py")):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    raise SystemExit("ERROR: repo root not found. Pass it: python3 deploy_v230.py /path/to/repo")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def main():
    repo = find_repo_root()
    print("== v19.34.230 TQS pillar de-compression deploy ==")
    print("repo root:", repo)

    plan = []   # (abs_path, new_bytes)
    for rel, meta in PAYLOAD.items():
        ap = os.path.join(repo, rel)
        new_bytes = base64.b64decode(meta["b64"])
        if meta.get("new_file"):
            plan.append((ap, new_bytes, "new"))
            continue
        if not os.path.isfile(ap):
            raise SystemExit(f"ABORT: expected existing file missing: {ap}")
        cur = open(ap, "r", encoding="utf-8", errors="replace").read()
        if MARKER in cur:
            print(f"  - SKIP (already patched): {rel}")
            continue
        for anc in meta["anchors"]:
            if anc not in cur:
                raise SystemExit(
                    f"ABORT: anchor not found in {rel!r}:\\n    {anc!r}\\n"
                    "  File diverged from the expected pre-patch base. Nothing was "
                    "written. Send this message back so we can adapt the patch."
                )
        plan.append((ap, new_bytes, "patch"))

    if not plan:
        print("Nothing to do — all files already at v19.34.230.")
        return

    for ap, data, kind in plan:
        os.makedirs(os.path.dirname(ap), exist_ok=True)
        with open(ap, "wb") as f:
            f.write(data)
        # verify marker present where expected
        if kind != "new" and MARKER not in open(ap, encoding="utf-8").read():
            raise SystemExit(f"ABORT: marker missing after write in {ap}")
        print(f"  - wrote ({kind}): {os.path.relpath(ap, repo)}")

    print("\\n=== git diff --stat (review) ===")
    d = git(repo, "--no-pager", "diff", "--stat")
    print(d.stdout.strip() or "(no tracked diff shown)")

    git(repo, "add", "-A")
    status = git(repo, "status", "--porcelain")
    if status.stdout.strip():
        msg = ("v19.34.230: TQS pillar de-compression (A1 EV-from-RR, A2 SMB "
               "neutral, B3 per-setup exec history); env-gated")
        c = git(repo, "commit", "-m", msg)
        print("\\n  - git commit:\\n    " + (c.stdout or c.stderr).strip().replace("\\n", "\\n    "))
        p = git(repo, "push")
        print("  - git push:\\n    " + (p.stdout or p.stderr).strip().replace("\\n", "\\n    "))
    else:
        print("  - git: nothing to commit")

    print("\\nNEXT STEPS:")
    print("  1) Run the regression tests:")
    print("       cd %s && python3 -m pytest backend/tests/test_v19_34_230_pillar_decompress.py -q" % repo)
    print("  2) RESTART the backend so the new scoring loads (StartTrading.bat / spark flow).")
    print("  3) After ~1 scan cycle, re-run the diagnostic to SEE the spread widen:")
    print("       python3 /tmp/diag_tqs_dist.py 1")
    print("\\nRevert anytime without redeploy:  set TQS_SETUP_DECOMPRESS=0 / TQS_EXEC_DECOMPRESS=0 in backend/.env + restart.")


if __name__ == "__main__":
    main()
'''

with open("/app/deploy_v19_34_230_pillar_decompress.py", "w") as f:
    f.write(HEADER)
    f.write(json.dumps(payload, indent=0))
    f.write('""")\n')
    f.write(FOOTER)

print("wrote /app/deploy_v19_34_230_pillar_decompress.py")
