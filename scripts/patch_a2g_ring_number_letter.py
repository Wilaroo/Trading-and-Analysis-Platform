#!/usr/bin/env python3
r"""
patch_a2g_ring_number_letter.py — UI Track A · A2g (v19.34.279).

Operator polish on the provenance ring:
  1) Ring center now shows the numeric TQS score WITH the grade letter beneath
     it (e.g. 58 / B), instead of number-only.
  2) Removes the now-redundant TQS badge chip from the scanner card header —
     the ring carries score + grade, so the header chip was duplicative.

2 files, FRONTEND-ONLY, presentational, idempotent, reversible (.a2gbak):
  WRITE  v5/ProvenanceRing.jsx   (stacked number + grade letter in center)
  EDIT   v5/ScannerCardsV5.jsx    (drop <TqsBadge/> from header + its import)

Runtime-verified (transpile+exec the component, 4/4 render). APPLIES ON TOP OF
A2f (v278). HASH GUARDS (v322t+):
  ProvenanceRing.jsx   PRE 29ad9c2a4fa9…  POST ef43a78596fe…
  ScannerCardsV5.jsx   PRE b7ff08ae52ec…  POST 18697ef6affc…

Usage (repo root):
    python3 scripts/patch_a2g_ring_number_letter.py --check
    python3 scripts/patch_a2g_ring_number_letter.py --apply
    python3 scripts/patch_a2g_ring_number_letter.py --rollback
After --apply:  cd frontend && yarn build   (then hard-refresh the cockpit)

On a PRE mismatch (drift) the patcher ABORTS — upload the live file(s); never --force.
"""
import os, sys, base64, shutil, hashlib, argparse

