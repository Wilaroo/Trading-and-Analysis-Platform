#!/usr/bin/env python3
"""Prepend a one-line v382 marker to memory/CHANGELOG.md (idempotent). Run from repo root."""
from pathlib import Path
f = Path("memory/CHANGELOG.md"); t = f.read_text()
LINE = ("## 2026-06-18 v382 — v379 (smart_filter grade-gate) + v381 (dedup post-trade) LIVE-VERIFIED "
        "(dedup_cooldown 92.9%->0; borderline TQS gate gone). Path B probe diag_v382 shipped (paste.rs/qBmJu).\n\n")
if "v382 —" in t:
    print("already present — skip")
else:
    f.write_text(LINE + t); print("prepended v382 line to CHANGELOG")
