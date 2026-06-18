#!/usr/bin/env python3
# patch_v362_gap_give_go_doctrine.py
# ---------------------------------------------------------------------------
# v362 — REWRITE `_check_gap_give_go` to the SMB cheat-sheet DOCTRINE (was a loose VWAP-pullback proxy).
#
# DOCTRINE (1-min): gap-up -> a quick "give" (pullback) that holds ABOVE prior close and does NOT
# fill >50% of the gap -> a 3-7 bar mini-consolidation on DECLINING volume -> ENTER on the break of
# the consolidation HIGH, STOP .02 below the consolidation LOW, fixed 2.0R target. Opening-drive only.
#
# EVIDENCE (diag_v362b_gap_give_go_doctrine.py, 180d / 300-sym, 1-min):
#   loose code-mirror (5-min)         : winsorAvg +0.069 (breakeven; +0.018 after slippage levers)
#   DOCTRINE 2.0R, gap>=1% band<=0.6% : n=492 win 47% winsorAvg +0.233  <-- shipped config
#   DOCTRINE 2.0R, gap>=2% band<=0.4% : n=128 win 47% winsorAvg +0.282
#   Ground truth (8 real fills) was -1.32R but tiny + artifact closes; the loose code never modeled
#   the give/consolidation/range-break structure, used a VWAP stop and a fixed HOD target.
#   The doctrine entry (cons-high break) + cons-low stop + 2R target is ~3x the loose edge.
#
# The new detector fetches 1-min bars via ts._get_intraday_bars_from_db(symbol, "1 min", 60)
# (same pattern as the live vwap_fade detector) and is DETECTOR-ONLY (no exit-management changes).
#
# Anchored-chunk patcher (AGENTS.md §2): whole-file PRE-SHA guard + exact OLD-bytes match
# (count MUST be 1) + post-write self-verify + py_compile. ABORTS before writing on ANY drift.
# Auto-backup. Supports --check dry-run.
#
# Deploy (DGX, repo root):
#   curl -sS -o /tmp/patch_v362.py https://paste.rs/<id>
#   .venv/bin/python /tmp/patch_v362.py --check
#   .venv/bin/python /tmp/patch_v362.py
#   .venv/bin/python -m pytest backend/tests/test_v362_gap_give_go_doctrine.py -q
#   git add backend/ memory/ && git commit -m "v362: rewrite gap_give_go to SMB doctrine (give->consolidation->range-break, 2R)" && git push origin main
#   git status --short
#   ./start_backend.sh --force
# ---------------------------------------------------------------------------
import base64
import hashlib
import py_compile
import shutil
import sys
import tempfile

FILE = "backend/services/enhanced_scanner.py"
PRE_FILE_SHA = "8df7dd8c5da7bd92d53d8a5d0d5862d82ae8b22ab3b8bb8e5446d8dca37f7b9e"

OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfZ2FwX2dpdmVfZ28oc2VsZiwgc3ltYm9sOiBzdHIsIHNuYXBzaG90LCB0YXBlOiBUYXBlUmVhZGluZykgLT4gT3B0aW9uYWxbTGl2ZUFsZXJ0XToKICAgICAgICAiIiJHYXAgR2l2ZSBhbmQgR28gLSBHYXAgdXAsIHB1bGxiYWNrLCBjb250aW51YXRpb24iIiIKICAgICAgICBjdXJyZW50X3dpbmRvdyA9IHNlbGYuX2dldF9jdXJyZW50X3RpbWVfd2luZG93KCkKICAgICAgICAKICAgICAgICBpZiBjdXJyZW50X3dpbmRvdyBub3QgaW4gW1RpbWVXaW5kb3cuT1BFTklOR19EUklWRSwgVGltZVdpbmRvdy5NT1JOSU5HX01PTUVOVFVNXToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAKICAgICAgICBpZiAoc25hcHNob3QuZ2FwX3BjdCA+IDMuMCBhbmQgCiAgICAgICAgICAgIHNuYXBzaG90LmhvbGRpbmdfZ2FwIGFuZAogICAgICAgICAgICBzbmFwc2hvdC5hYm92ZV92d2FwIGFuZAogICAgICAgICAgICAwIDwgc25hcHNob3QuZGlzdF9mcm9tX3Z3YXAgPCAxLjUgYW5kCiAgICAgICAgICAgIHNuYXBzaG90LnJ2b2wgPj0gMi4wKToKICAgICAgICAgICAgCiAgICAgICAgICAgIHByaW9yaXR5ID0gQWxlcnRQcmlvcml0eS5ISUdIIGlmIHRhcGUuY29uZmlybWF0aW9uX2Zvcl9sb25nIGVsc2UgQWxlcnRQcmlvcml0eS5NRURJVU0KICAgICAgICAgICAgCiAgICAgICAgICAgIHJldHVybiBMaXZlQWxlcnQoCiAgICAgICAgICAgICAgICBpZD1mImdhcF9naXZlX2dvX3tzeW1ib2x9X3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJUglTSVTJyl9IiwKICAgICAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgICAgICBzZXR1cF90eXBlPSJnYXBfZ2l2ZV9nbyIsCiAgICAgICAgICAgICAgICBzdHJhdGVneV9uYW1lPSJHYXAgR2l2ZSBhbmQgR28gKElOVC0zNCkiLAogICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJsb25nIiwKICAgICAgICAgICAgICAgIHByaW9yaXR5PXByaW9yaXR5LAogICAgICAgICAgICAgICAgY3VycmVudF9wcmljZT1zbmFwc2hvdC5jdXJyZW50X3ByaWNlLAogICAgICAgICAgICAgICAgdHJpZ2dlcl9wcmljZT1zbmFwc2hvdC5jdXJyZW50X3ByaWNlLAogICAgICAgICAgICAgICAgc3RvcF9sb3NzPXNlbGYuX2F0cl9mbG9vcmVkX3N0b3AoCiAgICAgICAgICAgICAgICAgICAgZW50cnlfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgICAgICByYXdfc3RvcD1zbmFwc2hvdC52d2FwIC0gMC4wMiwKICAgICAgICAgICAgICAgICAgICBhdHI9Z2V0YXR0cihzbmFwc2hvdCwgImF0ciIsIE5vbmUpLAogICAgICAgICAgICAgICAgICAgIGRpcmVjdGlvbj0ibG9uZyIsCiAgICAgICAgICAgICAgICAgICAgbWluX2F0cl9tdWx0PTAuNSwKICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICB0YXJnZXQ9cm91bmQoc25hcHNob3QuaGlnaF9vZl9kYXksIDIpLAogICAgICAgICAgICAgICAgcmlza19yZXdhcmQ9Mi4wLAogICAgICAgICAgICAgICAgdHJpZ2dlcl9wcm9iYWJpbGl0eT0wLjYwLAogICAgICAgICAgICAgICAgd2luX3Byb2JhYmlsaXR5PTAuNTUsCiAgICAgICAgICAgICAgICBtaW51dGVzX3RvX3RyaWdnZXI9MTAsCiAgICAgICAgICAgICAgICBoZWFkbGluZT1mIvCfjoEge3N5bWJvbH0gR2FwIEdpdmUgYW5kIEdvIC0ge3NuYXBzaG90LmdhcF9wY3Q6LjFmfSUgeyfinJMgVEFQRScgaWYgdGFwZS5jb25maXJtYXRpb25fZm9yX2xvbmcgZWxzZSAnJ30iLAogICAgICAgICAgICAgICAgcmVhc29uaW5nPVsKICAgICAgICAgICAgICAgICAgICBmIkdhcCB1cCB7c25hcHNob3QuZ2FwX3BjdDouMWZ9JSIsCiAgICAgICAgICAgICAgICAgICAgIlB1bGxlZCBiYWNrIGJ1dCBob2xkaW5nIFZXQVAiLAogICAgICAgICAgICAgICAgICAgIGYiUlZPTDoge3NuYXBzaG90LnJ2b2w6LjFmfXgiLAogICAgICAgICAgICAgICAgICAgIGYiVGFwZToge3RhcGUub3ZlcmFsbF9zaWduYWwudmFsdWV9IgogICAgICAgICAgICAgICAgXSwKICAgICAgICAgICAgICAgIHRpbWVfd2luZG93PWN1cnJlbnRfd2luZG93LnZhbHVlLAogICAgICAgICAgICAgICAgbWFya2V0X3JlZ2ltZT1zZWxmLl9tYXJrZXRfcmVnaW1lLnZhbHVlLAogICAgICAgICAgICAgICAgZXhwaXJlc19hdD0oZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykgKyB0aW1lZGVsdGEobWludXRlcz00NSkpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gTm9uZQogICAgCg=="

