#!/usr/bin/env python3
"""
patch_v350_off_sides_snapback.py  (AGENTS.md §2.2 — function-anchored patcher)

WHAT: replaces enhanced_scanner._check_off_sides (a loose range-top STATE check —
      regime in {RANGE_BOUND,FADE} + |dist_vwap|<1% + daily_range>1.5% + within 1% of HOD,
      no trigger bar, no min-risk gate, target = LOD-(HOD-LOD) [a full range BELOW the LOD])
      with a range-top fade SHORT SNAPBACK: same gates + a RED 1-min double-bar-LOW-break
      rejection within accel(1.3x) + stop>=1.0% of entry + 2 fires/day per symbol, and a
      CLOSER target = nearer-of(VWAP, LOD) below entry (VWAP mean-reversion if there's room,
      else the range low).
WHY : v349 14d risk-controlled native-1min replay — in off_sides' actual UNIQUE near-VWAP
      zone (|dist_vwap|<1%, complementary to vwap_fade-short which needs >1% ABOVE VWAP) the
      setup is +EV but the shipping target is too far: LIVE target +0.099R, LOD target
      +0.129R/58% win, VWAP target +0.140R/78% win. The loose state-detector fired ~94%
      sub-edge alerts (9659/10296 events gated by the 1.0% min-risk floor in replay).
      1-min bars come from ib_historical_data (IB-only) via
      self.technical_service._get_intraday_bars_from_db(sym,"1 min",60).

DRIFT NOTE: FUNCTION-ANCHORED. Asserts live whole-file SHA == DGX baseline AND the exact
      _check_off_sides bytes present (count==1), replaces, asserts new func SHA, then
      py_compiles the whole file before writing. (file > paste limit -> no precomputed
      whole-file POST_SHA; compile + func-SHA guards + backup cover it.)

§2.2: PRE whole-file SHA + function PRE/POST SHA + anchor-uniqueness + compile guard +
      auto-backup + --check/--apply/--rollback.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/patch_v350_off_sides_snapback.py --check
  .venv/bin/python backend/scripts/patch_v350_off_sides_snapback.py --apply
  .venv/bin/python backend/scripts/patch_v350_off_sides_snapback.py --rollback
Then: pytest backend/tests/test_v350_off_sides.py -q ; commit ; ./start_backend.sh --force
"""
import base64, hashlib, sys, shutil, os, py_compile, tempfile

