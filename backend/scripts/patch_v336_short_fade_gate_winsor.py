#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_v336 \u2014 SHORT-FADE eligibility gate + R-winsorization (v19.34.323)

WHY (diag_v333 + diag_v334, READ-ONLY forensics on 120d of genuine bot-own trades):
  \u2022 trade_2_hold is net +$56.9k; the "-878R" was a risk_amount artifact.
  \u2022 BUT a real P0 tail exists: ~$26k EXCESS lost BEYOND the stop, ~90% SHORTS,
    ~88% vwap_fade_short \u2014 shorting STRENGTH on low-priced / illiquid names with
    2-4c (sub-1%) stops (WTI 2.84/2c->3.21; PRCT 26.67/4c->27.02; USO 0.03%).
  \u2022 AUDIT VERDICT: the stop/target/IB-execution engines are SOUND. OCA stops are
    real GTC market StopOrders that fire correctly; the loss is gap/squeeze
    slippage on a no-edge entry held overnight. The bulletproof fix is to NEVER
    ENTER the danger profile + stop the R-artifacts from poisoning the meta-labeler.

WHAT THIS PATCH DOES (all fail-OPEN, all env-reversible \u2014 zero changes to
close_trade / submit_with_bracket / EOD safety-critical paths):
  1. opportunity_evaluator.py \u2014 SHORT-FADE entry gate: blocks short fade/reversion
     setups when price < MIN_SHORT_FADE_PRICE ($5) or stop-distance% <
     MIN_SHORT_FADE_STOP_PCT (1.0%). Policy SHORT_FADE_GATE_POLICY={block,observe,off}.
  2. learning_loop_service.py \u2014 winsorize _bucket mean_r to \u00b1R_WINSOR_CLAMP (3.0).
  3. ev_tracking_service.py \u2014 winsorize EV R-outcomes to \u00b1R_WINSOR_CLAMP (3.0).

USAGE (repo root on DGX):
  python3 /tmp/patch_v336_short_fade_gate_winsor.py --check    # dry-run, no writes
  python3 /tmp/patch_v336_short_fade_gate_winsor.py            # apply (auto-backup)
  python3 /tmp/patch_v336_short_fade_gate_winsor.py --rollback # restore .bak.v336
