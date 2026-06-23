#!/usr/bin/env python3
r"""
patch_v401_earnings_universe_actuals.py — Fundamental pillar · earnings dark-feed fix (v401).

WHY (proven by diag_earnings_universe.py on live DGX)
  The earnings_calendar 15%-weighted sub-pillar is dark for the names we trade:
    * RC1 universe mismatch — refresh fed symbol_fundamentals_cache[:300] (+ a
      free-tier-sampled date-range), so only 15/814 (2%) of the traded/scanner
      universe had an earnings row.
    * RC2 actuals never stored — _normalize_earnings_row kept estimates only;
      is_reported / eps_result / eps_surprise_pct were 0/335, so the v390 post-
      earnings-drift score could never light, and the 2-day prune would nuke a
      reported row long before the 10-day drift lookback.
  (IB client-12 fundamentals are fine — float/SI/institutional/DTC/margin lit;
   only the Finnhub earnings CALENDAR was dark. The 6am cron is already covered
   by scheduler_catchup's boot re-run, so this is a single-file collector fix.)

FIX (BACKEND-ONLY, metadata only — no order/scoring/execution path)
  Rewrite EarningsService.refresh_earnings_calendar to:
    1. Build the universe from the bot's live-traded names (recent live_alerts
       with tqs_score>0 + open bot_trades), capped EARNINGS_UNIVERSE_CAP (400).
    2. Per symbol, store BOTH the upcoming estimate row AND the most-recent
       REPORTED row WITH actuals (is_reported/eps_result/eps_surprise_pct).
    3. Retain REPORTED rows ~EARNINGS_REPORTED_RETAIN_DAYS (14) so post-earnings
       drift can read them; prune only stale UNREPORTED estimates 2d after date.

1 anchored, idempotent edit to ONE file (.v401bak backup, reversible).
  EDIT backend/services/earnings_service.py  (refresh_earnings_calendar)

ENV (all optional, safe defaults):
  EARNINGS_UNIVERSE_CAP=400          # per-symbol Finnhub calls (~1.1s each)
  EARNINGS_REPORTED_RETAIN_DAYS=14   # reported-row retention for drift lookback

HASH GUARDS (built against live DGX bytes):
  PRE_SHA256  = a549b8be28626c31d2f8780a3e8f587a4c50c99484bd440bdbbee2fb27e5f57d
  POST_SHA256 = c780e2e63178bf347dd87987cccb56076b61ec8f9ac977d25ab4ae44a96ad7cd

Usage (repo root, DGX):
    .venv/bin/python backend/scripts/patch_v401_earnings_universe_actuals.py --check
    .venv/bin/python backend/scripts/patch_v401_earnings_universe_actuals.py --apply
    .venv/bin/python backend/scripts/patch_v401_earnings_universe_actuals.py --rollback
After --apply:  commit, then ./start_backend.sh --force (backend-only).
The boot catch-up re-runs earnings_calendar_refresh ~120s after start; or force
it now:  python -c "import asyncio;from services.earnings_service import get_earnings_service as g;print(asyncio.run(g().refresh_earnings_calendar()))"
Then re-run diag_earnings_universe.py — overlap should jump and ACTUALS light.

On a PRE_SHA mismatch (DGX drift), DO NOT --force. Upload your live copy:
  gzip -9 -c backend/services/earnings_service.py | base64 -w0 | curl --data-binary @- https://paste.rs/
and send the link so the edit can be rebased onto the canonical baseline.
"""
import os
import sys
import base64
import shutil
import hashlib
import argparse
import py_compile

BAK = ".v401bak"
TARGET = "backend/services/earnings_service.py"
PRE_SHA = "a549b8be28626c31d2f8780a3e8f587a4c50c99484bd440bdbbee2fb27e5f57d"
POST_SHA = "c780e2e63178bf347dd87987cccb56076b61ec8f9ac977d25ab4ae44a96ad7cd"

