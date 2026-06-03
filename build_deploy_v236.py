#!/usr/bin/env python3
"""Generator for the v19.34.236 (Part A) DGX deploy — pending fill attribution.
Run locally: python3 build_deploy_v236.py -> /tmp/deploy_v236.py.
The promoter is FLAG-GATED (PENDING_FILL_ATTRIBUTION_ENABLED, default OFF), so
this deploy is INERT until the operator enables it at the close."""
import base64
import gzip
import os

REPO = "/app"
FILES = [
    "backend/services/pending_fill_attribution.py",                  # NEW (pure matcher)
    "backend/services/trading_bot_service.py",                       # PATCH (flag-gated promoter + reaper-loop call)
    "backend/tests/test_v19_34_236_pending_fill_attribution.py",     # NEW
]
COMMIT_MSG = (
    "v19.34.236 (Part A): pending fill attribution (ON by default). "
    "When an entry actually fills at IB but the fill isn't attributed back "
    "(entry_order_id=None race), the reaper tick now MATCHES the live IB "
    "orphan to its original PENDING row and PROMOTES it to OPEN (preserving "
    "entered_by=bot_fired/setup/TQS), instead of falsely rejecting it and "
    "letting the reconciler re-adopt the shares as a synthetic slice. Submits "
    "NO orders — leaves the promoted trade for the v235-clamped naked-sweep to "
    "protect. Disable via PENDING_FILL_ATTRIBUTION_ENABLED=0."
)


def _pack(path):
    with open(os.path.join(REPO, path), "rb") as f:
        return base64.b64encode(gzip.compress(f.read(), 9)).decode("ascii")


def main():
    payload = {p: _pack(p) for p in FILES}
    L = ["#!/usr/bin/env python3",
         '"""v19.34.236 deploy — idempotent full-file writer + git push."""',
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
    print("== v19.34.236 (Part A) pending-fill-attribution deploy ==")
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
        print("\\nNothing changed — already at v19.34.236.")
        return

    print("\\n=== git diff --stat ===")
    subprocess.run(["git", "-C", r, "add"] + FILES, check=False)
    subprocess.run(["git", "-C", r, "diff", "--cached", "--stat"], check=False)
    print("\\n  - commit:")
    subprocess.run(["git", "-C", r, "commit", "-m", COMMIT_MSG], check=False)
    print("  - push:")
    subprocess.run(["git", "-C", r, "push"], check=False)

    print('''
NEXT STEPS:
  1) .venv/bin/python -m pytest backend/tests/test_v19_34_236_pending_fill_attribution.py -q   # expect 12 passed
  2) ./start_backend.sh --force        # deploys + ENABLES it (ON by default)
  3) Watch it work the next time a fill goes unattributed:
       grep "v19.34.236" /tmp/backend.log
       # Mongo audit:  db.state_integrity_events.find({event:"pending_fill_attributed"})
     A promoted name shows up in _open_trades with entered_by=bot_fired (NOT a
     reconciled_excess slice) and the v235-clamped naked-sweep protects it.

Disable instantly: set PENDING_FILL_ATTRIBUTION_ENABLED=0 in backend/.env + restart.
Notes: matcher requires pre_submit age 30s..3600s, same symbol+direction, and
order size that could produce the fill. Promoter submits NO orders.
''')


if __name__ == "__main__":
    main()
""")
    with open("/tmp/deploy_v236.py", "w") as f:
        f.write("\n".join(L))
    print(f"wrote /tmp/deploy_v236.py ({os.path.getsize('/tmp/deploy_v236.py')} bytes); packed {len(FILES)} files")


if __name__ == "__main__":
    main()