ABORTS BEFORE WRITING ANYTHING on any PRE or POST hash mismatch (drift-safe).
"""
import base64, hashlib, os, sys

MANIFEST = [
{
"path": "backend/services/opportunity_evaluator.py",
"pre": "886bb28761779e61e4dfb5d8737cf0231a8f52f57199bab4c842fa6222f40a2b",
"post": "2625116e94117f280b64f33c0e456231951207c8a3e0cbac22a2f0b1ca083b49",
"chunks": [
{
"old_b64": "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBfcTlfZXJyOgogICAgICAgICAgICAgICAgbG9nZ2VyLmRlYnVnKAogICAgICAgICAgICAgICAgICAgICJbdjE5LjM0LjE5NCB2b2wtZmxvb3JdIGdhdGUgY3Jhc2hlZCAoZmFpbC1vcGVuKTogJXMiLCBfcTlfZXJyLAogICAgICAgICAgICAgICAgKQoKICAgICAgICAgICAgIyDilIDilIAgdjE5LjM0LjQ0IOKAlCBTdGFsZSBBbGVydCBUVEwgKGRlZmF1bHQgMzBzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIA=",
"new_b64": "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBfcTlfZXJyOgogICAgICAgICAgICAgICAgbG9nZ2VyLmRlYnVnKAogICAgICAgICAgICAgICAgICAgICJbdjE5LjM0LjE5NCB2b2wtZmxvb3JdIGdhdGUgY3Jhc2hlZCAoZmFpbC1vcGVuKTogJXMiLCBfcTlfZXJyLAogICAgICAgICAgICAgICAgKQoKICAgICAgICAgICAgIyDilIDilIAgdjE5LjM0LjMyMyDigJQgU0hPUlQtRkFERSBlbGlnaWJpbGl0eSBnYXRlICh2MzM0IHN0b3Atb3ZlcnJ1bikg4pSA4pSACiAgICAgICAgICAgICMgZGlhZ192MzM0IHByb3ZlZCB0aGUgY2F0YXN0cm9waGljIHN0b3Atb3ZlcnJ1biB0YWlsICh+JDIzayBvZgogICAgICAgICAgICAjICQyNmsgZXhjZXNzIGxvc3MpIGlzIH45MCUgU0hPUlRTIGFuZCB+ODglIHZ3YXBfZmFkZV9zaG9ydDoKICAgICAgICAgICAgIyBzaG9ydGluZyBTVFJFTkdUSCBvbiBsb3ctcHJpY2VkIC8gaWxsaXF1aWQgbmFtZXMgd2l0aCBhYnN1cmRseQogICAgICAgICAgICAjIHRpZ2h0IHN0b3BzIChXVEkgJDIuODQvMmMgc3RvcC0+ZXhpdCAzLjIxOyBQUkNUICQyNi42Ny80Yy0+MjcuMDI7CiAgICAgICAgICAgICMgVVNPIDAuMDMlIHN0b3ApLiBUaGUgc3RvcCBlbmdpbmUgZmlyZWQgY29ycmVjdGx5IOKAlCB0aGUgbG9zcyBpcwogICAgICAgICAgICAjIGdhcC9zcXVlZXplIHNsaXBwYWdlIG9uIGEgbm8tZWRnZSBlbnRyeSBoZWxkIG92ZXJuaWdodC4gQ2hlYXBlc3QKICAgICAgICAgICAgIyBidWxsZXRwcm9vZiBmaXg6IG5ldmVyIGVudGVyIHRoZSBkYW5nZXIgcHJvZmlsZS4gVHdvIGZhaWwtT1BFTgogICAgICAgICAgICAjIGxldmVycyBvbiBTSE9SVCBmYWRlL3JldmVyc2lvbiBzZXR1cHMgb25seToKICAgICAgICAgICAgIyAgIDEuIE1JTl9TSE9SVF9GQURFX1BSSUNFICAoZGVmYXVsdCAkNSkgIOKAlCBraWxscyBzdWItJDUgc3F1ZWV6ZXJzLgogICAgICAgICAgICAjICAgMi4gTUlOX1NIT1JUX0ZBREVfU1RPUF9QQ1QgKGRlZmF1bHQgMS4wJSkg4oCUIGtpbGxzIG5vaXNlLXN0b3AKICAgICAgICAgICAgIyAgICAgIGZhZGVzIChzdG9wIGRpc3RhbmNlIDwgcGN0IG9mIHByaWNlKSB0aGF0IGFueSBzcXVlZXplIGJsb3dzCiAgICAgICAgICAgICMgICAgICBzdHJhaWdodCB0aHJvdWdoLgogICAgICAgICAgICAjIEVudjogU0hPUlRfRkFERV9HQVRFX1BPTElDWSBpbiB7YmxvY2ssb2JzZXJ2ZSxvZmZ9IChkZWZhdWx0IGJsb2NrKTsKICAgICAgICAgICAgIyAgICAgIFNIT1JUX0ZBREVfU0VUVVBfS0VZV09SRFMgKGNzdiBzdWJzdHJpbmcgbWF0Y2ggb24gc2V0dXBfdHlwZSkuCiAgICAgICAgICAgICMgRHJvcHMgbGFuZCBpbiBgdHJhZGVfZHJvcHNgIHZpYSByZWNvcmRfcmVqZWN0aW9uLgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbXBvcnQgb3MgYXMgX29zX3NmCiAgICAgICAgICAgICAgICBfc2ZfcG9saWN5ID0gKF9vc19zZi5lbnZpcm9uLmdldCgKICAgICAgICAgICAgICAgICAgICAiU0hPUlRfRkFERV9HQVRFX1BPTElDWSIsICJibG9jayIpIG9yICJibG9jayIpLmxvd2VyKCkKICAgICAgICAgICAgICAgIGlmIF9zZl9wb2xpY3kgIT0gIm9mZiIgYW5kIHN0cihkaXJlY3Rpb25fc3RyKS5sb3dlcigpLnN0YXJ0c3dpdGgoInMiKToKICAgICAgICAgICAgICAgICAgICBfc3ltX3NmID0gKHN5bWJvbCBvciAiIikudXBwZXIoKQogICAgICAgICAgICAgICAgICAgIF9zdV9sID0gc3RyKHNldHVwX3R5cGUgb3IgIiIpLmxvd2VyKCkKICAgICAgICAgICAgICAgICAgICBfa3dfcmF3ID0gX29zX3NmLmVudmlyb24uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAiU0hPUlRfRkFERV9TRVRVUF9LRVlXT1JEUyIsCiAgICAgICAgICAgICAgICAgICAgICAgICJmYWRlLGJvdW5jZSxyZXZlcnNpb24scnViYmVyX2JhbmQsb2ZmX3NpZGVzLGJhY2tzaWRlIiwKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgX2t3cyA9IFtrLnN0cmlwKCkgZm9yIGsgaW4gX2t3X3Jhdy5zcGxpdCgiLCIpIGlmIGsuc3RyaXAoKV0KICAgICAgICAgICAgICAgICAgICBpZiBhbnkoayBpbiBfc3VfbCBmb3IgayBpbiBfa3dzKToKICAgICAgICAgICAgICAgICAgICAgICAgX3B4X3NmID0gKGFsZXJ0LmdldCgicHJpY2UiKSBvciBhbGVydC5nZXQoImN1cnJlbnRfcHJpY2UiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgb3IgYWxlcnQuZ2V0KCJlbnRyeV9wcmljZSIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBvciBhbGVydC5nZXQoInRyaWdnZXJfcHJpY2UiKSkKICAgICAgICAgICAgICAgICAgICAgICAgX3N0b3Bfc2YgPSAoYWxlcnQuZ2V0KCJzdG9wX2xvc3MiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBvciBhbGVydC5nZXQoInN0b3BfcHJpY2UiKSkKICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgX3B4X3NmID0gZmxvYXQoX3B4X3NmKSBpZiBfcHhfc2YgZWxzZSBOb25lCiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCAoVHlwZUVycm9yLCBWYWx1ZUVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9weF9zZiA9IE5vbmUKICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgX3N0b3Bfc2YgPSBmbG9hdChfc3RvcF9zZikgaWYgX3N0b3Bfc2YgZWxzZSBOb25lCiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCAoVHlwZUVycm9yLCBWYWx1ZUVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9zdG9wX3NmID0gTm9uZQogICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBfbWluX3ByaWNlID0gZmxvYXQoX29zX3NmLmVudmlyb24uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJNSU5fU0hPUlRfRkFERV9QUklDRSIsICI1LjAiKSkKICAgICAgICAgICAgICAgICAgICAgICAgZXhjZXB0IChUeXBlRXJyb3IsIFZhbHVlRXJyb3IpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgX21pbl9wcmljZSA9IDUuMAogICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBfbWluX3N0b3BfcGN0ID0gZmxvYXQoX29zX3NmLmVudmlyb24uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJNSU5fU0hPUlRfRkFERV9TVE9QX1BDVCIsICIwLjAxMCIpKQogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQgKFR5cGVFcnJvciwgVmFsdWVFcnJvcik6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBfbWluX3N0b3BfcGN0ID0gMC4wMTAKICAgICAgICAgICAgICAgICAgICAgICAgX2Jsb2NrX3JlYXNvbiA9IE5vbmUKICAgICAgICAgICAgICAgICAgICAgICAgX3NmX2N0eCA9IHt9CiAgICAgICAgICAgICAgICAgICAgICAgIGlmIChfcHhfc2YgaXMgbm90IE5vbmUgYW5kIF9taW5fcHJpY2UgPiAwCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYW5kIF9weF9zZiA8IF9taW5fcHJpY2UpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgX2Jsb2NrX3JlYXNvbiA9ICJzaG9ydF9mYWRlX2xvd19wcmljZSIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9zZl9jdHggPSB7InByaWNlIjogcm91bmQoX3B4X3NmLCA0KSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIm1pbl9wcmljZSI6IF9taW5fcHJpY2V9CiAgICAgICAgICAgICAgICAgICAgICAgIGVsaWYgKF9weF9zZiBhbmQgX3N0b3Bfc2YgYW5kIF9taW5fc3RvcF9wY3QgPiAwKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIF9zZF9wY3QgPSBhYnMoX3N0b3Bfc2YgLSBfcHhfc2YpIC8gX3B4X3NmCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBfc2RfcGN0IDwgX21pbl9zdG9wX3BjdDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBfYmxvY2tfcmVhc29uID0gInNob3J0X2ZhZGVfc3RvcF90b29fdGlnaHQiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX3NmX2N0eCA9IHsic3RvcF9wY3QiOiByb3VuZChfc2RfcGN0LCA1KSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJtaW5fc3RvcF9wY3QiOiBfbWluX3N0b3BfcGN0LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgInByaWNlIjogcm91bmQoX3B4X3NmLCA0KSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJzdG9wIjogcm91bmQoX3N0b3Bfc2YsIDQpfQogICAgICAgICAgICAgICAgICAgICAgICBpZiBfYmxvY2tfcmVhc29uOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgbG9nZ2VyLmluZm8oCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlxVMDAwMWY2YWIgW3YxOS4zNC4zMjMgc2hvcnQtZmFkZV0gJXMgJXMgJXMg4oCUICVzICVzIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAoIk9CU0VSVkUiIGlmIF9zZl9wb2xpY3kgPT0gIm9ic2VydmUiIGVsc2UgIkJMT0NLIiksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgX3N5bV9zZiwgc2V0dXBfdHlwZSwgX2Jsb2NrX3JlYXNvbiwgX3NmX2N0eCwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIF9zZl9wb2xpY3kgIT0gIm9ic2VydmUiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYm90LnJlY29yZF9yZWplY3Rpb24oCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzeW1ib2w9c3ltYm9sLCBzZXR1cF90eXBlPXNldHVwX3R5cGUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBkaXJlY3Rpb249ZGlyZWN0aW9uX3N0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbl9jb2RlPV9ibG9ja19yZWFzb24sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBjb250ZXh0PV9zZl9jdHgsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBfc2ZfZXJyOgogICAgICAgICAgICAgICAgbG9nZ2VyLmRlYnVnKAogICAgICAgICAgICAgICAgICAgICJbdjE5LjM0LjMyMyBzaG9ydC1mYWRlXSBnYXRlIGNyYXNoZWQgKGZhaWwtb3Blbik6ICVzIiwKICAgICAgICAgICAgICAgICAgICBfc2ZfZXJyLAogICAgICAgICAgICAgICAgKQoKICAgICAgICAgICAgIyDilIDilIAgdjE5LjM0LjQ0IOKAlCBTdGFsZSBBbGVydCBUVEwgKGRlZmF1bHQgMzBzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIA="
}
]
},
{
"path": "backend/services/learning_loop_service.py",
"pre": "b6805b41117b1aebcdf898da9167c7b479a129e53c34b1d35ee7c826cf540d67",
"post": "c6e43449058f5b5c56bddfd0d8409be96d6fda502701bc778b1ae44d89428ba3",
"chunks": [
{
"old_b64": "ICAgICAgICBkZWYgX2J1Y2tldChyczogTGlzdFtmbG9hdF0pIC0+IE9wdGlvbmFsW0RpY3Rbc3RyLCBBbnldXToKICAgICAgICAgICAgaWYgbm90IHJzOgogICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgd2lucyA9IHN1bSgxIGZvciByIGluIHJzIGlmIHIgPiAwKQogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgIm4iOiAgICAgICAgIGxlbihycyksCiAgICAgICAgICAgICAgICAid2luX3JhdGUiOiAgcm91bmQod2lucyAvIGxlbihycyksIDMpLAogICAgICAgICAgICAgICAgIm1lYW5fciI6ICAgIHJvdW5kKHN1bShycykgLyBsZW4ocnMpLCAzKSwKICAgICAgICAgICAgfQ==",
"new_b64": "ICAgICAgICBkZWYgX2J1Y2tldChyczogTGlzdFtmbG9hdF0pIC0+IE9wdGlvbmFsW0RpY3Rbc3RyLCBBbnldXToKICAgICAgICAgICAgaWYgbm90IHJzOgogICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgd2lucyA9IHN1bSgxIGZvciByIGluIHJzIGlmIHIgPiAwKQogICAgICAgICAgICAjIHYxOS4zNC4zMjMg4oCUIHdpbnNvcml6ZSBlYWNoIFIgdG8gwrFSX1dJTlNPUl9DTEFNUCBmb3IgdGhlIG1lYW4gc28gYQogICAgICAgICAgICAjIHNpbmdsZSBibG93bi1zdG9wIC8gdGlueS1yaXNrIGFydGlmYWN0IChlLmcuIC0yNjFSKSBjYW4ndCBwb2lzb24KICAgICAgICAgICAgIyB0aGUgbWV0YS1sYWJlbGVyJ3MgZWRnZSBlc3RpbWF0ZS4gd2luX3JhdGUgdXNlcyBzaWduIG9ubHkuCiAgICAgICAgICAgIGltcG9ydCBvcyBhcyBfb3NfdwogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBfY2wgPSBmbG9hdChfb3Nfdy5lbnZpcm9uLmdldCgiUl9XSU5TT1JfQ0xBTVAiLCAiMy4wIikpCiAgICAgICAgICAgIGV4Y2VwdCAoVHlwZUVycm9yLCBWYWx1ZUVycm9yKToKICAgICAgICAgICAgICAgIF9jbCA9IDMuMAogICAgICAgICAgICBfcnNfdyA9IFttYXgoLV9jbCwgbWluKF9jbCwgcikpIGZvciByIGluIHJzXSBpZiBfY2wgPiAwIGVsc2UgcnMKICAgICAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgICAgICJuIjogICAgICAgICBsZW4ocnMpLAogICAgICAgICAgICAgICAgIndpbl9yYXRlIjogIHJvdW5kKHdpbnMgLyBsZW4ocnMpLCAzKSwKICAgICAgICAgICAgICAgICJtZWFuX3IiOiAgICByb3VuZChzdW0oX3JzX3cpIC8gbGVuKF9yc193KSwgMyksCiAgICAgICAgICAgIH0="
}
]
},
{
"path": "backend/services/ev_tracking_service.py",
"pre": "72edc34c8d23d850e92014908bdc75cf8cda8ce3456dc250fb08d09d2369e696",
"post": "44a4f8426f6336a52d34db44f140da5c2b2c5f1f933fe591f81fa7b518dbccf6",
"chunks": [
{
"old_b64": "ICAgICAgICAjIENhbGN1bGF0ZSBmcm9tIFItb3V0Y29tZXMKICAgICAgICB3aW5zX3IgPSBbciBmb3IgciBpbiByZWNvcmQucl9vdXRjb21lcyBpZiByID4gMF0KICAgICAgICBsb3NzZXNfciA9IFtyIGZvciByIGluIHJlY29yZC5yX291dGNvbWVzIGlmIHIgPD0gMF0=",
"new_b64": "ICAgICAgICAjIENhbGN1bGF0ZSBmcm9tIFItb3V0Y29tZXMKICAgICAgICAjIHYxOS4zNC4zMjMg4oCUIHdpbnNvcml6ZSBlYWNoIFIgdG8gwrFSX1dJTlNPUl9DTEFNUCBzbyBhIHNpbmdsZQogICAgICAgICMgYmxvd24tc3RvcCAvIHRpbnktcmlzayBhcnRpZmFjdCAoZS5nLiAtMjYxUiBvciArMjYxUikgY2FuJ3QgcG9pc29uCiAgICAgICAgIyB0aGUgRVYgZ2F0ZS4gUmF3IHJlY29yZC5yX291dGNvbWVzIGlzIHByZXNlcnZlZCAobm90IG11dGF0ZWQpLgogICAgICAgIGltcG9ydCBvcyBhcyBfb3NfdwogICAgICAgIHRyeToKICAgICAgICAgICAgX2NsID0gZmxvYXQoX29zX3cuZW52aXJvbi5nZXQoIlJfV0lOU09SX0NMQU1QIiwgIjMuMCIpKQogICAgICAgIGV4Y2VwdCAoVHlwZUVycm9yLCBWYWx1ZUVycm9yKToKICAgICAgICAgICAgX2NsID0gMy4wCiAgICAgICAgX3JvID0gKFttYXgoLV9jbCwgbWluKF9jbCwgcikpIGZvciByIGluIHJlY29yZC5yX291dGNvbWVzXQogICAgICAgICAgICAgICBpZiBfY2wgPiAwIGVsc2UgcmVjb3JkLnJfb3V0Y29tZXMpCiAgICAgICAgd2luc19yID0gW3IgZm9yIHIgaW4gX3JvIGlmIHIgPiAwXQogICAgICAgIGxvc3Nlc19yID0gW3IgZm9yIHIgaW4gX3JvIGlmIHIgPD0gMF0="
}
]
}
]

BAK = ".bak.v336"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _rollback() -> int:
    n = 0
    for e in MANIFEST:
        bak = e["path"] + BAK
        if os.path.exists(bak):
            data = _read(bak)
            with open(e["path"], "w", encoding="utf-8") as f:
                f.write(data)
            os.remove(bak)
            print(f"  \u21a9 restored {e['path']} (sha {_sha(data.encode())[:12]})")
            n += 1
        else:
            print(f"  \u2014 no backup for {e['path']} (skip)")
    print(f"rollback complete: {n} file(s) restored")
    return 0


def main() -> int:
    check = "--check" in sys.argv
    if "--rollback" in sys.argv:
        return _rollback()

    # PHASE 1 \u2014 validate everything in memory; write NOTHING until all pass.
    staged = []
    for e in MANIFEST:
        path = e["path"]
        if not os.path.exists(path):
            print(f"\u274c ABORT: missing file {path}")
            return 2
        src = _read(path)
        cur = _sha(src.encode())
        if cur != e["pre"]:
            print(f"\u274c ABORT: PRE-hash drift on {path}")
            print(f"    expected {e['pre']}")
            print(f"    found    {cur}")
            print("    \u2192 your file differs from the tested baseline. Upload it:")
            print(f"      curl -sS --data-binary @{path} https://paste.rs/")
            return 3
        new = src
        for c in e["chunks"]:
            old = base64.b64decode(c["old_b64"]).decode("utf-8")
            rep = base64.b64decode(c["new_b64"]).decode("utf-8")
            cnt = new.count(old)
            if cnt != 1:
                print(f"\u274c ABORT: anchor found {cnt}x (expected 1) in {path}")
                return 4
            new = new.replace(old, rep)
        post = _sha(new.encode())
        if post != e["post"]:
            print(f"\u274c ABORT: POST-hash mismatch on {path}")
            print(f"    expected {e['post']}")
            print(f"    computed {post}")
            return 5
        staged.append((path, src, new, post))
        print(f"  \u2713 {path}  pre\u2192post {e['pre'][:10]}\u2192{post[:10]}  ({len(e['chunks'])} chunk)")

    if check:
        print("\n\u2705 --check OK: all PRE hashes match, all anchors unique, all POST "
              "hashes verified. No files written.")
        return 0

    # PHASE 2 \u2014 all validated; back up + write.
    for path, src, new, post in staged:
        with open(path + BAK, "w", encoding="utf-8") as f:
            f.write(src)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
        assert _sha(_read(path).encode()) == post, f"post-write verify failed {path}"
        print(f"  \U0001f4be wrote {path} (backup {path}{BAK})")

    print("\n\u2705 patch_v336 applied. Verify, COMMIT BEFORE RESTART, then restart:")
    print("    cd backend && .venv/bin/python -m pytest tests/test_v336_short_fade_winsor.py -q")
    print("    git add backend/ && git commit -m 'v19.34.323: short-fade gate + R-winsor' && git push origin main")
    print("    ./start_backend.sh --force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
