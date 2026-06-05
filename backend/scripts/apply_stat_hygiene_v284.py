#!/usr/bin/env python3
"""
apply_stat_hygiene_v284.py  (SentCom v19.34.284)

Idempotent applier for the Stat Hygiene / Win-rate Pollution fix.

DOES TWO THINGS
  1. Patches  backend/services/pnl_compute.py :
       a) adds _is_reconciliation_artifact() (legacy-row artifact guard)
       b) hardens recompute_strategy_stats_for_setup() to exclude legacy
          alert_outcomes rows (no `genuine` field) that decode to
          reconciliation/phantom artifacts.
  2. Drops    backend/scripts/rebuild_strategy_stats_v284.py  (one-time rebuild;
              DRY-RUN by default, --commit to write).

SAFETY
  - Fully idempotent: re-running is a no-op once 'v19.34.284' markers exist.
  - Refuses to write pnl_compute.py unless BOTH hunks match exactly once.
  - Timestamped .bak before write + py_compile validation w/ auto-restore.
  - Hunk text is base64-embedded => byte-exact, no escaping drift.

USAGE  (run from anywhere; pass --repo if autodetect misses)
  python3 apply_stat_hygiene_v284.py
  python3 apply_stat_hygiene_v284.py --repo /home/spark-1a60/Trading-and-Analysis-Platform
  python3 apply_stat_hygiene_v284.py --dry-run
"""
import argparse
import base64
import os
import py_compile
import shutil
import sys
import time

MARKER = "v19.34.284"

