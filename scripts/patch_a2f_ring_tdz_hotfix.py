#!/usr/bin/env python3
r"""
patch_a2f_ring_tdz_hotfix.py — UI Track A · A2f HOTFIX (v19.34.278).

FIXES THE CRASH introduced by A2e: "SCANNER CRASHED — Cannot access 'NOM'
before initialization". A2e's center-number edit referenced the `NOM` constant
ABOVE its own `const NOM = 100` declaration → JS temporal-dead-zone ReferenceError
at render → the whole scanner panel crashed. (yarn build did NOT catch it; TDZ is
a runtime error.) This rewrites ProvenanceRing.jsx with the declarations in the
correct order. Same colors + numeric center as A2e — just no crash. Runtime-
verified by executing the transpiled component (4/4 cases render, no throw).

1 file, FRONTEND-ONLY, idempotent, reversible (.a2fbak backup). Applies on top of
the broken A2e (or the pre-A2e A2d state). HASH GUARDS (v322t+):
  accepts PRE aa0613232748… (broken A2e)  OR  87871429d9c8… (A2d)  →  POST 29ad9c2a4fa9…

Usage (repo root):
    python3 scripts/patch_a2f_ring_tdz_hotfix.py --check
    python3 scripts/patch_a2f_ring_tdz_hotfix.py --apply
    python3 scripts/patch_a2f_ring_tdz_hotfix.py --rollback
After --apply:  cd frontend && yarn build   (then hard-refresh the cockpit)
"""
import os, sys, base64, shutil, hashlib, argparse

