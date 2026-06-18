#!/usr/bin/env python3
"""patch_v379b_agents_sync_protocol.py
Add the "Codebase sync protocol" section (new §0.5) to AGENTS.md so every
agent keeps the DGX, GitHub repo, and Emergent sandbox in lockstep. Docs-only,
fully reversible. Anchored insert before "§1. What this app is".

Usage (DGX, repo root):
  .venv/bin/python backend/scripts/patch_v379b_agents_sync_protocol.py --check
  .venv/bin/python backend/scripts/patch_v379b_agents_sync_protocol.py --apply
  .venv/bin/python backend/scripts/patch_v379b_agents_sync_protocol.py --rollback
"""
import base64, hashlib, os, sys

TARGET = "AGENTS.md"
BAK = TARGET + ".bak.v379b"
PRE_SHA = "cda7ce5fcbeb41cdc6c92feee68ae7d95d7d78e206a08fc167934c8ccf8c6be3"
POST_SHA = "5b346bb7f8c03c819fea320c0b1dd362bbe8f896577903c5fe0e2c65ec9e8acb"
OLD = base64.b64decode("IyMgMS4gV2hhdCB0aGlzIGFwcCBpcyAob25lIHBhcmFncmFwaCk=").decode("utf-8")
NEW = base64.b64decode("IyMgMC41IENvZGViYXNlIHN5bmMgcHJvdG9jb2wg4oCUIGtlZXAgREdYIOKGlCByZXBvIOKGlCBzYW5kYm94IHRvZ2V0aGVyCgo+ICoqV2h5IHRoaXMgZXhpc3RzOioqIHRoZXJlIGFyZSBUSFJFRSBjb3BpZXMgb2YgdGhpcyBjb2RlIGFuZCB0aGV5IGRyaWZ0Lgo+IEEgMjAyNi0wNi0xOCBhdWRpdCBmb3VuZCB0aGUgRW1lcmdlbnQgc2FuZGJveCB3YXMgfjUwIGNvbW1pdHMgYmVoaW5kIHRoZQo+IERHWCAobWlzc2luZyB2MzM24oCTdjM3OSkgd2hpbGUgdGhlIHJlcG8ncyBgbWVtb3J5L2Agbm90ZXMgd2VyZSBzdHVjayBhdCB2MzIwCj4gZXZlbiB0aG91Z2ggdGhlIGNvZGUgd2FzIGF0IHYzNzkuIERyaWZ0IGlzIHRoZSAjMSBzaWxlbnQgdGltZS1zaW5rLiBUaGVzZQo+IHJ1bGVzIGtlZXAgYWxsIHRocmVlIGluIGxvY2tzdGVwIGFzIHdlIGdyb3cuCgoqKlRoZSB0aHJlZSBjb3BpZXMgKGFuZCB3aG8gaXMgYXV0aG9yaXRhdGl2ZSk6KioKCnwgQ29weSB8IFJvbGUgfCBBdXRob3JpdGF0aXZlIGZvciB8CnwtLS18LS0tfC0tLXwKfCAqKkRHWCBTcGFyayoqIChgfi9UcmFkaW5nLWFuZC1BbmFseXNpcy1QbGF0Zm9ybWApIHwgdGhlIExJVkUgcnVubmluZyBhcHAgfCB0aGUgcnVubmluZyBzeXN0ZW0g4oCUICoqc2luZ2xlIHNvdXJjZSBvZiB0cnV0aCoqIHwKfCAqKkdpdEh1YiByZXBvKiogKGBXaWxhcm9vL1RyYWRpbmctYW5kLUFuYWx5c2lzLVBsYXRmb3JtYCkgfCBkdXJhYmxlIHJlY29yZCAvIGhpc3RvcnkgfCB3aGF0IGV2ZXJ5IGFnZW50IHJlYWRzIHRvIGdldCBjdXJyZW50IHwKfCAqKkVtZXJnZW50IHNhbmRib3gqKiAoYC9hcHBgKSB8IGJ1aWxkICYgZGlhZ25vc3RpY3Mgc2NyYXRjaCB8ICoqTk9USElORyoqIOKAlCBpdCBEUklGVFM7IG5ldmVyIHRydXN0IGl0cyBmaWxlcyBhcyBhIHBhdGNoIGJhc2VsaW5lIHwKCioqR29sZGVuIHJ1bGVzIChORVZFUiB2aW9sYXRlKToqKgoxLiAqKkRpcmVjdGlvbiBpcyBmaXhlZC4qKiBDb2RlIGZsb3dzICoqREdYIOKGkiByZXBvKiogKG9wZXJhdG9yIGBnaXQgcHVzaGAgZnJvbSB0aGUKICAgREdYKSBhbmQgKipyZXBvIOKGkiBzYW5kYm94KiogKEVtZXJnZW50ICJQdWxsIGZyb20gR2l0SHViIikuICoqTkVWRVIqKiAiU2F2ZSB0bwogICBHaXRodWIiIGZyb20gdGhlIHNhbmRib3gg4oCUIGl0IHdvdWxkIGNsb2JiZXIgbGl2ZSBER1ggd29yayB3aXRoIHN0YWxlIGNvZGUuCjIuICoqQ29tbWl0IGNvZGUgQU5EIG5vdGVzIHRvZ2V0aGVyLCBldmVyeSB0aW1lLioqIEFmdGVyIGFwcGx5aW5nIGEgcGF0Y2ggb24gdGhlCiAgIERHWCwgdGhlIG9wZXJhdG9yIHJ1bnMgYGdpdCBhZGQgLUFgIChzbyBgbWVtb3J5L0NIQU5HRUxPRy5tZGAgKyBgUFJELm1kYCArCiAgIGBST0FETUFQLm1kYCByaWRlIGFsb25nIHdpdGggdGhlIGNvZGUpIOKGkiBgY29tbWl0YCDihpIgYHB1c2hgLiBUaGUgYmlnZ2VzdCBwYXN0CiAgIGRyaWZ0IHdhcyBjb21taXR0aW5nIGNvZGUgYnV0IE5PVCB0aGUgbm90ZXMuICoqUHV0IHRoZSBjb21taXQgaGFzaCBpbiB0aGUKICAgQ0hBTkdFTE9HIGVudHJ5LioqCjMuICoqQnVpbGQgcGF0Y2hlcnMgYWdhaW5zdCBMSVZFIERHWCBieXRlcywgbmV2ZXIgdGhlIHNhbmRib3guKiogQWx3YXlzIHJ1bgogICBgZXh0cmFjdF9yZWdpb25fZ2VuZXJpYy5weWAgLyBgZXh0cmFjdF9mdW5jX2dlbmVyaWMucHlgIG9uIHRoZSBER1ggYW5kIHBpbiB0aGUKICAgcGF0Y2hlciB0byB0aGUgcmV0dXJuZWQgYE9MRF9CNjRgICsgUFJFLVNIQS4gQSBzYW5kYm94LWRlcml2ZWQgcGF0Y2ggd2lsbAogICBoYXNoLW1pc21hdGNoIChiZXN0IGNhc2UpIG9yIHNpbGVudGx5IGFwcGx5IHRvIGRyaWZ0ZWQgY29kZSAod29yc3QgY2FzZSkuCjQuICoqU2Vzc2lvbi1zdGFydCBzeW5jIGNoZWNrIChkbyB0aGlzIEZJUlNULCBldmVyeSBzZXNzaW9uKToqKgogICBgYGBiYXNoCiAgIGdpdCBjbG9uZSAtLWRlcHRoIDEgaHR0cHM6Ly9naXRodWIuY29tL1dpbGFyb28vVHJhZGluZy1hbmQtQW5hbHlzaXMtUGxhdGZvcm0uZ2l0IC90bXAvcmVwbwogICBnaXQgLUMgL3RtcC9yZXBvIGxvZyAtLW9uZWxpbmUgLTEgICAgICAgICAgICAjIHJlcG8gSEVBRCArIGxhdGVzdCB2Tk5OCiAgIGdyZXAgLWMgIjxsYXRlc3QgdmVyc2lvbiBtYXJrZXI+IiBiYWNrZW5kL3NlcnZpY2VzLzxmaWxlPiAgICMgZG9lcyBzYW5kYm94IGhhdmUgaXQ/CiAgIGBgYAogICBJZiB0aGUgc2FuZGJveCBpcyBiZWhpbmQg4oaSICJQdWxsIGZyb20gR2l0SHViIiBiZWZvcmUgZG9pbmcgYW55IHdvcmsuIElmIHRoZQogICBzYW5kYm94IGlzIHNvbWVob3cgYWhlYWQgKGUuZy4gbm90ZXMgd3JpdHRlbiBoZXJlKSwgc2hpcCB0aGUgZGVsdGEgdG8gdGhlIERHWAogICBhbmQgY29tbWl0IGl0IOKAlCBkb24ndCBsZXQgdGhlIGxlYWQgZXZhcG9yYXRlLgo1LiAqKmBtZW1vcnkvYCBjYW4gZGl2ZXJnZSDigJQgUFJFUEVORCwgZG9uJ3QgYmxpbmQtb3ZlcndyaXRlIHRoZSBDSEFOR0VMT0cuKiogVGhlCiAgIGFwcGVuZC1vbmx5IENIQU5HRUxPRyBvZnRlbiBoYXMgc2FtZS1kYXkgZW50cmllcyBvbiBvbmUgc2lkZSB0aGUgb3RoZXIgbGFja3M7CiAgIHByZXBlbmQgdGhlIG5ld2VyIGJsb2NrIChpZGVtcG90ZW50IG9uIGEgdmVyc2lvbiBhbmNob3IpIGluc3RlYWQgb2YKICAgb3ZlcndyaXRpbmcuIGBQUkQubWRgIC8gYFJPQURNQVAubWRgIGFyZSBlZGl0ZWQtaW4tcGxhY2Ug4oaSIGZ1bGwgb3ZlcndyaXRlIGlzIE9LLgoKKipDYWRlbmNlOioqIHN5bmMtY2hlY2sgYXQgc2Vzc2lvbiBzdGFydCwgYW5kIGNvbW1pdCtwdXNoIGZyb20gdGhlIERHWCBhZnRlcgoqZXZlcnkqIGFwcGxpZWQgcGF0Y2ggKG5vdCBpbiBiYXRjaGVzKSBzbyB0aGUgcmVwbyBuZXZlciB0cmFpbHMgdGhlIGxpdmUgc3lzdGVtCmJ5IG1vcmUgdGhhbiBvbmUgY2hhbmdlLgoKLS0tCgojIyAxLiBXaGF0IHRoaXMgYXBwIGlzIChvbmUgcGFyYWdyYXBoKQ==").decode("utf-8")