_B64 = {
    "HA_OLD": "ZGVmIF9iYXNlX3NldHVwKHNldHVwX3R5cGU6IEFueSkgLT4gc3RyOgogICAgIiIiTm9ybWFsaXplIGEgc2V0dXBfdHlwZSB0byB0aGUgZmFtaWx5IGtleSB0aGUgVFFTIFNldHVwIHBpbGxhciBxdWVyaWVzCiAgICAoYGVuaGFuY2VkX3NjYW5uZXJgIGNvbnN1bWVyIGF0IEwzMjAxKTogc3RyaXAgdGhlIF9sb25nL19zaG9ydCBzdWZmaXguCiAgICBNVVNUIG1hdGNoIGBiYWNrZmlsbF9zdHJhdGVneV9zdGF0cy5iYXNlX3NldHVwYCBleGFjdGx5LiIiIgogICAgcmV0dXJuIHN0cihzZXR1cF90eXBlIG9yICIiKS5zcGxpdCgiX2xvbmciKVswXS5zcGxpdCgiX3Nob3J0IilbMF0K",
    "HA_NEW": "ZGVmIF9iYXNlX3NldHVwKHNldHVwX3R5cGU6IEFueSkgLT4gc3RyOgogICAgIiIiTm9ybWFsaXplIGEgc2V0dXBfdHlwZSB0byB0aGUgZmFtaWx5IGtleSB0aGUgVFFTIFNldHVwIHBpbGxhciBxdWVyaWVzCiAgICAoYGVuaGFuY2VkX3NjYW5uZXJgIGNvbnN1bWVyIGF0IEwzMjAxKTogc3RyaXAgdGhlIF9sb25nL19zaG9ydCBzdWZmaXguCiAgICBNVVNUIG1hdGNoIGBiYWNrZmlsbF9zdHJhdGVneV9zdGF0cy5iYXNlX3NldHVwYCBleGFjdGx5LiIiIgogICAgcmV0dXJuIHN0cihzZXR1cF90eXBlIG9yICIiKS5zcGxpdCgiX2xvbmciKVswXS5zcGxpdCgiX3Nob3J0IilbMF0KCgojIOKUgOKUgCB2MTkuMzQuMjg0IOKAlCBsZWdhY3ktcm93IGFydGlmYWN0IGd1YXJkIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIGByZWNvbXB1dGVfc3RyYXRlZ3lfc3RhdHNfZm9yX3NldHVwYCBmaWx0ZXJzIG9uIHRoZSBgZ2VudWluZWAgZmxhZywgYnV0CiMgYWxlcnRfb3V0Y29tZXMgcm93cyB3cml0dGVuIEJFRk9SRSB0aGUgdjI0MCBoeWdpZW5lIHRhZ2dpbmcgcHJlZGF0ZSB0aGF0IGZpZWxkCiMgZW50aXJlbHkuIGBkLmdldCgiZ2VudWluZSIsIFRydWUpYCB0aGVyZWZvcmUgZGVmYXVsdHMgbGVnYWN5IGFydGlmYWN0IHJvd3MKIyAocmVjb25jaWxlZF9vcnBoYW4gLyByZWNvbmNpbGVkX2V4Y2Vzc19zbGljZSAvIHBoYW50b20gc3dlZXBzKSB0byBnZW51aW5lPVRydWUsCiMgc28gdGhleSBsZWFrZWQgYmFjayBpbnRvIHRoZSBFVi93aW4tcmF0ZSBmZWVkIGFuZCBkcmFnZ2VkIHRoZSBTbWFydCBGaWx0ZXIgaW50bwojIG92ZXItZ2F0aW5nLiBUaGlzIHJlLWRlcml2ZXMgZ2VudWluZW5lc3MgZnJvbSBzZXR1cF90eXBlL2Nsb3NlX3JlYXNvbiB1c2luZyB0aGUKIyBTQU1FIHN1YnN0cmluZ3MgYXMgdHJhZGVfb3V0Y29tZV9oeWdpZW5lLmNsYXNzaWZ5X2Nsb3NlLCByZWdhcmRsZXNzIG9mIHdoZXRoZXIKIyB0aGUgcm93IGNhcnJpZXMgYSBgZ2VudWluZWAgZmxhZy4KX0FSVElGQUNUX1NFVFVQX1NVQlNUUl9GQUxMQkFDSyA9ICgicmVjb25jaWxlZCIsICJpbXBvcnRlZCIsICJwaGFudG9tIikKX0FSVElGQUNUX1JFQVNPTl9TVUJTVFJfRkFMTEJBQ0sgPSAoCiAgICAicGhhbnRvbSIsICJzd2VlcCIsICJwdXJnZSIsICJyZWNvbmNpbGUiLCAiZXh0ZXJuYWxfZmxhdHRlbiIsICJvcGVyYXRvcl9leHRlcm5hbCIsCikKCgpkZWYgX2lzX3JlY29uY2lsaWF0aW9uX2FydGlmYWN0KHNldHVwX3R5cGU6IEFueSwgY2xvc2VfcmVhc29uOiBBbnkpIC0+IGJvb2w6CiAgICAiIiJUcnVlIHdoZW4gYSByb3cgaXMgYW4gZXhlY3V0aW9uL3JlY29uY2lsaWF0aW9uIGFydGlmYWN0IChOT1QgYSBnZW51aW5lCiAgICBzdHJhdGVneSBjbG9zZSkganVkZ2VkIHB1cmVseSBmcm9tIGl0cyBzZXR1cF90eXBlIC8gY2xvc2VfcmVhc29uIOKAlCB1c2VkIHRvCiAgICBleGNsdWRlIGxlZ2FjeSByb3dzIHRoYXQgaGF2ZSBubyBgZ2VudWluZWAgZmllbGQuIE1pcnJvcnMgdGhlIGh5Z2llbmUKICAgIG1vZHVsZSdzIHN1YnN0cmluZ3M7IGltcG9ydHMgdGhlbSB3aGVuIGF2YWlsYWJsZSwgZWxzZSB1c2VzIHRoZSBmYWxsYmFjay4iIiIKICAgIHRyeToKICAgICAgICBmcm9tIHNlcnZpY2VzLnRyYWRlX291dGNvbWVfaHlnaWVuZSBpbXBvcnQgKAogICAgICAgICAgICBfQVJUSUZBQ1RfU0VUVVBfU1VCU1RSSU5HUyBhcyBfc3MsCiAgICAgICAgICAgIF9BUlRJRkFDVF9SRUFTT05fU1VCU1RSSU5HUyBhcyBfcnMsCiAgICAgICAgKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBfc3MsIF9ycyA9IF9BUlRJRkFDVF9TRVRVUF9TVUJTVFJfRkFMTEJBQ0ssIF9BUlRJRkFDVF9SRUFTT05fU1VCU1RSX0ZBTExCQUNLCiAgICBzdCA9IHN0cihzZXR1cF90eXBlIG9yICIiKS5sb3dlcigpCiAgICByciA9IHN0cihjbG9zZV9yZWFzb24gb3IgIiIpLmxvd2VyKCkKICAgIGlmIGFueShzdWIgaW4gc3QgZm9yIHN1YiBpbiBfc3MpOgogICAgICAgIHJldHVybiBUcnVlCiAgICBpZiBhbnkoc3ViIGluIHJyIGZvciBzdWIgaW4gX3JzKToKICAgICAgICByZXR1cm4gVHJ1ZQogICAgcmV0dXJuIEZhbHNlCgoKX1dJTl9UT0sgPSB7IndvbiIsICJ3aW4iLCAid2lubmVyIiwgInRhcmdldCIsICJ0YXJnZXRfaGl0IiwgInByb2ZpdCIsICJ0cCIsCiAgICAgICAgICAgICJ0YWtlX3Byb2ZpdCIsICJwcm9maXRfdGFyZ2V0In0KX0xPU1NfVE9LID0geyJsb3N0IiwgImxvc3MiLCAibG9zZXIiLCAic3RvcHBlZCIsICJzdG9wIiwgInN0b3BfaGl0IiwKICAgICAgICAgICAgICJzdG9wcGVkX291dCIsICJzbCIsICJzdG9wX2xvc3MifQoKCmRlZiBfY2xhc3NpZnlfb3V0Y29tZShvdXRjb21lLCByLCBwbmwpOgogICAgIiIid2luL2xvc3MvTm9uZSDigJQgb3V0Y29tZSBzdHJpbmcgZmlyc3QsIHRoZW4gUiwgdGhlbiBwbmwgKG1hdGNoZXMKICAgIGJhY2tmaWxsX3N0cmF0ZWd5X3N0YXRzLl9jbGFzc2lmeSkuIiIiCiAgICBvID0gc3RyKG91dGNvbWUgb3IgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgaWYgbyBpbiBfV0lOX1RPSzoKICAgICAgICByZXR1cm4gIndpbiIKICAgIGlmIG8gaW4gX0xPU1NfVE9LOgogICAgICAgIHJldHVybiAibG9zcyIKICAgIGlmIHIgaXMgbm90IE5vbmUgYW5kIHIgIT0gMDoKICAgICAgICByZXR1cm4gIndpbiIgaWYgciA+IDAgZWxzZSAibG9zcyIKICAgIGlmIHBubDoKICAgICAgICByZXR1cm4gIndpbiIgaWYgcG5sID4gMCBlbHNlICJsb3NzIgogICAgcmV0dXJuIE5vbmUK",
    "HB_OLD": "ICAgICAgICBhbyA9IF9BT19EQlsiYWxlcnRfb3V0Y29tZXMiXQogICAgICAgIHJvd3MgPSBbCiAgICAgICAgICAgIGQgZm9yIGQgaW4gYW8uZmluZCgKICAgICAgICAgICAgICAgIHt9LCB7Il9pZCI6IDEsICJzZXR1cF90eXBlIjogMSwgIm91dGNvbWUiOiAxLCAicl9tdWx0aXBsZSI6IDEsCiAgICAgICAgICAgICAgICAgICAgICJuZXRfcG5sIjogMSwgInBubCI6IDEsICJjbG9zZWRfYXQiOiAxLCAiZ2VudWluZSI6IDF9KQogICAgICAgICAgICBpZiBfYmFzZV9zZXR1cChkLmdldCgic2V0dXBfdHlwZSIpKSA9PSBiYXNlCiAgICAgICAgXQogICAgICAgIGlmIGdlbnVpbmVfb25seToKICAgICAgICAgICAgcm93cyA9IFtkIGZvciBkIGluIHJvd3MgaWYgZC5nZXQoImdlbnVpbmUiLCBUcnVlKSBpcyBub3QgRmFsc2VdCg==",
    "HB_NEW": "ICAgICAgICBhbyA9IF9BT19EQlsiYWxlcnRfb3V0Y29tZXMiXQogICAgICAgIHJvd3MgPSBbCiAgICAgICAgICAgIGQgZm9yIGQgaW4gYW8uZmluZCgKICAgICAgICAgICAgICAgIHt9LCB7Il9pZCI6IDEsICJzZXR1cF90eXBlIjogMSwgIm91dGNvbWUiOiAxLCAicl9tdWx0aXBsZSI6IDEsCiAgICAgICAgICAgICAgICAgICAgICJuZXRfcG5sIjogMSwgInBubCI6IDEsICJjbG9zZWRfYXQiOiAxLCAiZ2VudWluZSI6IDEsCiAgICAgICAgICAgICAgICAgICAgICJjbG9zZV9yZWFzb24iOiAxfSkKICAgICAgICAgICAgaWYgX2Jhc2Vfc2V0dXAoZC5nZXQoInNldHVwX3R5cGUiKSkgPT0gYmFzZQogICAgICAgIF0KICAgICAgICBpZiBnZW51aW5lX29ubHk6CiAgICAgICAgICAgICMgRXhjbHVkZSBib3RoIGZsYWdnZWQgYXJ0aWZhY3RzIEFORCBsZWdhY3kgcm93cyAobm8gYGdlbnVpbmVgIGZpZWxkKQogICAgICAgICAgICAjIHRoYXQgZGVjb2RlIHRvIHJlY29uY2lsaWF0aW9uL3BoYW50b20gYXJ0aWZhY3RzIGJ5IHNldHVwL3JlYXNvbi4KICAgICAgICAgICAgcm93cyA9IFsKICAgICAgICAgICAgICAgIGQgZm9yIGQgaW4gcm93cwogICAgICAgICAgICAgICAgaWYgZC5nZXQoImdlbnVpbmUiLCBUcnVlKSBpcyBub3QgRmFsc2UKICAgICAgICAgICAgICAgIGFuZCBub3QgX2lzX3JlY29uY2lsaWF0aW9uX2FydGlmYWN0KAogICAgICAgICAgICAgICAgICAgIGQuZ2V0KCJzZXR1cF90eXBlIiksIGQuZ2V0KCJjbG9zZV9yZWFzb24iKSkKICAgICAgICAgICAgXQo=",
    "REBUILD": "IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwoiIiIKcmVidWlsZF9zdHJhdGVneV9zdGF0c192Mjg0LnB5IOKAlCBTdGF0IEh5Z2llbmUgLyBXaW4tcmF0ZSBQb2xsdXRpb24gcmVidWlsZC4KCldIWQogIGBzdHJhdGVneV9zdGF0c2AgKHRoZSBUUVMgU2V0dXAtcGlsbGFyIEVWICsgcmVhbC13aW4tcmF0ZSBmZWVkIHRoYXQgZHJpdmVzIHRoZQogIFNtYXJ0IEZpbHRlcikgd2FzIHBvbGx1dGVkIGJ5IHJlY29uY2lsaWF0aW9uL3BoYW50b20gQVJUSUZBQ1Qgcm93czoKICAgIC0gcmVjb25jaWxlZF9vcnBoYW4sIHJlY29uY2lsZWRfZXhjZXNzX3NsaWNlLCAqX3N3ZWVwLCBwaGFudG9tXyogY2xvc2VzLgogIFRoZXNlIHdlcmUgdGFnZ2VkIGdlbnVpbmU9RmFsc2UgZnJvbSB2MjQwIG9ud2FyZCwgYnV0IExFR0FDWSBhbGVydF9vdXRjb21lcyByb3dzCiAgd3JpdHRlbiBiZWZvcmUgdjI0MCBoYXZlIE5PIGBnZW51aW5lYCBmaWVsZCwgc28gdGhlIHJlY29tcHV0ZSBkZWZhdWx0ZWQgdGhlbSB0bwogIGdlbnVpbmU9VHJ1ZSBhbmQgdGhleSBrZXB0IGRyYWdnaW5nIHdpbi1yYXRlcyAvIEVWIGRvd24g4oaSIFNtYXJ0IEZpbHRlciBvdmVyLWdhdGVkLgoKV0hBVCBJVCBET0VTICAoaWRlbXBvdGVudCwgRFJZLVJVTiBieSBkZWZhdWx0KQogIDEuIEJBQ0tGSUxMOiBzdGFtcHMgZ2VudWluZT1GYWxzZSArIGh5Z2llbmVfdGFnIG9uIGV2ZXJ5IGxlZ2FjeSBhbGVydF9vdXRjb21lcwogICAgIHJvdyB3aG9zZSBzZXR1cF90eXBlIC8gY2xvc2VfcmVhc29uIGRlY29kZXMgdG8gYSByZWNvbmNpbGlhdGlvbi9waGFudG9tCiAgICAgYXJ0aWZhY3QgKHNhbWUgc3Vic3RyaW5ncyBhcyBzZXJ2aWNlcy50cmFkZV9vdXRjb21lX2h5Z2llbmUpLiBSb3dzIGFscmVhZHkKICAgICBmbGFnZ2VkIGdlbnVpbmU9RmFsc2UgYXJlIGxlZnQgdW50b3VjaGVkLgogIDIuIFJFQ09NUFVURTogcmVidWlsZHMgc3RyYXRlZ3lfc3RhdHMgd2hvbGUtdHJhZGUgZnJvbSBhbGVydF9vdXRjb21lcyBmb3IgRVZFUlkKICAgICBzZXR1cCBmYW1pbHkgdmlhIHRoZSBjYW5vbmljYWwgcG5sX2NvbXB1dGUucmVjb21wdXRlX3N0cmF0ZWd5X3N0YXRzX2Zvcl9zZXR1cAogICAgIChnZW51aW5lX29ubHk9VHJ1ZSkuIDAtUG5MIHNjcmF0Y2hlcyBhcmUgY29ycmVjdGx5IGV4Y2x1ZGVkIChuZWl0aGVyIHdpbiBub3IKICAgICBsb3NzKSwgZml4aW5nIHRoZSBvbGQgYm90X3RyYWRlcy1iYXNlZCAiMCBQbkwgY291bnRlZCBhcyBhIGxvc3MiIGJ1Zy4KClVTQUdFCiAgLnZlbnYvYmluL3B5dGhvbiBiYWNrZW5kL3NjcmlwdHMvcmVidWlsZF9zdHJhdGVneV9zdGF0c192Mjg0LnB5ICAgICAgICAgICAgIyBEUlkgUlVOCiAgLnZlbnYvYmluL3B5dGhvbiBiYWNrZW5kL3NjcmlwdHMvcmVidWlsZF9zdHJhdGVneV9zdGF0c192Mjg0LnB5IC0tY29tbWl0ICAgIyBXUklURQoiIiIKaW1wb3J0IGFyZ3BhcnNlCmltcG9ydCBvcwppbXBvcnQgc3lzCgpzeXMucGF0aC5pbnNlcnQoMCwgb3MucGF0aC5kaXJuYW1lKG9zLnBhdGguZGlybmFtZShvcy5wYXRoLmFic3BhdGgoX19maWxlX18pKSkpCgpmcm9tIHB5bW9uZ28gaW1wb3J0IE1vbmdvQ2xpZW50ICAjIG5vcWE6IEU0MDIKCm1vbmdvX3VybCA9IG9zLmVudmlyb24uZ2V0KCJNT05HT19VUkwiLCAibW9uZ29kYjovL2xvY2FsaG9zdDoyNzAxNyIpCmRiX25hbWUgPSBvcy5lbnZpcm9uLmdldCgiREJfTkFNRSIsICJ0cmFkZWNvbW1hbmQiKQpkYiA9IE1vbmdvQ2xpZW50KG1vbmdvX3VybCwgc2VydmVyU2VsZWN0aW9uVGltZW91dE1TPTUwMDApW2RiX25hbWVdCmRiLmNsaWVudC5hZG1pbi5jb21tYW5kKCJwaW5nIikKcHJpbnQoZiJbZGJdIHttb25nb191cmx9IC8ge2RiX25hbWV9IikKCmZyb20gc2VydmljZXMgaW1wb3J0IHBubF9jb21wdXRlICAjIG5vcWE6IEU0MDIKZnJvbSBzZXJ2aWNlcy5wbmxfY29tcHV0ZSBpbXBvcnQgX2Jhc2Vfc2V0dXAsIF9pc19yZWNvbmNpbGlhdGlvbl9hcnRpZmFjdCAgIyBub3FhOiBFNDAyCgojIFBvaW50IHRoZSBjYW5vbmljYWwgcmVjb21wdXRlIHdyaXRlciBhdCBUSElTIGRiIChpdCBsYXppbHkgaW5pdHMgaXRzIG93biBjbGllbnQKIyBhZ2FpbnN0IHRoZSBzYW1lIGVudiwgYnV0IG1ha2UgdGhlIGJpbmRpbmcgZXhwbGljaXQgZm9yIHRoZSByZWJ1aWxkIHJ1bikuCnBubF9jb21wdXRlLl9nZXRfb3V0Y29tZXNfY29sbGVjdGlvbigpCnBubF9jb21wdXRlLl9BT19EQiA9IGRiCgphcCA9IGFyZ3BhcnNlLkFyZ3VtZW50UGFyc2VyKCkKYXAuYWRkX2FyZ3VtZW50KCItLWNvbW1pdCIsIGFjdGlvbj0ic3RvcmVfdHJ1ZSIpCmFyZ3MgPSBhcC5wYXJzZV9hcmdzKCkKCmFvID0gZGJbImFsZXJ0X291dGNvbWVzIl0Kc3MgPSBkYlsic3RyYXRlZ3lfc3RhdHMiXQoKCmRlZiBldl90YWJsZSh0YWcpOgogICAgcHJpbnQoZiJcbiAgc3RyYXRlZ3lfc3RhdHMgRVYgc25hcHNob3QgW3t0YWd9XToiKQogICAgcHJpbnQoZiIgIHsnc2V0dXAnOjwyNn17J3RyaWcnOj41fXsnd29uJzo+NX17J3dpbiUnOj42fXsnRVZfcic6Pjh9IikKICAgIGZvciBkIGluIHNzLmZpbmQoe30sIHsiX2lkIjogMH0pLnNvcnQoImFsZXJ0c190cmlnZ2VyZWQiLCAtMSkubGltaXQoMjApOgogICAgICAgIHdyID0gKGQuZ2V0KCJ3aW5fcmF0ZSIpIG9yIDApICogMTAwCiAgICAgICAgcHJpbnQoZiIgIHtzdHIoZC5nZXQoJ3NldHVwX3R5cGUnKSlbOjI2XTo8MjZ9e2QuZ2V0KCdhbGVydHNfdHJpZ2dlcmVkJywgMCk6PjV9IgogICAgICAgICAgICAgIGYie2QuZ2V0KCdhbGVydHNfd29uJywgMCk6PjV9e3dyOj41LjBmfSV7ZC5nZXQoJ2V4cGVjdGVkX3ZhbHVlX3InLCAwKTo+OC4yZn0iKQoKCiMg4pSA4pSAIFNURVAgMTogaWRlbnRpZnkgbGVnYWN5IGFydGlmYWN0IHJvd3Mg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmFydGlmYWN0X2lkcyA9IFtdCmZvciBkIGluIGFvLmZpbmQoe30sIHsiX2lkIjogMSwgInNldHVwX3R5cGUiOiAxLCAiY2xvc2VfcmVhc29uIjogMSwgImdlbnVpbmUiOiAxfSk6CiAgICBpZiBkLmdldCgiZ2VudWluZSIpIGlzIEZhbHNlOgogICAgICAgIGNvbnRpbnVlICAjIGFscmVhZHkgY29ycmVjdGx5IGZsYWdnZWQKICAgIGlmIF9pc19yZWNvbmNpbGlhdGlvbl9hcnRpZmFjdChkLmdldCgic2V0dXBfdHlwZSIpLCBkLmdldCgiY2xvc2VfcmVhc29uIikpOgogICAgICAgIGFydGlmYWN0X2lkcy5hcHBlbmQoZFsiX2lkIl0pCgp0b3RhbF9hbyA9IGFvLmNvdW50X2RvY3VtZW50cyh7fSkKYWxyZWFkeV9mbGFnZ2VkID0gYW8uY291bnRfZG9jdW1lbnRzKHsiZ2VudWluZSI6IEZhbHNlfSkKcHJpbnQoZiJcbkJFRk9SRSAgYWxlcnRfb3V0Y29tZXM9e3RvdGFsX2FvfSAgYWxyZWFkeV9mbGFnZ2VkX2FydGlmYWN0cz17YWxyZWFkeV9mbGFnZ2VkfSIKICAgICAgZiIgIGxlZ2FjeV9hcnRpZmFjdHNfdG9fZml4PXtsZW4oYXJ0aWZhY3RfaWRzKX0iKQpldl90YWJsZSgiYmVmb3JlIikKCiMg4pSA4pSAIFNURVAgMjogYmFja2ZpbGwgZ2VudWluZT1GYWxzZSBvbiBsZWdhY3kgYXJ0aWZhY3Qgcm93cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKaWYgYXJ0aWZhY3RfaWRzOgogICAgaWYgYXJncy5jb21taXQ6CiAgICAgICAgcmVzID0gYW8udXBkYXRlX21hbnkoCiAgICAgICAgICAgIHsiX2lkIjogeyIkaW4iOiBhcnRpZmFjdF9pZHN9fSwKICAgICAgICAgICAgeyIkc2V0IjogeyJnZW51aW5lIjogRmFsc2UsICJoeWdpZW5lX3RhZyI6ICJyZWJ1aWxkX3YyODRfbGVnYWN5X2FydGlmYWN0In19LAogICAgICAgICkKICAgICAgICBwcmludChmIlxuW3N0ZXAxXSBmbGFnZ2VkIHtyZXMubW9kaWZpZWRfY291bnR9IGxlZ2FjeSBhcnRpZmFjdCByb3dzIGdlbnVpbmU9RmFsc2UiKQogICAgZWxzZToKICAgICAgICBwcmludChmIlxuW3N0ZXAxXSBXT1VMRCBmbGFnIHtsZW4oYXJ0aWZhY3RfaWRzKX0gbGVnYWN5IGFydGlmYWN0IHJvd3MgZ2VudWluZT1GYWxzZSIpCgojIOKUgOKUgCBTVEVQIDM6IHJlY29tcHV0ZSBzdHJhdGVneV9zdGF0cyBmb3IgZXZlcnkgc2V0dXAgZmFtaWx5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApiYXNlcyA9IHNvcnRlZCh7X2Jhc2Vfc2V0dXAocykgZm9yIHMgaW4gYW8uZGlzdGluY3QoInNldHVwX3R5cGUiKSBpZiBfYmFzZV9zZXR1cChzKX0pCnByaW50KGYiXG5bc3RlcDJdIHtsZW4oYmFzZXMpfSBzZXR1cCBmYW1pbGllcyB0byByZWNvbXB1dGU6IHtiYXNlc30iKQoKaWYgYXJncy5jb21taXQ6CiAgICByZWNvbXB1dGVkID0gMAogICAgZm9yIGIgaW4gYmFzZXM6CiAgICAgICAgZG9jID0gcG5sX2NvbXB1dGUucmVjb21wdXRlX3N0cmF0ZWd5X3N0YXRzX2Zvcl9zZXR1cChiLCBnZW51aW5lX29ubHk9VHJ1ZSkKICAgICAgICBpZiBkb2MgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJlY29tcHV0ZWQgKz0gMQogICAgcHJpbnQoZiJbc3RlcDJdIHJlY29tcHV0ZWQge3JlY29tcHV0ZWR9L3tsZW4oYmFzZXMpfSBmYW1pbGllcyIpCiAgICBldl90YWJsZSgiYWZ0ZXIiKQogICAgcHJpbnQoIlxu4pyFIENPTU1JVFRFRC4gUmVzdGFydCBiYWNrZW5kIHNvIFRRUyByZWxvYWRzIHN0cmF0ZWd5X3N0YXRzLiIpCmVsc2U6CiAgICAjIERyeS1ydW4gcHJldmlldzogY29tcHV0ZSAoaW4tbWVtb3J5KSB3aXRob3V0IHdyaXRpbmcgYnkgcmVhZGluZyBjdXJyZW50IHN0YXRlLgogICAgcHJpbnQoIlxuRFJZIFJVTiDigJQgbm90aGluZyB3cml0dGVuLiBSZS1ydW4gd2l0aCAtLWNvbW1pdCB0byBhcHBseS4iKQo=",
}

