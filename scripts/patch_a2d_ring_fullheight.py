#!/usr/bin/env python3
r"""
patch_a2d_ring_fullheight.py — UI Track A · A2 polish (v19.34.276).

Makes the scanner-card provenance ring legible. It was a cramped 28px inline
chip ("can hardly see the detail"). Now promoted to a FULL-HEIGHT left rail on
each card (capped ~88px) so the 5 pillar arcs + center TQS grade are readable
at a glance. Purely presentational — no data/behaviour change.

2 files, FRONTEND-ONLY, idempotent, reversible (.a2dbak backups):
  WRITE  v5/ProvenanceRing.jsx   (scalable: 100x100 nominal viewBox + `fill` mode)
  EDIT   v5/ScannerCardsV5.jsx    (2 anchored chunks: ring rail + content column)

APPLIES ON TOP OF A2c (v274) + A2b (v275). HASH GUARDS (v322t+ convention).
Usage (repo root):
    python3 scripts/patch_a2d_ring_fullheight.py --check
    python3 scripts/patch_a2d_ring_fullheight.py --apply
    python3 scripts/patch_a2d_ring_fullheight.py --rollback
After --apply:  cd frontend && yarn build   (then hard-refresh the cockpit)

On a PRE mismatch (DGX drift) the patcher ABORTS — upload the live file(s) so
the change can be rebased; never --force.
"""
import os, sys, base64, shutil, hashlib, argparse

BAK = ".a2dbak"
PROVENANCE = "frontend/src/components/sentcom/v5/ProvenanceRing.jsx"
SCANNER = "frontend/src/components/sentcom/v5/ScannerCardsV5.jsx"

PR_PRE_SHA = "3c3e8f98c107333610bbbe14d2b08002d0be95df2246f3299cb772fbde00f8aa"
PR_POST_SHA = "87871429d9c87172bd642b2001434c5ab7ea43ff521d3802d16c9600737052e0"
SC_PRE_SHA = "605bb2993cfe0197815e212aa733a279223b6dabd02cdb5d0a1a67bfbb1543e0"
SC_POST_SHA = "b7ff08ae52ecdde5105eb30454746724a31aaeb2741f511a3b0e299f0e630e87"

