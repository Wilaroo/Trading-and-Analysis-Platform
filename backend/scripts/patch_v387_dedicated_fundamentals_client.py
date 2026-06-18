#!/usr/bin/env python3
"""patch_v387 — dedicated read-only IB clientId for fundamentals (RTH-safe).
Writes services/ib_fundamentals_client.py (separate clientId, default 12, lazy-connect)
and rewires unified_fundamentals_cache.py to prefer it for ReportSnapshot + ReportsOwnership
(falls back to the clientId-11 trading socket only if the dedicated client is unavailable).
Heavy fundamental pulls no longer contend with orders/quotes → can run during the trading day.
Anchored + py_compile-gated + .bak + --rollback. Run from repo root:
  .venv/bin/python backend/scripts/patch_v387_dedicated_fundamentals_client.py --check | (apply) | --rollback
Optional: set IB_FUNDAMENTALS_CLIENT_ID in backend/.env (default 12; ensure it's free in IB Gateway).
"""
import base64, hashlib, py_compile, sys
from pathlib import Path


def _f(*c):
    for x in c:
        if Path(x).exists():
            return Path(x)
    return Path(c[0])


MODULE = _f("backend/services/ib_fundamentals_client.py", "services/ib_fundamentals_client.py")
CACHE = _f("backend/services/unified_fundamentals_cache.py", "services/unified_fundamentals_cache.py")
MODULE_B64 = "IiIiRGVkaWNhdGVkIHJlYWQtb25seSBJQiBjb25uZWN0aW9uIGZvciBmdW5kYW1lbnRhbCByZXBvcnRzICh2Mzg2YikuCgpIZWF2eSBmdW5kYW1lbnRhbCBwdWxscyAoYGBSZXBvcnRzT3duZXJzaGlwYGAgaXMgbXVsdGktTUIpIHVzZWQgdG8gc2hhcmUgdGhlCmNsaWVudElkLTExIHRyYWRpbmcgc29ja2V0LCBzbyB0aGV5IGNvdWxkIG9ubHkgcnVuIG9mZi1ob3Vycy4gVGhpcyBtb2R1bGUgb3BlbnMgYQpTRVBBUkFURSBgYGliX2FzeW5jYGAgY29ubmVjdGlvbiBvbiBpdHMgb3duIGNsaWVudElkIChgYElCX0ZVTkRBTUVOVEFMU19DTElFTlRfSURgYCwKZGVmYXVsdCAxMikg4oCUIGlzb2xhdGVkIGZyb20gb3JkZXJzL3F1b3RlcyDigJQgc28gZnVuZGFtZW50YWxzIGNhbiBiZSBmZXRjaGVkIGR1cmluZwpSVEggd2l0aG91dCBjb250ZW5kaW5nIHdpdGggdGhlIHRyYWRpbmcgcGF0aC4gUmVhZC1vbmx5LCBsYXp5LWNvbm5lY3QgKG5vdGhpbmcKaGFwcGVucyB1bnRpbCB0aGUgZmlyc3QgcmVxdWVzdCDihpIgemVybyBib290L3N0YXJ0dXAgcmlzaykuCiIiIgpmcm9tIF9fZnV0dXJlX18gaW1wb3J0IGFubm90YXRpb25zCgppbXBvcnQgYXN5bmNpbwppbXBvcnQgbG9nZ2luZwppbXBvcnQgb3MKZnJvbSB0eXBpbmcgaW1wb3J0IE9wdGlvbmFsCgpsb2dnZXIgPSBsb2dnaW5nLmdldExvZ2dlcihfX25hbWVfXykKCnRyeToKICAgIGZyb20gaWJfYXN5bmMgaW1wb3J0IElCLCBTdG9jawogICAgX0hBVkVfSUIgPSBUcnVlCmV4Y2VwdCBJbXBvcnRFcnJvcjogICMgcHJhZ21hOiBubyBjb3ZlcgogICAgX0hBVkVfSUIgPSBGYWxzZQoKCmRlZiBfaW50X2VudihrZXk6IHN0ciwgZGVmYXVsdDogaW50KSAtPiBpbnQ6CiAgICB0cnk6CiAgICAgICAgcmV0dXJuIGludChvcy5lbnZpcm9uLmdldChrZXksIGRlZmF1bHQpKQogICAgZXhjZXB0IChUeXBlRXJyb3IsIFZhbHVlRXJyb3IpOgogICAgICAgIHJldHVybiBkZWZhdWx0CgoKY2xhc3MgRnVuZGFtZW50YWxzSUJDbGllbnQ6CiAgICAiIiJTaW5nbGV0b24sIHJlYWQtb25seSBpYl9hc3luYyBjb25uZWN0aW9uIGZvciBSZXV0ZXJzIGZ1bmRhbWVudGFsIFhNTC4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9pYjogT3B0aW9uYWxbIklCIl0gPSBOb25lCiAgICAgICAgc2VsZi5fbG9jayA9IGFzeW5jaW8uTG9jaygpCiAgICAgICAgc2VsZi5ob3N0ID0gb3MuZW52aXJvbi5nZXQoIklCX0RJUkVDVF9IT1NUIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBvcy5lbnZpcm9uLmdldCgiSUJfSE9TVCIsICIxOTIuMTY4LjUwLjEiKSkKICAgICAgICBzZWxmLnBvcnQgPSBfaW50X2VudigiSUJfRElSRUNUX1BPUlQiLCA0MDAyKQogICAgICAgICMgU2VwYXJhdGUgY2xpZW50SWQgc28gdGhpcyBuZXZlciBjb2xsaWRlcyB3aXRoIHB1c2hlcigxMCkvYm90LWRpcmVjdCgxMSkuCiAgICAgICAgc2VsZi5jbGllbnRfaWQgPSBfaW50X2VudigiSUJfRlVOREFNRU5UQUxTX0NMSUVOVF9JRCIsIDEyKQoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5faWIgaXMgbm90IE5vbmUgYW5kIHNlbGYuX2liLmlzQ29ubmVjdGVkKCkKCiAgICBhc3luYyBkZWYgY29ubmVjdChzZWxmKSAtPiBib29sOgogICAgICAgIGlmIG5vdCBfSEFWRV9JQjoKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgaWYgc2VsZi5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICBhc3luYyB3aXRoIHNlbGYuX2xvY2s6CiAgICAgICAgICAgIGlmIHNlbGYuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9pYiA9IElCKCkKICAgICAgICAgICAgICAgIGF3YWl0IHNlbGYuX2liLmNvbm5lY3RBc3luYygKICAgICAgICAgICAgICAgICAgICBob3N0PXNlbGYuaG9zdCwgcG9ydD1zZWxmLnBvcnQsCiAgICAgICAgICAgICAgICAgICAgY2xpZW50SWQ9c2VsZi5jbGllbnRfaWQsIHJlYWRvbmx5PVRydWUsIHRpbWVvdXQ9MTUsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBsb2dnZXIuaW5mbygiW0lCLUZVTkRdIGNvbm5lY3RlZCAlczolZCBjbGllbnRJZD0lZCAocmVhZC1vbmx5KSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLmhvc3QsIHNlbGYucG9ydCwgc2VsZi5jbGllbnRfaWQpCiAgICAgICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4YzoKICAgICAgICAgICAgICAgIGxvZ2dlci53YXJuaW5nKCJbSUItRlVORF0gY29ubmVjdCBmYWlsZWQgKGNsaWVudElkPSVkKTogJXMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5jbGllbnRfaWQsIGV4YykKICAgICAgICAgICAgICAgIHNlbGYuX2liID0gTm9uZQogICAgICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgYXN5bmMgZGVmIGdldF9mdW5kYW1lbnRhbF9yZXBvcnQoc2VsZiwgc3ltYm9sOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXBvcnRfdHlwZTogc3RyID0gIlJlcG9ydFNuYXBzaG90IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRpbWVvdXQ6IGZsb2F0ID0gMzAuMCkgLT4gT3B0aW9uYWxbc3RyXToKICAgICAgICAiIiJGZXRjaCBhIFJldXRlcnMgZnVuZGFtZW50YWwgWE1MIHJlcG9ydC4gU2FtZSBzaWduYXR1cmUvYmVoYXZpb3VyIGFzCiAgICAgICAgSUJEaXJlY3RTZXJ2aWNlLmdldF9mdW5kYW1lbnRhbF9yZXBvcnQsIGJ1dCBvbiB0aGUgZGVkaWNhdGVkIHNvY2tldC4iIiIKICAgICAgICBpZiBub3QgYXdhaXQgc2VsZi5jb25uZWN0KCk6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjb250cmFjdCA9IFN0b2NrKHN5bWJvbC51cHBlcigpLCAiU01BUlQiLCAiVVNEIikKICAgICAgICAgICAgcXVhbGlmaWVkID0gYXdhaXQgc2VsZi5faWIucXVhbGlmeUNvbnRyYWN0c0FzeW5jKGNvbnRyYWN0KQogICAgICAgICAgICBpZiBub3QgcXVhbGlmaWVkOgogICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgeG1sID0gYXdhaXQgYXN5bmNpby53YWl0X2ZvcigKICAgICAgICAgICAgICAgIHNlbGYuX2liLnJlcUZ1bmRhbWVudGFsRGF0YUFzeW5jKHF1YWxpZmllZFswXSwgcmVwb3J0X3R5cGUpLAogICAgICAgICAgICAgICAgdGltZW91dD10aW1lb3V0LAogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybiB4bWwgb3IgTm9uZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXhjOgogICAgICAgICAgICBsb2dnZXIuZGVidWcoIltJQi1GVU5EXSAlcy8lcyBmYWlsZWQ6ICVzIiwgc3ltYm9sLCByZXBvcnRfdHlwZSwgZXhjKQogICAgICAgICAgICByZXR1cm4gTm9uZQoKCl9jbGllbnQ6IE9wdGlvbmFsW0Z1bmRhbWVudGFsc0lCQ2xpZW50XSA9IE5vbmUKCgpkZWYgZ2V0X2Z1bmRhbWVudGFsc19pYl9jbGllbnQoKSAtPiAiRnVuZGFtZW50YWxzSUJDbGllbnQiOgogICAgZ2xvYmFsIF9jbGllbnQKICAgIGlmIF9jbGllbnQgaXMgTm9uZToKICAgICAgICBfY2xpZW50ID0gRnVuZGFtZW50YWxzSUJDbGllbnQoKQogICAgcmV0dXJuIF9jbGllbnQK"