BAK = ".a2gbak"
PROVENANCE = "frontend/src/components/sentcom/v5/ProvenanceRing.jsx"
SCANNER = "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx"
PR_PRE_SHA = "29ad9c2a4fa9dcaa20ea2d3c6b6fc1ed2f178ec7aa62afc679981e9b6321d065"
PR_POST_SHA = "ef43a78596fedb70775ab71de65632fd8d36354cc7a280e600d73830e06dfb45"
SC_PRE_SHA = "b7ff08ae52ecdde5105eb30454746724a31aaeb2741f511a3b0e299f0e630e87"
SC_POST_SHA = "18697ef6affcee7567be4d049715e60e5a1873d3e30ef27878a4664dd9a9fa87"
PROVENANCE_B64 = "LyoqCiAqIFByb3ZlbmFuY2VSaW5nIOKAlCB2MTkuMzQuMjczIChVSSBUcmFjayBBIC8gQTIpIMK3IHYxOS4zNC4yNzYgc2NhbGFibGUgcmFpbAogKgogKiBDb21wYWN0IFNWRyAicHJvdmVuYW5jZSByaW5nIjogNSBlcXVhbCBhcmNzLCBvbmUgcGVyIFRRUyBwaWxsYXIKICogKHNldHVwIMK3IHRlY2huaWNhbCDCtyBmdW5kYW1lbnRhbCDCtyBjb250ZXh0IMK3IGV4ZWN1dGlvbiksIGVhY2ggY29sb3JlZCBieQogKiB0aGF0IHBpbGxhcidzIGdyYWRlLiBUaGUgb3ZlcmFsbCBUUVMgZ3JhZGUgbGV0dGVyIHNpdHMgaW4gdGhlIGNlbnRlci4KICoKICogSXQgYW5zd2VycyAid2hlcmUgZG9lcyB0aGlzIHNjb3JlIGNvbWUgZnJvbT8iIGF0IGEgZ2xhbmNlIOKAlCB0aGUKICogPFRxc0JhZGdlLz4gc3RpbGwgc2hvd3MgdGhlIHByZWNpc2UgbnVtYmVyOyB0aGlzIHNob3dzIGl0cyBjb21wb3NpdGlvbi4KICogQ2xpY2sgb3BlbnMgdGhlIHNoYXJlZCA8VHFzRHJpbGxEb3duRHJhd2VyLz4gKHZpYSB0cXNEcmF3ZXJCdXMpLgogKgogKiBSZW5kZXJzIG5vdGhpbmcgd2hlbiBubyBwZXItcGlsbGFyIGdyYWRlcyB3ZXJlIGNhcHR1cmVkIChsZWdhY3kgcm93cykuCiAqIERhdGEgc291cmNlOiBhbGVydC9wb3NpdGlvbiBgdHFzX3BpbGxhcl9ncmFkZXNgIChhc2RpY3QgZnJvbSB0aGUgYmFja2VuZCkuCiAqCiAqIFNpemluZzogcGFzcyBgc2l6ZWAgKHB4KSBmb3IgYSBmaXhlZCBiYWRnZSwgT1IgYGZpbGxgIHRvIG1ha2UgdGhlIFNWRyBmaWxsCiAqIGl0cyBwYXJlbnQgKDEwMCUgw5cgMTAwJSkgc28gdGhlIGNhbGxlciBjYW4gc2NhbGUgaXQgdG8gZS5nLiBmdWxsIGNhcmQKICogaGVpZ2h0LiBHZW9tZXRyeSB1c2VzIGEgZml4ZWQgMTAww5cxMDAgbm9taW5hbCBjb29yZGluYXRlIHNwYWNlIHNvIGFyY3MsCiAqIHN0cm9rZSBhbmQgdGhlIGNlbnRlciBsZXR0ZXIgc2NhbGUgcHJvcG9ydGlvbmFsbHkgYXQgYW55IHJlbmRlcmVkIHNpemUuCiAqLwppbXBvcnQgUmVhY3QgZnJvbSAncmVhY3QnOwoKaW1wb3J0IHsgb3BlblRxc0RyYXdlciB9IGZyb20gJy4vdHFzRHJhd2VyQnVzJzsKaW1wb3J0IHsgZ3JhZGVGcm9tU2NvcmUgfSBmcm9tICcuL1Rxc0JhZGdlJzsKCi8vIENhbm9uaWNhbCBwaWxsYXIgb3JkZXIg4oCUIG1hdGNoZXMgc2VydmljZXMvdHFzL3Rxc19lbmdpbmUucHkgKyBUcXNQaWxsYXJQYW5lbC4KY29uc3QgUElMTEFSX09SREVSID0gWydzZXR1cCcsICd0ZWNobmljYWwnLCAnZnVuZGFtZW50YWwnLCAnY29udGV4dCcsICdleGVjdXRpb24nXTsKY29uc3QgUElMTEFSX0xBQkVMID0gewogIHNldHVwOiAnU2V0dXAnLAogIHRlY2huaWNhbDogJ1RlY2huaWNhbCcsCiAgZnVuZGFtZW50YWw6ICdGdW5kYW1lbnRhbCcsCiAgY29udGV4dDogJ0NvbnRleHQnLAogIGV4ZWN1dGlvbjogJ0V4ZWN1dGlvbicsCn07CgovLyBHcmFkZSDihpIgc3Ryb2tlIGNvbG9yIChtaXJyb3JzIFRxc0JhZGdlLmdyYWRlVG9uZSBmYW1pbGllcykuCi8vIENob3NlbiBzbyBldmVyeSBiYW5kIGlzIGNsZWFybHkgZGlzdGluZ3Vpc2hhYmxlIG9uIHRoZSBkYXJrIGNhcmQg4oCUIGluCi8vIHBhcnRpY3VsYXIgQyAoeWVsbG93KSB2cyBEIChvcmFuZ2UpLCB3aGljaCBwcmV2aW91c2x5IHJlYWQgYXMgb25lIGNvbG9yLgpjb25zdCBHUkFERV9TVFJPS0UgPSB7CiAgJ0ErJzogJyMyMmM1NWUnLCBBOiAnIzIyYzU1ZScsIC8vIGdyZWVuLTUwMAogICdCKyc6ICcjMzhiZGY4JywgQjogJyMzOGJkZjgnLCAvLyBza3ktNDAwCiAgJ0MrJzogJyNmYWNjMTUnLCBDOiAnI2ZhY2MxNScsIC8vIHllbGxvdy00MDAgKGNsZWFybHkgeWVsbG93KQogIEQ6ICcjZjk3MzE2JywgICAgICAgICAgICAgICAgICAvLyBvcmFuZ2UtNTAwIChjbGVhcmx5IG9yYW5nZSkKICBGOiAnI2VmNDQ0NCcsICAgICAgICAgICAgICAgICAgLy8gcmVkLTUwMAp9Owpjb25zdCBNSVNTSU5HID0gJyM1MjUyNWInOyAvLyB6aW5jLTYwMCDigJQgdmlzaWJsZSBuZXV0cmFsIGFyYyBmb3IgYW4gdW5ncmFkZWQgcGlsbGFyCmNvbnN0IHN0cm9rZUZvciA9IChnKSA9PiBHUkFERV9TVFJPS0VbU3RyaW5nKGcgfHwgJycpLnRvVXBwZXJDYXNlKCldIHx8IE1JU1NJTkc7Cgpjb25zdCBwb2xhciA9IChjeCwgY3ksIHIsIGRlZykgPT4gewogIGNvbnN0IGEgPSAoKGRlZyAtIDkwKSAqIE1hdGguUEkpIC8gMTgwOwogIHJldHVybiBbY3ggKyByICogTWF0aC5jb3MoYSksIGN5ICsgciAqIE1hdGguc2luKGEpXTsKfTsKY29uc3QgYXJjUGF0aCA9IChjeCwgY3ksIHIsIHN0YXJ0RGVnLCBlbmREZWcpID0+IHsKICBjb25zdCBbeDEsIHkxXSA9IHBvbGFyKGN4LCBjeSwgciwgc3RhcnREZWcpOwogIGNvbnN0IFt4MiwgeTJdID0gcG9sYXIoY3gsIGN5LCByLCBlbmREZWcpOwogIGNvbnN0IGxhcmdlID0gZW5kRGVnIC0gc3RhcnREZWcgPiAxODAgPyAxIDogMDsKICByZXR1cm4gYE0gJHt4MS50b0ZpeGVkKDIpfSAke3kxLnRvRml4ZWQoMil9IEEgJHtyfSAke3J9IDAgJHtsYXJnZX0gMSAke3gyLnRvRml4ZWQoMil9ICR7eTIudG9GaXhlZCgyKX1gOwp9OwoKLyoqCiAqIFByb3BzOgogKiAgIHN5bWJvbCwgc291cmNlICAgICAgICAgICA6IGZvciB0aGUgZHJhd2VyCiAqICAgcGlsbGFyR3JhZGVzICAgICAgICAgICAgIDogeyBzZXR1cCwgdGVjaG5pY2FsLCBmdW5kYW1lbnRhbCwgY29udGV4dCwgZXhlY3V0aW9uIH0KICogICBncmFkZSAgICAgICAgICAgICAgICAgICAgOiBvdmVyYWxsIFRRUyBncmFkZSAoY2VudGVyIGxldHRlcik7IGZhbGxzIGJhY2sgdG8gc2NvcmUKICogICBzY29yZSAgICAgICAgICAgICAgICAgICAgOiBvdmVyYWxsIFRRUyBzY29yZSAodXNlZCBpZiBncmFkZSBtaXNzaW5nKQogKiAgIHNpemUgICAgICAgICAgICAgICAgICAgICA6IHB4IGRpYW1ldGVyIChkZWZhdWx0IDI4KSDigJQgaWdub3JlZCB3aGVuIGBmaWxsYAogKiAgIGZpbGwgICAgICAgICAgICAgICAgICAgICA6IHdoZW4gdHJ1ZSB0aGUgU1ZHIGZpbGxzIGl0cyBwYXJlbnQgKDEwMCUgw5cgMTAwJSkKICogICBjbGFzc05hbWUgICAgICAgICAgICAgICAgOiBleHRyYSBjbGFzc2VzIG9uIHRoZSBidXR0b24gKHNpemluZyBpbiBmaWxsIG1vZGUpCiAqICAgdGVzdElkU3VmZml4CiAqLwpleHBvcnQgZGVmYXVsdCBmdW5jdGlvbiBQcm92ZW5hbmNlUmluZyh7CiAgc3ltYm9sLAogIHNvdXJjZSA9ICdhbGVydCcsCiAgcGlsbGFyR3JhZGVzLAogIGdyYWRlID0gJycsCiAgc2NvcmUgPSBudWxsLAogIHNpemUgPSAyOCwKICBmaWxsID0gZmFsc2UsCiAgY2xhc3NOYW1lID0gJycsCiAgdGVzdElkU3VmZml4LAp9KSB7CiAgY29uc3QgZ3JhZGVzID0gcGlsbGFyR3JhZGVzICYmIHR5cGVvZiBwaWxsYXJHcmFkZXMgPT09ICdvYmplY3QnID8gcGlsbGFyR3JhZGVzIDogbnVsbDsKICBjb25zdCBoYXNBbnkgPSBncmFkZXMgJiYgUElMTEFSX09SREVSLnNvbWUoKGspID0+IGdyYWRlc1trXSk7CiAgaWYgKCFoYXNBbnkpIHJldHVybiBudWxsOwoKICBjb25zdCBjZW50ZXJHcmFkZSA9IFN0cmluZyhncmFkZSB8fCAoc2NvcmUgIT0gbnVsbCA/IGdyYWRlRnJvbVNjb3JlKHNjb3JlKSA6ICcnKSB8fCAnJykudG9VcHBlckNhc2UoKTsKICAvLyBGaXhlZCAxMDDDlzEwMCBub21pbmFsIHNwYWNlIOKGkiByaW5nIHNjYWxlcyBjbGVhbmx5IHZpYSBDU1MgKGZpeGVkIGBzaXplYAogIC8vIHB4IE9SIGBmaWxsYCA9IDEwMCUgb2YgaXRzIGNvbnRhaW5lcikuCiAgY29uc3QgTk9NID0gMTAwOwogIGNvbnN0IHN3ID0gTk9NICogMC4xMTsKICBjb25zdCBjID0gTk9NIC8gMjsKICBjb25zdCByID0gYyAtIHN3IC8gMiAtIDAuNTsKICBjb25zdCBnYXAgPSA5OyAvLyBkZWdyZWVzIGJldHdlZW4gc2VnbWVudHMKICBjb25zdCBzZWcgPSAzNjAgLyBQSUxMQVJfT1JERVIubGVuZ3RoOwogIGNvbnN0IHRlc3RJZCA9IGBwcm92ZW5hbmNlLXJpbmcke3Rlc3RJZFN1ZmZpeCA/IGAtJHt0ZXN0SWRTdWZmaXh9YCA6ICcnfWA7CiAgY29uc3Qgc3ZnRGltID0gZmlsbCA/ICcxMDAlJyA6IHNpemU7CiAgLy8gQ2VudGVyIHNob3dzIHRoZSBudW1lcmljIFRRUyBzY29yZSAodGhlICJUUVMgbnVtYmVyIikgd2hlbiBhdmFpbGFibGUsIHNvCiAgLy8gdGhlIHJpbmcgaXMgc2VsZi1leHBsYW5hdG9yeTsgdGhlIGdyYWRlIGxldHRlciBzdGlsbCBsaXZlcyBvbiB0aGUgY2hpcC4KICAvLyBGYWxscyBiYWNrIHRvIHRoZSBncmFkZSBsZXR0ZXIgZm9yIHJvd3MgdGhhdCBvbmx5IGNhcnJ5IGEgZ3JhZGUuCiAgY29uc3QgaGFzU2NvcmUgPSBzY29yZSAhPSBudWxsICYmICFOdW1iZXIuaXNOYU4oTnVtYmVyKHNjb3JlKSk7CiAgY29uc3QgY2VudGVyVGV4dCA9IGhhc1Njb3JlID8gU3RyaW5nKE1hdGgucm91bmQoTnVtYmVyKHNjb3JlKSkpIDogY2VudGVyR3JhZGU7CiAgY29uc3QgY2VudGVyRm9udCA9IGNlbnRlclRleHQubGVuZ3RoID49IDMgPyBOT00gKiAwLjI2IDogTk9NICogMC4zNDsKCiAgY29uc3QgdGl0bGUgPQogICAgJ1Byb3ZlbmFuY2Ug4oCUICcgKwogICAgUElMTEFSX09SREVSLm1hcCgoaykgPT4gYCR7UElMTEFSX0xBQkVMW2tdfSAke2dyYWRlc1trXSB8fCAn4oCUJ31gKS5qb2luKCcgwrcgJyk7CgogIGNvbnN0IGhhbmRsZUNsaWNrID0gKGUpID0+IHsKICAgIGUuc3RvcFByb3BhZ2F0aW9uKCk7CiAgICBpZiAoc3ltYm9sKSBvcGVuVHFzRHJhd2VyKHsgc3ltYm9sLCBzb3VyY2UgfSk7CiAgfTsKCiAgcmV0dXJuICgKICAgIDxidXR0b24KICAgICAgdHlwZT0iYnV0dG9uIgogICAgICBkYXRhLXRlc3RpZD17dGVzdElkfQogICAgICBvbkNsaWNrPXtoYW5kbGVDbGlja30KICAgICAgdGl0bGU9e3RpdGxlfQogICAgICBhcmlhLWxhYmVsPXt0aXRsZX0KICAgICAgY2xhc3NOYW1lPXtgc2hyaW5rLTAgcm91bmRlZC1mdWxsIHRyYW5zaXRpb24tdHJhbnNmb3JtIGhvdmVyOnNjYWxlLTEwNSBmb2N1czpvdXRsaW5lLW5vbmUgJHtjbGFzc05hbWV9YH0KICAgICAgc3R5bGU9e2ZpbGwgPyB7IGxpbmVIZWlnaHQ6IDAgfSA6IHsgd2lkdGg6IHNpemUsIGhlaWdodDogc2l6ZSwgbGluZUhlaWdodDogMCB9fQogICAgPgogICAgICA8c3ZnIHdpZHRoPXtzdmdEaW19IGhlaWdodD17c3ZnRGltfSB2aWV3Qm94PXtgMCAwICR7Tk9NfSAke05PTX1gfSBzdHlsZT17eyBkaXNwbGF5OiAnYmxvY2snIH19PgogICAgICAgIHsvKiB0cmFjayAqL30KICAgICAgICA8Y2lyY2xlIGN4PXtjfSBjeT17Y30gcj17cn0gZmlsbD0ibm9uZSIgc3Ryb2tlPSIjMTgxODFiIiBzdHJva2VXaWR0aD17c3d9IC8+CiAgICAgICAgey8qIHBpbGxhciBhcmNzICovfQogICAgICAgIHtQSUxMQVJfT1JERVIubWFwKChrLCBpKSA9PiB7CiAgICAgICAgICBjb25zdCBzdGFydCA9IGkgKiBzZWcgKyBnYXAgLyAyOwogICAgICAgICAgY29uc3QgZW5kID0gKGkgKyAxKSAqIHNlZyAtIGdhcCAvIDI7CiAgICAgICAgICByZXR1cm4gKAogICAgICAgICAgICA8cGF0aAogICAgICAgICAgICAgIGtleT17a30KICAgICAgICAgICAgICBkPXthcmNQYXRoKGMsIGMsIHIsIHN0YXJ0LCBlbmQpfQogICAgICAgICAgICAgIGZpbGw9Im5vbmUiCiAgICAgICAgICAgICAgc3Ryb2tlPXtzdHJva2VGb3IoZ3JhZGVzW2tdKX0KICAgICAgICAgICAgICBzdHJva2VXaWR0aD17c3d9CiAgICAgICAgICAgICAgc3Ryb2tlTGluZWNhcD0icm91bmQiCiAgICAgICAgICAgICAgZGF0YS1waWxsYXI9e2t9CiAgICAgICAgICAgICAgZGF0YS1ncmFkZT17Z3JhZGVzW2tdIHx8ICcnfQogICAgICAgICAgICAvPgogICAgICAgICAgKTsKICAgICAgICB9KX0KICAgICAgICB7LyogY2VudGVyOiBudW1lcmljIFRRUyBzY29yZSB3aXRoIHRoZSBncmFkZSBsZXR0ZXIgYmVuZWF0aCBpdCAod2hlbgogICAgICAgICAgICBib3RoIGFyZSBrbm93bik7IGdyYWRlLW9ubHkgcm93cyBzaG93IGp1c3QgdGhlIGxldHRlciwgY2VudGVyZWQuICovfQogICAgICAgIHtoYXNTY29yZSA/ICgKICAgICAgICAgIDw+CiAgICAgICAgICAgIDx0ZXh0CiAgICAgICAgICAgICAgeD17Y30KICAgICAgICAgICAgICB5PXtjIC0gTk9NICogMC4wOX0KICAgICAgICAgICAgICB0ZXh0QW5jaG9yPSJtaWRkbGUiCiAgICAgICAgICAgICAgZG9taW5hbnRCYXNlbGluZT0iY2VudHJhbCIKICAgICAgICAgICAgICBmb250U2l6ZT17Y2VudGVyRm9udH0KICAgICAgICAgICAgICBmb250V2VpZ2h0PSI3MDAiCiAgICAgICAgICAgICAgZmlsbD17c3Ryb2tlRm9yKGNlbnRlckdyYWRlKX0KICAgICAgICAgICAgICBmb250RmFtaWx5PSJ1aS1tb25vc3BhY2UsIFNGTW9uby1SZWd1bGFyLCBNZW5sbywgbW9ub3NwYWNlIgogICAgICAgICAgICA+CiAgICAgICAgICAgICAge2NlbnRlclRleHR9CiAgICAgICAgICAgIDwvdGV4dD4KICAgICAgICAgICAge2NlbnRlckdyYWRlICYmICgKICAgICAgICAgICAgICA8dGV4dAogICAgICAgICAgICAgICAgeD17Y30KICAgICAgICAgICAgICAgIHk9e2MgKyBOT00gKiAwLjIyfQogICAgICAgICAgICAgICAgdGV4dEFuY2hvcj0ibWlkZGxlIgogICAgICAgICAgICAgICAgZG9taW5hbnRCYXNlbGluZT0iY2VudHJhbCIKICAgICAgICAgICAgICAgIGZvbnRTaXplPXtOT00gKiAwLjIyfQogICAgICAgICAgICAgICAgZm9udFdlaWdodD0iNzAwIgogICAgICAgICAgICAgICAgZmlsbD17c3Ryb2tlRm9yKGNlbnRlckdyYWRlKX0KICAgICAgICAgICAgICAgIG9wYWNpdHk9IjAuOSIKICAgICAgICAgICAgICAgIGZvbnRGYW1pbHk9InVpLW1vbm9zcGFjZSwgU0ZNb25vLVJlZ3VsYXIsIE1lbmxvLCBtb25vc3BhY2UiCiAgICAgICAgICAgICAgPgogICAgICAgICAgICAgICAge2NlbnRlckdyYWRlfQogICAgICAgICAgICAgIDwvdGV4dD4KICAgICAgICAgICAgKX0KICAgICAgICAgIDwvPgogICAgICAgICkgOiAoCiAgICAgICAgICBjZW50ZXJUZXh0ICYmICgKICAgICAgICAgICAgPHRleHQKICAgICAgICAgICAgICB4PXtjfQogICAgICAgICAgICAgIHk9e2N9CiAgICAgICAgICAgICAgdGV4dEFuY2hvcj0ibWlkZGxlIgogICAgICAgICAgICAgIGRvbWluYW50QmFzZWxpbmU9ImNlbnRyYWwiCiAgICAgICAgICAgICAgZm9udFNpemU9e05PTSAqIDAuNDB9CiAgICAgICAgICAgICAgZm9udFdlaWdodD0iNzAwIgogICAgICAgICAgICAgIGZpbGw9e3N0cm9rZUZvcihjZW50ZXJHcmFkZSl9CiAgICAgICAgICAgICAgZm9udEZhbWlseT0idWktbW9ub3NwYWNlLCBTRk1vbm8tUmVndWxhciwgTWVubG8sIG1vbm9zcGFjZSIKICAgICAgICAgICAgPgogICAgICAgICAgICAgIHtjZW50ZXJUZXh0fQogICAgICAgICAgICA8L3RleHQ+CiAgICAgICAgICApCiAgICAgICAgKX0KICAgICAgPC9zdmc+CiAgICA8L2J1dHRvbj4KICApOwp9Cg=="
SCANNER_CHUNKS = [
    ("aW1wb3J0IFRxc0JhZGdlIGZyb20gJy4vVHFzQmFkZ2UnOw==",
     "Ly8gdjE5LjM0LjI3OSDigJQgVFFTIGJhZGdlIHJlbW92ZWQgZnJvbSB0aGUgc2Nhbm5lciBjYXJkIGhlYWRlciAodGhlIHByb3ZlbmFuY2UKLy8gcmluZyBub3cgY2FycmllcyBzY29yZSArIGdyYWRlKS4gVHFzQmFkZ2UgaW1wb3J0IGRyb3BwZWQu"),
    ("ICAgICAgICAgIHsvKiB2MTkuMzQuMjU4IOKAlCBzaW5nbGUgdHJ1c3RlZCBUUVMgc2NvcmUgb24gdGhlIGZhY2U7IGNsaWNrCiAgICAgICAgICAgICAgb3BlbnMgdGhlIGNvbnNvbGlkYXRlZCBkcmlsbC1kb3duIGRyYXdlci4gUmVwbGFjZXMgdGhlIG9sZAogICAgICAgICAgICAgIFNldHVwR3JhZGVDaGlwIC8gU01CIHNjYXR0ZXIuICovfQogICAgICAgICAgPFRxc0JhZGdlCiAgICAgICAgICAgIHN5bWJvbD17Y2FyZC5zeW1ib2x9CiAgICAgICAgICAgIHNjb3JlPXtjYXJkLnRxc19zY29yZX0KICAgICAgICAgICAgZ3JhZGVGYWxsYmFjaz17Y2FyZC50cXNfZ3JhZGV9CiAgICAgICAgICAgIHNvdXJjZT17Y2FyZC5zb3VyY2UgfHwgJ2FsZXJ0J30KICAgICAgICAgICAgdGVzdElkU3VmZml4PXtgc2Nhbm5lci0ke2NhcmQuc3ltYm9sfWB9CiAgICAgICAgICAvPgogICAgICAgICAgey8qIHYxOS4zNC4yNzIgKFVJIFRyYWNrIEEgLyBQMSkg4oCUIGdyYWRpbmcgc3R5bGUgVFFTIHNjb3JlZCB3aXRo",
     "ICAgICAgICAgIHsvKiB2MTkuMzQuMjc5IChVSSBUcmFjayBBIC8gQTJnKSDigJQgaGVhZGVyIFRRUyBiYWRnZSByZW1vdmVkOyB0aGUKICAgICAgICAgICAgICBwcm92ZW5hbmNlIHJpbmcgbm93IHNob3dzIHRoZSBzY29yZSArIGdyYWRlLCBzbyB0aGUgY2hpcCB3YXMKICAgICAgICAgICAgICByZWR1bmRhbnQgb24gdGhlIGNhcmQgZmFjZS4gKi99CiAgICAgICAgICB7LyogdjE5LjM0LjI3MiAoVUkgVHJhY2sgQSAvIFAxKSDigJQgZ3JhZGluZyBzdHlsZSBUUVMgc2NvcmVkIHdpdGg=")
]


