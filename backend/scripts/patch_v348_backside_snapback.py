#!/usr/bin/env python3
"""
patch_v348_backside_snapback.py  (AGENTS.md §2.2 — function-anchored patcher)

WHAT: replaces enhanced_scanner._check_backside (a loose dist_from_vwap STATE check —
      uptrend + above_ema9 + below VWAP + dist_from_vwap>-2% + rvol>=1.2, no trigger,
      no min-risk gate) with a VWAP-recovery SNAPBACK detector confined to the shallow
      [0.3%, 1.0%) dip band: dip BELOW session VWAP + 9-EMA reclaim + a 1-min double-bar
      HIGH-break snapback within +1..+4 bars of the dip-low + accel(1.3x) + RVOL>=1.2 +
      stop>=1.0% of entry + 2 fires/day per symbol. LONG only, target = VWAP.
WHY : v347 14d risk-controlled native-1min replay validated +EV and ~97% UNIQUE vs the
      now-live vwap_fade (n=32/33 UNIQUE; 0-0.5% band win93%/+0.11R, 0.5-1% band win88%/
      +0.41R; ALL win91%/+0.28R). The loose live state-detector fired ~454 sub-edge alerts
      (2468/2580 events gated by the 1.0% min-risk floor in replay). The new [0.3%,1.0%)
      band is COMPLEMENTARY to vwap_fade ([1.0%,3.0%)) -> zero double-fire by construction.
      1-min bars come from ib_historical_data (IB-only) via
      self.technical_service._get_intraday_bars_from_db(sym,"1 min",60).

DRIFT NOTE: FUNCTION-ANCHORED. Asserts live whole-file SHA == DGX baseline AND the exact
      _check_backside bytes present (count==1), replaces, asserts new func SHA, then
      py_compiles the whole file before writing. (file > paste limit -> no precomputed
      whole-file POST_SHA; compile + func-SHA guards + backup cover it.)

§2.2: PRE whole-file SHA + function PRE/POST SHA + anchor-uniqueness + compile guard +
      auto-backup + --check/--apply/--rollback.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/patch_v348_backside_snapback.py --check
  .venv/bin/python backend/scripts/patch_v348_backside_snapback.py --apply
  .venv/bin/python backend/scripts/patch_v348_backside_snapback.py --rollback
Then: pytest backend/tests/test_v348_backside.py -q ; commit ; ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os, py_compile, tempfile

FILE = "backend/services/enhanced_scanner.py"
DGX_WHOLE_PRE = "9520d851d28a55ba6f64a20831680e33d5612558d27e9f9b2fa524ebb91ba5b1"
PRE_FUNC_SHA  = "c89eef207feb4d2ea2e1e72975b5915481d5e6888c251ac7831330daeb4edb48"
POST_FUNC_SHA = "2f6f4f6100c8a49399a130349b08cd0f1967568cf06b68f4838cb90302df2b4d"
OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfYmFja3NpZGUoc2VsZiwgc3ltYm9sOiBzdHIsIHNuYXBzaG90LCB0YXBlOiBUYXBlUmVhZGluZykgLT4gT3B0aW9uYWxbTGl2ZUFsZXJ0XToKICAgICAgICAiIiJCYWNrJGlkZSAtIFJlY292ZXJ5IGZyb20gTE9EIiIiCiAgICAgICAgaWYgKHNuYXBzaG90LnRyZW5kID09ICJ1cHRyZW5kIiBhbmQKICAgICAgICAgICAgc25hcHNob3QuYWJvdmVfZW1hOSBhbmQKICAgICAgICAgICAgbm90IHNuYXBzaG90LmFib3ZlX3Z3YXAgYW5kCiAgICAgICAgICAgIHNuYXBzaG90LmRpc3RfZnJvbV92d2FwID4gLTIuMCBhbmQKICAgICAgICAgICAgc25hcHNob3QucnZvbCA+PSAxLjIpOgogICAgICAgICAgICAKICAgICAgICAgICAgcmV0dXJuIExpdmVBbGVydCgKICAgICAgICAgICAgICAgIGlkPWYiYmFja3NpZGVfe3N5bWJvbH1fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclSCVNJVMnKX0iLAogICAgICAgICAgICAgICAgc3ltYm9sPXN5bWJvbCwKICAgICAgICAgICAgICAgIHNldHVwX3R5cGU9ImJhY2tzaWRlIiwKICAgICAgICAgICAgICAgIHN0cmF0ZWd5X25hbWU9IkJhY2skaWRlIFNjYWxwIChJTlQtMzIpIiwKICAgICAgICAgICAgICAgIGRpcmVjdGlvbj0ibG9uZyIsCiAgICAgICAgICAgICAgICAjIHYxOS4zNC4zMjByIOKAlCB0YXBlLWdhdGVkIEhJR0ggYnJhbmNoICh3YXMgaGFyZGNvZGVkIE1FRElVTSwgd2hpY2ggY2FwcGVkCiAgICAgICAgICAgICAgICAjIHRoaXMgaW50cmFkYXkgc2NhbHAgYmVsb3cgdGhlIGF1dG8tZmlyZSBiYXIgcmVnYXJkbGVzcyBvZiBzaWduYWwKICAgICAgICAgICAgICAgICMgcXVhbGl0eTsgc2VlIHYzMjBxICsgdjMyMHItcHJlY2hlY2spLiBPbmx5IHRoZSB0YXBlLWNvbmZpcm1lZAogICAgICAgICAgICAgICAgIyBzdWJzZXQgcHJvbW90ZXM7IEVWL3dpbi1yYXRlIGdhdGUgc3RpbGwgZ292ZXJucyBhdXRvLWZpcmUuCiAgICAgICAgICAgICAgICBwcmlvcml0eT1BbGVydFByaW9yaXR5LkhJR0ggaWYgdGFwZS5jb25maXJtYXRpb25fZm9yX2xvbmcgZWxzZSBBbGVydFByaW9yaXR5Lk1FRElVTSwKICAgICAgICAgICAgICAgIGN1cnJlbnRfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgIHRyaWdnZXJfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgIHN0b3BfbG9zcz1zZWxmLl9hdHJfZmxvb3JlZF9zdG9wKAogICAgICAgICAgICAgICAgICAgIGVudHJ5X3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICAgICAgcmF3X3N0b3A9c25hcHNob3QuZW1hXzkgLSAwLjAyLAogICAgICAgICAgICAgICAgICAgIGF0cj1nZXRhdHRyKHNuYXBzaG90LCAiYXRyIiwgTm9uZSksCiAgICAgICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJsb25nIiwKICAgICAgICAgICAgICAgICAgICBtaW5fYXRyX211bHQ9MC41LAogICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgIHRhcmdldD1yb3VuZChzbmFwc2hvdC52d2FwLCAyKSwKICAgICAgICAgICAgICAgIHJpc2tfcmV3YXJkPTIuMCwKICAgICAgICAgICAgICAgIHRyaWdnZXJfcHJvYmFiaWxpdHk9MC41NSwKICAgICAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjU1LAogICAgICAgICAgICAgICAgbWludXRlc190b190cmlnZ2VyPTE1LAogICAgICAgICAgICAgICAgaGVhZGxpbmU9ZiLihpfvuI8ge3N5bWJvbH0gQmFjayRpZGUgLSBSZWNvdmVyaW5nIHRvIFZXQVAiLAogICAgICAgICAgICAgICAgcmVhc29uaW5nPVsKICAgICAgICAgICAgICAgICAgICAiSGlnaGVyIGhpZ2hzL2xvd3MgYWJvdmUgOS1FTUEiLAogICAgICAgICAgICAgICAgICAgIGYiVGFwZToge3RhcGUub3ZlcmFsbF9zaWduYWwudmFsdWV9IiwKICAgICAgICAgICAgICAgICAgICBmIlRhcmdldDogVldBUCAke3NuYXBzaG90LnZ3YXA6LjJmfSIKICAgICAgICAgICAgICAgIF0sCiAgICAgICAgICAgICAgICB0aW1lX3dpbmRvdz1zZWxmLl9nZXRfY3VycmVudF90aW1lX3dpbmRvdygpLnZhbHVlLAogICAgICAgICAgICAgICAgbWFya2V0X3JlZ2ltZT1zZWxmLl9tYXJrZXRfcmVnaW1lLnZhbHVlLAogICAgICAgICAgICAgICAgZXhwaXJlc19hdD0oZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykgKyB0aW1lZGVsdGEoaG91cnM9MSkpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gTm9uZQogICAgCg=="
NEW_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfYmFja3NpZGUoc2VsZiwgc3ltYm9sOiBzdHIsIHNuYXBzaG90LCB0YXBlOiBUYXBlUmVhZGluZykgLT4gT3B0aW9uYWxbTGl2ZUFsZXJ0XToKICAgICAgICAiIiJCYWNrJGlkZSBcdTIwMTQgc2hhbGxvdyBWV0FQLXJlY292ZXJ5IHNuYXBiYWNrICh2MTkuMzQuMzQ4IHJlZGVzaWduLCBMT05HLW9ubHkpLgoKICAgICAgICBGaXJlcyBvbiB0aGUgVFJJR0dFUiwgbm90IGEgZGlzdF9mcm9tX3Z3YXAgU1RBVEU6IGFmdGVyIGEgU0hBTExPVyBkaXAgQkVMT1cgc2Vzc2lvbgogICAgICAgIFZXQVAgKHRoZSBbMC4zJSwgMS4wJSkgYmFuZCB0aGF0IHZ3YXBfZmFkZSBcdTIwMTQgd2hpY2ggZmxvb3JzIGF0IDEuMCUgXHUyMDE0IHN0cnVjdHVyYWxseQogICAgICAgIGNhbm5vdCBzZXJ2ZSksIHByaWNlIG11c3QgcmVjbGFpbSB0aGUgOS1FTUEgYW5kIGEgMS1taW4gZG91YmxlLWJhci1ISUdILWJyZWFrIHNuYXBiYWNrCiAgICAgICAgcHJpbnRzIHdpdGhpbiArMS4uKzQgYmFycyBvZiB0aGUgZGlwLWxvdywgc25hcHBpbmcgYmFjayBVUCB0byBWV0FQLiBWYWxpZGF0ZWQgK0VWIG9uIGEKICAgICAgICAxNGQgcmlzay1jb250cm9sbGVkIG5hdGl2ZS0xbWluIHJlcGxheSAodjM0NzogMC0wLjUlIGJhbmQgd2luOTMlLyswLjExUiwgMC41LTElIGJhbmQKICAgICAgICB3aW44OCUvKzAuNDFSOyBuPTMyLzMzIFVOSVFVRSB2cyB2d2FwX2ZhZGUgXHUyMDE0IGEgZGlzdGluY3Qgc2hhbGxvdy1kaXAgcmVjb3ZlcnkgZWRnZSwKICAgICAgICBOT1QgYSBkdXBsaWNhdGUpLiBSZXF1aXJlcyBzdG9wID49IDEuMCUgb2YgZW50cnkgKHRoZSBtaW4tcmlzayBmbG9vciB0aGF0IGdhdGVkIH45NiUgb2YKICAgICAgICB0aGUgbG9vc2Ugc3RhdGUgZmlyZXMpICsgUlZPTCA+PSAxLjIgKyBwcmljZSBhYm92ZSB0aGUgOS1FTUEgKyAyIGZpcmVzL2RheSBwZXIgc3ltYm9sLgogICAgICAgICIiIgogICAgICAgIERJUF9GTE9PUiA9IDAuMwogICAgICAgIERJUF9DRUlMID0gMS4wICAgICAgICAgICMgPj0gMS4wJSBpcyB2d2FwX2ZhZGUncyBiYW5kIFx1MjAxNCBrZWVwIGJhY2tzaWRlIGNvbXBsZW1lbnRhcnkgKHplcm8gb3ZlcmxhcCkKICAgICAgICBUUklHR0VSX1dJTiA9IDQKICAgICAgICBBQ0NFTCA9IDEuMwogICAgICAgIE1JTl9SVk9MID0gMS4yCiAgICAgICAgTUlOX1JJU0tfUENUID0gMS4wCgogICAgICAgIGlmIG5vdCBnZXRhdHRyKHNuYXBzaG90LCAiYWJvdmVfZW1hOSIsIEZhbHNlKToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICB0cyA9IGdldGF0dHIoc2VsZiwgInRlY2huaWNhbF9zZXJ2aWNlIiwgTm9uZSkKICAgICAgICBpZiB0cyBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGJhcnMgPSB0cy5fZ2V0X2ludHJhZGF5X2JhcnNfZnJvbV9kYihzeW1ib2wsICIxIG1pbiIsIDYwKQogICAgICAgIGlmIG5vdCBiYXJzIG9yIGxlbihiYXJzKSA8IDU6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgcnZvbCA9IGZsb2F0KGdldGF0dHIoc25hcHNob3QsICJydm9sIiwgMC4wKSBvciAwLjApCiAgICAgICAgaWYgcnZvbCA8IE1JTl9SVk9MOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHZ3YXAgPSBmbG9hdChnZXRhdHRyKHNuYXBzaG90LCAidndhcCIsIDAuMCkgb3IgMC4wKQogICAgICAgIGlmIHZ3YXAgPD0gMDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgY2FwcyA9IGdldGF0dHIoc2VsZiwgIl9iYWNrc2lkZV9kYWlseV9jYXBzIiwgTm9uZSkKICAgICAgICBpZiBjYXBzIGlzIE5vbmU6CiAgICAgICAgICAgIGNhcHMgPSBzZWxmLl9iYWNrc2lkZV9kYWlseV9jYXBzID0ge30KICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLnN0cmZ0aW1lKCIlWS0lbS0lZCIpCgogICAgICAgIGRlZiBfbWVkaWFuKHhzKToKICAgICAgICAgICAgcyA9IHNvcnRlZCh4cykKICAgICAgICAgICAgbiA9IGxlbihzKQogICAgICAgICAgICBpZiBuID09IDA6CiAgICAgICAgICAgICAgICByZXR1cm4gMC4wCiAgICAgICAgICAgIHJldHVybiBzW24gLy8gMl0gaWYgbiAlIDIgZWxzZSAoc1tuIC8vIDIgLSAxXSArIHNbbiAvLyAyXSkgLyAyLjAKCiAgICAgICAgaSA9IGxlbihiYXJzKSAtIDEKICAgICAgICBsYXN0ID0gYmFyc1tpXQogICAgICAgIHJhbmdlcyA9IFsoYlsiaGlnaCJdIC0gYlsibG93Il0pIGZvciBiIGluIGJhcnNbOmldCiAgICAgICAgICAgICAgICAgIGlmIGIuZ2V0KCJoaWdoIikgaXMgbm90IE5vbmUgYW5kIGIuZ2V0KCJsb3ciKSBpcyBub3QgTm9uZV0KICAgICAgICBtZWRfciA9IF9tZWRpYW4ocmFuZ2VzKQoKICAgICAgICBsb3dzID0gWyhqLCBiWyJsb3ciXSkgZm9yIGosIGIgaW4gZW51bWVyYXRlKGJhcnMpIGlmIGIuZ2V0KCJsb3ciKSBpcyBub3QgTm9uZV0KICAgICAgICBpZiBsb3dzOgogICAgICAgICAgICBsb2QgPSBtaW4odiBmb3IgXywgdiBpbiBsb3dzKQogICAgICAgICAgICBsb2RfaWR4ID0gbWF4KGogZm9yIGosIHYgaW4gbG93cyBpZiB2ID09IGxvZCkKICAgICAgICAgICAgZGlwID0gKHZ3YXAgLSBsb2QpIC8gdndhcCAqIDEwMC4wCiAgICAgICAgICAgIGFjY2VsX29rID0gKG1lZF9yIDw9IDApIG9yICgoYmFyc1tsb2RfaWR4XVsiaGlnaCJdIC0gYmFyc1tsb2RfaWR4XVsibG93Il0pID49IEFDQ0VMICogbWVkX3IpCiAgICAgICAgICAgIGdyZWVuID0gbGFzdFsiY2xvc2UiXSA+IGxhc3RbIm9wZW4iXQogICAgICAgICAgICBjbGVhcnNfaGkgPSBpID49IDIgYW5kIGxhc3RbImhpZ2giXSA+IG1heChiYXJzW2kgLSAxXVsiaGlnaCJdLCBiYXJzW2kgLSAyXVsiaGlnaCJdKQogICAgICAgICAgICBpZiAoRElQX0ZMT09SIDw9IGRpcCA8IERJUF9DRUlMIGFuZCBhY2NlbF9vayBhbmQgZ3JlZW4gYW5kIGNsZWFyc19oaQogICAgICAgICAgICAgICAgICAgIGFuZCAxIDw9IChpIC0gbG9kX2lkeCkgPD0gVFJJR0dFUl9XSU4pOgogICAgICAgICAgICAgICAga2V5ID0gZiJ7c3ltYm9sfTp7dG9kYXl9OmxvbmciCiAgICAgICAgICAgICAgICBpZiBjYXBzLmdldChrZXksIDApID49IDI6CiAgICAgICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgICAgIGVudHJ5ID0gcm91bmQobWF4KGJhcnNbaSAtIDFdWyJoaWdoIl0sIGJhcnNbaSAtIDJdWyJoaWdoIl0pLCAyKQogICAgICAgICAgICAgICAgaWYgZW50cnkgPj0gdndhcDoKICAgICAgICAgICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgICAgICAgICAgc3RvcF9sb3NzID0gcm91bmQobWluKGxvZCAtIDAuMDIsIHNuYXBzaG90LnN1cHBvcnQgLSAoc25hcHNob3QuYXRyICogMC4yNSkpLCAyKQogICAgICAgICAgICAgICAgcmlzayA9IGVudHJ5IC0gc3RvcF9sb3NzCiAgICAgICAgICAgICAgICBpZiByaXNrIDw9IDAgb3IgZW50cnkgPD0gMCBvciAocmlzayAvIGVudHJ5ICogMTAwLjApIDwgTUlOX1JJU0tfUENUOgogICAgICAgICAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgICAgICAgICB0YXJnZXRfMSA9IHJvdW5kKHZ3YXAsIDIpCiAgICAgICAgICAgICAgICByZXdhcmQgPSB0YXJnZXRfMSAtIGVudHJ5CiAgICAgICAgICAgICAgICByX211bHRpcGxlID0gcm91bmQocmV3YXJkIC8gcmlzaywgMikgaWYgcmlzayA+IDAgZWxzZSAyLjAKICAgICAgICAgICAgICAgIHByaW9yaXR5ID0gQWxlcnRQcmlvcml0eS5ISUdIIGlmIHRhcGUuY29uZmlybWF0aW9uX2Zvcl9sb25nIGVsc2UgQWxlcnRQcmlvcml0eS5NRURJVU0KICAgICAgICAgICAgICAgIGV2X2luZm8gPSAiIgogICAgICAgICAgICAgICAgaWYgImJhY2tzaWRlIiBpbiBzZWxmLl9zdHJhdGVneV9zdGF0czoKICAgICAgICAgICAgICAgICAgICBzdCA9IHNlbGYuX3N0cmF0ZWd5X3N0YXRzWyJiYWNrc2lkZSJdCiAgICAgICAgICAgICAgICAgICAgaWYgc3Qud2luX3JhdGUgPiAwOgogICAgICAgICAgICAgICAgICAgICAgICBldl9pbmZvID0gZiJIaXN0b3JpY2FsOiB7c3Qud2luX3JhdGU6LjAlfSB3aW4sIEVWIHtzdC5leHBlY3RlZF92YWx1ZV9yOi4yZn1SIgogICAgICAgICAgICAgICAgY2Fwc1trZXldID0gY2Fwcy5nZXQoa2V5LCAwKSArIDEKICAgICAgICAgICAgICAgIHRhcGVfdGFnID0gIlx1MjcxMyBUQVBFIiBpZiB0YXBlLmNvbmZpcm1hdGlvbl9mb3JfbG9uZyBlbHNlICIiCiAgICAgICAgICAgICAgICByZXR1cm4gTGl2ZUFsZXJ0KAogICAgICAgICAgICAgICAgICAgIGlkPWYiYmFja3NpZGVfe3N5bWJvbH1fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclSCVNJVMnKX0iLAogICAgICAgICAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgICAgICAgICAgc2V0dXBfdHlwZT0iYmFja3NpZGUiLAogICAgICAgICAgICAgICAgICAgIHN0cmF0ZWd5X25hbWU9IkJhY2skaWRlIFNjYWxwIChJTlQtMzIpIiwKICAgICAgICAgICAgICAgICAgICBkaXJlY3Rpb249ImxvbmciLAogICAgICAgICAgICAgICAgICAgIHByaW9yaXR5PXByaW9yaXR5LAogICAgICAgICAgICAgICAgICAgIGN1cnJlbnRfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPWVudHJ5LAogICAgICAgICAgICAgICAgICAgIHN0b3BfbG9zcz1zdG9wX2xvc3MsCiAgICAgICAgICAgICAgICAgICAgdGFyZ2V0PXRhcmdldF8xLAogICAgICAgICAgICAgICAgICAgIHJpc2tfcmV3YXJkPXJfbXVsdGlwbGUsCiAgICAgICAgICAgICAgICAgICAgdHJpZ2dlcl9wcm9iYWJpbGl0eT0wLjY1LAogICAgICAgICAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjczLAogICAgICAgICAgICAgICAgICAgIG1pbnV0ZXNfdG9fdHJpZ2dlcj0wLAogICAgICAgICAgICAgICAgICAgIGhlYWRsaW5lPWYiXFUwMDAxZjNhZiB7c3ltYm9sfSBCYWNrJGlkZSBzbmFwYmFjayBcdTIwMTQge2RpcDouMWZ9JSBkaXAgcmVjbGFpbSB0byBWV0FQIHt0YXBlX3RhZ30iLAogICAgICAgICAgICAgICAgICAgIHJlYXNvbmluZz1bCiAgICAgICAgICAgICAgICAgICAgICAgIGYiU2hhbGxvdyB7ZGlwOi4xZn0lIGRpcCBiZWxvdyBWV0FQICR7dndhcDouMmZ9IFx1MjE5MiAxLW1pbiBkb3VibGUtYmFyLWJyZWFrIHJlY2xhaW0iLAogICAgICAgICAgICAgICAgICAgICAgICBmIlNuYXBiYWNrIHtpIC0gbG9kX2lkeH0gYmFyKHMpIGFmdGVyIExPRCAke2xvZDouMmZ9IChmbHVzaCByYW5nZSA+PSB7QUNDRUw6Z314IG1lZGlhbiksIGFib3ZlIDktRU1BIiwKICAgICAgICAgICAgICAgICAgICAgICAgZiJSOlIgPSB7cl9tdWx0aXBsZTouMWZ9OjEgKFN0b3AgJHtzdG9wX2xvc3M6LjJmfSBiZWxvdyBMT0QsIFRhcmdldCBWV0FQICR7dGFyZ2V0XzE6LjJmfSkiLAogICAgICAgICAgICAgICAgICAgICAgICBmIlJWT0wge3J2b2w6LjFmfXggfCBUYXBlOiB7dGFwZS5vdmVyYWxsX3NpZ25hbC52YWx1ZX0iLAogICAgICAgICAgICAgICAgICAgICAgICBldl9pbmZvIGlmIGV2X2luZm8gZWxzZSAiU2hhbGxvdyBWV0FQLXJlY292ZXJ5ICh2MzQ3IHJlcGxheSArMC4yOFIsIDkxJSB3aW4sIDAuMy0xJSBiYW5kKSIsCiAgICAgICAgICAgICAgICAgICAgICAgICJFbnRyeTogZ3JlZW4gYmFyIHJlY2xhaW1lZCBwcmlvci0yIGhpZ2hzICgwLjMtMSUgYmFuZCwgY29tcGxlbWVudGFyeSB0byB2d2FwX2ZhZGUsIDIvZGF5IGNhcCkiLAogICAgICAgICAgICAgICAgICAgIF0sCiAgICAgICAgICAgICAgICAgICAgdGltZV93aW5kb3c9c2VsZi5fZ2V0X2N1cnJlbnRfdGltZV93aW5kb3coKS52YWx1ZSwKICAgICAgICAgICAgICAgICAgICBtYXJrZXRfcmVnaW1lPXNlbGYuX21hcmtldF9yZWdpbWUudmFsdWUsCiAgICAgICAgICAgICAgICAgICAgZXhwaXJlc19hdD0oZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykgKyB0aW1lZGVsdGEoaG91cnM9MSkpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgcmV0dXJuIE5vbmUKICAgIAo="
BACKUP = FILE + ".bak_v348"


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
        print("\nDRIFT: live file != DGX baseline. Re-extract the function and rebuild.")
        return False
    if src.count(old) != 1:
        print("\nAnchor missing/ambiguous — abort."); return False
    print("\nREADY: --apply installs the Back$ide VWAP-recovery snapback detector ([0.3%,1.0%) band).")
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
    print("Verify: pytest backend/tests/test_v348_backside.py -q ; commit BEFORE restart ; ./start_backend.sh --force")


def rollback():
    src = _read(); old, new = _old(), _new()
    if old in src and _sha(src) == DGX_WHOLE_PRE:
        print("Already at baseline (unpatched). No-op."); return
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