def main():
    if "--rollback" in sys.argv:
        if os.path.exists(BAK):
            open(TARGET, "w", encoding="utf-8").write(open(BAK, encoding="utf-8").read())
            print(f"restored {TARGET} from {BAK}")
        else:
            print(f"no backup {BAK}")
        return
    apply_mode = "--apply" in sys.argv
    force = "--force" in sys.argv
    src = open(TARGET, encoding="utf-8").read()
    cur = hashlib.sha256(src.encode()).hexdigest()
    print(f"whole-file SHA: {cur}")
    print(f"expected PRE  : {PRE_SHA}  {'OK' if cur == PRE_SHA else 'MISMATCH'}")
    if cur == POST_SHA:
        print("Already applied (file matches POST-SHA). Nothing to do.")
        return
    n = src.count(OLD)
    print(f"anchor count  : {n} (need 1)")
    if n != 1:
        sys.exit("ABORT: anchor not unique.")
    if cur != PRE_SHA and not force:
        sys.exit("ABORT: PRE-SHA drift. Re-extract AGENTS.md or use --force if anchor is right.")
    out = src.replace(OLD, NEW, 1)
    got = hashlib.sha256(out.encode()).hexdigest()
    print(f"would-be POST : {got}  {'OK' if got == POST_SHA else '(differs from tested build — drift)'}")
    if not apply_mode:
        print("--check complete. Re-run with --apply.")
        return
    open(BAK, "w", encoding="utf-8").write(src)
    open(TARGET, "w", encoding="utf-8").write(out)
    print(f"APPLIED {TARGET} (backup {BAK}). POST SHA: {got}")
    print("Commit:  git add AGENTS.md memory/ && git commit -m 'docs: AGENTS.md sync protocol (v379b)' && git push")


if __name__ == "__main__":
    main()
