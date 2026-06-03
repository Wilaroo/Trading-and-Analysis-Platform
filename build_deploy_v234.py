#!/usr/bin/env python3
"""Generator for the v19.34.234 DGX deploy script (reaper fill-race guard +
truth-diff remaining_shares fix). Run locally: python3 build_deploy_v234.py
-> /tmp/deploy_v234.py (self-contained, stdlib-only, idempotent, git push)."""
import base64
import gzip
import os

REPO = "/app"
FILES = [
    "backend/services/trading_bot_service.py",                  # PATCH (reaper guard + helper)
    "backend/routers/trading_bot.py",                           # PATCH (truth-diff remaining_shares)
    "backend/tests/test_v19_34_234_reaper_fill_guard.py",       # NEW
]
COMMIT_MSG = (
    "v19.34.234: stop the bot-vs-IB drift at its source. "
    "(1) Pending-reaper fill-race guard: never reap a stale 'pending' whose "
    "symbol still shows a live IB position the bot isn't tracking as open "
    "(the entry_order_id=None unattributed-fill race that orphaned "
    "SOXX/LRCX/ALAB/ASTS on 2026-06-03) — skip + log + state_integrity_event "
    "instead of falsely marking the real fill 'rejected'. "
    "(2) truth-diff now compares IB against remaining_shares (live) instead of "
    "stale .shares, which had falsely flagged SOXX 43-vs-17 while the tracked "
    "position (17) actually matched IB."
)


def _pack(path):
    with open(os.path.join(REPO, path), "rb") as f:
        return base64.b64encode(gzip.compress(f.read(), 9)).decode("ascii")


def main():
    payload = {p: _pack(p) for p in FILES}
    L = []
    L.append("#!/usr/bin/env python3")
    L.append('"""v19.34.234 deploy — idempotent full-file writer + git push."""')
    L.append("import base64, gzip, os, subprocess")
    L.append("")
    L.append("FILES = [")
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
    print("== v19.34.234 deploy ==")
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
        print("\\nNothing changed — already at v19.34.234.")
        return

    print("\\n=== git diff --stat ===")
    subprocess.run(["git", "-C", r, "add"] + FILES, check=False)
    subprocess.run(["git", "-C", r, "diff", "--cached", "--stat"], check=False)
    print("\\n  - commit:")
    subprocess.run(["git", "-C", r, "commit", "-m", COMMIT_MSG], check=False)
    print("  - push:")
    subprocess.run(["git", "-C", r, "push"], check=False)

    print('''
NEXT STEPS (bot is FLAT — safe window):
  1) .venv/bin/python -m pytest backend/tests/test_v19_34_234_reaper_fill_guard.py -q   # expect 5 passed
  2) ./start_backend.sh --force        # ~30s restart; applies the Python changes
  3) Verify after boot:
       curl -s 'http://localhost:8001/api/trading-bot/positions/truth-diff' | python3 -m json.tool
     -> bot_count/ib_count should match; no false 'share_mismatch' from stale .shares.
  4) Watch the reaper guard in action (next time a fill isn't attributed):
       grep -E "reaper-guard|reaper_skip_likely_filled" /tmp/backend.log
     and the new audit trail:  db.state_integrity_events.find({event:"reaper_skip_likely_filled"})

Revert: PENDING_REAPER_ENABLED=0 disables the reaper entirely; or git revert this commit.
NOTE: This is the SOURCE-side guard. The full cure (capture entry_order_id +
attribute execDetails so pendings flip to filled, and clamp bracket re-issue
to live IB qty) is the next, larger change — recommend deploying that with the
bot paused or after the close.
''')


if __name__ == "__main__":
    main()
""")
    with open("/tmp/deploy_v234.py", "w") as f:
        f.write("\n".join(L))
    print(f"wrote /tmp/deploy_v234.py ({os.path.getsize('/tmp/deploy_v234.py')} bytes); packed {len(FILES)} files")


if __name__ == "__main__":
    main()
