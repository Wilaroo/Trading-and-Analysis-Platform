#!/usr/bin/env python3
"""Generator for deploy_v19_34_231_premarket_tqs.py (embeds base64 payload)."""
import json, base64, gzip

with open("/tmp/v231_payload.json") as f:
    payload = json.load(f)
# recompress: store gzip+base64 to fit paste.rs size cap (enhanced_scanner is large)
for rel, meta in payload.items():
    raw = base64.b64decode(meta["b64"])
    meta["b64"] = base64.b64encode(gzip.compress(raw, 9)).decode()
    meta["gz"] = True

HEADER = '''#!/usr/bin/env python3
"""
deploy_v19_34_231_premarket_tqs.py

v19.34.231 — REPAIR the silently-broken premarket scanner + TQS-grade it.

THE BUG: every inline premarket LiveAlert(...) constructor used a stale schema
(stop_price/target_price/score/timestamp + missing required fields) and threw
TypeError, swallowed by `except Exception: pass` → ZERO premarket alerts have
been produced for a long time (log always printed "0 morning watchlist alerts").

THE FIX (3 files):
  enhanced_scanner.py
    - NEW _make_premarket_alert() factory builds a schema-valid LiveAlert (all
      required fields, risk_reward from stop/target, time_window="premarket",
      live regime, priority from score, trigger/win prob from setup base rate).
      All 7 broken premarket constructors now call it.
    - _process_new_alert(): TQS-grade any UNenriched alert (premarket + non-RTH
      paths) — RTH alerts already enriched upstream (tqs_score>0) are skipped.
      Gated by PREMARKET_TQS_ENABLED (default ON); enrich is fully try/except.
  grade_calibration.py
    - Keep the v228 percentile reference RTH-PURE: exclude time_window in
      {premarket, closed} so premarket gappers are GRADED AGAINST RTH norms
      (an "A premarket" = it'd be an A intraday) without skewing the reference.
  tests/test_v19_34_231_premarket_tqs.py — new pytest (13 cases).

SAFE DELIVERY: full-file replace via base64 (curl-downloaded, never pasted).
  * IDEMPOTENT (skips files already carrying the v19.34.231 marker).
  * ANCHOR-GUARDED (won't overwrite a diverged file; aborts cleanly).
  * Prints `git diff --stat`, auto-commits + pushes (survives `git checkout -- .`).

USAGE on the DGX:
    curl -s https://paste.rs/XXXX -o /tmp/deploy_v231.py
    python3 /tmp/deploy_v231.py
    # then: .venv/bin/python -m pytest backend/tests/test_v19_34_231_premarket_tqs.py -q
    #       ./start_backend.sh --force
"""
import base64
import gzip
import json
import os
import subprocess
import sys

MARKER = "v19.34.231"

PAYLOAD = json.loads(r"""'''

FOOTER = '''

def find_repo_root() -> str:
    cands = []
    if len(sys.argv) > 1:
        cands.append(os.path.abspath(sys.argv[1]))
    cands += [os.getcwd(), os.path.dirname(os.path.abspath(__file__)),
              os.path.expanduser("~/Trading-and-Analysis-Platform")]
    seen = set()
    for start in cands:
        cur = start
        for _ in range(8):
            if cur in seen:
                break
            seen.add(cur)
            if os.path.isfile(os.path.join(cur, "backend", "server.py")):
                return cur
            p = os.path.dirname(cur)
            if p == cur:
                break
            cur = p
    raise SystemExit("ERROR: repo root not found. Pass it: python3 deploy_v231.py /path/to/repo")


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)


def main():
    repo = find_repo_root()
    print("== v19.34.231 premarket repair + TQS grading deploy ==")
    print("repo root:", repo)
    plan = []
    for rel, meta in PAYLOAD.items():
        ap = os.path.join(repo, rel)
        data = base64.b64decode(meta["b64"])
        if meta.get("gz"):
            data = gzip.decompress(data)
        if meta.get("new_file"):
            plan.append((ap, data, "new"))
            continue
        if not os.path.isfile(ap):
            raise SystemExit(f"ABORT: expected file missing: {ap}")
        cur = open(ap, "r", encoding="utf-8", errors="replace").read()
        if MARKER in cur:
            print(f"  - SKIP (already patched): {rel}")
            continue
        for anc in meta["anchors"]:
            if anc not in cur:
                raise SystemExit(
                    f"ABORT: anchor not found in {rel!r}:\\n    {anc!r}\\n"
                    "  File diverged from the expected base. Nothing written."
                )
        plan.append((ap, data, "patch"))

    if not plan:
        print("Nothing to do — all files already at v19.34.231.")
        return

    for ap, data, kind in plan:
        os.makedirs(os.path.dirname(ap), exist_ok=True)
        with open(ap, "wb") as f:
            f.write(data)
        if kind != "new" and MARKER not in open(ap, encoding="utf-8").read():
            raise SystemExit(f"ABORT: marker missing after write in {ap}")
        print(f"  - wrote ({kind}): {os.path.relpath(ap, repo)}")

    print("\\n=== git diff --stat ===")
    print(git(repo, "--no-pager", "diff", "--stat").stdout.strip() or "(none)")
    git(repo, "add", "-A")
    if git(repo, "status", "--porcelain").stdout.strip():
        msg = ("v19.34.231: repair premarket scanner (schema-valid alert factory) "
               "+ TQS-grade premarket; keep calibration reference RTH-pure")
        c = git(repo, "commit", "-m", msg)
        print("  - commit:\\n    " + (c.stdout or c.stderr).strip().replace("\\n", "\\n    "))
        p = git(repo, "push")
        print("  - push:\\n    " + (p.stdout or p.stderr).strip().replace("\\n", "\\n    "))
    else:
        print("  - git: nothing to commit")

    print("\\nNEXT STEPS:")
    print("  1) .venv/bin/python -m pytest backend/tests/test_v19_34_231_premarket_tqs.py -q   (expect 13 passed)")
    print("  2) ./start_backend.sh --force")
    print("  3) Tomorrow premarket: watch the log for 'Pre-market scan: N symbols, M morning watchlist alerts'")
    print("     (M should be > 0 now), then python3 /tmp/diag_tqs_today.py to see them graded.")
    print("\\nRevert: set PREMARKET_TQS_ENABLED=0 in backend/.env + restart (disables only the grading;")
    print("the premarket alert REPAIR is structural and stays).")


if __name__ == "__main__":
    main()
'''

with open("/app/deploy_v19_34_231_premarket_tqs.py", "w") as f:
    f.write(HEADER)
    f.write(json.dumps(payload, indent=0))
    f.write('""")\n')
    f.write(FOOTER)
print("wrote /app/deploy_v19_34_231_premarket_tqs.py")