NEW_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfZ2FwX2dpdmVfZ28oc2VsZiwgc3ltYm9sOiBzdHIsIHNuYXBzaG90LCB0YXBlOiBUYXBlUmVhZGluZykgLT4gT3B0aW9uYWxbTGl2ZUFsZXJ0XToKICAgICAgICAiIiJHYXAgR2l2ZSBhbmQgR28gKElOVC0zNCkgLSBET0NUUklORSByZXdyaXRlICh2MzYyKS4KICAgICAgICBTTUIgY2hlYXQtc2hlZXQgc3RydWN0dXJlIG9uIDEtbWluIGJhcnM6IGdhcC11cCwgYSBxdWljayAnZ2l2ZScgKHB1bGxiYWNrKSB0aGF0IGhvbGRzIGFib3ZlCiAgICAgICAgdGhlIHByaW9yIGNsb3NlIGFuZCBkb2VzIE5PVCBmaWxsID41MCUgb2YgdGhlIGdhcCwgdGhlbiBhIDMtNyBiYXIgbWluaS1jb25zb2xpZGF0aW9uIG9uCiAgICAgICAgZGVjbGluaW5nIHZvbHVtZTsgRU5URVIgb24gdGhlIGJyZWFrIG9mIHRoZSBjb25zb2xpZGF0aW9uIGhpZ2gsIFNUT1AgLjAyIGJlbG93IHRoZQogICAgICAgIGNvbnNvbGlkYXRpb24gbG93LCBmaXhlZCAyLjBSIHRhcmdldC4gT3BlbmluZy1kcml2ZSBvbmx5LiAxODBkLzMwMC1zeW0gMS1taW4gcmVwbGF5OgogICAgICAgIG49NDkyIHdpbiA0NyUgd2luc29yQXZnICswLjIzM1IgKHZzIHRoZSBwcmlvciBsb29zZSBWV0FQLXB1bGxiYWNrIGNvZGUgfiswLjA3UikuCiAgICAgICAgU2VlIG1lbW9yeS92MzYyX2dhcF9naXZlX2dvX2J1aWxkLm1kLiIiIgogICAgICAgIGN1cnJlbnRfd2luZG93ID0gc2VsZi5fZ2V0X2N1cnJlbnRfdGltZV93aW5kb3coKQogICAgICAgIGlmIGN1cnJlbnRfd2luZG93IG5vdCBpbiBbVGltZVdpbmRvdy5PUEVOSU5HX0FVQ1RJT04sIFRpbWVXaW5kb3cuT1BFTklOR19EUklWRV06CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIE1JTl9HQVAgPSAxLjAKICAgICAgICBDT05TX01JTiwgQ09OU19NQVggPSAzLCA3CiAgICAgICAgQ09OU19CQU5EX01BWCA9IDAuNiAgICAgICMgY29uc29saWRhdGlvbiBiYW5kIGFzICUgb2YgcHJpY2UKICAgICAgICBWT0xfREVDTElORSA9IDAuNyAgICAgICAgIyBjb25zIGF2ZyB2b2wgbXVzdCBiZSA8PSAwLjd4IHRoZSBnaXZlIGF2ZyB2b2wKICAgICAgICBHSVZFX01BWF9GSUxMID0gNTAuMCAgICAgIyBnaXZlIG11c3Qgbm90IHJldHJhY2UgPjUwJSBvZiB0aGUgZ2FwCiAgICAgICAgVEFSR0VUX1JNVUxUID0gMi4wCgogICAgICAgIGdhcF9wY3QgPSBmbG9hdChnZXRhdHRyKHNuYXBzaG90LCAiZ2FwX3BjdCIsIDAuMCkgb3IgMC4wKQogICAgICAgIHByZXZfY2xvc2UgPSBmbG9hdChnZXRhdHRyKHNuYXBzaG90LCAicHJldl9jbG9zZSIsIDAuMCkgb3IgMC4wKQogICAgICAgIGRheV9vcGVuID0gZmxvYXQoZ2V0YXR0cihzbmFwc2hvdCwgIm9wZW4iLCAwLjApIG9yIDAuMCkKICAgICAgICBjcCA9IGZsb2F0KGdldGF0dHIoc25hcHNob3QsICJjdXJyZW50X3ByaWNlIiwgMC4wKSBvciAwLjApCiAgICAgICAgc2Vzc2lvbl9oaWdoID0gZmxvYXQoZ2V0YXR0cihzbmFwc2hvdCwgImhpZ2hfb2ZfZGF5IiwgMC4wKSBvciAwLjApCiAgICAgICAgaWYgZ2FwX3BjdCA8IE1JTl9HQVAgb3IgcHJldl9jbG9zZSA8PSAwIG9yIGNwIDw9IDAgb3IgZGF5X29wZW4gPD0gcHJldl9jbG9zZToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgdHMgPSBnZXRhdHRyKHNlbGYsICJ0ZWNobmljYWxfc2VydmljZSIsIE5vbmUpCiAgICAgICAgaWYgdHMgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBiYXJzID0gdHMuX2dldF9pbnRyYWRheV9iYXJzX2Zyb21fZGIoc3ltYm9sLCAiMSBtaW4iLCA2MCkKICAgICAgICBpZiBub3QgYmFycyBvciBsZW4oYmFycykgPCBDT05TX01JTiArIDI6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGkgPSBsZW4oYmFycykgLSAxICAgICAgICAgICAgICAgICAgICAgICAjIGN1cnJlbnQvbW9zdC1yZWNlbnQgYmFyID0gdGhlIHJhbmdlLWJyZWFrIGJhcgogICAgICAgIGxhc3RfaGlnaCA9IGJhcnNbaV0uZ2V0KCJoaWdoIikKICAgICAgICBpZiBsYXN0X2hpZ2ggaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgY2hvc2VuID0gTm9uZQogICAgICAgIGZvciB3IGluIHJhbmdlKENPTlNfTUFYLCBDT05TX01JTiAtIDEsIC0xKToKICAgICAgICAgICAgYSA9IGkgLSB3CiAgICAgICAgICAgIGlmIGEgPCAxOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgY3cgPSBiYXJzW2E6aV0KICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY29uc19oaWdoID0gbWF4KGJbImhpZ2giXSBmb3IgYiBpbiBjdykKICAgICAgICAgICAgICAgIGNvbnNfbG93ID0gbWluKGJbImxvdyJdIGZvciBiIGluIGN3KQogICAgICAgICAgICBleGNlcHQgKEtleUVycm9yLCBUeXBlRXJyb3IsIFZhbHVlRXJyb3IpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgYmFuZCA9IGNvbnNfaGlnaCAtIGNvbnNfbG93CiAgICAgICAgICAgIGlmIGJhbmQgPD0gMCBvciBiYW5kIC8gY3AgKiAxMDAuMCA+IENPTlNfQkFORF9NQVg6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBzZXNzaW9uX2hpZ2ggPiAwIGFuZCBjb25zX2hpZ2ggPj0gc2Vzc2lvbl9oaWdoOiAgICAgICMgYSBnaXZlL3B1bGxiYWNrIG11c3QgaGF2ZSBoYXBwZW5lZAogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgY29uc19sb3cgPD0gcHJldl9jbG9zZTogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAjIGNvbnNvbGlkYXRpb24gaG9sZHMgYWJvdmUgc3VwcG9ydAogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgZ2l2ZV9sb3dzID0gW2JbImxvdyJdIGZvciBiIGluIGJhcnNbOmFdIGlmIGIuZ2V0KCJsb3ciKSBpcyBub3QgTm9uZV0KICAgICAgICAgICAgZ2l2ZV9sb3cgPSBtaW4oZ2l2ZV9sb3dzKSBpZiBnaXZlX2xvd3MgZWxzZSBjb25zX2xvdwogICAgICAgICAgICBpZiAoZGF5X29wZW4gLSBnaXZlX2xvdykgLyAoZGF5X29wZW4gLSBwcmV2X2Nsb3NlKSAqIDEwMC4wID4gR0lWRV9NQVhfRklMTDoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGdpdmVfdiA9IFtiWyJ2b2x1bWUiXSBmb3IgYiBpbiBiYXJzWzphXSBpZiAoYi5nZXQoInZvbHVtZSIpIG9yIDApID4gMF0KICAgICAgICAgICAgY29uc192ID0gW2JbInZvbHVtZSJdIGZvciBiIGluIGN3IGlmIChiLmdldCgidm9sdW1lIikgb3IgMCkgPiAwXQogICAgICAgICAgICBpZiBnaXZlX3YgYW5kIGNvbnNfdiBhbmQgKHN1bShjb25zX3YpIC8gbGVuKGNvbnNfdikpID4gVk9MX0RFQ0xJTkUgKiAoc3VtKGdpdmVfdikgLyBsZW4oZ2l2ZV92KSk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBjaG9zZW4gPSAoY29uc19oaWdoLCBjb25zX2xvdykKICAgICAgICAgICAgYnJlYWsKICAgICAgICBpZiBub3QgY2hvc2VuOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGNvbnNfaGlnaCwgY29uc19sb3cgPSBjaG9zZW4KCiAgICAgICAgZW50cnkgPSByb3VuZChjb25zX2hpZ2ggKyAwLjAxLCAyKQogICAgICAgIGlmIG5vdCAoY3AgPj0gZW50cnkgb3IgbGFzdF9oaWdoID49IGVudHJ5KTogICAgICAgICAgICAgICAgICMgcmFuZ2UtYnJlYWsgbXVzdCBiZSBwcmludGluZwogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHN0b3AgPSByb3VuZChjb25zX2xvdyAtIDAuMDIsIDIpCiAgICAgICAgcmlzayA9IGVudHJ5IC0gc3RvcAogICAgICAgIGlmIHJpc2sgPD0gMDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICB0YXJnZXQgPSByb3VuZChlbnRyeSArIFRBUkdFVF9STVVMVCAqIHJpc2ssIDIpCgogICAgICAgIHByaW9yaXR5ID0gQWxlcnRQcmlvcml0eS5ISUdIIGlmIHRhcGUuY29uZmlybWF0aW9uX2Zvcl9sb25nIGVsc2UgQWxlcnRQcmlvcml0eS5NRURJVU0KICAgICAgICByZXR1cm4gTGl2ZUFsZXJ0KAogICAgICAgICAgICBpZD1mImdhcF9naXZlX2dvX3tzeW1ib2x9X3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJUglTSVTJyl9IiwKICAgICAgICAgICAgc3ltYm9sPXN5bWJvbCwKICAgICAgICAgICAgc2V0dXBfdHlwZT0iZ2FwX2dpdmVfZ28iLAogICAgICAgICAgICBzdHJhdGVneV9uYW1lPSJHYXAgR2l2ZSBhbmQgR28gKElOVC0zNCkiLAogICAgICAgICAgICBkaXJlY3Rpb249ImxvbmciLAogICAgICAgICAgICBwcmlvcml0eT1wcmlvcml0eSwKICAgICAgICAgICAgY3VycmVudF9wcmljZT1jcCwKICAgICAgICAgICAgdHJpZ2dlcl9wcmljZT1lbnRyeSwKICAgICAgICAgICAgc3RvcF9sb3NzPXN0b3AsCiAgICAgICAgICAgIHRhcmdldD10YXJnZXQsCiAgICAgICAgICAgIHJpc2tfcmV3YXJkPVRBUkdFVF9STVVMVCwKICAgICAgICAgICAgdHJpZ2dlcl9wcm9iYWJpbGl0eT0wLjYwLAogICAgICAgICAgICB3aW5fcHJvYmFiaWxpdHk9MC41NSwKICAgICAgICAgICAgbWludXRlc190b190cmlnZ2VyPTUsCiAgICAgICAgICAgIGhlYWRsaW5lPWYi8J+OgSB7c3ltYm9sfSBHYXAgR2l2ZSBhbmQgR28gLSB7Z2FwX3BjdDouMWZ9JSBicmVhayB7J+KckyBUQVBFJyBpZiB0YXBlLmNvbmZpcm1hdGlvbl9mb3JfbG9uZyBlbHNlICcnfSIsCiAgICAgICAgICAgIHJlYXNvbmluZz1bCiAgICAgICAgICAgICAgICBmIkdhcCB1cCB7Z2FwX3BjdDouMWZ9JSwgZ2l2ZSBoZWxkIGFib3ZlIHByaW9yIGNsb3NlIiwKICAgICAgICAgICAgICAgIGYiMy03IGJhciBjb25zb2xpZGF0aW9uIHtjb25zX2xvdzouMmZ9LXtjb25zX2hpZ2g6LjJmfSBvbiBkZWNsaW5pbmcgdm9sdW1lIiwKICAgICAgICAgICAgICAgIGYiQnJlYWsgZW50cnkge2VudHJ5Oi4yZn0sIHN0b3Age3N0b3A6LjJmfSAoY29ucyBsb3cpLCAyUiB0YXJnZXQge3RhcmdldDouMmZ9IiwKICAgICAgICAgICAgICAgIGYiVGFwZToge3RhcGUub3ZlcmFsbF9zaWduYWwudmFsdWV9IgogICAgICAgICAgICBdLAogICAgICAgICAgICB0aW1lX3dpbmRvdz1jdXJyZW50X3dpbmRvdy52YWx1ZSwKICAgICAgICAgICAgbWFya2V0X3JlZ2ltZT1zZWxmLl9tYXJrZXRfcmVnaW1lLnZhbHVlLAogICAgICAgICAgICBleHBpcmVzX2F0PShkYXRldGltZS5ub3codGltZXpvbmUudXRjKSArIHRpbWVkZWx0YShtaW51dGVzPTMwKSkuaXNvZm9ybWF0KCkKICAgICAgICApCiAgICAK"


