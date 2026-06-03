#!/usr/bin/env python3
"""Generator for deploy_v19_34_232_catalyst_tags.py (gzip+base64 superset payload)."""
import json

with open("/tmp/v232_payload.json") as f:
    payload = json.load(f)

HEADER = '''#!/usr/bin/env python3
"""
deploy_v19_34_232_catalyst_tags.py

v19.34.232 (task B) — Catalyst classification for premarket gappers + surface on
the Game Plan. SUPERSET deploy: also carries v19.34.231 (premarket scanner repair
+ TQS grading) so a single run brings everything since v230 — safe whether or not
the separate v231 deploy was already applied (byte-identical files are skipped).

WHAT B ADDS:
  • NEW services/catalyst_classifier_service.py — categorical tag answering "why
    is it gapping?": earnings | analyst | news | sympathy | no_catalyst.
    Composes EXISTING plumbing (earnings_calendar Mongo collection, NewsService,
    sector classifier) — NO new integration; ZERO hot-path Finnhub calls (earnings
    read from Mongo; per-symbol news cached 30 min, IB-first).
  • enhanced_scanner.py — LiveAlert.catalyst_tag/catalyst_summary fields; lazy
    classifier; premarket alerts classified in _process_new_alert (informational
    only in v1; fail-open). Plus all v231 premarket repair + TQS grading.
  • gameplan_service.py — stocks-in-play now carries catalyst_tag/summary AND the
    premarket tqs_score/tqs_grade (enrich the Game Plan you already use).
  • grade_calibration.py — (v231) keep the percentile reference RTH-pure.
  • tests — v231 (13) + v232 (9) pytest.

Env flags (default ON; revert via env + restart, no redeploy):
  CATALYST_TAGGING_ENABLED, PREMARKET_TQS_ENABLED
Tunables: CATALYST_NEWS_TTL_SEC=1800, CATALYST_EARN_TTL_SEC=1800.

SAFE DELIVERY: gzip+base64 full-file replace (curl-downloaded, never pasted).
  * BYTE-IDEMPOTENT (skips any file whose content already matches — so re-runs and
    an already-applied v231 are both no-ops for those files).
  * ANCHOR-GUARDED (won't overwrite a diverged existing file; aborts cleanly).
  * Prints `git diff --stat`, auto-commits + pushes (survives `git checkout -- .`).

USAGE on the DGX:
    curl -s https://paste.rs/XXXX -o /tmp/deploy_v232.py
    python3 /tmp/deploy_v232.py
    .venv/bin/python -m pytest backend/tests/test_v19_34_231_premarket_tqs.py backend/tests/test_v19_34_232_catalyst_classifier.py -q
    ./start_backend.sh --force
"""
import base64
import gzip
import json
import os
import subprocess
import sys

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
    raise SystemExit("ERROR: repo root not found. Pass it: python3 deploy_v232.py /path/to/repo")


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)


def main():
    repo = find_repo_root()
    print("== v19.34.232 catalyst tags (+v231 superset) deploy ==")
    print("repo root:", repo)
    plan = []
    for rel, meta in PAYLOAD.items():
        ap = os.path.join(repo, rel)
        data = base64.b64decode(meta["b64"])
        if meta.get("gz"):
            data = gzip.decompress(data)
        exists = os.path.isfile(ap)
        if exists and open(ap, "rb").read() == data:
            print(f"  - SKIP (identical): {rel}")
            continue
        if meta.get("new_file"):
            plan.append((ap, data, "new"))
            continue
        if not exists:
            raise SystemExit(f"ABORT: expected existing file missing: {ap}")
        cur = open(ap, "r", encoding="utf-8", errors="replace").read()
        for anc in meta["anchors"]:
            if anc not in cur:
                raise SystemExit(
                    f"ABORT: anchor not found in {rel!r}:\\n    {anc!r}\\n"
                    "  File diverged from the expected base. Nothing written."
                )
        plan.append((ap, data, "patch"))

    if not plan:
        print("Nothing to do — everything already up to date.")
        return

    for ap, data, kind in plan:
        os.makedirs(os.path.dirname(ap), exist_ok=True)
        with open(ap, "wb") as f:
            f.write(data)
        print(f"  - wrote ({kind}): {os.path.relpath(ap, repo)}")

    print("\\n=== git diff --stat ===")
    print(git(repo, "--no-pager", "diff", "--stat").stdout.strip() or "(none)")
    git(repo, "add", "-A")
    if git(repo, "status", "--porcelain").stdout.strip():
        msg = ("v19.34.232: catalyst classification for premarket gappers + "
               "surface on Game Plan (superset incl v231 premarket repair/TQS)")
        c = git(repo, "commit", "-m", msg)
        print("  - commit:\\n    " + (c.stdout or c.stderr).strip().replace("\\n", "\\n    "))
        p = git(repo, "push")
        print("  - push:\\n    " + (p.stdout or p.stderr).strip().replace("\\n", "\\n    "))
    else:
        print("  - git: nothing to commit")

    print("\\nNEXT STEPS:")
    print("  1) .venv/bin/python -m pytest backend/tests/test_v19_34_231_premarket_tqs.py "
          "backend/tests/test_v19_34_232_catalyst_classifier.py -q   (expect 22 passed)")
    print("  2) ./start_backend.sh --force")
    print("  3) Tomorrow premarket: the Game Plan stocks-in-play will show a catalyst_tag")
    print("     (earnings/analyst/news/sympathy/no_catalyst) + tqs_grade per name.")
    print("\\nRevert: CATALYST_TAGGING_ENABLED=0 (and/or PREMARKET_TQS_ENABLED=0) in backend/.env + restart.")


if __name__ == "__main__":
    main()
'''

with open("/app/deploy_v19_34_232_catalyst_tags.py", "w") as f:
    f.write(HEADER)
    f.write(json.dumps(payload, indent=0))
    f.write('""")\n')
    f.write(FOOTER)
print("wrote /app/deploy_v19_34_232_catalyst_tags.py")
