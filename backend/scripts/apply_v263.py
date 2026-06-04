#!/usr/bin/env python3
"""
apply_v263.py — idempotent deployer for v19.34.263 (external scalp-exit reclass).

Writes 4 files into the repo, each guarded + backed up + compile-validated:
  backend/services/trade_outcome_hygiene.py   (+ reclassify_external_exit)
  backend/services/pnl_compute.py             (effective_close_reason stamp)
  backend/services/learning_reconciler.py     (+ reprocess_external_closes)
  backend/tests/test_v19_34_263_external_exit_reclass.py

Safe by design:
  - idempotent: skips a file whose v263 marker is already present.
  - base-guard: refuses to overwrite a file that doesn't look like the
    expected pre-v263 version (prints a warning instead of corrupting).
  - backs up every changed file to <path>.bak_v263 and ROLLS BACK if the
    new content fails py_compile.

Run from the repo root:
    curl -s <this-url> | python3 -
Then restart the backend and run the backfill (backfill_v263.py).
Does NOT touch git — commit via your normal flow once verified.
"""
from __future__ import annotations
import os
import py_compile
import shutil
import sys
import urllib.request
from pathlib import Path

FILES = [
    # (url, rel_path, applied_marker, base_anchor)
    ("https://paste.rs/IFs6q", "backend/services/trade_outcome_hygiene.py",
     "def reclassify_external_exit(", "def classify_close("),
    ("https://paste.rs/Q4bvi", "backend/services/pnl_compute.py",
     '"effective_close_reason"', "_record_alert_outcome_bestEffort"),
    ("https://paste.rs/kVBmN", "backend/services/learning_reconciler.py",
     "def reprocess_external_closes(", "def reconcile("),
    ("https://paste.rs/bsVPc", "backend/tests/test_v19_34_263_external_exit_reclass.py",
     None, None),  # new file → always (idempotent overwrite)
]


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


def main() -> int:
    root = Path.cwd()
    if not (root / "backend").is_dir():
        print(f"ERROR: run from the repo root (no ./backend under {root}).")
        return 2

    print("=" * 70)
    print("v19.34.263 deployer — external scalp-exit reclassification")
    print("=" * 70)
    changed, skipped, failed = 0, 0, 0

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
            print(f"  • {rel}: already at v263 ({marker.strip()[:32]}…) — skip.")
            skipped += 1
            continue
        if anchor and existing and anchor not in existing:
            print(f"  ! {rel}: base anchor '{anchor}' NOT found — SKIPPING to avoid "
                  f"corrupting a drifted file. Patch this one manually.")
            failed += 1
            continue

        bak = path.with_suffix(path.suffix + ".bak_v263")
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
        print("Some files were skipped/failed — review above before restarting.")
        return 1
    print("\nNEXT STEPS:")
    print("  1) Restart the backend so the live path reclassifies new closes:")
    print("       pkill -f 'python server.py'; cd backend && nohup python server.py "
          "> /tmp/backend.log 2>&1 &")
    print("  2) Backfill historical external closes (DRY-RUN first):")
    print("       curl -s https://paste.rs/EzAZK | python3 - --days 30")
    print("     then commit it:")
    print("       curl -s https://paste.rs/EzAZK | python3 - --days 30 --commit")
    print("  3) Optional unit check:")
    print("       cd backend && python -m pytest tests/test_v19_34_263_external_exit_reclass.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
