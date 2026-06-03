#!/usr/bin/env python3
"""Generator for the v19.34.235 (Part B) DGX deploy — bracket-size clamp.
Run locally: python3 build_deploy_v235.py -> /tmp/deploy_v235.py."""
import base64
import gzip
import os

REPO = "/app"
FILES = [
    "backend/services/ib_direct_service.py",                 # PATCH (clamp helper + live_position_abs + place_oca_stop_target)
    "backend/services/trade_executor_service.py",            # PATCH (queue-path clamp)
    "backend/tests/test_v19_34_235_bracket_clamp.py",        # NEW
]
COMMIT_MSG = (
    "v19.34.235 (Part B): bracket-size clamp. Every OCA stop+target re-issue "
    "now clamps its qty to the LIVE IB position (clamp_protective_qty + "
    "live_position_abs) so a stale trade.shares can never arm a closing order "
    "larger than the position holds (the SOXX Sell-43-vs-17 flip hazard, "
    "2026-06-03). Only ever shrinks to a confirmed smaller position; fail-open "
    "when the live size is unknown. Scoped to the adoption/re-issue protective "
    "paths (place_oca_stop_target direct + attach_oca_stop_target queue) — the "
    "two-step entry stop is intentionally untouched."
)


def _pack(path):
    with open(os.path.join(REPO, path), "rb") as f:
        return base64.b64encode(gzip.compress(f.read(), 9)).decode("ascii")


def main():
    payload = {p: _pack(p) for p in FILES}
    L = ["#!/usr/bin/env python3",
         '"""v19.34.235 deploy — idempotent full-file writer + git push."""',
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
    print("== v19.34.235 (Part B) bracket-clamp deploy ==")
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
        print("\\nNothing changed — already at v19.34.235.")
        return

    print("\\n=== git diff --stat ===")
    subprocess.run(["git", "-C", r, "add"] + FILES, check=False)
    subprocess.run(["git", "-C", r, "diff", "--cached", "--stat"], check=False)
    print("\\n  - commit:")
    subprocess.run(["git", "-C", r, "commit", "-m", COMMIT_MSG], check=False)
    print("  - push:")
    subprocess.run(["git", "-C", r, "push"], check=False)

    print('''
NEXT STEPS (scanner paused, only BE 29 open — safe window):
  1) .venv/bin/python -m pytest backend/tests/test_v19_34_235_bracket_clamp.py -q   # expect 6 passed
  2) ./start_backend.sh --force
  3) Sanity: BE's bracket should re-attach at 29 (no clamp, since live==requested).
     Watch for any clamp firing:  grep "v19.34.235 clamp" /tmp/backend.log
  4) Confirm BE still protected in TWS (STP+LMT both qty 29).

Revert: git revert this commit (the clamp is additive; helper defaults fail-open).
''')


if __name__ == "__main__":
    main()
""")
    with open("/tmp/deploy_v235.py", "w") as f:
        f.write("\n".join(L))
    print(f"wrote /tmp/deploy_v235.py ({os.path.getsize('/tmp/deploy_v235.py')} bytes); packed {len(FILES)} files")


if __name__ == "__main__":
    main()