PROVENANCE_B64 = "LyoqCiAqIFByb3ZlbmFuY2VSaW5nIOKAlCB2MTkuMzQuMjczIChVSSBUcmFjayBBIC8gQTIpIMK3IHYxOS4zNC4yNzYgc2NhbGFibGUgcmFpbAogKgogKiBDb21wYWN0IFNWRyAicHJvdmVuYW5jZSByaW5nIjogNSBlcXVhbCBhcmNzLCBvbmUgcGVyIFRRUyBwaWxsYXIKICogKHNldHVwIMK3IHRlY2huaWNhbCDCtyBmdW5kYW1lbnRhbCDCtyBjb250ZXh0IMK3IGV4ZWN1dGlvbiksIGVhY2ggY29sb3JlZCBieQogKiB0aGF0IHBpbGxhcidzIGdyYWRlLiBUaGUgb3ZlcmFsbCBUUVMgZ3JhZGUgbGV0dGVyIHNpdHMgaW4gdGhlIGNlbnRlci4KICoKICogSXQgYW5zd2VycyAid2hlcmUgZG9lcyB0aGlzIHNjb3JlIGNvbWUgZnJvbT8iIGF0IGEgZ2xhbmNlIOKAlCB0aGUKICogPFRxc0JhZGdlLz4gc3RpbGwgc2hvd3MgdGhlIHByZWNpc2UgbnVtYmVyOyB0aGlzIHNob3dzIGl0cyBjb21wb3NpdGlvbi4KICogQ2xpY2sgb3BlbnMgdGhlIHNoYXJlZCA8VHFzRHJpbGxEb3duRHJhd2VyLz4gKHZpYSB0cXNEcmF3ZXJCdXMpLgogKgogKiBSZW5kZXJzIG5vdGhpbmcgd2hlbiBubyBwZXItcGlsbGFyIGdyYWRlcyB3ZXJlIGNhcHR1cmVkIChsZWdhY3kgcm93cykuCiAqIERhdGEgc291cmNlOiBhbGVydC9wb3NpdGlvbiBgdHFzX3BpbGxhcl9ncmFkZXNgIChhc2RpY3QgZnJvbSB0aGUgYmFja2VuZCkuCiAqCiAqIFNpemluZzogcGFzcyBgc2l6ZWAgKHB4KSBmb3IgYSBmaXhlZCBiYWRnZSwgT1IgYGZpbGxgIHRvIG1ha2UgdGhlIFNWRyBmaWxsCiAqIGl0cyBwYXJlbnQgKDEwMCUgw5cgMTAwJSkgc28gdGhlIGNhbGxlciBjYW4gc2NhbGUgaXQgdG8gZS5nLiBmdWxsIGNhcmQKICogaGVpZ2h0LiBHZW9tZXRyeSB1c2VzIGEgZml4ZWQgMTAww5cxMDAgbm9taW5hbCBjb29yZGluYXRlIHNwYWNlIHNvIGFyY3MsCiAqIHN0cm9rZSBhbmQgdGhlIGNlbnRlciBsZXR0ZXIgc2NhbGUgcHJvcG9ydGlvbmFsbHkgYXQgYW55IHJlbmRlcmVkIHNpemUuCiAqLwppbXBvcnQgUmVhY3QgZnJvbSAncmVhY3QnOwoKaW1wb3J0IHsgb3BlblRxc0RyYXdlciB9IGZyb20gJy4vdHFzRHJhd2VyQnVzJzsKaW1wb3J0IHsgZ3JhZGVGcm9tU2NvcmUgfSBmcm9tICcuL1Rxc0JhZGdlJzsKCi8vIENhbm9uaWNhbCBwaWxsYXIgb3JkZXIg4oCUIG1hdGNoZXMgc2VydmljZXMvdHFzL3Rxc19lbmdpbmUucHkgKyBUcXNQaWxsYXJQYW5lbC4KY29uc3QgUElMTEFSX09SREVSID0gWydzZXR1cCcsICd0ZWNobmljYWwnLCAnZnVuZGFtZW50YWwnLCAnY29udGV4dCcsICdleGVjdXRpb24nXTsKY29uc3QgUElMTEFSX0xBQkVMID0gewogIHNldHVwOiAnU2V0dXAnLAogIHRlY2huaWNhbDogJ1RlY2huaWNhbCcsCiAgZnVuZGFtZW50YWw6ICdGdW5kYW1lbnRhbCcsCiAgY29udGV4dDogJ0NvbnRleHQnLAogIGV4ZWN1dGlvbjogJ0V4ZWN1dGlvbicsCn07CgovLyBHcmFkZSDihpIgc3Ryb2tlIGNvbG9yIChtaXJyb3JzIFRxc0JhZGdlLmdyYWRlVG9uZSBmYW1pbGllcykuCmNvbnN0IEdSQURFX1NUUk9LRSA9IHsKICAnQSsnOiAnIzEwYjk4MScsIEE6ICcjMTBiOTgxJywKICAnQisnOiAnIzBlYTVlOScsIEI6ICcjMGVhNWU5JywKICAnQysnOiAnI2Y1OWUwYicsIEM6ICcjZjU5ZTBiJywKICBEOiAnI2Y5NzMxNicsCiAgRjogJyNmNDNmNWUnLAp9Owpjb25zdCBNSVNTSU5HID0gJyMzZjNmNDYnOyAvLyB6aW5jLTcwMCDigJQgcGlsbGFyIHdpdGggbm8gZ3JhZGUKY29uc3Qgc3Ryb2tlRm9yID0gKGcpID0+IEdSQURFX1NUUk9LRVtTdHJpbmcoZyB8fCAnJykudG9VcHBlckNhc2UoKV0gfHwgTUlTU0lORzsKCmNvbnN0IHBvbGFyID0gKGN4LCBjeSwgciwgZGVnKSA9PiB7CiAgY29uc3QgYSA9ICgoZGVnIC0gOTApICogTWF0aC5QSSkgLyAxODA7CiAgcmV0dXJuIFtjeCArIHIgKiBNYXRoLmNvcyhhKSwgY3kgKyByICogTWF0aC5zaW4oYSldOwp9Owpjb25zdCBhcmNQYXRoID0gKGN4LCBjeSwgciwgc3RhcnREZWcsIGVuZERlZykgPT4gewogIGNvbnN0IFt4MSwgeTFdID0gcG9sYXIoY3gsIGN5LCByLCBzdGFydERlZyk7CiAgY29uc3QgW3gyLCB5Ml0gPSBwb2xhcihjeCwgY3ksIHIsIGVuZERlZyk7CiAgY29uc3QgbGFyZ2UgPSBlbmREZWcgLSBzdGFydERlZyA+IDE4MCA/IDEgOiAwOwogIHJldHVybiBgTSAke3gxLnRvRml4ZWQoMil9ICR7eTEudG9GaXhlZCgyKX0gQSAke3J9ICR7cn0gMCAke2xhcmdlfSAxICR7eDIudG9GaXhlZCgyKX0gJHt5Mi50b0ZpeGVkKDIpfWA7Cn07CgovKioKICogUHJvcHM6CiAqICAgc3ltYm9sLCBzb3VyY2UgICAgICAgICAgIDogZm9yIHRoZSBkcmF3ZXIKICogICBwaWxsYXJHcmFkZXMgICAgICAgICAgICAgOiB7IHNldHVwLCB0ZWNobmljYWwsIGZ1bmRhbWVudGFsLCBjb250ZXh0LCBleGVjdXRpb24gfQogKiAgIGdyYWRlICAgICAgICAgICAgICAgICAgICA6IG92ZXJhbGwgVFFTIGdyYWRlIChjZW50ZXIgbGV0dGVyKTsgZmFsbHMgYmFjayB0byBzY29yZQogKiAgIHNjb3JlICAgICAgICAgICAgICAgICAgICA6IG92ZXJhbGwgVFFTIHNjb3JlICh1c2VkIGlmIGdyYWRlIG1pc3NpbmcpCiAqICAgc2l6ZSAgICAgICAgICAgICAgICAgICAgIDogcHggZGlhbWV0ZXIgKGRlZmF1bHQgMjgpIOKAlCBpZ25vcmVkIHdoZW4gYGZpbGxgCiAqICAgZmlsbCAgICAgICAgICAgICAgICAgICAgIDogd2hlbiB0cnVlIHRoZSBTVkcgZmlsbHMgaXRzIHBhcmVudCAoMTAwJSDDlyAxMDAlKQogKiAgIGNsYXNzTmFtZSAgICAgICAgICAgICAgICA6IGV4dHJhIGNsYXNzZXMgb24gdGhlIGJ1dHRvbiAoc2l6aW5nIGluIGZpbGwgbW9kZSkKICogICB0ZXN0SWRTdWZmaXgKICovCmV4cG9ydCBkZWZhdWx0IGZ1bmN0aW9uIFByb3ZlbmFuY2VSaW5nKHsKICBzeW1ib2wsCiAgc291cmNlID0gJ2FsZXJ0JywKICBwaWxsYXJHcmFkZXMsCiAgZ3JhZGUgPSAnJywKICBzY29yZSA9IG51bGwsCiAgc2l6ZSA9IDI4LAogIGZpbGwgPSBmYWxzZSwKICBjbGFzc05hbWUgPSAnJywKICB0ZXN0SWRTdWZmaXgsCn0pIHsKICBjb25zdCBncmFkZXMgPSBwaWxsYXJHcmFkZXMgJiYgdHlwZW9mIHBpbGxhckdyYWRlcyA9PT0gJ29iamVjdCcgPyBwaWxsYXJHcmFkZXMgOiBudWxsOwogIGNvbnN0IGhhc0FueSA9IGdyYWRlcyAmJiBQSUxMQVJfT1JERVIuc29tZSgoaykgPT4gZ3JhZGVzW2tdKTsKICBpZiAoIWhhc0FueSkgcmV0dXJuIG51bGw7CgogIGNvbnN0IGNlbnRlckdyYWRlID0gU3RyaW5nKGdyYWRlIHx8IChzY29yZSAhPSBudWxsID8gZ3JhZGVGcm9tU2NvcmUoc2NvcmUpIDogJycpIHx8ICcnKS50b1VwcGVyQ2FzZSgpOwogIC8vIEZpeGVkIDEwMMOXMTAwIG5vbWluYWwgc3BhY2Ug4oaSIHJpbmcgc2NhbGVzIGNsZWFubHkgdmlhIENTUyAoZml4ZWQgYHNpemVgCiAgLy8gcHggT1IgYGZpbGxgID0gMTAwJSBvZiBpdHMgY29udGFpbmVyKS4KICBjb25zdCBOT00gPSAxMDA7CiAgY29uc3Qgc3cgPSBOT00gKiAwLjExOwogIGNvbnN0IGMgPSBOT00gLyAyOwogIGNvbnN0IHIgPSBjIC0gc3cgLyAyIC0gMC41OwogIGNvbnN0IGdhcCA9IDk7IC8vIGRlZ3JlZXMgYmV0d2VlbiBzZWdtZW50cwogIGNvbnN0IHNlZyA9IDM2MCAvIFBJTExBUl9PUkRFUi5sZW5ndGg7CiAgY29uc3QgdGVzdElkID0gYHByb3ZlbmFuY2UtcmluZyR7dGVzdElkU3VmZml4ID8gYC0ke3Rlc3RJZFN1ZmZpeH1gIDogJyd9YDsKICBjb25zdCBzdmdEaW0gPSBmaWxsID8gJzEwMCUnIDogc2l6ZTsKCiAgY29uc3QgdGl0bGUgPQogICAgJ1Byb3ZlbmFuY2Ug4oCUICcgKwogICAgUElMTEFSX09SREVSLm1hcCgoaykgPT4gYCR7UElMTEFSX0xBQkVMW2tdfSAke2dyYWRlc1trXSB8fCAn4oCUJ31gKS5qb2luKCcgwrcgJyk7CgogIGNvbnN0IGhhbmRsZUNsaWNrID0gKGUpID0+IHsKICAgIGUuc3RvcFByb3BhZ2F0aW9uKCk7CiAgICBpZiAoc3ltYm9sKSBvcGVuVHFzRHJhd2VyKHsgc3ltYm9sLCBzb3VyY2UgfSk7CiAgfTsKCiAgcmV0dXJuICgKICAgIDxidXR0b24KICAgICAgdHlwZT0iYnV0dG9uIgogICAgICBkYXRhLXRlc3RpZD17dGVzdElkfQogICAgICBvbkNsaWNrPXtoYW5kbGVDbGlja30KICAgICAgdGl0bGU9e3RpdGxlfQogICAgICBhcmlhLWxhYmVsPXt0aXRsZX0KICAgICAgY2xhc3NOYW1lPXtgc2hyaW5rLTAgcm91bmRlZC1mdWxsIHRyYW5zaXRpb24tdHJhbnNmb3JtIGhvdmVyOnNjYWxlLTEwNSBmb2N1czpvdXRsaW5lLW5vbmUgJHtjbGFzc05hbWV9YH0KICAgICAgc3R5bGU9e2ZpbGwgPyB7IGxpbmVIZWlnaHQ6IDAgfSA6IHsgd2lkdGg6IHNpemUsIGhlaWdodDogc2l6ZSwgbGluZUhlaWdodDogMCB9fQogICAgPgogICAgICA8c3ZnIHdpZHRoPXtzdmdEaW19IGhlaWdodD17c3ZnRGltfSB2aWV3Qm94PXtgMCAwICR7Tk9NfSAke05PTX1gfSBzdHlsZT17eyBkaXNwbGF5OiAnYmxvY2snIH19PgogICAgICAgIHsvKiB0cmFjayAqL30KICAgICAgICA8Y2lyY2xlIGN4PXtjfSBjeT17Y30gcj17cn0gZmlsbD0ibm9uZSIgc3Ryb2tlPSIjMTgxODFiIiBzdHJva2VXaWR0aD17c3d9IC8+CiAgICAgICAgey8qIHBpbGxhciBhcmNzICovfQogICAgICAgIHtQSUxMQVJfT1JERVIubWFwKChrLCBpKSA9PiB7CiAgICAgICAgICBjb25zdCBzdGFydCA9IGkgKiBzZWcgKyBnYXAgLyAyOwogICAgICAgICAgY29uc3QgZW5kID0gKGkgKyAxKSAqIHNlZyAtIGdhcCAvIDI7CiAgICAgICAgICByZXR1cm4gKAogICAgICAgICAgICA8cGF0aAogICAgICAgICAgICAgIGtleT17a30KICAgICAgICAgICAgICBkPXthcmNQYXRoKGMsIGMsIHIsIHN0YXJ0LCBlbmQpfQogICAgICAgICAgICAgIGZpbGw9Im5vbmUiCiAgICAgICAgICAgICAgc3Ryb2tlPXtzdHJva2VGb3IoZ3JhZGVzW2tdKX0KICAgICAgICAgICAgICBzdHJva2VXaWR0aD17c3d9CiAgICAgICAgICAgICAgc3Ryb2tlTGluZWNhcD0icm91bmQiCiAgICAgICAgICAgICAgZGF0YS1waWxsYXI9e2t9CiAgICAgICAgICAgICAgZGF0YS1ncmFkZT17Z3JhZGVzW2tdIHx8ICcnfQogICAgICAgICAgICAvPgogICAgICAgICAgKTsKICAgICAgICB9KX0KICAgICAgICB7LyogY2VudGVyIGdyYWRlIGxldHRlciAqL30KICAgICAgICB7Y2VudGVyR3JhZGUgJiYgKAogICAgICAgICAgPHRleHQKICAgICAgICAgICAgeD17Y30KICAgICAgICAgICAgeT17Y30KICAgICAgICAgICAgdGV4dEFuY2hvcj0ibWlkZGxlIgogICAgICAgICAgICBkb21pbmFudEJhc2VsaW5lPSJjZW50cmFsIgogICAgICAgICAgICBmb250U2l6ZT17Tk9NICogMC4zNH0KICAgICAgICAgICAgZm9udFdlaWdodD0iNzAwIgogICAgICAgICAgICBmaWxsPXtzdHJva2VGb3IoY2VudGVyR3JhZGUpfQogICAgICAgICAgICBmb250RmFtaWx5PSJ1aS1tb25vc3BhY2UsIFNGTW9uby1SZWd1bGFyLCBNZW5sbywgbW9ub3NwYWNlIgogICAgICAgICAgPgogICAgICAgICAgICB7Y2VudGVyR3JhZGV9CiAgICAgICAgICA8L3RleHQ+CiAgICAgICAgKX0KICAgICAgPC9zdmc+CiAgICA8L2J1dHRvbj4KICApOwp9Cg=="
SCANNER_CHUNKS = [
    ("ICAgID4KICAgICAgPGRpdiBjbGFzc05hbWU9ImZsZXggaXRlbXMtY2VudGVyIGp1c3RpZnktYmV0d2VlbiI+CiAgICAgICAgPGRpdiBjbGFzc05hbWU9ImZsZXggaXRlbXMtY2VudGVyIGdhcC0yIG1pbi13LTAgZmxleC13cmFwIj4KICAgICAgICAgIHsvKiB2MTkuMzQuMjczIChVSSBUcmFjayBBIC8gQTIpIOKAlCBwcm92ZW5hbmNlIHJpbmc6IDUgcGlsbGFyIGFyY3MKICAgICAgICAgICAgICBjb2xvcmVkIGJ5IGdyYWRlLCBUUVMgZ3JhZGUgaW4gY2VudGVyLiBDb21wb3NpdGlvbiBhdCBhIGdsYW5jZTsKICAgICAgICAgICAgICB0aGUgVFFTIGJhZGdlIHN0aWxsIHNob3dzIHRoZSBudW1iZXIuIENsaWNrIG9wZW5zIHRoZSBkcmF3ZXIuICovfQogICAgICAgICAge2NhcmQudHFzX3BpbGxhcl9ncmFkZXMgJiYgKAogICAgICAgICAgICA8UHJvdmVuYW5jZVJpbmcKICAgICAgICAgICAgICBzeW1ib2w9e2NhcmQuc3ltYm9sfQogICAgICAgICAgICAgIHNvdXJjZT17Y2FyZC5zb3VyY2UgfHwgJ2FsZXJ0J30KICAgICAgICAgICAgICBwaWxsYXJHcmFkZXM9e2NhcmQudHFzX3BpbGxhcl9ncmFkZXN9CiAgICAgICAgICAgICAgZ3JhZGU9e2NhcmQudHFzX2dyYWRlfQogICAgICAgICAgICAgIHNjb3JlPXtjYXJkLnRxc19zY29yZX0KICAgICAgICAgICAgICBzaXplPXsyOH0KICAgICAgICAgICAgICB0ZXN0SWRTdWZmaXg9e2BzY2FubmVyLSR7Y2FyZC5zeW1ib2x9YH0KICAgICAgICAgICAgLz4KICAgICAgICAgICl9CiAgICAgICAgICA8c3Bhbg==",
     "ICAgID4KICAgICAgey8qIHYxOS4zNC4yNzYgKFVJIFRyYWNrIEEgLyBBMiBwb2xpc2gpIOKAlCBwcm92ZW5hbmNlIHJpbmcgcHJvbW90ZWQgdG8gYQogICAgICAgICAgZnVsbC1oZWlnaHQgbGVmdCByYWlsIHNvIHRoZSA1IHBpbGxhciBhcmNzICsgY2VudGVyIGdyYWRlIGFyZSBsZWdpYmxlCiAgICAgICAgICBhdCBhIGdsYW5jZSAod2FzIGEgY3JhbXBlZCAyOHB4IGlubGluZSBjaGlwKS4gKi99CiAgICAgIDxkaXYgY2xhc3NOYW1lPSJmbGV4IGl0ZW1zLXN0cmV0Y2ggZ2FwLTMiPgogICAgICAgIHtjYXJkLnRxc19waWxsYXJfZ3JhZGVzICYmICgKICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJzaHJpbmstMCBzZWxmLXN0cmV0Y2ggZmxleCBpdGVtcy1jZW50ZXIiIGRhdGEtdGVzdGlkPXtgcHJvdmVuYW5jZS1yYWlsLSR7Y2FyZC5zeW1ib2x9YH0+CiAgICAgICAgICAgIDxkaXYgc3R5bGU9e3sgaGVpZ2h0OiAnMTAwJScsIGFzcGVjdFJhdGlvOiAnMSAvIDEnLCBtYXhIZWlnaHQ6IDg4LCBtaW5IZWlnaHQ6IDQwIH19PgogICAgICAgICAgICAgIDxQcm92ZW5hbmNlUmluZwogICAgICAgICAgICAgICAgc3ltYm9sPXtjYXJkLnN5bWJvbH0KICAgICAgICAgICAgICAgIHNvdXJjZT17Y2FyZC5zb3VyY2UgfHwgJ2FsZXJ0J30KICAgICAgICAgICAgICAgIHBpbGxhckdyYWRlcz17Y2FyZC50cXNfcGlsbGFyX2dyYWRlc30KICAgICAgICAgICAgICAgIGdyYWRlPXtjYXJkLnRxc19ncmFkZX0KICAgICAgICAgICAgICAgIHNjb3JlPXtjYXJkLnRxc19zY29yZX0KICAgICAgICAgICAgICAgIGZpbGwKICAgICAgICAgICAgICAgIGNsYXNzTmFtZT0idy1mdWxsIGgtZnVsbCIKICAgICAgICAgICAgICAgIHRlc3RJZFN1ZmZpeD17YHNjYW5uZXItJHtjYXJkLnN5bWJvbH1gfQogICAgICAgICAgICAgIC8+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgKX0KICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iZmxleC0xIG1pbi13LTAiPgogICAgICA8ZGl2IGNsYXNzTmFtZT0iZmxleCBpdGVtcy1jZW50ZXIganVzdGlmeS1iZXR3ZWVuIj4KICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iZmxleCBpdGVtcy1jZW50ZXIgZ2FwLTIgbWluLXctMCBmbGV4LXdyYXAiPgogICAgICAgICAgPHNwYW4="),
    ("ICAgICAgICA8L2Rpdj4KICAgICAgKX0KICAgIDwvZGl2PgogICk7Cn07",
     "ICAgICAgICA8L2Rpdj4KICAgICAgKX0KICAgICAgICA8L2Rpdj57LyogL2ZsZXgtMSBjb250ZW50IGNvbHVtbiAodjE5LjM0LjI3NikgKi99CiAgICAgIDwvZGl2PnsvKiAvZmxleCBpdGVtcy1zdHJldGNoIHJpbmctcmFpbCByb3cgKHYxOS4zNC4yNzYpICovfQogICAgPC9kaXY+CiAgKTsKfTs=")
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
    print("  A2d PATCH — full-height provenance ring (legibility)")
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
        print("\n  DRIFT: file(s) match neither PRE nor POST hash. Do NOT --force.")
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
