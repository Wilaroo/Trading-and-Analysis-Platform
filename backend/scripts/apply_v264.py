#!/usr/bin/env python3
"""
apply_v264.py — idempotent deployer for v19.34.264 (orphan-vs-pending guard).

Writes 2 files, guarded + backed up + compile-validated:
  backend/services/position_reconciler.py   (widen v185 to _pending_trades +
                                              add v264 pending-fill match skip)
  backend/tests/test_v19_34_264_orphan_pending_guard.py

Safe by design: idempotent (skips if v264 marker present), base-anchor guard
(refuses to overwrite a drifted file), backup to <path>.bak_v264, ROLLBACK on
compile failure.

Run from repo root:   curl -s <this-url> | python3 -
Then restart the backend. Does NOT touch git.
"""
from __future__ import annotations
import py_compile
import shutil
import sys
import urllib.request
from pathlib import Path

FILES = [
    # (url, rel_path, applied_marker, base_anchor)
    ("https://paste.rs/e0XxD", "backend/services/position_reconciler.py",
     "v19.34.264 — Pending-fill match guard", "v19.34.260 — EOD-window"),
    ("https://paste.rs/iHwfB", "backend/tests/test_v19_34_264_orphan_pending_guard.py",
     None, None),
]


def _fetch(url):
    with urllib.request.urlopen(url, timeout=40) as r:
        return r.read().decode("utf-8")


def main():
    root = Path.cwd()
    if not (root / "backend").is_dir():
        print(f"ERROR: run from the repo root (no ./backend under {root}).")
        return 2
    print("=" * 70)
    print("v19.34.264 deployer — orphan-vs-pending guard")
    print("=" * 70)
    changed = skipped = failed = 0

    for url, rel, marker, anchor in FILES:
        path = root / rel
        try:
            new_content = _fetch(url)
        except Exception as e:
            print(f"  ✗ {rel}: download failed: {e}")
            failed += 1
            continue
        existing = path.read_text() if path.exists() else ""
        if marker and marker in existing:
            print(f"  • {rel}: already at v264 — skip.")
            skipped += 1
            continue
        if anchor and existing and anchor not in existing:
            print(f"  ! {rel}: base anchor '{anchor}' NOT found — SKIPPING to "
                  f"avoid corrupting a drifted file. Patch manually.")
            failed += 1
            continue
        bak = path.with_suffix(path.suffix + ".bak_v264")
        if path.exists() and not bak.exists():
            shutil.copy2(path, bak)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_content)
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            print(f"  ✗ {rel}: compile FAILED, rolling back: {e}")
            if bak.exists():
                shutil.copy2(bak, path)
            failed += 1
            continue
        print(f"  ✓ {rel}: written + compiled (backup: {bak.name})")
        changed += 1

    print("-" * 70)
    print(f"changed={changed}  skipped={skipped}  failed={failed}")
    if failed:
        print("Some files skipped/failed — review before restarting.")
        return 1
    print("\nNEXT STEPS:")
    print("  1) Restart backend:")
    print("       pkill -f 'python server.py'")
    print("       ( cd backend && nohup python server.py > /tmp/backend.log 2>&1 & )")
    print("  2) Re-attribute today's two mis-adopted orphans (DRY-RUN then commit):")
    print("       curl -s https://paste.rs/TenGz | python3 -")
    print("       curl -s https://paste.rs/TenGz | python3 - --commit")
    print("  3) Optional unit check:")
    print("       cd backend && python -m pytest "
          "tests/test_v19_34_264_orphan_pending_guard.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