def main():
    check = "--check" in sys.argv
    src = open(FILE, encoding="utf-8").read()
    cur_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
    print(f"file            : {FILE}")
    print(f"live SHA        : {cur_sha}")
    print(f"expected SHA    : {PRE_FILE_SHA}")
    if cur_sha != PRE_FILE_SHA:
        print("\nABORT: live file SHA != expected baseline. The DGX file has DRIFTED.")
        print("Re-run extract_func.py _check_gap_give_go and rebase. NOTHING was written.")
        sys.exit(2)

    old = base64.b64decode(OLD_B64).decode("utf-8")
    new = base64.b64decode(NEW_B64).decode("utf-8")
    n = src.count(old)
    print(f"OLD anchor count: {n}  (MUST be 1)")
    if n != 1:
        print("\nABORT: OLD anchor not uniquely found. NOTHING was written.")
        sys.exit(3)

    patched = src.replace(old, new, 1)
    post_sha = hashlib.sha256(patched.encode("utf-8")).hexdigest()
    if patched.count(new) != 1 or old in patched:
        print("\nABORT: post-replace self-check failed. NOTHING was written.")
        sys.exit(4)

    # compile the patched content before touching disk
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(patched); tmp = tf.name
    try:
        py_compile.compile(tmp, doraise=True)
    except py_compile.PyCompileError as e:
        print(f"\nABORT: patched file fails to compile: {e}. NOTHING was written.")
        sys.exit(5)
    print(f"POST SHA        : {post_sha}")
    print("py_compile      : OK")

    if check:
        print("\n--check OK: guards pass, OLD found exactly once, patched compiles cleanly.")
        print("Run without --check to apply.")
        return

    bak = FILE + ".v362.bak"
    shutil.copy2(FILE, bak)
    with open(FILE, "w", encoding="utf-8") as f:
        f.write(patched)
    verify = hashlib.sha256(open(FILE, encoding="utf-8").read().encode("utf-8")).hexdigest()
    if verify != post_sha:
        print(f"\nABORT: post-write verify mismatch ({verify} != {post_sha}).")
        sys.exit(6)
    print(f"\nAPPLIED. backup -> {bak}")
    print(f"new live SHA    : {verify}")
    print("Next: pytest -> commit -> ./start_backend.sh --force")


if __name__ == "__main__":
    main()
