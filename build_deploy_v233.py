#!/usr/bin/env python3
"""
Generator for the v19.34.233 (Phase D) DGX deploy script.

Run locally (in /app):  python3 build_deploy_v233.py
  -> writes /tmp/deploy_v233.py  (self-contained, stdlib-only)

Then upload to paste.rs and hand the operator the one-liner. The generated
deploy script embeds FULL FILE CONTENTS (gzip+base64), writes them
idempotently (SKIP when identical), then `git add/commit/push` — committing
is mandatory because the DGX `.bat` restart runs `git checkout -- .` which
would otherwise wipe uncommitted work.
"""
import base64
import gzip
import os

REPO = "/app"

FILES = [
    "backend/services/gameplan_edge_ranker.py",          # NEW
    "backend/services/gameplan_service.py",              # PATCH
    "backend/models/learning_models.py",                 # PATCH
    "backend/services/learning_loop_service.py",         # PATCH
    "backend/tests/test_v19_34_233_gameplan_edge_rank.py",  # NEW
    "frontend/src/components/sentcom/v5/GamePlanStockCard.jsx",  # PATCH
]

COMMIT_MSG = (
    "v19.34.233: Phase D — rank Game Plan stocks-in-play by REALIZED "
    "open-session edge (EV-R from trade_outcomes, bucketed by "
    "setup+catalyst+gap+regime with shrinkage walk) blended with TQS; "
    "cold-start falls back to TQS order. Persist catalyst_tag+gap_pct on "
    "trade_outcomes. Surface #edge_rank badge on GamePlanStockCard."
)


def _pack(path: str) -> str:
    with open(os.path.join(REPO, path), "rb") as f:
        raw = f.read()
    return base64.b64encode(gzip.compress(raw, 9)).decode("ascii")


def main() -> None:
    payload = {p: _pack(p) for p in FILES}

    lines = []
    lines.append("#!/usr/bin/env python3")
    lines.append('"""v19.34.233 (Phase D) deploy — idempotent full-file writer + git push."""')
    lines.append("import base64, gzip, os, subprocess, sys")
    lines.append("")
    lines.append("FILES = [")
    for p in FILES:
        lines.append(f"    {p!r},")
    lines.append("]")
    lines.append("")
    lines.append("PAYLOAD = {")
    for p, b in payload.items():
        lines.append(f"    {p!r}: {b!r},")
    lines.append("}")
    lines.append("")
    lines.append(f"COMMIT_MSG = {COMMIT_MSG!r}")
    lines.append("")
    lines.append("""
def repo_root():
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True).strip()
        return out
    except Exception:
        return os.getcwd()


def main():
    root = repo_root()
    print("== v19.34.233 Phase D deploy ==")
    print("repo root:", root)
    changed = []
    for path in FILES:
        dst = os.path.join(root, path)
        new_bytes = gzip.decompress(base64.b64decode(PAYLOAD[path]))
        existed = os.path.exists(dst)
        if existed:
            with open(dst, "rb") as f:
                cur = f.read()
            if cur == new_bytes:
                print(f"  - SKIP (identical): {path}")
                continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(new_bytes)
        changed.append(path)
        print(f"  - wrote ({'patch' if existed else 'new'}): {path}")

    if not changed:
        print("\\nNothing changed — already at v19.34.233.")
        return

    print("\\n=== git diff --stat ===")
    subprocess.run(["git", "-C", root, "add"] + FILES, check=False)
    subprocess.run(["git", "-C", root, "diff", "--cached", "--stat"], check=False)

    print("\\n  - commit:")
    rc = subprocess.run(["git", "-C", root, "commit", "-m", COMMIT_MSG], check=False)
    if rc.returncode != 0:
        print("    (commit returned non-zero — maybe nothing staged; continuing)")
    print("  - push:")
    subprocess.run(["git", "-C", root, "push"], check=False)

    print('''
NEXT STEPS:
  1) .venv/bin/python -m pytest \\
       backend/tests/test_v19_34_231_premarket_tqs.py \\
       backend/tests/test_v19_34_232_catalyst_classifier.py \\
       backend/tests/test_v19_34_233_gameplan_edge_rank.py -q
     (expect 32 passed)
  2) cd frontend && yarn build && cd ..   # GamePlanStockCard edge badge
  3) ./start_backend.sh --force
  4) Next gameplan build (premarket): stocks-in-play are now ordered by
     realized edge. Each name carries edge_rank / edge_source
     (realized|tqs_fallback) / edge_ev_r / edge_sample_size. The V5
     GamePlan card shows a #rank badge (cyan = realized, grey = TQS fallback).

Revert: this is additive ranking + 2 new trade_outcome fields. To disable
the re-ordering, comment the GamePlanEdgeRanker block in
backend/services/gameplan_service.py::_auto_populate_game_plan and rebuild.
''')


if __name__ == "__main__":
    main()
""")

    out_path = "/tmp/deploy_v233.py"
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"wrote {out_path} ({os.path.getsize(out_path)} bytes)")
    print(f"packed {len(FILES)} files")


if __name__ == "__main__":
    main()
