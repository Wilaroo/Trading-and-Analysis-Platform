#!/usr/bin/env python3
"""
apply_v263_ui.py — idempotent deployer for the v19.34.263 Mission Control
Bot-Edge vs Adopted P&L chip (frontend).

Writes 5 files under frontend/src/, each guarded + backed up:
  components/sentcom/v5/BotEdgeChip.jsx               (NEW)
  components/sentcom/hooks/useSentComPositions.js     (surface split fields)
  components/SentCom.jsx                              (prop drill)
  components/sentcom/SentComV5View.jsx               (prop drill)
  components/sentcom/panels/PipelineHUDV5.jsx        (render chip)

Safe by design:
  - idempotent: skips a file whose v263 marker is already present.
  - base-guard: refuses to overwrite a file that doesn't look like the
    expected base version (prints a warning instead of corrupting).
  - sanity-check: aborts a write whose downloaded marker is missing.
  - backs up every changed file to <path>.bak_v263ui.

Run from the repo root:
    curl -s <this-url> | python3 -
Then rebuild the frontend (yarn build) / let the dev server hot-reload.
Does NOT touch git — commit via your normal flow once verified.
"""
from __future__ import annotations
import shutil
import sys
import urllib.request
from pathlib import Path

SRC = "frontend/src"
FILES = [
    # (url, rel_path_under_src, applied_marker, base_anchor, downloaded_marker)
    ("https://paste.rs/QDfhx", "components/sentcom/v5/BotEdgeChip.jsx",
     None, None, "export const BotEdgeChip"),
    ("https://paste.rs/knXhQ", "components/sentcom/hooks/useSentComPositions.js",
     "botEdgePnlToday", "useSentComPositions", "botEdgePnlToday"),
    ("https://paste.rs/mmr4n", "components/SentCom.jsx",
     "botEdgePnlToday", "useSentComPositions", "botEdgePnlToday"),
    ("https://paste.rs/607zD", "components/sentcom/SentComV5View.jsx",
     "botEdgePnlToday", "PipelineHUDV5", "botEdgePnlToday"),
    ("https://paste.rs/wMzpY", "components/sentcom/panels/PipelineHUDV5.jsx",
     "BotEdgeChip", "pipeline-pnl-block", "BotEdgeChip"),
]


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


def main() -> int:
    root = Path.cwd()
    if not (root / SRC).is_dir():
        print(f"ERROR: run from the repo root (no ./{SRC} under {root}).")
        return 2

    print("=" * 70)
    print("v19.34.263 UI deployer — Bot-Edge vs Adopted P&L chip")
    print("=" * 70)
    changed, skipped, failed = 0, 0, 0

    for url, rel, marker, anchor, dl_marker in FILES:
        path = root / SRC / rel
        try:
            new_content = _fetch(url)
        except Exception as e:
            print(f"  ✗ {rel}: download failed: {e}")
            failed += 1
            continue

        if dl_marker and dl_marker not in new_content:
            print(f"  ✗ {rel}: downloaded content missing '{dl_marker}' "
                  f"(bad/expired paste) — skipping.")
            failed += 1
            continue

        existing = path.read_text() if path.exists() else ""
        if marker and marker in existing:
            print(f"  • {rel}: already at v263 — skip.")
            skipped += 1
            continue
        if anchor and existing and anchor not in existing:
            print(f"  ! {rel}: base anchor '{anchor}' NOT found — SKIPPING to avoid "
                  f"corrupting a drifted file. Patch this one manually.")
            failed += 1
            continue

        bak = path.with_suffix(path.suffix + ".bak_v263ui")
        if path.exists() and not bak.exists():
            shutil.copy2(path, bak)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_content)
        print(f"  ✓ {rel}: written ({'backup: ' + bak.name if path.exists() else 'new'})")
        changed += 1

    print("-" * 70)
    print(f"changed={changed}  skipped={skipped}  failed={failed}")
    if failed:
        print("Some files were skipped/failed — review above before rebuilding.")
        return 1
    print("\nNEXT STEPS:")
    print("  1) Rebuild the frontend (or let the dev server hot-reload):")
    print("       cd frontend && yarn build   # or: yarn start")
    print("  2) Open Mission Control — the P&L tile now shows a second line:")
    print("       Bot <bot-edge>  ·  Adopted <adopted-pnl>")
    print("     (data-testid: bot-edge-chip / bot-edge-value / adopted-pnl-value)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