BAK = ".a2fbak"
TARGET = "frontend/src/components/sentcom/v5/ProvenanceRing.jsx"
PRE_SHAS = {"aa061323274818bff8311abdaf44870f88de8fe884ecc1df31ee404aa8c9df65": "broken A2e", "87871429d9c87172bd642b2001434c5ab7ea43ff521d3802d16c9600737052e0": "A2d (pre-A2e)"}
POST_SHA = "29ad9c2a4fa9dcaa20ea2d3c6b6fc1ed2f178ec7aa62afc679981e9b6321d065"
CONTENT_B64 = "LyoqCiAqIFByb3ZlbmFuY2VSaW5nIOKAlCB2MTkuMzQuMjczIChVSSBUcmFjayBBIC8gQTIpIMK3IHYxOS4zNC4yNzYgc2NhbGFibGUgcmFpbAogKgogKiBDb21wYWN0IFNWRyAicHJvdmVuYW5jZSByaW5nIjogNSBlcXVhbCBhcmNzLCBvbmUgcGVyIFRRUyBwaWxsYXIKICogKHNldHVwIMK3IHRlY2huaWNhbCDCtyBmdW5kYW1lbnRhbCDCtyBjb250ZXh0IMK3IGV4ZWN1dGlvbiksIGVhY2ggY29sb3JlZCBieQogKiB0aGF0IHBpbGxhcidzIGdyYWRlLiBUaGUgb3ZlcmFsbCBUUVMgZ3JhZGUgbGV0dGVyIHNpdHMgaW4gdGhlIGNlbnRlci4KICoKICogSXQgYW5zd2VycyAid2hlcmUgZG9lcyB0aGlzIHNjb3JlIGNvbWUgZnJvbT8iIGF0IGEgZ2xhbmNlIOKAlCB0aGUKICogPFRxc0JhZGdlLz4gc3RpbGwgc2hvd3MgdGhlIHByZWNpc2UgbnVtYmVyOyB0aGlzIHNob3dzIGl0cyBjb21wb3NpdGlvbi4KICogQ2xpY2sgb3BlbnMgdGhlIHNoYXJlZCA8VHFzRHJpbGxEb3duRHJhd2VyLz4gKHZpYSB0cXNEcmF3ZXJCdXMpLgogKgogKiBSZW5kZXJzIG5vdGhpbmcgd2hlbiBubyBwZXItcGlsbGFyIGdyYWRlcyB3ZXJlIGNhcHR1cmVkIChsZWdhY3kgcm93cykuCiAqIERhdGEgc291cmNlOiBhbGVydC9wb3NpdGlvbiBgdHFzX3BpbGxhcl9ncmFkZXNgIChhc2RpY3QgZnJvbSB0aGUgYmFja2VuZCkuCiAqCiAqIFNpemluZzogcGFzcyBgc2l6ZWAgKHB4KSBmb3IgYSBmaXhlZCBiYWRnZSwgT1IgYGZpbGxgIHRvIG1ha2UgdGhlIFNWRyBmaWxsCiAqIGl0cyBwYXJlbnQgKDEwMCUgw5cgMTAwJSkgc28gdGhlIGNhbGxlciBjYW4gc2NhbGUgaXQgdG8gZS5nLiBmdWxsIGNhcmQKICogaGVpZ2h0LiBHZW9tZXRyeSB1c2VzIGEgZml4ZWQgMTAww5cxMDAgbm9taW5hbCBjb29yZGluYXRlIHNwYWNlIHNvIGFyY3MsCiAqIHN0cm9rZSBhbmQgdGhlIGNlbnRlciBsZXR0ZXIgc2NhbGUgcHJvcG9ydGlvbmFsbHkgYXQgYW55IHJlbmRlcmVkIHNpemUuCiAqLwppbXBvcnQgUmVhY3QgZnJvbSAncmVhY3QnOwoKaW1wb3J0IHsgb3BlblRxc0RyYXdlciB9IGZyb20gJy4vdHFzRHJhd2VyQnVzJzsKaW1wb3J0IHsgZ3JhZGVGcm9tU2NvcmUgfSBmcm9tICcuL1Rxc0JhZGdlJzsKCi8vIENhbm9uaWNhbCBwaWxsYXIgb3JkZXIg4oCUIG1hdGNoZXMgc2VydmljZXMvdHFzL3Rxc19lbmdpbmUucHkgKyBUcXNQaWxsYXJQYW5lbC4KY29uc3QgUElMTEFSX09SREVSID0gWydzZXR1cCcsICd0ZWNobmljYWwnLCAnZnVuZGFtZW50YWwnLCAnY29udGV4dCcsICdleGVjdXRpb24nXTsKY29uc3QgUElMTEFSX0xBQkVMID0gewogIHNldHVwOiAnU2V0dXAnLAogIHRlY2huaWNhbDogJ1RlY2huaWNhbCcsCiAgZnVuZGFtZW50YWw6ICdGdW5kYW1lbnRhbCcsCiAgY29udGV4dDogJ0NvbnRleHQnLAogIGV4ZWN1dGlvbjogJ0V4ZWN1dGlvbicsCn07CgovLyBHcmFkZSDihpIgc3Ryb2tlIGNvbG9yIChtaXJyb3JzIFRxc0JhZGdlLmdyYWRlVG9uZSBmYW1pbGllcykuCi8vIENob3NlbiBzbyBldmVyeSBiYW5kIGlzIGNsZWFybHkgZGlzdGluZ3Vpc2hhYmxlIG9uIHRoZSBkYXJrIGNhcmQg4oCUIGluCi8vIHBhcnRpY3VsYXIgQyAoeWVsbG93KSB2cyBEIChvcmFuZ2UpLCB3aGljaCBwcmV2aW91c2x5IHJlYWQgYXMgb25lIGNvbG9yLgpjb25zdCBHUkFERV9TVFJPS0UgPSB7CiAgJ0ErJzogJyMyMmM1NWUnLCBBOiAnIzIyYzU1ZScsIC8vIGdyZWVuLTUwMAogICdCKyc6ICcjMzhiZGY4JywgQjogJyMzOGJkZjgnLCAvLyBza3ktNDAwCiAgJ0MrJzogJyNmYWNjMTUnLCBDOiAnI2ZhY2MxNScsIC8vIHllbGxvdy00MDAgKGNsZWFybHkgeWVsbG93KQogIEQ6ICcjZjk3MzE2JywgICAgICAgICAgICAgICAgICAvLyBvcmFuZ2UtNTAwIChjbGVhcmx5IG9yYW5nZSkKICBGOiAnI2VmNDQ0NCcsICAgICAgICAgICAgICAgICAgLy8gcmVkLTUwMAp9Owpjb25zdCBNSVNTSU5HID0gJyM1MjUyNWInOyAvLyB6aW5jLTYwMCDigJQgdmlzaWJsZSBuZXV0cmFsIGFyYyBmb3IgYW4gdW5ncmFkZWQgcGlsbGFyCmNvbnN0IHN0cm9rZUZvciA9IChnKSA9PiBHUkFERV9TVFJPS0VbU3RyaW5nKGcgfHwgJycpLnRvVXBwZXJDYXNlKCldIHx8IE1JU1NJTkc7Cgpjb25zdCBwb2xhciA9IChjeCwgY3ksIHIsIGRlZykgPT4gewogIGNvbnN0IGEgPSAoKGRlZyAtIDkwKSAqIE1hdGguUEkpIC8gMTgwOwogIHJldHVybiBbY3ggKyByICogTWF0aC5jb3MoYSksIGN5ICsgciAqIE1hdGguc2luKGEpXTsKfTsKY29uc3QgYXJjUGF0aCA9IChjeCwgY3ksIHIsIHN0YXJ0RGVnLCBlbmREZWcpID0+IHsKICBjb25zdCBbeDEsIHkxXSA9IHBvbGFyKGN4LCBjeSwgciwgc3RhcnREZWcpOwogIGNvbnN0IFt4MiwgeTJdID0gcG9sYXIoY3gsIGN5LCByLCBlbmREZWcpOwogIGNvbnN0IGxhcmdlID0gZW5kRGVnIC0gc3RhcnREZWcgPiAxODAgPyAxIDogMDsKICByZXR1cm4gYE0gJHt4MS50b0ZpeGVkKDIpfSAke3kxLnRvRml4ZWQoMil9IEEgJHtyfSAke3J9IDAgJHtsYXJnZX0gMSAke3gyLnRvRml4ZWQoMil9ICR7eTIudG9GaXhlZCgyKX1gOwp9OwoKLyoqCiAqIFByb3BzOgogKiAgIHN5bWJvbCwgc291cmNlICAgICAgICAgICA6IGZvciB0aGUgZHJhd2VyCiAqICAgcGlsbGFyR3JhZGVzICAgICAgICAgICAgIDogeyBzZXR1cCwgdGVjaG5pY2FsLCBmdW5kYW1lbnRhbCwgY29udGV4dCwgZXhlY3V0aW9uIH0KICogICBncmFkZSAgICAgICAgICAgICAgICAgICAgOiBvdmVyYWxsIFRRUyBncmFkZSAoY2VudGVyIGxldHRlcik7IGZhbGxzIGJhY2sgdG8gc2NvcmUKICogICBzY29yZSAgICAgICAgICAgICAgICAgICAgOiBvdmVyYWxsIFRRUyBzY29yZSAodXNlZCBpZiBncmFkZSBtaXNzaW5nKQogKiAgIHNpemUgICAgICAgICAgICAgICAgICAgICA6IHB4IGRpYW1ldGVyIChkZWZhdWx0IDI4KSDigJQgaWdub3JlZCB3aGVuIGBmaWxsYAogKiAgIGZpbGwgICAgICAgICAgICAgICAgICAgICA6IHdoZW4gdHJ1ZSB0aGUgU1ZHIGZpbGxzIGl0cyBwYXJlbnQgKDEwMCUgw5cgMTAwJSkKICogICBjbGFzc05hbWUgICAgICAgICAgICAgICAgOiBleHRyYSBjbGFzc2VzIG9uIHRoZSBidXR0b24gKHNpemluZyBpbiBmaWxsIG1vZGUpCiAqICAgdGVzdElkU3VmZml4CiAqLwpleHBvcnQgZGVmYXVsdCBmdW5jdGlvbiBQcm92ZW5hbmNlUmluZyh7CiAgc3ltYm9sLAogIHNvdXJjZSA9ICdhbGVydCcsCiAgcGlsbGFyR3JhZGVzLAogIGdyYWRlID0gJycsCiAgc2NvcmUgPSBudWxsLAogIHNpemUgPSAyOCwKICBmaWxsID0gZmFsc2UsCiAgY2xhc3NOYW1lID0gJycsCiAgdGVzdElkU3VmZml4LAp9KSB7CiAgY29uc3QgZ3JhZGVzID0gcGlsbGFyR3JhZGVzICYmIHR5cGVvZiBwaWxsYXJHcmFkZXMgPT09ICdvYmplY3QnID8gcGlsbGFyR3JhZGVzIDogbnVsbDsKICBjb25zdCBoYXNBbnkgPSBncmFkZXMgJiYgUElMTEFSX09SREVSLnNvbWUoKGspID0+IGdyYWRlc1trXSk7CiAgaWYgKCFoYXNBbnkpIHJldHVybiBudWxsOwoKICBjb25zdCBjZW50ZXJHcmFkZSA9IFN0cmluZyhncmFkZSB8fCAoc2NvcmUgIT0gbnVsbCA/IGdyYWRlRnJvbVNjb3JlKHNjb3JlKSA6ICcnKSB8fCAnJykudG9VcHBlckNhc2UoKTsKICAvLyBGaXhlZCAxMDDDlzEwMCBub21pbmFsIHNwYWNlIOKGkiByaW5nIHNjYWxlcyBjbGVhbmx5IHZpYSBDU1MgKGZpeGVkIGBzaXplYAogIC8vIHB4IE9SIGBmaWxsYCA9IDEwMCUgb2YgaXRzIGNvbnRhaW5lcikuCiAgY29uc3QgTk9NID0gMTAwOwogIGNvbnN0IHN3ID0gTk9NICogMC4xMTsKICBjb25zdCBjID0gTk9NIC8gMjsKICBjb25zdCByID0gYyAtIHN3IC8gMiAtIDAuNTsKICBjb25zdCBnYXAgPSA5OyAvLyBkZWdyZWVzIGJldHdlZW4gc2VnbWVudHMKICBjb25zdCBzZWcgPSAzNjAgLyBQSUxMQVJfT1JERVIubGVuZ3RoOwogIGNvbnN0IHRlc3RJZCA9IGBwcm92ZW5hbmNlLXJpbmcke3Rlc3RJZFN1ZmZpeCA/IGAtJHt0ZXN0SWRTdWZmaXh9YCA6ICcnfWA7CiAgY29uc3Qgc3ZnRGltID0gZmlsbCA/ICcxMDAlJyA6IHNpemU7CiAgLy8gQ2VudGVyIHNob3dzIHRoZSBudW1lcmljIFRRUyBzY29yZSAodGhlICJUUVMgbnVtYmVyIikgd2hlbiBhdmFpbGFibGUsIHNvCiAgLy8gdGhlIHJpbmcgaXMgc2VsZi1leHBsYW5hdG9yeTsgdGhlIGdyYWRlIGxldHRlciBzdGlsbCBsaXZlcyBvbiB0aGUgY2hpcC4KICAvLyBGYWxscyBiYWNrIHRvIHRoZSBncmFkZSBsZXR0ZXIgZm9yIHJvd3MgdGhhdCBvbmx5IGNhcnJ5IGEgZ3JhZGUuCiAgY29uc3QgaGFzU2NvcmUgPSBzY29yZSAhPSBudWxsICYmICFOdW1iZXIuaXNOYU4oTnVtYmVyKHNjb3JlKSk7CiAgY29uc3QgY2VudGVyVGV4dCA9IGhhc1Njb3JlID8gU3RyaW5nKE1hdGgucm91bmQoTnVtYmVyKHNjb3JlKSkpIDogY2VudGVyR3JhZGU7CiAgY29uc3QgY2VudGVyRm9udCA9IGNlbnRlclRleHQubGVuZ3RoID49IDMgPyBOT00gKiAwLjMwIDogTk9NICogMC40MDsKCiAgY29uc3QgdGl0bGUgPQogICAgJ1Byb3ZlbmFuY2Ug4oCUICcgKwogICAgUElMTEFSX09SREVSLm1hcCgoaykgPT4gYCR7UElMTEFSX0xBQkVMW2tdfSAke2dyYWRlc1trXSB8fCAn4oCUJ31gKS5qb2luKCcgwrcgJyk7CgogIGNvbnN0IGhhbmRsZUNsaWNrID0gKGUpID0+IHsKICAgIGUuc3RvcFByb3BhZ2F0aW9uKCk7CiAgICBpZiAoc3ltYm9sKSBvcGVuVHFzRHJhd2VyKHsgc3ltYm9sLCBzb3VyY2UgfSk7CiAgfTsKCiAgcmV0dXJuICgKICAgIDxidXR0b24KICAgICAgdHlwZT0iYnV0dG9uIgogICAgICBkYXRhLXRlc3RpZD17dGVzdElkfQogICAgICBvbkNsaWNrPXtoYW5kbGVDbGlja30KICAgICAgdGl0bGU9e3RpdGxlfQogICAgICBhcmlhLWxhYmVsPXt0aXRsZX0KICAgICAgY2xhc3NOYW1lPXtgc2hyaW5rLTAgcm91bmRlZC1mdWxsIHRyYW5zaXRpb24tdHJhbnNmb3JtIGhvdmVyOnNjYWxlLTEwNSBmb2N1czpvdXRsaW5lLW5vbmUgJHtjbGFzc05hbWV9YH0KICAgICAgc3R5bGU9e2ZpbGwgPyB7IGxpbmVIZWlnaHQ6IDAgfSA6IHsgd2lkdGg6IHNpemUsIGhlaWdodDogc2l6ZSwgbGluZUhlaWdodDogMCB9fQogICAgPgogICAgICA8c3ZnIHdpZHRoPXtzdmdEaW19IGhlaWdodD17c3ZnRGltfSB2aWV3Qm94PXtgMCAwICR7Tk9NfSAke05PTX1gfSBzdHlsZT17eyBkaXNwbGF5OiAnYmxvY2snIH19PgogICAgICAgIHsvKiB0cmFjayAqL30KICAgICAgICA8Y2lyY2xlIGN4PXtjfSBjeT17Y30gcj17cn0gZmlsbD0ibm9uZSIgc3Ryb2tlPSIjMTgxODFiIiBzdHJva2VXaWR0aD17c3d9IC8+CiAgICAgICAgey8qIHBpbGxhciBhcmNzICovfQogICAgICAgIHtQSUxMQVJfT1JERVIubWFwKChrLCBpKSA9PiB7CiAgICAgICAgICBjb25zdCBzdGFydCA9IGkgKiBzZWcgKyBnYXAgLyAyOwogICAgICAgICAgY29uc3QgZW5kID0gKGkgKyAxKSAqIHNlZyAtIGdhcCAvIDI7CiAgICAgICAgICByZXR1cm4gKAogICAgICAgICAgICA8cGF0aAogICAgICAgICAgICAgIGtleT17a30KICAgICAgICAgICAgICBkPXthcmNQYXRoKGMsIGMsIHIsIHN0YXJ0LCBlbmQpfQogICAgICAgICAgICAgIGZpbGw9Im5vbmUiCiAgICAgICAgICAgICAgc3Ryb2tlPXtzdHJva2VGb3IoZ3JhZGVzW2tdKX0KICAgICAgICAgICAgICBzdHJva2VXaWR0aD17c3d9CiAgICAgICAgICAgICAgc3Ryb2tlTGluZWNhcD0icm91bmQiCiAgICAgICAgICAgICAgZGF0YS1waWxsYXI9e2t9CiAgICAgICAgICAgICAgZGF0YS1ncmFkZT17Z3JhZGVzW2tdIHx8ICcnfQogICAgICAgICAgICAvPgogICAgICAgICAgKTsKICAgICAgICB9KX0KICAgICAgICB7LyogY2VudGVyOiBudW1lcmljIFRRUyBzY29yZSAoZmFsbHMgYmFjayB0byBncmFkZSBsZXR0ZXIpICovfQogICAgICAgIHtjZW50ZXJUZXh0ICYmICgKICAgICAgICAgIDx0ZXh0CiAgICAgICAgICAgIHg9e2N9CiAgICAgICAgICAgIHk9e2N9CiAgICAgICAgICAgIHRleHRBbmNob3I9Im1pZGRsZSIKICAgICAgICAgICAgZG9taW5hbnRCYXNlbGluZT0iY2VudHJhbCIKICAgICAgICAgICAgZm9udFNpemU9e2NlbnRlckZvbnR9CiAgICAgICAgICAgIGZvbnRXZWlnaHQ9IjcwMCIKICAgICAgICAgICAgZmlsbD17c3Ryb2tlRm9yKGNlbnRlckdyYWRlKX0KICAgICAgICAgICAgZm9udEZhbWlseT0idWktbW9ub3NwYWNlLCBTRk1vbm8tUmVndWxhciwgTWVubG8sIG1vbm9zcGFjZSIKICAgICAgICAgID4KICAgICAgICAgICAge2NlbnRlclRleHR9CiAgICAgICAgICA8L3RleHQ+CiAgICAgICAgKX0KICAgICAgPC9zdmc+CiAgICA8L2J1dHRvbj4KICApOwp9Cg=="