def sha_full(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..")):
        c = os.path.abspath(os.path.join(base, path))
        if os.path.exists(c):
            return c
    return os.path.abspath(os.path.join(".", path))


def dec(x):
    return base64.b64decode(x).decode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--rollback", action="store_true")
    a = ap.parse_args()

    print("=" * 84)
    print("  A2g PATCH — ring center number+letter & remove header TQS chip")
    print("  mode:", "CHECK" if a.check else "APPLY" if a.apply else "ROLLBACK")
    print("=" * 84)

    pr, sc = resolve(PROVENANCE), resolve(SCANNER)
    for p, n in ((pr, PROVENANCE), (sc, SCANNER)):
        if not os.path.exists(p):
            print("  MISSING FILE:", n)
            sys.exit(2)

    if a.rollback:
        for p, n in ((pr, PROVENANCE), (sc, SCANNER)):
            if os.path.exists(p + BAK):
                shutil.copy2(p + BAK, p)
                print("  restored", n, "sha=" + sha_full(p)[:12])
        print("\n  ROLLBACK complete.  NEXT: cd frontend && yarn build")
        return

    pr_sha, sc_sha = sha_full(pr), sha_full(sc)
    pr_state = "ALREADY-APPLIED" if pr_sha == PR_POST_SHA else ("READY" if pr_sha == PR_PRE_SHA else "DRIFT")
    sc_state = "ALREADY-APPLIED" if sc_sha == SC_POST_SHA else ("READY" if sc_sha == SC_PRE_SHA else "DRIFT")
    print("\n  ProvenanceRing.jsx  sha=%s  state=%s" % (pr_sha[:12], pr_state))
    print("  ScannerCardsV5.jsx  sha=%s  state=%s" % (sc_sha[:12], sc_state))

    drift = [n for n, s in ((PROVENANCE, pr_state), (SCANNER, sc_state)) if s == "DRIFT"]
    if drift:
        print("\n  DRIFT: file(s) match neither PRE nor POST. Do NOT --force.")
        for n in drift:
            print("     upload:  curl --data-binary @%s https://paste.rs/" % n)
        sys.exit(3)

    if sc_state == "READY":
        cur = open(sc, encoding="utf-8").read()
        for i, (ob, _nb) in enumerate(SCANNER_CHUNKS, 1):
            if cur.count(dec(ob)) != 1:
                print("  ScannerCardsV5 chunk %d anchor not unique — ABORT." % i)
                sys.exit(3)

    if a.check:
        nready = sum(1 for s in (pr_state, sc_state) if s == "READY")
        print("\n  CHECK ok. %d file(s) ready. Re-run with --apply." % nready)
        return

    changed = 0
    if pr_state == "READY":
        if not os.path.exists(pr + BAK):
            shutil.copy2(pr, pr + BAK)
        open(pr, "w", encoding="utf-8").write(dec(PROVENANCE_B64))
        got = sha_full(pr)
        print("  wrote ProvenanceRing.jsx  sha=%s  %s" % (got[:12], "POST OK" if got == PR_POST_SHA else "MISMATCH"))
        if got != PR_POST_SHA:
            sys.exit(5)
        changed += 1
    else:
        print("  skip ProvenanceRing.jsx (already applied)")

    if sc_state == "READY":
        if not os.path.exists(sc + BAK):
            shutil.copy2(sc, sc + BAK)
        cur = open(sc, encoding="utf-8").read()
        for ob, nb in SCANNER_CHUNKS:
            cur = cur.replace(dec(ob), dec(nb), 1)
        open(sc, "w", encoding="utf-8").write(cur)
        got = sha_full(sc)
        print("  patched ScannerCardsV5.jsx  sha=%s  %s" % (got[:12], "POST OK" if got == SC_POST_SHA else "MISMATCH"))
        if got != SC_POST_SHA:
            sys.exit(5)
        changed += 1
    else:
        print("  skip ScannerCardsV5.jsx (already applied)")

    print("\n  APPLY complete. %d file(s)." % changed)
    print("  NEXT: cd frontend && yarn build   (then hard-refresh the cockpit)")


if __name__ == "__main__":
    main()
