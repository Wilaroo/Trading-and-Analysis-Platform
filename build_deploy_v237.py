#!/usr/bin/env python3
"""Generator for the v19.34.237 DGX deploy — Phase D follow-up B:
direction-aware edge buckets + coverage audit. Run: python3 build_deploy_v237.py"""
import base64
import gzip
import os

REPO = "/app"
FILES = [
    "backend/services/gameplan_edge_ranker.py",              # PATCH (direction dim + coverage_summary)
    "backend/tests/test_v19_34_237_edge_direction.py",       # NEW
]
COMMIT_MSG = (
    "v19.34.237 (Phase D follow-up B): direction-aware realized-edge buckets. "
    "Every edge bucket key (L1-L4) now includes trade direction (long/short) "
    "since a setup's realized EV differs by side — long history no longer "
    "leaks into a short setup's score. Adds GamePlanEdgeRanker.coverage_summary() "
    "to audit how often the fine L4/L3 catalyst+gap+direction buckets fire vs "
    "falling back to L2/L1 as history accrues."
)


def _pack(path):
    with open(os.path.join(REPO, path), "rb") as f:
        return base64.b64encode(gzip.compress(f.read(), 9)).decode("ascii")


def main():
    payload = {p: _pack(p) for p in FILES}
    L = ["#!/usr/bin/env python3",
         '"""v19.34.237 deploy — idempotent full-file writer + git push."""',
         "import base64, gzip, os, subprocess", "", "FILES = ["]
    for p in FILES:
        L.append(f"    {p!r},")
    L.append("]")
    L.append("")
    L.append("PAYLOAD = {")
    for p, b in payload.items():
        L.append(f"    {p!r}: {b!r},")
    L.append("}")
    L.append("")
    L.append(f"COMMIT_MSG = {COMMIT_MSG!r}")
    L.append("""

def root():
    try:
        return subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    except Exception:
        return os.getcwd()


def main():
    r = root()
    print("== v19.34.237 (Phase D follow-up B) deploy ==")
    print("repo root:", r)
    changed = []
    for path in FILES:
        dst = os.path.join(r, path)
        new = gzip.decompress(base64.b64decode(PAYLOAD[path]))
        existed = os.path.exists(dst)
        if existed:
            with open(dst, "rb") as f:
                if f.read() == new:
                    print(f"  - SKIP (identical): {path}")
                    continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(new)
        changed.append(path)
        print(f"  - wrote ({'patch' if existed else 'new'}): {path}")

    if not changed:
        print("\\nNothing changed — already at v19.34.237.")
        return

    print("\\n=== git diff --stat ===")
    subprocess.run(["git", "-C", r, "add"] + FILES, check=False)
    subprocess.run(["git", "-C", r, "diff", "--cached", "--stat"], check=False)
    print("\\n  - commit:")
    subprocess.run(["git", "-C", r, "commit", "-m", COMMIT_MSG], check=False)
    print("  - push:")
    subprocess.run(["git", "-C", r, "push"], check=False)

    print('''
NEXT STEPS (backend-only; not safety-critical, deploy anytime):
  1) .venv/bin/python -m pytest backend/tests/test_v19_34_237_edge_direction.py \\
       backend/tests/test_v19_34_233_gameplan_edge_rank.py -q   # expect 15 passed
  2) ./start_backend.sh --force
  3) Next premarket Game Plan: stocks-in-play ranked by direction-aware edge.
     Coverage audit available via GamePlanEdgeRanker.from_db(db).coverage_summary().

Revert: git revert this commit (pure ranking change; no trading-path impact).
''')


if __name__ == "__main__":
    main()
""")
    with open("/tmp/deploy_v237.py", "w") as f:
        f.write("\n".join(L))
    print(f"wrote /tmp/deploy_v237.py ({os.path.getsize('/tmp/deploy_v237.py')} bytes); packed {len(FILES)} files")


if __name__ == "__main__":
    main()