CACHE_MARKER = "v386b prefer the DEDICATED"
EDITS = [
    ("""    # 2. IB ReportSnapshot — prefer the LIVE ib_direct socket (clientId 11).
    # The legacy ib_service worker is usually disconnected on this deploy
    # (every cached doc historically came from Finnhub). ReportSnapshot is
    # ~10KB and carries float + shares-out via <SharesOut TotalFloat=...>.
    # (v19.34.202)
    try:
        from services.ib_direct_service import get_ib_direct_service
        from services.ib_fundamentals_parser import parse_report_snapshot
        ibd = get_ib_direct_service()
        if ibd is not None and ibd.is_connected():
            xml = await ibd.get_fundamental_report(symbol, "ReportSnapshot")
            if xml:
                parsed = parse_report_snapshot(xml)
                if parsed:
                    merged.update(parsed)
                    source_chain.append("ib_direct_report_snapshot")
    except Exception as exc:
        logger.debug("ib_direct fundamentals lookup failed for %s: %s", symbol, exc)""",
     """    # 2. IB ReportSnapshot — v386b prefer the DEDICATED fundamentals client
    # (separate clientId, so heavy reports never contend with the clientId-11
    # trading socket — safe during RTH); fall back to the trading socket only if
    # the dedicated client is unavailable. ReportSnapshot is ~10KB and carries
    # float + shares-out via <SharesOut TotalFloat=...>.
    try:
        from services.ib_fundamentals_parser import parse_report_snapshot
        xml = None
        try:
            from services.ib_fundamentals_client import get_fundamentals_ib_client
            xml = await get_fundamentals_ib_client().get_fundamental_report(
                symbol, "ReportSnapshot")
        except Exception as exc:
            logger.debug("fundamentals-client snapshot %s: %s", symbol, exc)
        if not xml:
            from services.ib_direct_service import get_ib_direct_service
            ibd = get_ib_direct_service()
            if ibd is not None and ibd.is_connected():
                xml = await ibd.get_fundamental_report(symbol, "ReportSnapshot")
        if xml:
            parsed = parse_report_snapshot(xml)
            if parsed:
                merged.update(parsed)
                source_chain.append("ib_direct_report_snapshot")
    except Exception as exc:
        logger.debug("ib fundamentals lookup failed for %s: %s", symbol, exc)"""),
    ("""    try:
        from services.ib_direct_service import get_ib_direct_service
        from services.ib_fundamentals_parser import parse_reports_ownership
        ibd = get_ib_direct_service()
        if ibd is None or not ibd.is_connected():
            return None""",
     """    try:
        from services.ib_fundamentals_client import get_fundamentals_ib_client
        from services.ib_fundamentals_parser import parse_reports_ownership
        ibd = get_fundamentals_ib_client()  # v386b — dedicated clientId, RTH-safe
        if not await ibd.connect():
            return None"""),
]