OLD_B64 = (
    "ICAgIGFzeW5jIGRlZiByZWZyZXNoX2Vhcm5pbmdzX2NhbGVuZGFyKAogICAgICAgIHNlbGYsIGRi"
    "PU5vbmUsIGRheXNfYWhlYWQ6IGludCA9IDIxLAogICAgICAgIGZhbGxiYWNrX3N5bWJvbHM6IE9w"
    "dGlvbmFsW0xpc3Rbc3RyXV0gPSBOb25lLAogICAgKSAtPiBpbnQ6CiAgICAgICAgIiIidjE5LjM0"
    "LjIwMyDigJQgcGVyc2lzdCB1cGNvbWluZyBlYXJuaW5ncyBpbnRvIHRoZSBgYGVhcm5pbmdzX2Nh"
    "bGVuZGFyYGAKICAgICAgICBjb2xsZWN0aW9uIHRoZSBUUVMgZnVuZGFtZW50YWwgcGlsbGFyIHJl"
    "YWRzLiBBcHByb2FjaCAoYSk6IG9uZQogICAgICAgIG1hcmtldC13aWRlIGRhdGUtcmFuZ2UgY2Fs"
    "bDsgZmFsbHMgYmFjayB0byAoYikgcGVyLXN5bWJvbCBvdmVyIHRoZQogICAgICAgIGFjdGl2ZSB1"
    "bml2ZXJzZSAoc3ltYm9sX2Z1bmRhbWVudGFsc19jYWNoZSksIHRocm90dGxlZCBmb3IgZnJlZSB0"
    "aWVyLgogICAgICAgIFVwc2VydHMgYnkgKHN5bWJvbCwgZGF0ZSksIHBydW5lcyByb3dzIG9sZGVy"
    "IHRoYW4gMiBkYXlzLiIiIgogICAgICAgIGlmIGRiIGlzIE5vbmU6CiAgICAgICAgICAgIGRiID0g"
    "X2Vhcm5pbmdzX2RiKCkKICAgICAgICBpZiBkYiBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4g"
    "MAoKICAgICAgICBkb2NzOiBMaXN0W0RpY3RdID0gW10KICAgICAgICByb3dzID0gYXdhaXQgc2Vs"
    "Zi5nZXRfdXBjb21pbmdfZWFybmluZ3MoZGF5c19haGVhZCkKICAgICAgICBpZiByb3dzOgogICAg"
    "ICAgICAgICBmb3IgZSBpbiByb3dzOgogICAgICAgICAgICAgICAgZG9jID0gX25vcm1hbGl6ZV9l"
    "YXJuaW5nc19yb3coZSkKICAgICAgICAgICAgICAgIGlmIGRvYzoKICAgICAgICAgICAgICAgICAg"
    "ICBkb2NzLmFwcGVuZChkb2MpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc3ltcyA9IGZhbGxi"
    "YWNrX3N5bWJvbHMgb3IgWwogICAgICAgICAgICAgICAgZFsic3ltYm9sIl0gZm9yIGQgaW4KICAg"
    "ICAgICAgICAgICAgIGRiWyJzeW1ib2xfZnVuZGFtZW50YWxzX2NhY2hlIl0uZmluZCh7fSwgeyJz"
    "eW1ib2wiOiAxLCAiX2lkIjogMH0pCiAgICAgICAgICAgICAgICBpZiBkLmdldCgic3ltYm9sIikK"
    "ICAgICAgICAgICAgXQogICAgICAgICAgICBmb3Igc3ltIGluIHN5bXNbOjMwMF06CiAgICAgICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgY2FsID0gYXdhaXQgc2VsZi5nZXRfZWFy"
    "bmluZ3NfY2FsZW5kYXIoc3ltKQogICAgICAgICAgICAgICAgICAgIG5lID0gY2FsLmdldCgibmV4"
    "dF9lYXJuaW5ncyIpIGlmIGNhbC5nZXQoImF2YWlsYWJsZSIpIGVsc2UgTm9uZQogICAgICAgICAg"
    "ICAgICAgICAgIGlmIG5lIGFuZCBuZS5nZXQoImRhdGUiKToKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZG9jID0gX25vcm1hbGl6ZV9lYXJuaW5nc19yb3coeyoqbmUsICJzeW1ib2wiOiBzeW19KQog"
    "ICAgICAgICAgICAgICAgICAgICAgICBpZiBkb2M6CiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBkb2NzLmFwcGVuZChkb2MpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgICAgIGF3YWl0IGFzeW5jaW8uc2xlZXAo"
    "MS4xKQoKICAgICAgICBub3dfaXNvID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9y"
    "bWF0KCkKICAgICAgICB3cml0dGVuID0gMAogICAgICAgIGZvciBkb2MgaW4gZG9jczoKICAgICAg"
    "ICAgICAgZG9jWyJmZXRjaGVkX2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIGRiWyJlYXJuaW5nc19jYWxlbmRhciJdLnVwZGF0ZV9vbmUoCiAgICAgICAgICAg"
    "ICAgICAgICAgeyJzeW1ib2wiOiBkb2NbInN5bWJvbCJdLCAiZGF0ZSI6IGRvY1siZGF0ZSJdfSwK"
    "ICAgICAgICAgICAgICAgICAgICB7IiRzZXQiOiBkb2N9LCB1cHNlcnQ9VHJ1ZSwKICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgICAgIHdyaXR0ZW4gKz0gMQogICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBsb2dnZXIuZGVidWcoImVhcm5pbmdzX2Nh"
    "bGVuZGFyIHVwc2VydCBmYWlsZWQgZm9yICVzOiAlcyIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZG9jLmdldCgic3ltYm9sIiksIGUpCgogICAgICAgIGN1dG9mZiA9IChkYXRldGltZS5u"
    "b3codGltZXpvbmUudXRjKSAtIHRpbWVkZWx0YShkYXlzPTIpKS5pc29mb3JtYXQoKQogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgZGJbImVhcm5pbmdzX2NhbGVuZGFyIl0uZGVsZXRlX21hbnkoeyJk"
    "YXRlIjogeyIkbHQiOiBjdXRvZmZ9fSkKICAgICAgICAgICAgZGJbImVhcm5pbmdzX2NhbGVuZGFy"
    "Il0uY3JlYXRlX2luZGV4KCJzeW1ib2wiLCBiYWNrZ3JvdW5kPVRydWUpCiAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgIGxvZ2dlci5pbmZvKCJbZWFybmlu"
    "Z3NdIGVhcm5pbmdzX2NhbGVuZGFyIHJlZnJlc2ggd3JvdGUgJWQgcm93cyAiCiAgICAgICAgICAg"
    "ICAgICAgICAgIiglcykiLCB3cml0dGVuLCAiZGF0ZS1yYW5nZSIgaWYgcm93cyBlbHNlICJwZXIt"
    "c3ltYm9sIikKICAgICAgICByZXR1cm4gd3JpdHRlbgogICAgCg=="
)
NEW_B64 = (
    "ICAgIGFzeW5jIGRlZiByZWZyZXNoX2Vhcm5pbmdzX2NhbGVuZGFyKAogICAgICAgIHNlbGYsIGRi"
    "PU5vbmUsIGRheXNfYWhlYWQ6IGludCA9IDIxLAogICAgICAgIGZhbGxiYWNrX3N5bWJvbHM6IE9w"
    "dGlvbmFsW0xpc3Rbc3RyXV0gPSBOb25lLAogICAgKSAtPiBpbnQ6CiAgICAgICAgIiIidjQwMSDi"
    "gJQgcGVyc2lzdCBlYXJuaW5ncyBpbnRvIGBgZWFybmluZ3NfY2FsZW5kYXJgYCBvdmVyIHRoZSBi"
    "b3QncwogICAgICAgIExJVkUtVFJBREVEIHVuaXZlcnNlIChyZWNlbnQgbGl2ZV9hbGVydHMgKyBv"
    "cGVuIHBvc2l0aW9ucyksIE5PVCB0aGUKICAgICAgICBzdGFsZSBgYHN5bWJvbF9mdW5kYW1lbnRh"
    "bHNfY2FjaGVbOjMwMF1gYC4gU3RvcmVzIEJPVEggdGhlIHVwY29taW5nCiAgICAgICAgZXN0aW1h"
    "dGUgcm93IEFORCB0aGUgbW9zdC1yZWNlbnQgUkVQT1JURUQgcm93IChpc19yZXBvcnRlZCAvIGVw"
    "c19yZXN1bHQKICAgICAgICAvIGVwc19zdXJwcmlzZV9wY3QpIHNvIHRoZSB2MzkwIHBvc3QtZWFy"
    "bmluZ3MtZHJpZnQgc3ViLXNjb3JlIGxpZ2h0cy4KICAgICAgICBSZXBvcnRlZCByb3dzIGFyZSBy"
    "ZXRhaW5lZCB+RUFSTklOR1NfUkVQT1JURURfUkVUQUlOX0RBWVMgKGRlZmF1bHQgMTQpOwogICAg"
    "ICAgIHN0YWxlIHVucmVwb3J0ZWQgZXN0aW1hdGVzIGFyZSBwcnVuZWQgMiBkYXlzIGFmdGVyIHRo"
    "ZWlyIGRhdGUuCgogICAgICAgIFRoZSBtYXJrZXQtd2lkZSBGaW5uaHViIGRhdGUtcmFuZ2UgY2Fs"
    "bCBpcyBmcmVlLXRpZXIgc2FtcGxlZCAofjI1OQogICAgICAgIG5hbWVzLCB+MiUlIG92ZXJsYXAg"
    "d2l0aCB3aGF0IHdlIHRyYWRlKSBzbyBpdCBjYW5ub3QgYW5jaG9yIGEgMTUlJS0KICAgICAgICB3"
    "ZWlnaHRlZCBwaWxsYXIg4oCUIHBlci1zeW1ib2wgbG9va3VwcyBvdmVyIE9VUiB1bml2ZXJzZSBp"
    "cyB0aGUgb25seQogICAgICAgIHZpYWJsZSBwYXRoICh0aHJvdHRsZWQgZm9yIHRoZSBmcmVlIHRp"
    "ZXIpLiIiIgogICAgICAgIGlmIGRiIGlzIE5vbmU6CiAgICAgICAgICAgIGRiID0gX2Vhcm5pbmdz"
    "X2RiKCkKICAgICAgICBpZiBkYiBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gMAoKICAgICAg"
    "ICAjIOKUgOKUgCBidWlsZCB0aGUgbGl2ZS10cmFkZWQgLyBzY2FubmVyIHVuaXZlcnNlIChjYXBw"
    "ZWQpIOKUgOKUgAogICAgICAgIHRyeToKICAgICAgICAgICAgY2FwID0gaW50KG9zLmVudmlyb24u"
    "Z2V0KCJFQVJOSU5HU19VTklWRVJTRV9DQVAiLCAiNDAwIikpCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgY2FwID0gNDAwCiAgICAgICAgdHJhZGVkLCBvcGVuX3N5bXMgPSBb"
    "XSwgW10KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNpbmNlID0gKGRhdGV0aW1lLm5vdyh0aW1l"
    "em9uZS51dGMpIC0gdGltZWRlbHRhKGRheXM9NSkpLnN0cmZ0aW1lKCIlWS0lbS0lZCIpCiAgICAg"
    "ICAgICAgIHRyYWRlZCA9IGxpc3QoZGJbImxpdmVfYWxlcnRzIl0uZGlzdGluY3QoCiAgICAgICAg"
    "ICAgICAgICAic3ltYm9sIiwgeyJjcmVhdGVkX2F0IjogeyIkZ3RlIjogc2luY2V9LCAidHFzX3Nj"
    "b3JlIjogeyIkZ3QiOiAwfX0pKQogICAgICAgICAgICBvcGVuX3N5bXMgPSBbdC5nZXQoInN5bWJv"
    "bCIpIGZvciB0IGluIGRiWyJib3RfdHJhZGVzIl0uZmluZCgKICAgICAgICAgICAgICAgIHsic3Rh"
    "dHVzIjogeyIkbmluIjogWyJjbG9zZWQiLCAiY2FuY2VsbGVkIiwgInJlamVjdGVkIl19fSwKICAg"
    "ICAgICAgICAgICAgIHsic3ltYm9sIjogMSwgIl9pZCI6IDB9KV0KICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIGxvZ2dlci5kZWJ1ZygiZWFybmluZ3MgdW5pdmVyc2Ug"
    "YnVpbGQgZmFpbGVkOiAlcyIsIGUpCiAgICAgICAgc2VlbiwgdW5pdmVyc2UgPSBzZXQoKSwgW10K"
    "ICAgICAgICBmb3IgcyBpbiBsaXN0KG9wZW5fc3ltcykgKyBzb3J0ZWQodHJhZGVkKSArIGxpc3Qo"
    "ZmFsbGJhY2tfc3ltYm9scyBvciBbXSk6CiAgICAgICAgICAgIHN1ID0gc3RyKHMgb3IgIiIpLnVw"
    "cGVyKCkuc3RyaXAoKQogICAgICAgICAgICBpZiBzdSBhbmQgc3Ugbm90IGluIHNlZW46CiAgICAg"
    "ICAgICAgICAgICBzZWVuLmFkZChzdSkKICAgICAgICAgICAgICAgIHVuaXZlcnNlLmFwcGVuZChz"
    "dSkKICAgICAgICBpZiBub3QgdW5pdmVyc2U6CiAgICAgICAgICAgIHVuaXZlcnNlID0gWwogICAg"
    "ICAgICAgICAgICAgZFsic3ltYm9sIl0gZm9yIGQgaW4KICAgICAgICAgICAgICAgIGRiWyJzeW1i"
    "b2xfZnVuZGFtZW50YWxzX2NhY2hlIl0uZmluZCh7fSwgeyJzeW1ib2wiOiAxLCAiX2lkIjogMH0p"
    "CiAgICAgICAgICAgICAgICBpZiBkLmdldCgic3ltYm9sIikKICAgICAgICAgICAgXQogICAgICAg"
    "IHVuaXZlcnNlID0gdW5pdmVyc2VbOmNhcF0KCiAgICAgICAgbm93X2lzbyA9IGRhdGV0aW1lLm5v"
    "dyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdHRlbiA9IDAKICAgICAgICBm"
    "b3Igc3ltIGluIHVuaXZlcnNlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjYWwg"
    "PSBhd2FpdCBzZWxmLmdldF9lYXJuaW5nc19jYWxlbmRhcihzeW0pCiAgICAgICAgICAgICAgICBp"
    "ZiBub3QgY2FsLmdldCgiYXZhaWxhYmxlIik6CiAgICAgICAgICAgICAgICAgICAgYXdhaXQgYXN5"
    "bmNpby5zbGVlcCgxLjEpCiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAg"
    "ICAgIHBlbmRpbmcgPSBbXQogICAgICAgICAgICAgICAgbmUgPSBjYWwuZ2V0KCJuZXh0X2Vhcm5p"
    "bmdzIikKICAgICAgICAgICAgICAgIGlmIG5lIGFuZCBuZS5nZXQoImRhdGUiKToKICAgICAgICAg"
    "ICAgICAgICAgICBwZW5kaW5nLmFwcGVuZCgobmUsIEZhbHNlKSkKICAgICAgICAgICAgICAgIGxl"
    "ID0gY2FsLmdldCgibGFzdF9lYXJuaW5ncyIpCiAgICAgICAgICAgICAgICBpZiBsZSBhbmQgbGUu"
    "Z2V0KCJkYXRlIik6CiAgICAgICAgICAgICAgICAgICAgcGVuZGluZy5hcHBlbmQoKGxlLCBUcnVl"
    "KSkKICAgICAgICAgICAgICAgIGZvciBzcm93LCBpc19yZXAgaW4gcGVuZGluZzoKICAgICAgICAg"
    "ICAgICAgICAgICBkID0gc3RyKHNyb3cuZ2V0KCJkYXRlIikgb3IgIiIpLnN0cmlwKCkKICAgICAg"
    "ICAgICAgICAgICAgICBpZiBsZW4oZCkgPCAxMDoKICAgICAgICAgICAgICAgICAgICAgICAgY29u"
    "dGludWUKICAgICAgICAgICAgICAgICAgICBkb2MgPSB7CiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICJzeW1ib2wiOiBzeW0sCiAgICAgICAgICAgICAgICAgICAgICAgICJkYXRlIjogZiJ7ZFs6MTBd"
    "fVQxMjowMDowMCswMDowMCIsCiAgICAgICAgICAgICAgICAgICAgICAgICJkYXRlX29ubHkiOiBk"
    "WzoxMF0sCiAgICAgICAgICAgICAgICAgICAgICAgICJob3VyIjogc3Jvdy5nZXQoImhvdXIiKSwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgImVwc19lc3RpbWF0ZSI6IHNyb3cuZ2V0KCJlcHNfZXN0"
    "aW1hdGUiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInJldmVudWVfZXN0aW1hdGUiOiBzcm93"
    "LmdldCgicmV2ZW51ZV9lc3RpbWF0ZSIpLAogICAgICAgICAgICAgICAgICAgICAgICAicXVhcnRl"
    "ciI6IHNyb3cuZ2V0KCJxdWFydGVyIiksCiAgICAgICAgICAgICAgICAgICAgICAgICJ5ZWFyIjog"
    "c3Jvdy5nZXQoInllYXIiKSwKICAgICAgICAgICAgICAgICAgICAgICAgImlzX3JlcG9ydGVkIjog"
    "Ym9vbChpc19yZXAgb3Igc3Jvdy5nZXQoImlzX3JlcG9ydGVkIikpLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAiZXBzX2FjdHVhbCI6IHNyb3cuZ2V0KCJlcHNfYWN0dWFsIiksCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJlcHNfcmVzdWx0Ijogc3Jvdy5nZXQoImVwc19yZXN1bHQiKSwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgImVwc19zdXJwcmlzZSI6IHNyb3cuZ2V0KCJlcHNfc3VycHJpc2Ui"
    "KSwKICAgICAgICAgICAgICAgICAgICAgICAgImVwc19zdXJwcmlzZV9wY3QiOiBzcm93LmdldCgi"
    "ZXBzX3N1cnByaXNlX3BjdCIpLAogICAgICAgICAgICAgICAgICAgICAgICAicmV2ZW51ZV9hY3R1"
    "YWwiOiBzcm93LmdldCgicmV2ZW51ZV9hY3R1YWwiKSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "InJldmVudWVfcmVzdWx0Ijogc3Jvdy5nZXQoInJldmVudWVfcmVzdWx0IiksCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJzb3VyY2UiOiAiZmlubmh1YiIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICJmZXRjaGVkX2F0Ijogbm93X2lzbywKICAgICAgICAgICAgICAgICAgICB9CiAgICAgICAgICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBkYlsiZWFybmluZ3NfY2FsZW5k"
    "YXIiXS51cGRhdGVfb25lKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgeyJzeW1ib2wiOiBz"
    "eW0sICJkYXRlIjogZG9jWyJkYXRlIl19LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgeyIk"
    "c2V0IjogZG9jfSwgdXBzZXJ0PVRydWUsCiAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgd3JpdHRlbiArPSAxCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgICAgICAgICBsb2dnZXIuZGVidWcoImVh"
    "cm5pbmdzIHVwc2VydCAlcyBmYWlsZWQ6ICVzIiwgc3ltLCBlKQogICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBsb2dnZXIuZGVidWcoImVhcm5pbmdzIHJl"
    "ZnJlc2ggJXMgZmFpbGVkOiAlcyIsIHN5bSwgZSkKICAgICAgICAgICAgYXdhaXQgYXN5bmNpby5z"
    "bGVlcCgxLjEpCgogICAgICAgICMg4pSA4pSAIHJldGVudGlvbjoga2VlcCBSRVBPUlRFRCByb3dz"
    "IGZvciB0aGUgZHJpZnQgbG9va2JhY2sgd2luZG93OwogICAgICAgICMgICAgZHJvcCBvbmx5IHN0"
    "YWxlIFVOUkVQT1JURUQgZXN0aW1hdGVzIDJkIGFmdGVyIHRoZWlyIGRhdGUuIOKUgOKUgAogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgcmV0YWluX2RheXMgPSBpbnQob3MuZW52aXJvbi5nZXQoIkVB"
    "Uk5JTkdTX1JFUE9SVEVEX1JFVEFJTl9EQVlTIiwgIjE0IikpCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgcmV0YWluX2RheXMgPSAxNAogICAgICAgIHVucmVwX2N1dG9mZiA9"
    "IChkYXRldGltZS5ub3codGltZXpvbmUudXRjKSAtIHRpbWVkZWx0YShkYXlzPTIpKS5pc29mb3Jt"
    "YXQoKQogICAgICAgIHJlcF9jdXRvZmYgPSAoZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykgLSB0"
    "aW1lZGVsdGEoZGF5cz1yZXRhaW5fZGF5cykpLmlzb2Zvcm1hdCgpCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBkYlsiZWFybmluZ3NfY2FsZW5kYXIiXS5kZWxldGVfbWFueSgKICAgICAgICAgICAg"
    "ICAgIHsiZGF0ZSI6IHsiJGx0IjogdW5yZXBfY3V0b2ZmfSwgImlzX3JlcG9ydGVkIjogeyIkbmUi"
    "OiBUcnVlfX0pCiAgICAgICAgICAgIGRiWyJlYXJuaW5nc19jYWxlbmRhciJdLmRlbGV0ZV9tYW55"
    "KAogICAgICAgICAgICAgICAgeyJkYXRlIjogeyIkbHQiOiByZXBfY3V0b2ZmfSwgImlzX3JlcG9y"
    "dGVkIjogVHJ1ZX0pCiAgICAgICAgICAgIGRiWyJlYXJuaW5nc19jYWxlbmRhciJdLmNyZWF0ZV9p"
    "bmRleCgic3ltYm9sIiwgYmFja2dyb3VuZD1UcnVlKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgIHBhc3MKICAgICAgICBsb2dnZXIuaW5mbygiW2Vhcm5pbmdzXSB2NDAxIHJl"
    "ZnJlc2ggd3JvdGUgJWQgcm93cyBvdmVyICVkIHRyYWRlZCAiCiAgICAgICAgICAgICAgICAgICAg"
    "InN5bWJvbHMgKHJlcG9ydGVkIHJldGFpbmVkICVkZCkiLCB3cml0dGVuLCBsZW4odW5pdmVyc2Up"
    "LAogICAgICAgICAgICAgICAgICAgIHJldGFpbl9kYXlzKQogICAgICAgIHJldHVybiB3cml0dGVu"
    "CiAgICAK"
)
APPLIED_MARKER = "EARNINGS_UNIVERSE_CAP"

