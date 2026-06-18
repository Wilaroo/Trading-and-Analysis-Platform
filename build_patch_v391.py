#!/usr/bin/env python3
"""Generates patch_v391_tqs_descriptors.py — a self-contained DGX patcher that
installs the v391 TQS descriptor layer + 2 data-integrity fixes."""
import base64
import gzip
import hashlib

ROOT = "/app"

# (repo-relative path, expected PRE-SHA of current file on disk; None = new file)
TARGETS = [
    ("backend/services/tqs/descriptors.py", None),
    ("backend/scripts/test_tqs_descriptors.py", None),
    ("backend/services/tqs/setup_quality.py", "83f8077ee99919a54a7a4177b1ffed3d32c6ef25e85ea298f8b185e4d79ed350"),
    ("backend/services/tqs/technical_quality.py", "f0f529f3cab3421665c0828a4f9c34ed801befebfe3c3b30f5c42df0ef5e3e72"),
    ("backend/services/tqs/fundamental_quality.py", "311679c13f99e544ef5a95f3cb96dc20d5e1444fb9dc55ad18181f60b8d975a1"),
    ("backend/services/tqs/context_quality.py", "d979b933609a841c968d79af04fa8f751758fa161dd7c8e9ca9483bdf85a6a72"),
    ("backend/services/tqs/execution_quality.py", "55fe798504e67c55fb7a1c524a034f3baafda190a27fdd29de91e04c0d95a9d7"),
    ("frontend/src/components/sentcom/v5/TqsPillarPanel.jsx", "254aa3235d6d607d3b699776e4e6224db23b43d15fdde7e3a468ed1caf3f5ec5"),
]

files = []
for rel, pre in TARGETS:
    with open(f"{ROOT}/{rel}", "rb") as fh:
        content = fh.read()
    post = hashlib.sha256(content).hexdigest()
    b64 = base64.b64encode(gzip.compress(content, 9)).decode()
    files.append({"path": rel, "pre": pre, "post": post, "b64": b64})

header = '''#!/usr/bin/env python3
"""
patch_v391_tqs_descriptors.py  —  TQS sub-score descriptor layer + integrity fixes

WHAT THIS DOES
  • Adds a `display` block ({label, verdict, reading}) to every TQS sub-score so
    the operator UI shows plain-language meaning + the ACTUAL reading
    (e.g. "VIX 16.6 · calm/normal · favorable") instead of a bare 0-100.
  • INTEGRITY FIX #1 — Fundamental/Institutional: stop emitting a FALSE
    "Good institutional ownership (50%) (+)" factor built from the placeholder
    default when ownership data is genuinely absent.
  • INTEGRITY FIX #2 — Execution/Entry-Tendency: stop scoring 85 +
    "Excellent entry execution (+)" when there is NO entry-execution data
    (slippage defaulted to 0.0). Neutralises to 50 with an honest descriptor.
  • Exposes the v389 Financial sub-score and the AI-model sub-score in the UI.

USAGE (run from repo root ~/Trading-and-Analysis-Platform):
  .venv/bin/python backend/scripts/patch_v391_tqs_descriptors.py --check   # dry-run, verify SHAs
  .venv/bin/python backend/scripts/patch_v391_tqs_descriptors.py           # apply (writes .bak.v391 backups)
  Then: ./start_backend.sh --force   AND rebuild the frontend.
"""
import base64, gzip, hashlib, os, sys

CHECK = "--check" in sys.argv
FILES = ''' + repr(files) + '''


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    drift = False
    for f in FILES:
        path, pre, post = f["path"], f["pre"], f["post"]
        exists = os.path.exists(path)
        cur = open(path, "rb").read() if exists else None
        cur_sha = sha(cur) if cur is not None else None
        if pre is None:
            status = "NEW" if not exists else ("UNCHANGED" if cur_sha == post else "OVERWRITE")
            print(f"  [{status}] {path}")
        else:
            if not exists:
                print(f"  [MISSING!] {path} — expected existing file"); drift = True; continue
            if cur_sha == post:
                print(f"  [ALREADY v391] {path}")
            elif cur_sha != pre:
                print(f"  [DRIFT!] {path}\\n      on-disk {cur_sha}\\n      expected PRE {pre}")
                drift = True
            else:
                print(f"  [OK] {path}  PRE {pre[:16]} → POST {post[:16]}")
    if CHECK:
        print("\\n--check complete." + ("  DRIFT DETECTED — do NOT apply." if drift else "  All anchors OK. Re-run without --check."))
        sys.exit(1 if drift else 0)
    if drift:
        print("\\nABORT: drift detected on a guarded file. Nothing written.")
        sys.exit(1)
    for f in FILES:
        path = f["path"]
        data = gzip.decompress(base64.b64decode(f["b64"]))
        if os.path.exists(path):
            bak = path + ".bak.v391"
            if not os.path.exists(bak):
                open(bak, "wb").write(open(path, "rb").read())
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(data)
        print(f"  WROTE {path}  POST-SHA {sha(data)[:16]}")
    print("\\nDONE. Restart backend (./start_backend.sh --force) and rebuild frontend.")


if __name__ == "__main__":
    main()
'''

out = f"{ROOT}/patch_v391_tqs_descriptors.py"
with open(out, "w") as fh:
    fh.write(header)
print("wrote", out)
for f in files:
    print(f"  {f['path']}  PRE={str(f['pre'])[:16]}  POST={f['post'][:16]}")