def sha_full(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else "MISSING"


def resolve(path):
    for base in (".", os.path.join(os.path.dirname(__file__), "..")):
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
    a = ap.parse_args()

    print("=" * 84)
    print("  A2f HOTFIX — provenance ring TDZ crash ('Cannot access NOM')")
    print("  mode:", "CHECK" if a.check else "APPLY" if a.apply else "ROLLBACK")
    print("=" * 84)

    p = resolve(TARGET)
    if not os.path.exists(p):
        print("  MISSING FILE:", TARGET)
        sys.exit(2)

    if a.rollback:
        if os.path.exists(p + BAK):
            shutil.copy2(p + BAK, p)
            print("  restored", TARGET, "sha=" + sha_full(p)[:12])
        else:
            print("  no backup (%s); nothing to restore." % BAK)
        print("\n  ROLLBACK complete.  NEXT: cd frontend && yarn build")
        return

    cur = sha_full(p)
    if cur == POST_SHA:
        state = "ALREADY-APPLIED"
    elif cur in PRE_SHAS:
        state = "READY (%s)" % PRE_SHAS[cur]
    else:
        state = "DRIFT"
    print("\n  %s  sha=%s  state=%s" % (TARGET, cur[:12], state))
    print("  POST=%s" % POST_SHA[:12])

    if state == "DRIFT":
        print("\n  DRIFT: matches neither an accepted PRE nor POST. Do NOT --force.")
        print("     upload:  curl --data-binary @%s https://paste.rs/" % TARGET)
        sys.exit(3)

    if a.check:
        print("\n  CHECK ok. %s" % ("nothing to do (applied)." if state == "ALREADY-APPLIED" else "ready — re-run with --apply."))
        return

    if state == "ALREADY-APPLIED":
        print("\n  Nothing to do — already at POST_SHA.")
        return

    if not os.path.exists(p + BAK):
        shutil.copy2(p, p + BAK)
    open(p, "w", encoding="utf-8").write(base64.b64decode(CONTENT_B64).decode("utf-8"))
    got = sha_full(p)
    print("  wrote %s  sha=%s  %s" % (TARGET, got[:12], "POST OK" if got == POST_SHA else "MISMATCH"))
    if got != POST_SHA:
        sys.exit(5)
    print("\n  APPLY complete. NEXT: cd frontend && yarn build  (then hard-refresh)")


if __name__ == "__main__":
    main()