FILE = "backend/services/enhanced_scanner.py"
DGX_WHOLE_PRE = "932d320f107222b4d5380dea0ffd43a4bc12a54908c0297c3ce78c605bdafef1"
PRE_FUNC_SHA  = "b7b484db624ed3152defc504b2eb75ce54e8a14ae72c1b6eac7f971b0d630f92"
POST_FUNC_SHA = "ad34fe118be21ec698ac8a35112bd9bed3f42e91c9089fca727ec39872d5b4e2"
OLD_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfb2ZmX3NpZGVzKHNlbGYsIHN5bWJvbDogc3RyLCBzbmFwc2hvdCwgdGFwZTogVGFwZVJlYWRpbmcpIC0+IE9wdGlvbmFsW0xpdmVBbGVydF06CiAgICAgICAgIiIiT2ZmIFNpZGVzIC0gUmFuZ2UgYnJlYWsgaW4gZmFkZSBtYXJrZXQiIiIKICAgICAgICBpZiBzZWxmLl9tYXJrZXRfcmVnaW1lIG5vdCBpbiBbTWFya2V0UmVnaW1lLlJBTkdFX0JPVU5ELCBNYXJrZXRSZWdpbWUuRkFERV06CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgCiAgICAgICAgaWYgYWJzKHNuYXBzaG90LmRpc3RfZnJvbV92d2FwKSA8IDEuMCBhbmQgc25hcHNob3QuZGFpbHlfcmFuZ2VfcGN0ID4gMS41OgogICAgICAgICAgICBkaXN0X2Zyb21faG9kID0gKChzbmFwc2hvdC5oaWdoX29mX2RheSAtIHNuYXBzaG90LmN1cnJlbnRfcHJpY2UpIC8gc25hcHNob3QuY3VycmVudF9wcmljZSkgKiAxMDAKICAgICAgICAgICAgCiAgICAgICAgICAgIGlmIGRpc3RfZnJvbV9ob2QgPCAxLjA6CiAgICAgICAgICAgICAgICByZXR1cm4gTGl2ZUFsZXJ0KAogICAgICAgICAgICAgICAgICAgIGlkPWYib2Zmc2lkZXNfc2hvcnRfe3N5bWJvbH1fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclSCVNJVMnKX0iLAogICAgICAgICAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgICAgICAgICAgc2V0dXBfdHlwZT0ib2ZmX3NpZGVzX3Nob3J0IiwKICAgICAgICAgICAgICAgICAgICBzdHJhdGVneV9uYW1lPSJPZmYgU2lkZXMgU2NhbHAgKElOVC0zMykiLAogICAgICAgICAgICAgICAgICAgIGRpcmVjdGlvbj0ic2hvcnQiLAogICAgICAgICAgICAgICAgICAgIHByaW9yaXR5PUFsZXJ0UHJpb3JpdHkuTUVESVVNLAogICAgICAgICAgICAgICAgICAgIGN1cnJlbnRfcHJpY2U9c25hcHNob3QuY3VycmVudF9wcmljZSwKICAgICAgICAgICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPXNuYXBzaG90Lmxvd19vZl9kYXksCiAgICAgICAgICAgICAgICAgICAgc3RvcF9sb3NzPXNlbGYuX2F0cl9mbG9vcmVkX3N0b3AoCiAgICAgICAgICAgICAgICAgICAgICAgIGVudHJ5X3ByaWNlPXNuYXBzaG90LmN1cnJlbnRfcHJpY2UsCiAgICAgICAgICAgICAgICAgICAgICAgIHJhd19zdG9wPXNuYXBzaG90LmhpZ2hfb2ZfZGF5ICsgMC4wMSwKICAgICAgICAgICAgICAgICAgICAgICAgYXRyPWdldGF0dHIoc25hcHNob3QsICJhdHIiLCBOb25lKSwKICAgICAgICAgICAgICAgICAgICAgICAgZGlyZWN0aW9uPSJzaG9ydCIsCiAgICAgICAgICAgICAgICAgICAgICAgIG1pbl9hdHJfbXVsdD0wLjUsCiAgICAgICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgICAgICB0YXJnZXQ9cm91bmQoc25hcHNob3QubG93X29mX2RheSAtIChzbmFwc2hvdC5oaWdoX29mX2RheSAtIHNuYXBzaG90Lmxvd19vZl9kYXkpLCAyKSwKICAgICAgICAgICAgICAgICAgICByaXNrX3Jld2FyZD0xLjUsCiAgICAgICAgICAgICAgICAgICAgdHJpZ2dlcl9wcm9iYWJpbGl0eT0wLjUwLAogICAgICAgICAgICAgICAgICAgIHdpbl9wcm9iYWJpbGl0eT0wLjUyLAogICAgICAgICAgICAgICAgICAgIG1pbnV0ZXNfdG9fdHJpZ2dlcj0yMCwKICAgICAgICAgICAgICAgICAgICBoZWFkbGluZT1mIuKalO+4jyB7c3ltYm9sfSBPZmYgU2lkZXMgU0hPUlQgLSBSYW5nZSBicmVhayIsCiAgICAgICAgICAgICAgICAgICAgcmVhc29uaW5nPVsKICAgICAgICAgICAgICAgICAgICAgICAgZiJSYW5nZTogJHtzbmFwc2hvdC5sb3dfb2ZfZGF5Oi4yZn0gLSAke3NuYXBzaG90LmhpZ2hfb2ZfZGF5Oi4yZn0iLAogICAgICAgICAgICAgICAgICAgICAgICBmIlJlZ2ltZToge3NlbGYuX21hcmtldF9yZWdpbWUudmFsdWV9IiwKICAgICAgICAgICAgICAgICAgICAgICAgZiJUYXBlOiB7dGFwZS5vdmVyYWxsX3NpZ25hbC52YWx1ZX0iCiAgICAgICAgICAgICAgICAgICAgXSwKICAgICAgICAgICAgICAgICAgICB0aW1lX3dpbmRvdz1zZWxmLl9nZXRfY3VycmVudF90aW1lX3dpbmRvdygpLnZhbHVlLAogICAgICAgICAgICAgICAgICAgIG1hcmtldF9yZWdpbWU9c2VsZi5fbWFya2V0X3JlZ2ltZS52YWx1ZSwKICAgICAgICAgICAgICAgICAgICBleHBpcmVzX2F0PShkYXRldGltZS5ub3codGltZXpvbmUudXRjKSArIHRpbWVkZWx0YShob3Vycz0xKSkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gTm9uZQogICAgCg=="
NEW_B64 = "ICAgIGFzeW5jIGRlZiBfY2hlY2tfb2ZmX3NpZGVzKHNlbGYsIHN5bWJvbDogc3RyLCBzbmFwc2hvdCwgdGFwZTogVGFwZVJlYWRpbmcpIC0+IE9wdGlvbmFsW0xpdmVBbGVydF06CiAgICAgICAgIiIiT2ZmIFNpZGVzIFx1MjAxNCByYW5nZS10b3AgZmFkZSBTSE9SVCBzbmFwYmFjayAodjE5LjM0LjM1MCByZWRlc2lnbikuCgogICAgICAgIEZpcmVzIG9uIHRoZSBUUklHR0VSLCBub3QgYSBzdGF0ZTogaW4gUkFOR0VfQk9VTkQvRkFERSByZWdpbWUsIHdoZW4gcHJpY2UgcmV0dXJucyB3aXRoaW4KICAgICAgICAxLjAlIG9mIHRoZSBzZXNzaW9uIEhPRCBpbiBhIHdpZGUgKD4xLjUlKSByYW5nZSBBTkQgaXMgbmVhciBWV0FQICh8ZGlzdHw8MS4wJSBcdTIwMTQgdGhlIHpvbmUKICAgICAgICB0aGF0IHZ3YXBfZmFkZS1zaG9ydCwgd2hpY2ggbmVlZHMgPjEuMCUgQUJPVkUgVldBUCwgc3RydWN0dXJhbGx5IGNhbm5vdCBzZXJ2ZSksIGEgUkVEIDEtbWluCiAgICAgICAgZG91YmxlLWJhci1MT1ctYnJlYWsgcmVqZWN0aW9uIG11c3QgcHJpbnQgKGFjY2VsIDEuM3gpLiBWYWxpZGF0ZWQgK0VWIG9uIGEgMTRkIHJpc2stY29udHJvbGxlZAogICAgICAgIG5hdGl2ZS0xbWluIHJlcGxheSAodjM0OSBVTklRVUUgem9uZTogTE9EIHRhcmdldCB3aW41OCUvKzAuMTI5UiwgVldBUCB0YXJnZXQgd2luNzglLyswLjE0MFI7CiAgICAgICAgdGhlIG9sZCBmYXIgdGFyZ2V0IExPRC0oSE9ELUxPRCkgd2FzIHRoZSB3ZWFrZXN0IGF0ICswLjA5OVIgXHUyMDE0IGhlbmNlIHRoZSBjbG9zZXIgdGFyZ2V0KS4gVGhlCiAgICAgICAgbG9vc2UgbGl2ZSBzdGF0ZS1kZXRlY3RvciBmaXJlZCB+OTQlIHN1Yi1lZGdlIGFsZXJ0cyAoOTY1OS8xMDI5NiBnYXRlZCBieSB0aGUgMS4wJSBtaW4tcmlzawogICAgICAgIGZsb29yIGluIHJlcGxheSkuIFJlcXVpcmVzIHN0b3AgPj0gMS4wJSBvZiBlbnRyeSArIDIgZmlyZXMvZGF5IHBlciBzeW1ib2wuIFRhcmdldCA9IHRoZQogICAgICAgIG5lYXJlci1vZihWV0FQLCBMT0QpIGJlbG93IGVudHJ5IChWV0FQIG1lYW4tcmV2ZXJzaW9uIGlmIHRoZXJlIGlzIHJvb20sIGVsc2UgdGhlIHJhbmdlIGxvdykuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fbWFya2V0X3JlZ2ltZSBub3QgaW4gW01hcmtldFJlZ2ltZS5SQU5HRV9CT1VORCwgTWFya2V0UmVnaW1lLkZBREVdOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIEhPRF9QUk9YID0gMS4wCiAgICAgICAgTUlOX1JBTkdFID0gMS41CiAgICAgICAgQUNDRUwgPSAxLjMKICAgICAgICBNSU5fUklTS19QQ1QgPSAxLjAKCiAgICAgICAgaWYgYWJzKHNuYXBzaG90LmRpc3RfZnJvbV92d2FwKSA+PSAxLjAgb3Igc25hcHNob3QuZGFpbHlfcmFuZ2VfcGN0IDw9IE1JTl9SQU5HRToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBjcCA9IHNuYXBzaG90LmN1cnJlbnRfcHJpY2UKICAgICAgICBpZiBub3QgY3Agb3IgY3AgPD0gMDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBkaXN0X2Zyb21faG9kID0gKChzbmFwc2hvdC5oaWdoX29mX2RheSAtIGNwKSAvIGNwKSAqIDEwMAogICAgICAgIGlmIGRpc3RfZnJvbV9ob2QgPj0gSE9EX1BST1g6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgdHMgPSBnZXRhdHRyKHNlbGYsICJ0ZWNobmljYWxfc2VydmljZSIsIE5vbmUpCiAgICAgICAgaWYgdHMgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBiYXJzID0gdHMuX2dldF9pbnRyYWRheV9iYXJzX2Zyb21fZGIoc3ltYm9sLCAiMSBtaW4iLCA2MCkKICAgICAgICBpZiBub3QgYmFycyBvciBsZW4oYmFycykgPCA1OgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHZ3YXAgPSBmbG9hdChnZXRhdHRyKHNuYXBzaG90LCAidndhcCIsIDAuMCkgb3IgMC4wKQogICAgICAgIGhvZCA9IGZsb2F0KHNuYXBzaG90LmhpZ2hfb2ZfZGF5IG9yIDAuMCkKICAgICAgICBsb2QgPSBmbG9hdChzbmFwc2hvdC5sb3dfb2ZfZGF5IG9yIDAuMCkKICAgICAgICBpZiB2d2FwIDw9IDAgb3IgaG9kIDw9IDAgb3IgbG9kIDw9IDAgb3IgaG9kIDw9IGxvZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgY2FwcyA9IGdldGF0dHIoc2VsZiwgIl9vZmZfc2lkZXNfZGFpbHlfY2FwcyIsIE5vbmUpCiAgICAgICAgaWYgY2FwcyBpcyBOb25lOgogICAgICAgICAgICBjYXBzID0gc2VsZi5fb2ZmX3NpZGVzX2RhaWx5X2NhcHMgPSB7fQogICAgICAgIHRvZGF5ID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0Yykuc3RyZnRpbWUoIiVZLSVtLSVkIikKICAgICAgICBrZXkgPSBmIntzeW1ib2x9Ont0b2RheX06c2hvcnQiCiAgICAgICAgaWYgY2Fwcy5nZXQoa2V5LCAwKSA+PSAyOgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAgICBkZWYgX21lZGlhbih4cyk6CiAgICAgICAgICAgIHMgPSBzb3J0ZWQoeHMpCiAgICAgICAgICAgIG4gPSBsZW4ocykKICAgICAgICAgICAgaWYgbiA9PSAwOgogICAgICAgICAgICAgICAgcmV0dXJuIDAuMAogICAgICAgICAgICByZXR1cm4gc1tuIC8vIDJdIGlmIG4gJSAyIGVsc2UgKHNbbiAvLyAyIC0gMV0gKyBzW24gLy8gMl0pIC8gMi4wCgogICAgICAgIGkgPSBsZW4oYmFycykgLSAxCiAgICAgICAgaWYgaSA8IDI6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgbGFzdCA9IGJhcnNbaV0KICAgICAgICByYW5nZXMgPSBbKGJbImhpZ2giXSAtIGJbImxvdyJdKSBmb3IgYiBpbiBiYXJzWzppXQogICAgICAgICAgICAgICAgICBpZiBiLmdldCgiaGlnaCIpIGlzIG5vdCBOb25lIGFuZCBiLmdldCgibG93IikgaXMgbm90IE5vbmVdCiAgICAgICAgbWVkX3IgPSBfbWVkaWFuKHJhbmdlcykKCiAgICAgICAgcmVkID0gbGFzdFsiY2xvc2UiXSA8IGxhc3RbIm9wZW4iXQogICAgICAgIGJyZWFrc19sbyA9IGxhc3RbImxvdyJdIDwgbWluKGJhcnNbaSAtIDFdWyJsb3ciXSwgYmFyc1tpIC0gMl1bImxvdyJdKQogICAgICAgIGFjY2VsX29rID0gKG1lZF9yIDw9IDApIG9yICgobGFzdFsiaGlnaCJdIC0gbGFzdFsibG93Il0pID49IEFDQ0VMICogbWVkX3IpCiAgICAgICAgaWYgbm90IChyZWQgYW5kIGJyZWFrc19sbyBhbmQgYWNjZWxfb2spOgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAgICBlbnRyeSA9IHJvdW5kKG1pbihiYXJzW2kgLSAxXVsibG93Il0sIGJhcnNbaSAtIDJdWyJsb3ciXSksIDIpCiAgICAgICAgc3RvcF9sb3NzID0gcm91bmQoaG9kICsgMC4wMiwgMikKICAgICAgICByaXNrID0gc3RvcF9sb3NzIC0gZW50cnkKICAgICAgICBpZiByaXNrIDw9IDAgb3IgZW50cnkgPD0gMCBvciAocmlzayAvIGVudHJ5ICogMTAwLjApIDwgTUlOX1JJU0tfUENUOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHVzZV92d2FwID0gbG9kIDwgdndhcCA8IGVudHJ5CiAgICAgICAgdGFyZ2V0XzEgPSByb3VuZCh2d2FwLCAyKSBpZiB1c2VfdndhcCBlbHNlIHJvdW5kKGxvZCwgMikKICAgICAgICBpZiB0YXJnZXRfMSA+PSBlbnRyeToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICByZXdhcmQgPSBlbnRyeSAtIHRhcmdldF8xCiAgICAgICAgcl9tdWx0aXBsZSA9IHJvdW5kKHJld2FyZCAvIHJpc2ssIDIpIGlmIHJpc2sgPiAwIGVsc2UgMS41CiAgICAgICAgcHJpb3JpdHkgPSBBbGVydFByaW9yaXR5LkhJR0ggaWYgdGFwZS5jb25maXJtYXRpb25fZm9yX3Nob3J0IGVsc2UgQWxlcnRQcmlvcml0eS5NRURJVU0KICAgICAgICBldl9pbmZvID0gIiIKICAgICAgICBpZiAib2ZmX3NpZGVzIiBpbiBzZWxmLl9zdHJhdGVneV9zdGF0czoKICAgICAgICAgICAgc3QgPSBzZWxmLl9zdHJhdGVneV9zdGF0c1sib2ZmX3NpZGVzIl0KICAgICAgICAgICAgaWYgc3Qud2luX3JhdGUgPiAwOgogICAgICAgICAgICAgICAgZXZfaW5mbyA9IGYiSGlzdG9yaWNhbDoge3N0Lndpbl9yYXRlOi4wJX0gd2luLCBFViB7c3QuZXhwZWN0ZWRfdmFsdWVfcjouMmZ9UiIKICAgICAgICBjYXBzW2tleV0gPSBjYXBzLmdldChrZXksIDApICsgMQogICAgICAgIHRhcGVfdGFnID0gIlx1MjcxMyBUQVBFIiBpZiB0YXBlLmNvbmZpcm1hdGlvbl9mb3Jfc2hvcnQgZWxzZSAiIgogICAgICAgIHRndF9sYWJlbCA9ICJWV0FQIiBpZiB1c2VfdndhcCBlbHNlICJyYW5nZS1sb3ciCiAgICAgICAgcmV0dXJuIExpdmVBbGVydCgKICAgICAgICAgICAgaWQ9ZiJvZmZzaWRlc19zaG9ydF97c3ltYm9sfV97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVIJU0lUycpfSIsCiAgICAgICAgICAgIHN5bWJvbD1zeW1ib2wsCiAgICAgICAgICAgIHNldHVwX3R5cGU9Im9mZl9zaWRlc19zaG9ydCIsCiAgICAgICAgICAgIHN0cmF0ZWd5X25hbWU9Ik9mZiBTaWRlcyBTY2FscCAoSU5ULTMzKSIsCiAgICAgICAgICAgIGRpcmVjdGlvbj0ic2hvcnQiLAogICAgICAgICAgICBwcmlvcml0eT1wcmlvcml0eSwKICAgICAgICAgICAgY3VycmVudF9wcmljZT1zbmFwc2hvdC5jdXJyZW50X3ByaWNlLAogICAgICAgICAgICB0cmlnZ2VyX3ByaWNlPWVudHJ5LAogICAgICAgICAgICBzdG9wX2xvc3M9c3RvcF9sb3NzLAogICAgICAgICAgICB0YXJnZXQ9dGFyZ2V0XzEsCiAgICAgICAgICAgIHJpc2tfcmV3YXJkPXJfbXVsdGlwbGUsCiAgICAgICAgICAgIHRyaWdnZXJfcHJvYmFiaWxpdHk9MC42NSwKICAgICAgICAgICAgd2luX3Byb2JhYmlsaXR5PTAuNzAsCiAgICAgICAgICAgIG1pbnV0ZXNfdG9fdHJpZ2dlcj0wLAogICAgICAgICAgICBoZWFkbGluZT1mIlx1MjY5NFx1ZmUwZiB7c3ltYm9sfSBPZmYgU2lkZXMgU0hPUlQgc25hcGJhY2sgXHUyMDE0IHJhbmdlLXRvcCBmYWRlIHRvIHt0Z3RfbGFiZWx9IHt0YXBlX3RhZ30iLAogICAgICAgICAgICByZWFzb25pbmc9WwogICAgICAgICAgICAgICAgZiJGYWRlZCB3aXRoaW4ge2Rpc3RfZnJvbV9ob2Q6LjFmfSUgb2YgSE9EICR7aG9kOi4yZn0gaW4gYSB7c25hcHNob3QuZGFpbHlfcmFuZ2VfcGN0Oi4xZn0lIHJhbmdlIFx1MjE5MiByZWQgMi1iYXItbG93LWJyZWFrIiwKICAgICAgICAgICAgICAgIGYiUjpSID0ge3JfbXVsdGlwbGU6LjFmfToxIChTdG9wICR7c3RvcF9sb3NzOi4yZn0gYWJvdmUgSE9ELCBUYXJnZXQge3RndF9sYWJlbH0gJHt0YXJnZXRfMTouMmZ9KSIsCiAgICAgICAgICAgICAgICBmIlJlZ2ltZToge3NlbGYuX21hcmtldF9yZWdpbWUudmFsdWV9IHwgVGFwZToge3RhcGUub3ZlcmFsbF9zaWduYWwudmFsdWV9IiwKICAgICAgICAgICAgICAgIGV2X2luZm8gaWYgZXZfaW5mbyBlbHNlICJSYW5nZS10b3AgZmFkZSAodjM0OSByZXBsYXkgVU5JUVVFOiArMC4xM1IvNTglIHRvIExPRCwgKzAuMTRSLzc4JSB0byBWV0FQKSIsCiAgICAgICAgICAgICAgICAiRW50cnk6IHJlZCBiYXIgYnJva2UgcHJpb3ItMiBsb3dzIChuZWFyLVZXQVAgem9uZSwgMSUgbWluLXJpc2ssIDIvZGF5IGNhcCkiLAogICAgICAgICAgICBdLAogICAgICAgICAgICB0aW1lX3dpbmRvdz1zZWxmLl9nZXRfY3VycmVudF90aW1lX3dpbmRvdygpLnZhbHVlLAogICAgICAgICAgICBtYXJrZXRfcmVnaW1lPXNlbGYuX21hcmtldF9yZWdpbWUudmFsdWUsCiAgICAgICAgICAgIGV4cGlyZXNfYXQ9KGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpICsgdGltZWRlbHRhKGhvdXJzPTEpKS5pc29mb3JtYXQoKQogICAgICAgICkKICAgICAgICByZXR1cm4gTm9uZQogICAgCg=="
BACKUP = FILE + ".bak_v350"


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
    print("\nREADY: --apply installs the Off Sides range-top fade SHORT snapback (near-VWAP zone, closer target).")
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
    print("Verify: pytest backend/tests/test_v350_off_sides.py -q ; commit BEFORE restart ; ./start_backend.sh --force")


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
