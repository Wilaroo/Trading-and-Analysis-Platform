#!/usr/bin/env python3
"""
patch_v353_second_chance_doctrine.py  (AGENTS.md 2.2 -- function-anchored patcher)

WHAT: rewrites enhanced_scanner._check_second_chance from the shipped near-VWAP momentum
      filter (within 0.5% above VWAP, uptrend, rvol>=1.2; stop=VWAP-0.5*ATR, target=HOD,
      R:R hard-coded 2.0) to the OFFICIAL SMB "2nd Chance Scalp": a RESISTANCE break on a
      HIGH-volume rush -> LOW-volume retest that HOLDS old resistance as new support ->
      confirmation candle closing above the prior candle. STOP = .02 below the TURN-CANDLE
      LOW; TARGET = the rush high (high of the initial pullback). LONG only, max 2/day/symbol.
WHY : the shipped rule is NEGATIVE-EV. v353 native-1min replay (diag_v353_second_chance_replay):
      LIVE-PROXY winsorAvg -0.062R over 3,761 fires (-233R total). The doctrine, RR-GATED to
      1.5-2.5 (the only +EV slice; >=2.5 was dead), is +EV and beats it:
        14d vol-filter 1.3: n=211, 39% win, winsorAvg +0.092R, avg R:R 1.92
        21d:                n=381, 38% win, winsorAvg +0.048R, avg R:R 1.89
      Cheat sheet claims ~1.9:1 R:R, 50-55% win. 1-min bars from ib_historical_data (IB-only)
      via self.technical_service._get_intraday_bars_from_db(sym,"1 min",60).

DRIFT NOTE: FUNCTION-ANCHORED. Asserts live whole-file SHA == DGX baseline AND the exact live
      _check_second_chance bytes present (count==1), replaces, asserts embedded NEW func SHA,
      py_compiles the whole file before writing. backup + func-SHA guards cover the (paste-
      limited) whole POST.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/patch_v353_second_chance_doctrine.py --check
  .venv/bin/python backend/scripts/patch_v353_second_chance_doctrine.py --apply
  .venv/bin/python backend/scripts/patch_v353_second_chance_doctrine.py --rollback
Then: pytest backend/tests/test_v353_second_chance.py -q ; commit ; ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os, py_compile, tempfile

FILE = "backend/services/enhanced_scanner.py"
DGX_WHOLE_PRE = "907581dcf313c5d1ba4e275d2de548dbf8f5119ecd479129c8dad63d77f0a50e"
PRE_FUNC_SHA  = "3b3d1209aa10f8032323154952387de633c0a0931ff1e2bfc20b19bbb7862cb1"
POST_FUNC_SHA = "7830560a5aca78cc42f2c553e3883c37b486e8b3d9f081d2692ca2efd562d892"
OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfc2Vjb25kX2NoYW5jZShzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIlNlY29uZCBDaGFuY2UgLSBSZXRlc3Qgb2YgYnJva2VuIGxldmVsIiIiCiAgICAgICAgZGlzdF9mcm9tX3Z3YXAgPSBhYnMoc25hcHNob3QuZGlzdF9mcm9tX3Z3YXApCiAgICAgICAgCiAgICAgICAgaWYgKGRpc3RfZnJvbV92d2FwIDwgMC41IGFuZCAKICAgICAgICAgICAgc25hcHNob3QuYWJvdmVfdndhcCBhbmQgCiAgICAgICAgICAgIHNuYXBzaG90LnRyZW5kID09ICJ1cHRyZW5kIiBhbmQKICAgICAgICAgICAgc25hcHNob3QucnZvbCA+PSAxLjIpOgogICAgICAgICAgICAKICAgICAgICAgICAgIyB2MTkuMzQuMzIwciDigJQgdGFwZS1nYXRlZCBISUdIIGJyYW5jaCAod2FzIGhhcmRjb2RlZCBNRURJVU0sIHdoaWNoCiAgICAgICAgICAgICMgY2FwcGVkIHRoaXMgaW50cmFkYXkgc2NhbHAgYmVsb3cgdGhlIGF1dG8tZmlyZSBiYXIgcmVnYXJkbGVzcyBvZgogICAgICAgICAgICAjIHNpZ25hbCBxdWFsaXR5OyBzZWUgdjMyMHEgKyB2MzIwci1wcmVjaGVjaykuIE9ubHkgdGhlIHRhcGUtY29uZmlybWVkCiAgICAgICAgICAgICMgc3Vic2V0IHByb21vdGVzOyBFVi93aW4tcmF0ZSBnYXRlIHN0aWxsIGdvdmVybnMgYXV0by1maXJlLgogICAgICAgICAgICBwcmlvcml0eSA9IEFsZXJ0UHJpb3JpdHkuSElHSCBpZiB0YXBlLmNvbmZpcm1hdGlvbl9mb3JfbG9uZyBlbHNlIEFsZXJ0UHJpb3JpdHkuTUVESVVNCiAgICAgICAgICAgIAogICAgICAgICAgICByZXR1cm4gTGl2ZUFsZXJ0KAogICAgICAgICAgICAgICAgaWQ9ZiJzZWNvbmRfY2hhbmNlX3tzeW1ib2x9X3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJUglTSVTJyl9IiwKICAgICAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgICAgICBzZXR1cF90eXBlPSJzZWNvbmRfY2hhbmNlIiwKICAgICAgICAgICAgICAgIHN0cmF0ZWd5X25hbWU9IlNlY29uZCBDaGFuY2UgU2NhbHAgKElOVC0yNCkiLAogICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJsb25nIiwKICAgICAgICAgICAgICAgIHByaW9yaXR5PXByaW9yaXR5LAogICAgICAgICAgICAgICAgY3VycmVudF9wcmljZT1zbmFwc2hvdC5jdXJyZW50X3ByaWNlLAogICAgICAgICAgICAgICAgdHJpZ2dlcl9wcmljZT1zbmFwc2hvdC52d2FwLAogICAgICAgICAgICAgICAgc3RvcF9sb3NzPXJvdW5kKHNuYXBzaG90LnZ3YXAgLSAoc25hcHNob3QuYXRyICogMC41KSwgMiksCiAgICAgICAgICAgICAgICB0YXJnZXQ9cm91bmQoc25hcHNob3QuaGlnaF9vZl9kYXksIDIpLAogICAgICAgICAgICAgICAgcmlza19yZXdhcmQ9Mi4wLAogICAgICAgICAgICAgICAgdHJpZ2dlcl9wcm9iYWJpbGl0eT0wLjU1LAogICAgICAgICAgICAgICAgd2luX3Byb2JhYmlsaXR5PTAuNTUsCiAgICAgICAgICAgICAgICBtaW51dGVzX3RvX3RyaWdnZXI9MTUsCiAgICAgICAgICAgICAgICBoZWFkbGluZT1mIvCflIQge3N5bWJvbH0gU2Vjb25kIENoYW5jZSAtIFJldGVzdGluZyBWV0FQIiwKICAgICAgICAgICAgICAgIHJlYXNvbmluZz1bCiAgICAgICAgICAgICAgICAgICAgZiJSZXRlc3RpbmcgVldBUCAke3NuYXBzaG90LnZ3YXA6LjJmfSIsCiAgICAgICAgICAgICAgICAgICAgIlVwdHJlbmQgaW50YWN0IiwKICAgICAgICAgICAgICAgICAgICBmIlRhcGU6IHt0YXBlLm92ZXJhbGxfc2lnbmFsLnZhbHVlfSIKICAgICAgICAgICAgICAgIF0sCiAgICAgICAgICAgICAgICB0aW1lX3dpbmRvdz1zZWxmLl9nZXRfY3VycmVudF90aW1lX3dpbmRvdygpLnZhbHVlLAogICAgICAgICAgICAgICAgbWFya2V0X3JlZ2ltZT1zZWxmLl9tYXJrZXRfcmVnaW1lLnZhbHVlLAogICAgICAgICAgICAgICAgZXhwaXJlc19hdD0oZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykgKyB0aW1lZGVsdGEoaG91cnM9MSkpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gTm9uZQogICAgCg=="
NEW_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfc2Vjb25kX2NoYW5jZShzZWxmLCBzeW1ib2w6IHN0ciwgc25hcHNob3QsIHRhcGU6IFRhcGVSZWFkaW5nKSAtPiBPcHRpb25hbFtMaXZlQWxlcnRdOgogICAgICAgICIiIlNlY29uZCBDaGFuY2UgU2NhbHAgXHUyMDE0IGNoZWF0LXNoZWV0LWZhaXRoZnVsIHJlc2lzdGFuY2UgYnJlYWsgXHUyMTkyIGxvdy12b2wgcmV0ZXN0ICh2MTkuMzQuMzUzKS4KCiAgICAgICAgVGhlIHNoaXBwZWQgZGV0ZWN0b3Igd2FzIGEgZ2VuZXJpYyAibmVhci1WV0FQIG1vbWVudHVtIiBmaWx0ZXIgKHdpdGhpbiAwLjUlIGFib3ZlIFZXQVAsCiAgICAgICAgdXB0cmVuZCwgcnZvbD49MS4yOyBzdG9wPVZXQVAtMC41KkFUUiwgdGFyZ2V0PUhJR0hfT0ZfREFZLCBSOlIgaGFyZC1jb2RlZCAyLjApLiBBIDE0ZCAmCiAgICAgICAgMjFkIG5hdGl2ZS0xbWluIHJlcGxheSBzaG93ZWQgdGhhdCBydWxlIGlzIE5FR0FUSVZFLUVWICh3aW5zb3JBdmcgLTAuMDZSIG92ZXIgMyw3NjEgZmlyZXMsCiAgICAgICAgLTIzM1IgdG90YWwpLiBUaGUgU01CICIybmQgQ2hhbmNlIFNjYWxwIiBpcyBhIFJFU0lTVEFOQ0UtUkVURVNUIHNjYWxwLCBOT1QgYSBWV0FQIHBsYXk6CiAgICAgICAgICAxKSBhIHJlc2lzdGFuY2UgbGV2ZWwgYnJlYWtzIG9uIGEgc3Ryb25nLCBISUdILVZPTFVNRSBydXNoIG91dCBvZiByYW5nZSwKICAgICAgICAgIDIpIHByaWNlIFBVTExTIEJBQ0sgYW5kIFJFVEVTVFMgdGhlIGJyb2tlbiBsZXZlbCBvbiBMT1cgdm9sdW1lIFx1MjAxNCBvbGQgcmVzaXN0YW5jZSBtdXN0CiAgICAgICAgICAgICBIT0xEIGFzIG5ldyBzdXBwb3J0IChkbyBOT1QgZmFsbCBiYWNrIGludG8gdGhlIHJhbmdlKSwKICAgICAgICAgIDMpIEVOVEVSIG9uIGEgY29uZmlybWF0aW9uIGNhbmRsZSB0aGF0IGNsb3NlcyBBQk9WRSB0aGUgcHJpb3IgY2FuZGxlIChidXllcnMgcmV0dXJuZWQpLAogICAgICAgICAgNCkgU1RPUCA9IC4wMiBiZWxvdyB0aGUgTE9XIE9GIFRIRSBUVVJOIENBTkRMRSAobmV3IHN1cHBvcnQpLAogICAgICAgICAgNSkgVEFSR0VUID0gdGhlIEhJR0ggT0YgVEhFIElOSVRJQUwgUFVMTEJBQ0sgKHRoZSBydXNoIGhpZ2ggdGhhdCBzZXQgdXAgdGhlIHNjYWxwKS4KICAgICAgICBWYWxpZGF0ZWQgKHYzNTMgcmVwbGF5LCBSUi1nYXRlZCAxLjUtMi41ID0gdGhlIG9ubHkgK0VWIHNsaWNlOyB0aGUgPj0yLjUgYmFuZCB3YXMgZGVhZCk6CiAgICAgICAgICAxNGQgdm9sLWZpbHRlcmVkOiBuPTIxMSwgMzklIHdpbiwgd2luc29yQXZnICswLjA5MlIsIGF2ZyBSOlIgMS45MjsKICAgICAgICAgIDIxZDogbj0zODEsIDM4JSB3aW4sIHdpbnNvckF2ZyArMC4wNDhSLCBhdmcgUjpSIDEuODkgXHUyMDE0ICtFViBhbmQgYmVhdHMgdGhlIGxpdmUgcnVsZS4KICAgICAgICBMT05HIG9ubHkuIDEtbWluIGJhcnMgZnJvbSBpYl9oaXN0b3JpY2FsX2RhdGEgKElCLW9ubHkpIHZpYSB0ZWNobmljYWxfc2VydmljZS4gTWF4IDIKICAgICAgICBhdHRlbXB0cy9kYXkvc3ltYm9sIChjaGVhdC1zaGVldCAiMiBzdHJpa2VzIGFuZCB3ZSdyZSBvdXQiKS4KICAgICAgICAiIiIKICAgICAgICBSRVNMT09LID0gMTUgICAgICAgICAgIyBjb25zb2xpZGF0aW9uIGxvb2tiYWNrID0gdGhlIHJlc2lzdGFuY2Ugd2luZG93IGJlZm9yZSB0aGUgcnVzaAogICAgICAgIFJVU0hXSU4gPSA2ICAgICAgICAgICAjIGJhcnMgb3ZlciB3aGljaCB0aGUgYnJlYWtvdXQgcnVzaCBoaWdoIGlzIG1lYXN1cmVkCiAgICAgICAgUkVUVEVTVCA9IDQgICAgICAgICAgICMgYmFycyBvdmVyIHdoaWNoIHRoZSByZXRlc3QgLyB0dXJuLWNhbmRsZSBsb3cgaXMgbWVhc3VyZWQKICAgICAgICBSRVRUT0wgPSAwLjIwICAgICAgICAgIyByZXRlc3QgbG93IG11c3QgY29tZSB3aXRoaW4gUkVUVE9MJSBhYm92ZSB0aGUgYnJva2VuIGxldmVsCiAgICAgICAgU1VQUE9SVFRPTCA9IDAuMTUgICAgICMgdHVybiBsb3cgbWF5IGRpcCBhdCBtb3N0IFNVUFBPUlRUT0wlIGJlbG93IHRoZSBsZXZlbCAoc3VwcG9ydCBoZWxkKQogICAgICAgIE1JTkJSRUFLID0gMC4xMCAgICAgICAjIHJ1c2ggbXVzdCBjbGVhciByZXNpc3RhbmNlIGJ5ID49IE1JTkJSRUFLJQogICAgICAgIFZPTE1VTFQgPSAxLjMgICAgICAgICAjIGJyZWFrIHZvbHVtZSBtdXN0IGJlID49IFZPTE1VTFQgKiBjb25zb2xpZGF0aW9uIG1lZGlhbiB2b2x1bWUKICAgICAgICBNQVhCUkVBS01VTFQgPSAxLjAgICAgIyBydXNoIGhlaWdodCBtdXN0IGJlIDw9IE1BWEJSRUFLTVVMVCAqIHByaW9yIHJhbmdlIGhlaWdodAogICAgICAgIE1JTl9SUiA9IDEuNSAgICAgICAgICAjIFJSIGdhdGUgKHZhbGlkYXRlZCArRVYgc2xpY2UgaXMgMS41LTIuNTsgZG9jdHJpbmUgfjEuOToxKQogICAgICAgIE1BWF9SUiA9IDIuNQoKICAgICAgICB0cyA9IGdldGF0dHIoc2VsZiwgInRlY2huaWNhbF9zZXJ2aWNlIiwgTm9uZSkKICAgICAgICBpZiB0cyBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGJhcnMgPSB0cy5fZ2V0X2ludHJhZGF5X2JhcnNfZnJvbV9kYihzeW1ib2wsICIxIG1pbiIsIDYwKQogICAgICAgIG5lZWQgPSBSRVNMT09LICsgUlVTSFdJTiArIFJFVFRFU1QgKyAzCiAgICAgICAgaWYgbm90IGJhcnMgb3IgbGVuKGJhcnMpIDwgbmVlZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgY2FwcyA9IGdldGF0dHIoc2VsZiwgIl9zZWNvbmRfY2hhbmNlX2RhaWx5X2NhcHMiLCBOb25lKQogICAgICAgIGlmIGNhcHMgaXMgTm9uZToKICAgICAgICAgICAgY2FwcyA9IHNlbGYuX3NlY29uZF9jaGFuY2VfZGFpbHlfY2FwcyA9IHt9CiAgICAgICAgdG9kYXkgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5zdHJmdGltZSgiJVktJW0tJWQiKQogICAgICAgIGtleSA9IGYie3N5bWJvbH06e3RvZGF5fTpsb25nIgogICAgICAgIGlmIGNhcHMuZ2V0KGtleSwgMCkgPj0gMjoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgZGVmIF9tZWRpYW4oeHMpOgogICAgICAgICAgICBzID0gc29ydGVkKHhzKQogICAgICAgICAgICBuID0gbGVuKHMpCiAgICAgICAgICAgIGlmIG4gPT0gMDoKICAgICAgICAgICAgICAgIHJldHVybiAwLjAKICAgICAgICAgICAgcmV0dXJuIHNbbiAvLyAyXSBpZiBuICUgMiBlbHNlIChzW24gLy8gMiAtIDFdICsgc1tuIC8vIDJdKSAvIDIuMAoKICAgICAgICBpID0gbGVuKGJhcnMpIC0gMQogICAgICAgIGxhc3QgPSBiYXJzW2ldCiAgICAgICAgZm9yIGIgaW4gKGJhcnNbaV0sIGJhcnNbaSAtIDFdKToKICAgICAgICAgICAgaWYgKGIuZ2V0KCJoaWdoIikgaXMgTm9uZSBvciBiLmdldCgibG93IikgaXMgTm9uZQogICAgICAgICAgICAgICAgICAgIG9yIGIuZ2V0KCJjbG9zZSIpIGlzIE5vbmUgb3IgYi5nZXQoIm9wZW4iKSBpcyBOb25lKToKICAgICAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGNvbnMgPSBiYXJzW2kgLSBSRVNMT09LIC0gUlVTSFdJTjppIC0gUlVTSFdJTl0gICAjIGNvbnNvbGlkYXRpb24gYmVmb3JlIHRoZSBydXNoCiAgICAgICAgcnVzaCA9IGJhcnNbaSAtIFJVU0hXSU46aV0gICAgICAgICAgICAgICAgICAgICAgICAjIHJ1c2ggKyBwdWxsYmFjayAoZXhjbC4gZW50cnkgYmFyKQogICAgICAgIHJldCA9IGJhcnNbaSAtIFJFVFRFU1Q6aV0gICAgICAgICAgICAgICAgICAgICAgICAgIyByZXRlc3QgLyB0dXJuIHJlZ2lvbiAoZXhjbC4gZW50cnkgYmFyKQogICAgICAgIGlmIG5vdCBjb25zIG9yIG5vdCBydXNoIG9yIG5vdCByZXQ6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIHJlc2lzdGFuY2UgPSBtYXgoYlsiaGlnaCJdIGZvciBiIGluIGNvbnMpCiAgICAgICAgY29uc19sbyA9IG1pbihiWyJsb3ciXSBmb3IgYiBpbiBjb25zKQogICAgICAgIHByaW9yX3JhbmdlID0gcmVzaXN0YW5jZSAtIGNvbnNfbG8KICAgICAgICBydXNoX2hpZ2ggPSBtYXgoYlsiaGlnaCJdIGZvciBiIGluIHJ1c2gpCiAgICAgICAgdHVybl9iYXIgPSBtaW4ocmV0LCBrZXk9bGFtYmRhIGI6IGJbImxvdyJdKQogICAgICAgIHR1cm5fbG93ID0gdHVybl9iYXJbImxvdyJdCiAgICAgICAgbWVkX3ZvbCA9IF9tZWRpYW4oW2IuZ2V0KCJ2b2x1bWUiKSBvciAwIGZvciBiIGluIGNvbnNdKQogICAgICAgIGJyZWFrX3ZvbCA9IG1heChiLmdldCgidm9sdW1lIikgb3IgMCBmb3IgYiBpbiBydXNoKQogICAgICAgIHJldGVzdF92b2wgPSBtaW4oYi5nZXQoInZvbHVtZSIpIG9yIDAgZm9yIGIgaW4gcmV0KQoKICAgICAgICBicm9rZSA9IHJ1c2hfaGlnaCA+PSByZXNpc3RhbmNlICogKDEgKyBNSU5CUkVBSyAvIDEwMC4wKQogICAgICAgIG5lYXIgPSB0dXJuX2xvdyA8PSByZXNpc3RhbmNlICogKDEgKyBSRVRUT0wgLyAxMDAuMCkKICAgICAgICBoZWxkID0gdHVybl9sb3cgPj0gcmVzaXN0YW5jZSAqICgxIC0gU1VQUE9SVFRPTCAvIDEwMC4wKQogICAgICAgIHZvbF9vayA9IChtZWRfdm9sIDw9IDApIG9yIChicmVha192b2wgPj0gVk9MTVVMVCAqIG1lZF92b2wgYW5kIHJldGVzdF92b2wgPCBicmVha192b2wpCiAgICAgICAgY29uZmlybSA9IChsYXN0WyJjbG9zZSJdID4gbGFzdFsib3BlbiJdKSBhbmQgKGxhc3RbImNsb3NlIl0gPiBiYXJzW2kgLSAxXVsiaGlnaCJdKQogICAgICAgIG5vdF90b29fdGFsbCA9IChNQVhCUkVBS01VTFQgPD0gMCkgb3IgKHByaW9yX3JhbmdlIDw9IDApIG9yIFwKICAgICAgICAgICAgKChydXNoX2hpZ2ggLSByZXNpc3RhbmNlKSA8PSBNQVhCUkVBS01VTFQgKiBwcmlvcl9yYW5nZSkKCiAgICAgICAgaWYgbm90IChicm9rZSBhbmQgbmVhciBhbmQgaGVsZCBhbmQgdm9sX29rIGFuZCBjb25maXJtIGFuZCBub3RfdG9vX3RhbGwpOgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAgICBlbnRyeSA9IHJvdW5kKGxhc3RbImNsb3NlIl0sIDIpCiAgICAgICAgc3RvcF9sb3NzID0gcm91bmQodHVybl9sb3cgLSAwLjAyLCAyKQogICAgICAgIHRhcmdldF8xID0gcm91bmQocnVzaF9oaWdoLCAyKQogICAgICAgIHJpc2sgPSBlbnRyeSAtIHN0b3BfbG9zcwogICAgICAgIGlmIHJpc2sgPD0gMCBvciBlbnRyeSA8PSAwIG9yIHRhcmdldF8xIDw9IGVudHJ5OgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHJyID0gKHRhcmdldF8xIC0gZW50cnkpIC8gcmlzawogICAgICAgIGlmIHJyIDwgTUlOX1JSIG9yIHJyID4gTUFYX1JSOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHJfbXVsdGlwbGUgPSByb3VuZChyciwgMikKCiAgICAgICAgY2Fwc1trZXldID0gY2Fwcy5nZXQoa2V5LCAwKSArIDEKICAgICAgICBwcmlvcml0eSA9IEFsZXJ0UHJpb3JpdHkuSElHSCBpZiB0YXBlLmNvbmZpcm1hdGlvbl9mb3JfbG9uZyBlbHNlIEFsZXJ0UHJpb3JpdHkuTUVESVVNCiAgICAgICAgZXZfaW5mbyA9ICIiCiAgICAgICAgaWYgInNlY29uZF9jaGFuY2UiIGluIHNlbGYuX3N0cmF0ZWd5X3N0YXRzOgogICAgICAgICAgICBzdCA9IHNlbGYuX3N0cmF0ZWd5X3N0YXRzWyJzZWNvbmRfY2hhbmNlIl0KICAgICAgICAgICAgaWYgc3Qud2luX3JhdGUgPiAwOgogICAgICAgICAgICAgICAgZXZfaW5mbyA9IGYiSGlzdG9yaWNhbDoge3N0Lndpbl9yYXRlOi4wJX0gd2luLCBFViB7c3QuZXhwZWN0ZWRfdmFsdWVfcjouMmZ9UiIKICAgICAgICB0YXBlX3RhZyA9ICJcdTI3MTMgVEFQRSIgaWYgdGFwZS5jb25maXJtYXRpb25fZm9yX2xvbmcgZWxzZSAiIgogICAgICAgIHJldHVybiBMaXZlQWxlcnQoCiAgICAgICAgICAgIGlkPWYic2Vjb25kX2NoYW5jZV97c3ltYm9sfV97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVIJU0lUycpfSIsCiAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgIHNldHVwX3R5cGU9InNlY29uZF9jaGFuY2UiLAogICAgICAgICAgICBzdHJhdGVneV9uYW1lPSJTZWNvbmQgQ2hhbmNlIFNjYWxwIChJTlQtMjQpIiwKICAgICAgICAgICAgZGlyZWN0aW9uPSJsb25nIiwKICAgICAgICAgICAgcHJpb3JpdHk9cHJpb3JpdHksCiAgICAgICAgICAgIGN1cnJlbnRfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgdHJpZ2dlcl9wcmljZT1lbnRyeSwKICAgICAgICAgICAgc3RvcF9sb3NzPXN0b3BfbG9zcywKICAgICAgICAgICAgdGFyZ2V0PXRhcmdldF8xLAogICAgICAgICAgICByaXNrX3Jld2FyZD1yX211bHRpcGxlLAogICAgICAgICAgICB0cmlnZ2VyX3Byb2JhYmlsaXR5PTAuNDAsCiAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjQwLAogICAgICAgICAgICBtaW51dGVzX3RvX3RyaWdnZXI9MCwKICAgICAgICAgICAgaGVhZGxpbmU9ZiJcVTAwMDFmNTA0IHtzeW1ib2x9IFNlY29uZCBDaGFuY2UgXHUyMDE0IGJyb2tlbiAke3Jlc2lzdGFuY2U6LjJmfSByZXRlc3RlZCAmIGhlbGQgKFI6UiB7cl9tdWx0aXBsZTouMWZ9KSB7dGFwZV90YWd9IiwKICAgICAgICAgICAgcmVhc29uaW5nPVsKICAgICAgICAgICAgICAgIGYiUmVzaXN0YW5jZSAke3Jlc2lzdGFuY2U6LjJmfSBicm9rZSBvbiBydXNoIHRvICR7cnVzaF9oaWdoOi4yZn07IGxvdy12b2wgcmV0ZXN0IGhlbGQgYXMgc3VwcG9ydCIsCiAgICAgICAgICAgICAgICBmIlR1cm4tY2FuZGxlIGxvdyAke3R1cm5fbG93Oi4yZn07IGNvbmZpcm0gYmFyIGNsb3NlZCBhYm92ZSBwcmlvciBoaWdoIFx1MjAxNCBidXllcnMgcmV0dXJuZWQiLAogICAgICAgICAgICAgICAgZiJSOlIgPSB7cl9tdWx0aXBsZTouMWZ9OjEgKFNUT1AgJHtzdG9wX2xvc3M6LjJmfSA9IC4wMiBiZWxvdyB0dXJuIGxvdywgVEFSR0VUIHJ1c2ggaGlnaCAke3RhcmdldF8xOi4yZn0pIiwKICAgICAgICAgICAgICAgIGYiVGFwZToge3RhcGUub3ZlcmFsbF9zaWduYWwudmFsdWV9IiwKICAgICAgICAgICAgICAgIGV2X2luZm8gaWYgZXZfaW5mbyBlbHNlICJDaGVhdC1zaGVldCAybmQgQ2hhbmNlICh2MzUzIHJlcGxheSAzOC0zOSUgd2luLCArMC4wNS4uMC4wOVIsIGF2ZyBSOlIgMS45LCBSUi1nYXRlZCAxLjUtMi41KSIsCiAgICAgICAgICAgIF0sCiAgICAgICAgICAgIHRpbWVfd2luZG93PXNlbGYuX2dldF9jdXJyZW50X3RpbWVfd2luZG93KCkudmFsdWUsCiAgICAgICAgICAgIG1hcmtldF9yZWdpbWU9c2VsZi5fbWFya2V0X3JlZ2ltZS52YWx1ZSwKICAgICAgICAgICAgZXhwaXJlc19hdD0oZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykgKyB0aW1lZGVsdGEoaG91cnM9MSkpLmlzb2Zvcm1hdCgpCiAgICAgICAgKQogICAgCg=="
BACKUP = FILE + ".bak_v353"


def _sha(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()
def _read():
    if not os.path.exists(FILE):
        print(f"ERROR: {FILE} not found (run from repo root)"); sys.exit(2)
    return open(FILE, encoding="utf-8").read()
def _old(): return base64.b64decode(OLD_B64).decode("utf-8")
def _new(): return base64.b64decode(NEW_B64).decode("utf-8")
def _compiles(text):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(text); tmp = tf.name
    try:
        py_compile.compile(tmp, doraise=True); return True
    except py_compile.PyCompileError as e:
        print("POST-PATCH COMPILE FAILED:\n", e); return False
    finally:
        os.unlink(tmp)


def check():
    src = _read(); cur = _sha(src); old = _old()
    print(f"file            : {FILE}")
    print(f"whole-file SHA  : {cur}")
    print(f"expected (DGX)  : {DGX_WHOLE_PRE}  {'OK' if cur == DGX_WHOLE_PRE else 'DRIFT!'}")
    print(f"func anchor     : present={old in src} count={src.count(old)}")
    print(f"func PRE sha    : {_sha(old)}  {'OK' if _sha(old) == PRE_FUNC_SHA else 'MISMATCH'}")
    print(f"func POST sha   : {_sha(_new())}  {'OK' if _sha(_new()) == POST_FUNC_SHA else 'MISMATCH'}")
    if _new() in src: print("state           : ALREADY PATCHED")
    if cur != DGX_WHOLE_PRE:
        print("\nDRIFT: live file != DGX baseline. Re-extract and rebuild."); return False
    if src.count(old) != 1:
        print("\nAnchor missing/ambiguous -- abort."); return False
    print("\nREADY: --apply installs the cheat-sheet 2nd Chance (resistance retest, RR-gated 1.5-2.5).")
    return True


def apply():
    src = _read(); old, new = _old(), _new()
    if new in src: print("Already patched. No-op."); return
    if _sha(src) != DGX_WHOLE_PRE:
        print(f"ABORT: whole-file SHA {_sha(src)} != DGX baseline. See --check."); sys.exit(3)
    if src.count(old) != 1:
        print(f"ABORT: anchor count={src.count(old)} (need 1)."); sys.exit(3)
    if _sha(old) != PRE_FUNC_SHA:
        print("ABORT: function PRE sha mismatch."); sys.exit(3)
    if _sha(new) != POST_FUNC_SHA:
        print("ABORT: embedded NEW function sha mismatch (corrupt patcher)."); sys.exit(3)
    patched = src.replace(old, new, 1)
    if not _compiles(patched):
        print("ABORT: patched file does not compile. No write."); sys.exit(3)
    shutil.copy2(FILE, BACKUP)
    with open(FILE, "w", encoding="utf-8") as f: f.write(patched)
    print(f"APPLIED. backup -> {BACKUP}")
    print(f"new whole-file SHA : {_sha(patched)}  (record this)")
    print("Verify: pytest backend/tests/test_v353_second_chance.py -q ; commit BEFORE restart ; ./start_backend.sh --force")


def rollback():
    src = _read(); old, new = _old(), _new()
    if old in src and _sha(src) == DGX_WHOLE_PRE:
        print("Already at baseline. No-op."); return
    if new in src and src.count(new) == 1:
        restored = src.replace(new, old, 1)
        shutil.copy2(FILE, FILE + ".bak_pre_rollback")
        with open(FILE, "w", encoding="utf-8") as f: f.write(restored)
        print(f"ROLLED BACK via reverse-anchor. whole-file SHA == DGX baseline: {_sha(restored) == DGX_WHOLE_PRE}")
        return
    if os.path.exists(BACKUP):
        bsrc = open(BACKUP, encoding="utf-8").read()
        if _sha(bsrc) == DGX_WHOLE_PRE:
            shutil.copy2(BACKUP, FILE); print(f"ROLLED BACK from {BACKUP} (== DGX baseline)."); return
    print("ABORT: could not safely roll back."); sys.exit(4)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--check"
    {"--check": check, "--apply": apply, "--rollback": rollback}.get(arg, lambda: print("usage: --check | --apply | --rollback"))()
