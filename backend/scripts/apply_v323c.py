#!/usr/bin/env python3
"""
apply_v323c.py — Idempotent applier for v323c (thought retention tiering)
==========================================================================
Operator decision (2026-06-12): keep evaluations / fills / rejections /
thoughts / alerts for the full 190d window, but DON'T keep scanner noise
past 7 days. At ~371K rows/week the noise kinds are the bulk of volume.

TIERS (sentcom_thoughts.kind):
  7d  (noise):  scan, skip, filter, info
  190d (keep):  thought, alert, evaluation, fill, rejection, system, brain
  (closed-trade stats / execution records live in bot_trades,
   bracket_lifecycle_events etc. — separate collections, NO TTL, untouched)

MECHANISM: new noise rows get a per-doc `expires_at` (+7d) pruned by a
new TTL index (expireAfterSeconds=0). Keep-rows carry no expires_at and
remain governed by the existing 190d created_at TTL backstop. This
patcher also MIGRATES existing noise rows (expires_at = created_at + 7d)
and creates the index live.

Touches backend/services/sentcom_service.py + writes
backend/tests/test_v323c_thought_retention.py.
SAFE TO RUN MULTIPLE TIMES.

Run from repo root:  .venv/bin/python /tmp/apply_v323c.py
Then: git add -A && git commit -m "v323c: tiered thought retention (noise 7d / signal 190d)" && git push
(commit BEFORE restarting — StartTrading.bat does `git checkout -- .`)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

MARKER = "_SCAN_NOISE_KINDS"
REL = "backend/services/sentcom_service.py"
NOISE_KINDS = ["scan", "skip", "filter", "info"]
NOISE_TTL_DAYS = 7

CHUNKS = [
    (
        "noise_kind_constants",
        '''THOUGHTS_COLLECTION = "sentcom_thoughts"
''',
        '''THOUGHTS_COLLECTION = "sentcom_thoughts"
# v323c — retention tiers. Scanner noise (scan/skip/filter/info) is ~90%
# of write volume and has no recall value past a few sessions: it gets a
# per-doc `expires_at` (+7d, pruned by the expires_at_ttl index). Signal
# kinds (thought/alert/evaluation/fill/rejection/system/brain) carry no
# expires_at and live the full _THOUGHTS_TTL_DAYS via the created_at TTL.
_SCAN_NOISE_KINDS = {"scan", "skip", "filter", "info"}
_NOISE_TTL_DAYS = 7
''',
    ),
    (
        "expires_at_index",
        '''        col.create_index([("symbol", 1), ("created_at", -1)], name="symbol_recent")
''',
        '''        col.create_index([("symbol", 1), ("created_at", -1)], name="symbol_recent")
        # v323c — per-doc expiry for noise kinds (docs without the field
        # are ignored by this TTL index and fall back to created_at_ttl).
        col.create_index("expires_at", expireAfterSeconds=0, name="expires_at_ttl")
''',
    ),
    (
        "persist_expires_at",
        '''        def _insert():
            db[THOUGHTS_COLLECTION].insert_one({
                "id": msg.id,
                "kind": msg.type,
''',
        '''        def _insert():
            _doc_kind = str(msg.type or "")
            _now = datetime.now(timezone.utc)
            db[THOUGHTS_COLLECTION].insert_one({
                "id": msg.id,
                "kind": msg.type,
''',
    ),
    (
        "persist_expires_at_field",
        '''                "timestamp": msg.timestamp,
                "created_at": datetime.now(timezone.utc),
            })
''',
        '''                "timestamp": msg.timestamp,
                "created_at": _now,
                # v323c — noise kinds expire at 7d; signal kinds omit the
                # field and live the full created_at TTL window (190d).
                **({"expires_at": _now + timedelta(days=_NOISE_TTL_DAYS)}
                   if _doc_kind in _SCAN_NOISE_KINDS else {}),
            })
''',
    ),
]

TEST_REL = Path("backend") / "tests" / "test_v323c_thought_retention.py"

TEST_CONTENT = '''"""v323c — tiered sentcom_thoughts retention.