OLD = base64.b64decode(OLD_B64).decode("utf-8")
NEW = base64.b64decode(NEW_B64).decode("utf-8")


def sha_full(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..", "..")):
        c = os.path.abspath(os.path.join(base, path))
        if os.path.exists(c):
            return c
    return os.path.abspath(os.path.join(".", path))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    print("=" * 84)
    print("  v401 — earnings collector: live-traded universe + actuals + retention")
    print("  mode:", "CHECK" if args.check else "APPLY" if args.apply else "ROLLBACK")
    print("=" * 84)

    p = resolve(TARGET)
    if not os.path.exists(p):
        print(f"  MISSING FILE: {TARGET}")
        sys.exit(2)

    if args.rollback:
        bak = p + BAK
        if os.path.exists(bak):
            shutil.copy2(bak, p)
            ok = "matches PRE_SHA" if sha_full(p) == PRE_SHA else "sha unexpected"
            print(f"  restored {TARGET}  sha={sha_full(p)[:12]}  {ok}")
        else:
            print(f"  no backup found ({BAK}); nothing to restore.")
        print("\n  ROLLBACK complete.  NEXT: ./start_backend.sh --force")
        return

    cur_sha = sha_full(p)
    if cur_sha == POST_SHA:
        file_state = "ALREADY-APPLIED"
    elif cur_sha == PRE_SHA:
        file_state = "READY"
    else:
        file_state = "DRIFT"

    print(f"\n  file   : {TARGET}")
    print(f"    sha     : {cur_sha[:12]}")
    print(f"    PRE_SHA : {PRE_SHA[:12]}  POST_SHA: {POST_SHA[:12]}")
    print(f"    state   : {file_state}")

    if file_state == "DRIFT":
        print("\n  DRIFT: live file matches neither PRE nor POST hash. Do NOT --force.")
        print(f"     gzip -9 -c {TARGET} | base64 -w0 | curl --data-binary @- https://paste.rs/")
        sys.exit(3)

    src = open(p, encoding="utf-8").read()
    applied = APPLIED_MARKER in src
    n = src.count(OLD)
    status = "ALREADY-APPLIED" if applied else ("READY" if n == 1 else f"ANCHOR x{n}")
    print(f"\n  [refresh_earnings_calendar rewrite]\n    status : {status}")
    if not applied and n != 1:
        print("    anchor not uniquely found — ABORT (no files changed).")
        sys.exit(3)

    if args.check:
        nready = 0 if applied else 1
        print(f"\n  CHECK ok. {nready} change(s) ready. Re-run with --apply.")
        return

    if file_state == "ALREADY-APPLIED" or applied:
        print("\n  Nothing to do — file already at POST_SHA.")
        return

    bak = p + BAK
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    out = src.replace(OLD, NEW, 1)
    open(p, "w", encoding="utf-8").write(out)

    try:
        py_compile.compile(p, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, p)
        print(f"  py_compile FAILED — reverted from {BAK}.\n     {e}")
        sys.exit(6)

    post = sha_full(p)
    print(f"\n  patched {TARGET}  sha={post[:12]}  ({BAK} saved)")
    if post == POST_SHA:
        print("  POST_SHA verified — byte-identical to the tested build.")
    else:
        shutil.copy2(bak, p)
        print(f"  POST_SHA MISMATCH — expected {POST_SHA[:12]} got {post[:12]}. Reverted.")
        sys.exit(5)
    print("\n  APPLY complete. 1 change.")
    print("  NEXT (commit BEFORE restart):")
    print("    git add -A && git commit -m 'v401: earnings collector live-traded universe + actuals + retention' && git push origin main")
    print("    ./start_backend.sh --force   (backend-only)")


if __name__ == "__main__":
    main()