def _d(k):
    return base64.b64decode(_B64[k]).decode("utf-8")

HA_OLD, HA_NEW = _d("HA_OLD"), _d("HA_NEW")
HB_OLD, HB_NEW = _d("HB_OLD"), _d("HB_NEW")
REBUILD_SCRIPT = _d("REBUILD")

PNL_HUNKS = [("Hunk A (artifact-guard helper)", HA_OLD, HA_NEW),
             ("Hunk B (recompute filter)", HB_OLD, HB_NEW)]


def log(m):
    print(f"[v284-applier] {m}", flush=True)


def find_repo(explicit):
    if explicit:
        return explicit
    here = os.path.abspath(os.path.dirname(__file__))
    for base in (here, os.getcwd(), os.path.expanduser("~/Trading-and-Analysis-Platform")):
        cur = base
        for _ in range(6):
            if os.path.isfile(os.path.join(cur, "backend", "services", "pnl_compute.py")):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None, help="repo root containing backend/")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = find_repo(args.repo)
    if not repo:
        log("ERROR: could not locate repo root (backend/services/pnl_compute.py). Pass --repo.")
        return 2
    pnl_path = os.path.join(repo, "backend", "services", "pnl_compute.py")
    script_path = os.path.join(repo, "backend", "scripts", "rebuild_strategy_stats_v284.py")
    log(f"repo: {repo}")

    with open(pnl_path, "r", encoding="utf-8") as fh:
        content = fh.read()

    need_patch = MARKER not in content
    if not need_patch:
        log(f"pnl_compute.py already patched ('{MARKER}' present).")
    else:
        for name, old, _new in PNL_HUNKS:
            n = content.count(old)
            if n != 1:
                log(f"ERROR: {name} anchor matched {n} times (expected 1). Aborting - nothing written.")
                return 3
        for name, old, new in PNL_HUNKS:
            content = content.replace(old, new, 1)
            log(f"staged: {name}")
        if content.count(MARKER) < 1:
            log("ERROR: post-apply marker count too low. Aborting.")
            return 4

    if args.dry_run:
        log("DRY-RUN: pnl_compute hunks match and the rebuild script would be written. Nothing written.")
        return 0

    if need_patch:
        bak = f"{pnl_path}.bak.v284.{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(pnl_path, bak)
        log(f"backup: {bak}")
        with open(pnl_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        try:
            py_compile.compile(pnl_path, doraise=True)
            log("pnl_compute.py py_compile OK.")
        except py_compile.PyCompileError as e:
            log(f"ERROR: py_compile failed: {e}; restoring backup.")
            shutil.copy2(bak, pnl_path)
            return 5

    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write(REBUILD_SCRIPT)
    try:
        py_compile.compile(script_path, doraise=True)
        log(f"wrote + compiled: {script_path}")
    except py_compile.PyCompileError as e:
        log(f"ERROR: rebuild script py_compile failed: {e}")
        return 6

    log("SUCCESS - v19.34.284 applied.")
    log("NEXT: dry-run the rebuild, then --commit:")
    log(f"  .venv/bin/python {os.path.relpath(script_path, repo)}")
    log(f"  .venv/bin/python {os.path.relpath(script_path, repo)} --commit")
    log("Then restart the backend so TQS reloads strategy_stats.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