Noise kinds (scan/skip/filter/info) expire at 7d via per-doc expires_at +
TTL(0) index; signal kinds (evaluation/fill/rejection/thought/alert/
system/brain) keep the full 190d created_at TTL.
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "sentcom_service.py").exists():
            return c
    raise AssertionError("repo root not found")


SRC = _repo_root() / "backend" / "services" / "sentcom_service.py"
TEXT = SRC.read_text()


def test_noise_tiers_defined():
    assert '_SCAN_NOISE_KINDS = {"scan", "skip", "filter", "info"}' in TEXT
    assert "_NOISE_TTL_DAYS = 7" in TEXT
    assert "_THOUGHTS_TTL_DAYS = 190" in TEXT


def test_expires_at_index_created():
    assert 'col.create_index("expires_at", expireAfterSeconds=0, name="expires_at_ttl")' in TEXT


def test_persist_sets_expiry_only_for_noise():
    i = TEXT.index('"expires_at": _now + timedelta(days=_NOISE_TTL_DAYS)')
    block = TEXT[i - 200:i + 200]
    assert "_doc_kind in _SCAN_NOISE_KINDS" in block


def test_file_compiles():
    py_compile.compile(str(SRC), doraise=True)
'''


def _repo_root() -> Path:
    for c in (Path.cwd(), Path.home() / "Trading-and-Analysis-Platform"):
        if (c / REL).exists():
            return c
    print("ERROR: could not locate repo root."); sys.exit(1)


def _migrate(root: Path) -> None:
    """Create the TTL index + stamp expires_at on EXISTING noise rows."""
    env = {}
    p = root / "backend" / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    if not env.get("MONGO_URL"):
        print("⚠ MONGO_URL not in backend/.env — migration SKIPPED."); return
    from pymongo import MongoClient
    col = MongoClient(env["MONGO_URL"])[env.get("DB_NAME", "tradecommand")]["sentcom_thoughts"]
    try:
        col.create_index("expires_at", expireAfterSeconds=0, name="expires_at_ttl")
        print("✓ expires_at_ttl index ensured")
    except Exception as e:
        print(f"⚠ index create: {e}")
    res = col.update_many(
        {"kind": {"$in": NOISE_KINDS}, "expires_at": {"$exists": False},
         "created_at": {"$type": "date"}},
        [{"$set": {"expires_at": {"$add": ["$created_at", NOISE_TTL_DAYS * 86400000]}}}],
    )
    total = col.estimated_document_count()
    print(f"✓ stamped expires_at on {res.modified_count:,} existing noise rows "
          f"(collection total {total:,}). Noise older than 7d will prune within "
          f"~60s of the TTL monitor's next pass — expect the row count to drop hard.")


def main() -> None:
    root = _repo_root()
    path = root / REL
    text = path.read_text()

    if MARKER in text:
        print(f"⏭  {REL} already patched (no-op).")
    else:
        # _persist_thought must import timedelta — sentcom_service already
        # imports it at module top (verified); anchors fail closed otherwise.
        problems = []
        for name, old, _new in CHUNKS:
            n = text.count(old)
            if n != 1:
                problems.append(f"  ✗ chunk {name!r}: anchor matched {n}× (expected 1)")
        if problems:
            print("ANCHOR DRIFT — NO changes made:")
            print("\n".join(problems))
            sys.exit(1)
        for name, old, new in CHUNKS:
            text = text.replace(old, new)
            print(f"✓ applied chunk: {name}")
        path.write_text(text)

    import py_compile
    py_compile.compile(str(path), doraise=True)
    print("✓ sentcom_service.py compiles")

    test_path = root / TEST_REL
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST_CONTENT)
    print(f"✓ wrote {TEST_REL}")

    _migrate(root)

    print("\nNext:")
    print("  .venv/bin/python -m pytest backend/tests/test_v323c_thought_retention.py -q")
    print('  git add -A && git commit -m "v323c: tiered thought retention (noise 7d / signal 190d)" && git push')
    print("  RESTART the backend (chat server unaffected).")


if __name__ == "__main__":
    main()
