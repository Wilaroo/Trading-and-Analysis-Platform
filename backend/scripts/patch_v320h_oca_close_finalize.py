#!/usr/bin/env python3
"""patch_v320h_oca_close_finalize.py  —  v19.34.320h patcher  (2026-06-16)

Finalizes OCA close-path accounting in position_manager.py.

THE BUG (v320h):
  The v19.31 externally-closed phantom sweep (the `oca_closed_externally_v19_31`
  path) marks the trade CLOSED and claims `realized_pnl`, but never finalizes
  `exit_price`, never recomputes `net_pnl` (so it stays at the -$1.00
  commission-min sentinel written by `_apply_commission`), and never refreshes
  `pnl_pct`. Every IB-OCA-closed trade (stops / targets) therefore lands in
  `bot_trades` with corrupt performance metrics (~4 records/hr).

THE FIX:
  Inserts a finalize block immediately BEFORE the `_persist_trade` call in the
  sweep. It:
    1) classifies the close leg (long→SELL, short→BUY),
    2) sources `exit_price` from the matching `ib_executions` fill within ±15m
       of `closed_at` (falls back to last `current_price` mark),
    3) recomputes `net_pnl = realized_pnl - total_commissions`,
    4) recomputes `pnl_pct` off the entry basis (fill_price||entry_price).

  Gated by ENV `V320H_OCA_FIX_POLICY`:
    observe (DEFAULT) — log the would-be finalized values, write nothing.
    fix               — write exit_price / net_pnl / pnl_pct onto the trade.
    off               — skip the block entirely.

AGENTS.md §2.2 COMPLIANCE:
  • PRE_SHA256 guard  : asserts the target file is the canonical baseline.
  • base64 (old,new)  : anchored single-chunk replacement, byte-exact.
  • POST_SHA256 guard : refuses to leave a file whose hash != tested build.
  • auto-backup       : writes a timestamped .bak.* side-file before writing.
  • --check / --apply / --rollback / --status.

LOCAL VALIDATION OVERRIDE:
  Set V320H_PM_TARGET=/path/to/position_manager.py (and/or TAP_REPO_ROOT) to
  point the patcher at a copy for CI/dev validation. On the DGX, leave unset.

DGX DEPLOY (operator):
  curl -sS -o /tmp/patch_v320h.py https://paste.rs/<id>
  .venv/bin/python /tmp/patch_v320h.py --check
  .venv/bin/python /tmp/patch_v320h.py --apply
  # COMMIT BEFORE RESTART (StartTrading.bat git-wipes uncommitted code):
  git add backend/services/position_manager.py && git commit -m "v19.34.320h: OCA close finalize (observe)" && git push origin main
  ./start_backend.sh --force
  # observe a few OCA closes in logs ([v19.34.320h OBSERVE]); when satisfied:
  #   export V320H_OCA_FIX_POLICY=fix   (in the backend env / start script) and restart
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PRE_SHA256 = "ee4f3f2ef837391e4b563b0a6dc48b0860c4b6b0fa19e2b4203f226f89117977"
POST_SHA256 = "e5cec8f958e9a26477d8d3fb1f0e7814e9b268c39013d49cf31640c161787d0e"

REPO_ROOT = Path(os.environ.get("TAP_REPO_ROOT") or (Path.home() / "Trading-and-Analysis-Platform"))
TARGET = Path(os.environ.get("V320H_PM_TARGET") or (REPO_ROOT / "backend" / "services" / "position_manager.py"))

OLD_B64 = "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF90cmFkZS5yZW1haW5pbmdfc2hhcmVzID0gMAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF3YWl0IGFzeW5jaW8udG9fdGhyZWFkKGJvdC5fcGVyc2lzdF90cmFkZSwgX3RyYWRlKQ=="
NEW_B64 = "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF90cmFkZS5yZW1haW5pbmdfc2hhcmVzID0gMAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAjIOKUgOKUgCB2MTkuMzQuMzIwaCDigJQgT0NBIGNsb3NlLXBhdGggYWNjb3VudGluZyBmaW5hbGl6ZSDilIDilIAgQkVHSU4g4pSA4pSACiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIyBUaGUgdjE5LjMxIGV4dGVybmFsLWNsb3NlIHN3ZWVwIGFib3ZlIG1hcmtzIHRoZSB0cmFkZSBDTE9TRUQgYW5kCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIyBjbGFpbXMgcmVhbGl6ZWRfcG5sLCBidXQgaGlzdG9yaWNhbGx5IGxlZnQgZXhpdF9wcmljZSB1bnNldCwgbmV0X3BubAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICMgc3R1Y2sgYXQgdGhlIC0kMS4wMCBjb21taXNzaW9uLW1pbiBzZW50aW5lbCwgYW5kIHBubF9wY3Qgc3RhbGUuCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIyBTb3VyY2UgZXhpdF9wcmljZSBmcm9tIHRoZSBtYXRjaGluZyBJQiBleGVjdXRpb24gKMKxMTVtIG9mIGNsb3NlKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAjIHJlY29tcHV0ZSBuZXRfcG5sID0gcmVhbGl6ZWRfcG5sIC0gdG90YWxfY29tbWlzc2lvbnMsIGFuZCBwbmxfcGN0CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIyBvZmYgdGhlIGVudHJ5IGJhc2lzLiBHYXRlZCBieSBWMzIwSF9PQ0FfRklYX1BPTElDWQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICMgKG9ic2VydmV8Zml4fG9mZiwgZGVmYXVsdCBvYnNlcnZlKS4KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGltcG9ydCBvcyBhcyBfb3NfdjMyMGgKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX3YzMjBoX3BvbGljeSA9IChfb3NfdjMyMGguZW52aXJvbi5nZXQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiVjMyMEhfT0NBX0ZJWF9QT0xJQ1kiLCAib2JzZXJ2ZSIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBvciAib2JzZXJ2ZSIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBfdjMyMGhfcG9saWN5IG5vdCBpbiAoIm9ic2VydmUiLCAiZml4IiwgIm9mZiIpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX3YzMjBoX3BvbGljeSA9ICJvYnNlcnZlIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBfdjMyMGhfcG9saWN5ICE9ICJvZmYiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2VudHJ5X2Jhc2lzID0gZmxvYXQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZ2V0YXR0cihfdHJhZGUsICJmaWxsX3ByaWNlIiwgTm9uZSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBvciBnZXRhdHRyKF90cmFkZSwgImVudHJ5X3ByaWNlIiwgMCkgb3IgMCkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF92MzIwaF9kaXIgPSBfZGlyCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfY2xvc2Vfc2lkZSA9ICJCVVkiIGlmIF92MzIwaF9kaXIgPT0gInNob3J0IiBlbHNlICJTRUxMIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2V4aXRfcHggPSBOb25lCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfZXhpdF9zcmMgPSBOb25lCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZnJvbSBkYXRldGltZSBpbXBvcnQgZGF0ZXRpbWUgYXMgX2R0X3YzMjBoLCB0aW1lem9uZSBhcyBfdHpfdjMyMGgsIHRpbWVkZWx0YSBhcyBfdGRfdjMyMGgKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfY2xvc2VkX3JhdyA9IGdldGF0dHIoX3RyYWRlLCAiY2xvc2VkX2F0IiwgTm9uZSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKF9jbG9zZWRfcmF3LCBzdHIpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfY2xvc2VkX2R0ID0gX2R0X3YzMjBoLmZyb21pc29mb3JtYXQoX2Nsb3NlZF9yYXcucmVwbGFjZSgiWiIsICIrMDA6MDAiKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBlbGlmIF9jbG9zZWRfcmF3IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfY2xvc2VkX2R0ID0gX2Nsb3NlZF9yYXcKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfY2xvc2VkX2R0ID0gX2R0X3YzMjBoLm5vdyhfdHpfdjMyMGgudXRjKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIF9jbG9zZWRfZHQudHppbmZvIGlzIE5vbmU6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9jbG9zZWRfZHQgPSBfY2xvc2VkX2R0LnJlcGxhY2UodHppbmZvPV90el92MzIwaC51dGMpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2xvID0gKF9jbG9zZWRfZHQgLSBfdGRfdjMyMGgobWludXRlcz0xNSkpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2hpID0gKF9jbG9zZWRfZHQgKyBfdGRfdjMyMGgobWludXRlcz0xNSkpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2RiX3YzMjBoID0gKGdldGF0dHIoYm90LCAiX2RiIiwgTm9uZSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgZ2V0YXR0cihib3QsICJfZGIiLCBOb25lKSBpcyBub3QgTm9uZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBlbHNlIGdldGF0dHIoYm90LCAiZGIiLCBOb25lKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBfZGJfdjMyMGggaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9xID0gewogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgInN5bWJvbCI6IChfdHJhZGUuc3ltYm9sIG9yICIiKS51cHBlcigpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIiRvciI6IFsKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB7InRpbWUiOiB7IiRndGUiOiBfbG8sICIkbHRlIjogX2hpfX0sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgeyJ0aW1lc3RhbXAiOiB7IiRndGUiOiBfbG8sICIkbHRlIjogX2hpfX0sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgeyJleGVjX3RpbWUiOiB7IiRndGUiOiBfbG8sICIkbHRlIjogX2hpfX0sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBdLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB9CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9leGVjcyA9IGF3YWl0IGFzeW5jaW8udG9fdGhyZWFkKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgbGFtYmRhOiBsaXN0KF9kYl92MzIwaFsiaWJfZXhlY3V0aW9ucyJdLmZpbmQoX3EsIHsiX2lkIjogMH0pKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX3dhbnQgPSBpbnQoZ2V0YXR0cihfdHJhZGUsICJzaGFyZXMiLCAwKSBvciAwKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfYmVzdCA9IE5vbmUKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2Jlc3Rfc2NvcmUgPSBOb25lCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZvciBfZXggaW4gX2V4ZWNzOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2VzaWRlID0gc3RyKF9leC5nZXQoInNpZGUiKSBvciBfZXguZ2V0KCJhY3Rpb24iKSBvciAiIikudXBwZXIoKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgX2Nsb3NlX3NpZGUgPT0gIlNFTEwiIGFuZCBub3QgX2VzaWRlLnN0YXJ0c3dpdGgoKCJTIiwpKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgX2Nsb3NlX3NpZGUgPT0gIkJVWSIgYW5kIG5vdCBfZXNpZGUuc3RhcnRzd2l0aCgoIkIiLCkpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfZXB4ID0gZmxvYXQoX2V4LmdldCgicHJpY2UiKSBvciBfZXguZ2V0KCJhdmdfcHJpY2UiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9yIF9leC5nZXQoImZpbGxfcHJpY2UiKSBvciAwKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgX2VweCA8PSAwOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfZXF0eSA9IGludChhYnMoZmxvYXQoX2V4LmdldCgic2hhcmVzIikgb3IgX2V4LmdldCgicXR5Iikgb3IgMCkpKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX3Njb3JlID0gYWJzKF9lcXR5IC0gX3dhbnQpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBfYmVzdF9zY29yZSBpcyBOb25lIG9yIF9zY29yZSA8IF9iZXN0X3Njb3JlOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9iZXN0X3Njb3JlID0gX3Njb3JlCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2Jlc3QgPSBfZXB4CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIF9iZXN0IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX2V4aXRfcHggPSByb3VuZChfYmVzdCwgNCkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9leGl0X3NyYyA9ICJpYl9leGVjdXRpb25zIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBfdjMyMGhfbGs6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgbG9nZ2VyLmRlYnVnKCJbdjE5LjM0LjMyMGhdIGliX2V4ZWN1dGlvbnMgcHJvYmUgdGhyZXc6ICVzIiwgX3YzMjBoX2xrKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgX2V4aXRfcHggaXMgTm9uZToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfY3AgPSBmbG9hdChnZXRhdHRyKF90cmFkZSwgImN1cnJlbnRfcHJpY2UiLCAwKSBvciAwKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIF9jcCA+IDA6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9leGl0X3B4ID0gcm91bmQoX2NwLCA0KQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfZXhpdF9zcmMgPSAiY3VycmVudF9wcmljZV9mYWxsYmFjayIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9uZXdfbmV0ID0gcm91bmQoZmxvYXQoZ2V0YXR0cihfdHJhZGUsICJyZWFsaXplZF9wbmwiLCAwKSBvciAwKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAtIGZsb2F0KGdldGF0dHIoX3RyYWRlLCAidG90YWxfY29tbWlzc2lvbnMiLCAwKSBvciAwKSwgMikKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9uZXdfcGN0ID0gTm9uZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgX2V4aXRfcHggaXMgbm90IE5vbmUgYW5kIF9lbnRyeV9iYXNpcyA+IDA6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgX3YzMjBoX2RpciA9PSAic2hvcnQiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfbmV3X3BjdCA9IHJvdW5kKChfZW50cnlfYmFzaXMgLSBfZXhpdF9weCkgLyBfZW50cnlfYmFzaXMgKiAxMDAsIDQpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX25ld19wY3QgPSByb3VuZCgoX2V4aXRfcHggLSBfZW50cnlfYmFzaXMpIC8gX2VudHJ5X2Jhc2lzICogMTAwLCA0KQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgX3YzMjBoX3BvbGljeSA9PSAiZml4IjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBfZXhpdF9weCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX3RyYWRlLmV4aXRfcHJpY2UgPSBfZXhpdF9weAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF90cmFkZS5uZXRfcG5sID0gX25ld19uZXQKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBfbmV3X3BjdCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX3RyYWRlLnBubF9wY3QgPSBfbmV3X3BjdAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGxvZ2dlci5pbmZvKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAi8J+UpyBbdjE5LjM0LjMyMGggRklYXSAlcyAlcyBmaW5hbGl6ZWQ6IGV4aXRfcHJpY2U9JXMgKCVzKSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJuZXRfcG5sPSUuMmYgcG5sX3BjdD0lcyB0cmFkZV9pZD0lcyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF90cmFkZS5zeW1ib2wsIF92MzIwaF9kaXIudXBwZXIoKSwgX2V4aXRfcHgsIF9leGl0X3NyYywKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX25ld19uZXQsIF9uZXdfcGN0LCBfdHJhZGUuaWQpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGxvZ2dlci5pbmZvKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAi8J+Rge+4jyBbdjE5LjM0LjMyMGggT0JTRVJWRV0gJXMgJXMgd291bGQgZmluYWxpemU6IGV4aXRfcHJpY2U9JXMgKCVzKSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJuZXRfcG5sPSUuMmYgcG5sX3BjdD0lcyAoY3VyIG5ldF9wbmw9JXMgZXhpdF9wcmljZT0lcykgdHJhZGVfaWQ9JXMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfdHJhZGUuc3ltYm9sLCBfdjMyMGhfZGlyLnVwcGVyKCksIF9leGl0X3B4LCBfZXhpdF9zcmMsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9uZXdfbmV0LCBfbmV3X3BjdCwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZ2V0YXR0cihfdHJhZGUsICJuZXRfcG5sIiwgTm9uZSksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGdldGF0dHIoX3RyYWRlLCAiZXhpdF9wcmljZSIsIE5vbmUpLCBfdHJhZGUuaWQpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBfdjMyMGhfZXJyOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBsb2dnZXIuZGVidWcoIlt2MTkuMzQuMzIwaF0gZmluYWxpemUgYmxvY2sgdGhyZXcgKG5vbi1mYXRhbCk6ICVzIiwgX3YzMjBoX2VycikKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAjIOKUgOKUgCB2MTkuMzQuMzIwaCDigJQgT0NBIGNsb3NlLXBhdGggYWNjb3VudGluZyBmaW5hbGl6ZSDilIDilIAgRU5EIOKUgOKUgAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXdhaXQgYXN5bmNpby50b190aHJlYWQoYm90Ll9wZXJzaXN0X3RyYWRlLCBfdHJhZGUp"
APPLIED_STAMP = "/tmp/v320h_oca_finalize.applied"

MARKER_OPEN = "# \u2500\u2500 v19.34.320h \u2014 OCA close-path accounting finalize \u2500\u2500 BEGIN \u2500\u2500"
MARKER_CLOSE = "# \u2500\u2500 v19.34.320h \u2014 OCA close-path accounting finalize \u2500\u2500 END \u2500\u2500"


def _old() -> str:
    return base64.b64decode(OLD_B64).decode("utf-8")


def _new() -> str:
    return base64.b64decode(NEW_B64).decode("utf-8")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> str:
    if not TARGET.exists():
        print(f"ERROR: target missing: {TARGET}")
        sys.exit(1)
    return TARGET.read_text(encoding="utf-8")


def cmd_check():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    print(f"  target : {TARGET}")
    print(f"  size   : {len(body):,} chars")
    print(f"  sha    : {cur}")
    if MARKER_OPEN in body:
        if cur == POST_SHA256:
            print("  \u2705 ALREADY APPLIED (sha == POST_SHA256). No-op. Use --rollback to revert.")
            sys.exit(0)
        print("  \u26a0\ufe0f  marker present but sha != POST_SHA256 \u2014 file drifted post-apply.")
        sys.exit(4)
    if cur != PRE_SHA256:
        print("  \u274c PRE_SHA256 MISMATCH \u2014 file drifted from canonical baseline.")
        print(f"     expected {PRE_SHA256}")
        print(f"     actual   {cur}")
        print("     -> ask operator to upload their copy; rebase the patch on it.")
        sys.exit(2)
    old = _old()
    n = body.count(old)
    if n != 1:
        print(f"  \u274c anchor chunk not unique (count={n}) \u2014 refusing to write.")
        sys.exit(3)
    projected = body.replace(old, _new(), 1)
    pp = _sha(projected.encode("utf-8"))
    print(f"  \u2713 PRE_SHA256 ok; anchor unique.")
    print(f"  \u2713 projected POST_SHA256 = {pp}")
    if pp != POST_SHA256:
        print(f"  \u274c projected sha != embedded POST_SHA256 ({POST_SHA256}) \u2014 ABORT.")
        sys.exit(5)
    print("  \u2713 projected hash matches embedded POST_SHA256. Run --apply to write.")


def cmd_apply():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    if MARKER_OPEN in body and cur == POST_SHA256:
        print("  ALREADY APPLIED. No-op.")
        return
    if cur != PRE_SHA256:
        print("  ABORT: PRE_SHA256 mismatch. Run --check.")
        sys.exit(2)
    old = _old()
    if body.count(old) != 1:
        print("  ABORT: anchor chunk not unique. Run --check.")
        sys.exit(3)
    new_body = body.replace(old, _new(), 1)
    pp = _sha(new_body.encode("utf-8"))
    if pp != POST_SHA256:
        print(f"  ABORT: post-patch sha {pp} != embedded POST_SHA256. No write.")
        sys.exit(5)
    bak = TARGET.with_suffix(TARGET.suffix + ".bak." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new_body, encoding="utf-8")
    Path(APPLIED_STAMP).write_text(
        f"applied_at={_now_iso()}\npre={PRE_SHA256}\npost={POST_SHA256}\nbackup={bak}\n")
    print(f"  \u2705 wrote {TARGET} ({len(new_body):,} chars)")
    print(f"  \u2705 backup at {bak.name}")
    print(f"  \u2705 POST_SHA256 verified == {POST_SHA256}")
    print("\n  NEXT STEPS:")
    print("    1) COMMIT before any restart (StartTrading.bat git-wipes uncommitted code):")
    print("       git add backend/services/position_manager.py && git commit -m 'v19.34.320h OCA close finalize (observe)' && git push origin main")
    print("    2) ./start_backend.sh --force")
    print("    3) tail logs for [v19.34.320h OBSERVE]; flip V320H_OCA_FIX_POLICY=fix when satisfied")


def cmd_rollback():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    if MARKER_OPEN not in body:
        print("  no v320h marker present \u2014 nothing to roll back.")
        return
    if cur != POST_SHA256:
        print("  \u26a0\ufe0f  file drifted from POST_SHA256; rolling back by exact chunk anyway.")
    new = body.replace(_new(), _old(), 1)
    if new == body:
        print("  WARNING: chunk-revert matched nothing (manual edits?). ABORT.")
        sys.exit(2)
    rp = _sha(new.encode("utf-8"))
    bak = TARGET.with_suffix(TARGET.suffix + ".bak_rollback." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    TARGET.rename(bak)
    TARGET.write_text(new, encoding="utf-8")
    try:
        os.remove(APPLIED_STAMP)
    except FileNotFoundError:
        pass
    print(f"  \u2705 rolled back. patched copy saved at {bak.name}")
    print(f"  restored sha = {rp}  (PRE_SHA256 == {PRE_SHA256}: {rp == PRE_SHA256})")


def cmd_status():
    body = _read()
    cur = _sha(body.encode("utf-8"))
    present = MARKER_OPEN in body
    print(f"  target  : {TARGET}")
    print(f"  sha     : {cur}")
    print(f"  applied : {present}  (sha==POST: {cur == POST_SHA256}; sha==PRE: {cur == PRE_SHA256})")
    print(f"  policy  : V320H_OCA_FIX_POLICY={os.environ.get('V320H_OCA_FIX_POLICY', 'observe (default)')}")
    if os.path.exists(APPLIED_STAMP):
        print("  stamp   :\n" + Path(APPLIED_STAMP).read_text())


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    g.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.check:
        cmd_check()
    elif args.apply:
        cmd_apply()
    elif args.rollback:
        cmd_rollback()
    elif args.status:
        cmd_status()


if __name__ == "__main__":
    main()