def sha(t): return hashlib.sha256(t.encode()).hexdigest()[:16]


def main():
    if "--rollback" in sys.argv:
        bak = CACHE.with_suffix(".py.bak.v387")
        if bak.exists():
            CACHE.write_text(bak.read_text()); bak.unlink(); print("ROLLED BACK", CACHE)
        if MODULE.exists():
            MODULE.unlink(); print("REMOVED", MODULE)
        return
    check = "--check" in sys.argv
    mod_bytes = base64.b64decode(MODULE_B64)
    mod_exists_ok = MODULE.exists() and MODULE.read_bytes() == mod_bytes
    t = CACHE.read_text()
    print(f"{CACHE.name} PRE-SHA {sha(t)}")
    if CACHE_MARKER in t:
        print("  cache already rewired — skip")
        new = t
    else:
        new = t
        for i, (old, rep) in enumerate(EDITS, 1):
            if old not in new:
                print(f"  ABORT: chunk {i} anchor not found (DGX drift). Upload:")
                print(f"    curl --data-binary @{CACHE} https://paste.rs/"); return
            new = new.replace(old, rep, 1)
        print(f"  POST-SHA(predicted) {sha(new)}")
    print(f"module {MODULE.name}: {'present+identical' if mod_exists_ok else 'will write'}")
    if check:
        print("--check OK. Re-run without --check to apply."); return
    MODULE.write_bytes(mod_bytes)
    try:
        py_compile.compile(str(MODULE), doraise=True)
    except py_compile.PyCompileError as e:
        print("MODULE COMPILE FAILED:", e); return
    if new != t:
        CACHE.with_suffix(".py.bak.v387").write_text(t)
        CACHE.write_text(new)
        try:
            py_compile.compile(str(CACHE), doraise=True)
        except py_compile.PyCompileError as e:
            CACHE.write_text(t); print("CACHE COMPILE FAILED — reverted:", e); return
    print("DONE. Restart backend. Fundamentals now use clientId 12 (default), RTH-safe.")


if __name__ == "__main__":
    main()
