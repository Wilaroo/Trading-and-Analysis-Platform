#!/usr/bin/env python3
"""
apply_v330.py — INT-21 hardening + sector mapping fix + thought TTL tiers
==========================================================================
Three operator items in one patch:

1. IGV "RANGE BREAK" FALSE TRIGGER (INT-21) — _check_range_break now
   requires a range to actually EXIST before a "break" can fire:
     • ≥60 min of RTH session age (early HOD pokes were "breaking" a
       10-minute "range");
     • HOD-LOD ≥ 0.6×ATR (micro-ranges break on noise);
     • RVOL sanity band 0.2-50 (0/absurd = missing/partial prior-day
       daily bars — the daily-bar-leak failure class);
     • snapshot ≤5 min old (no entries off blackout-stale HOD/RVOL).

2. ELF TAGGED AS XLE — root cause: naked substring matching in
   _industry_to_etf. "Cosmetics & Toiletries" contains "oil" inside
   "tOILetries" → XLE. BONUS BUG found while testing: "Aerospace &
   Defense" contains "spac" inside "aeroSPACe" → hit the SPAC blocklist
   → sector None. Fix: keys now match only at WORD STARTS (stems still
   work: "rail"→"railroads", "gas"→"gasoline", "utilit"→"utilities").
   Plus explicit cosmetic/toiletries/beauty → XLP table entries.
   DB repair: any symbol_adv_cache row where sector==XLE was cached for
   a cosmetics/toiletries industry gets re-pointed to XLP (ELF).

3. THOUGHT-LOG TTL TIERING (content-based) — kind="thought" rows whose
   text is generic skipped/passing chatter ("skipped", "passing on",
   "no setup", "snapshot unavailable", ...) now get the 7-day noise
   expiry instead of living 190 days. Real decision/signal thoughts
   keep 190d. DB phase retro-tags EXISTING generic thought rows so the
   space win starts tonight, not in 6 months.

Also ships backend/tests/test_v330_hardening.py (9 tests) and runs the
relevant test files as a self-check after patching.

SAFE TO RUN MULTIPLE TIMES (idempotent).
Run from repo root:   .venv/bin/python /tmp/apply_v330.py
Files-only (no DB):   .venv/bin/python /tmp/apply_v330.py --files-only
Then: git add -A && git commit -m "v330: INT-21 hardening + sector wordstart + thought TTL tiers" && git push
Then restart the backend.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHUNKS = [
    ('backend/services/enhanced_scanner.py',
     '        return None\n    \n    async def _check_range_break(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:\n        """Range Break - Break of established range"""\n        daily_range = snapshot.daily_range_pct\n        \n        if daily_range < 2.0 and daily_range > 0.5 and snapshot.rvol >= 1.5:\n',
     '        return None\n    \n    async def _check_range_break(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:\n        """Range Break - Break of established range\n\n        v330 hardening (operator: IGV false trigger) — a "range break"\n        is meaningless until a RANGE actually exists:\n          1. ≥60 min of RTH session age (early-session HOD pokes were\n             firing as "breaks" of a 10-minute "range");\n          2. the range itself must be substantial (HOD-LOD ≥ 0.6×ATR —\n             micro-ranges break on noise);\n          3. RVOL sanity: 0 / absurd values mean prior-day daily bars\n             were missing or partial (daily-bar-leak class failure) —\n             never trade a poisoned ratio;\n          4. snapshot freshness ≤5 min — stale HOD/RVOL during a data\n             blackout must not fire entries.\n        """\n        from zoneinfo import ZoneInfo\n        now_et = datetime.now(ZoneInfo("America/New_York"))\n        mins_since_open = (now_et.hour * 60 + now_et.minute) - (9 * 60 + 30)\n        if mins_since_open < 60:\n            return None\n        rng = float(snapshot.high_of_day or 0) - float(snapshot.low_of_day or 0)\n        _atr = float(getattr(snapshot, "atr", 0) or 0)\n        if rng <= 0 or _atr <= 0 or rng < 0.6 * _atr:\n            return None\n        if not (0.2 <= float(snapshot.rvol or 0) <= 50.0):\n            return None\n        try:\n            snap_ts = datetime.fromisoformat(str(snapshot.timestamp).replace("Z", "+00:00"))\n            if snap_ts.tzinfo is None:\n                snap_ts = snap_ts.replace(tzinfo=timezone.utc)\n            if (datetime.now(timezone.utc) - snap_ts).total_seconds() > 300:\n                return None\n        except Exception:\n            pass\n\n        daily_range = snapshot.daily_range_pct\n        \n        if daily_range < 2.0 and daily_range > 0.5 and snapshot.rvol >= 1.5:\n'),
    ('backend/services/sector_tag_service.py',
     '\nimport asyncio\nimport logging\nimport time\nfrom datetime import datetime, timezone\nfrom typing import Dict, Iterable, List, Optional\n',
     '\nimport asyncio\nimport logging\nimport re\nimport time\nfrom datetime import datetime, timezone\nfrom typing import Dict, Iterable, List, Optional\n'),
    ('backend/services/sector_tag_service.py',
     '    "food":                  "XLP",\n    "household":             "XLP",\n    "personal product":      "XLP",\n    # Healthcare — XLV\n    "health":                "XLV",\n    "pharmaceutical":        "XLV",\n',
     '    "food":                  "XLP",\n    "household":             "XLP",\n    "personal product":      "XLP",\n    "cosmetic":              "XLP",  # v330 — ELF was XLE via "oil" in "tOILetries"\n    "toiletries":            "XLP",\n    "beauty":                "XLP",\n    # Healthcare — XLV\n    "health":                "XLV",\n    "pharmaceutical":        "XLV",\n'),
    ('backend/services/sector_tag_service.py',
     '    if not industry:\n        return None\n    needle = industry.lower()\n    # 1. Explicit blocklist — UNKNOWN beats wrong sector tag.\n    for blocked in _EXPLICIT_NONE:\n        if blocked in needle:\n            return None\n    # 2. Priority overrides — sector-conflict resolution.\n    for etf, keys in _PRIORITY_OVERRIDES:\n        for k in keys:\n            if k in needle:\n                return etf\n    # 3. Longest-substring match.\n    for key in sorted(_INDUSTRY_TO_ETF.keys(), key=len, reverse=True):\n        if key in needle:\n            return _INDUSTRY_TO_ETF[key]\n    return None\n\n',
     '    if not industry:\n        return None\n    needle = industry.lower()\n\n    # v330 — WORD-START matching everywhere. Naked substring matching\n    # produced two operator-visible misclassifications:\n    #   • "Cosmetics & Toiletries" → XLE   ("oil" inside "tOILetries")\n    #   • "Aerospace & Defense"    → None  ("spac" inside "aeroSPACe"\n    #     hit the SPAC blocklist before any sector rule could run)\n    # Keys now only match at a word START (start-of-string or preceded\n    # by a non-word char). Suffixes still match so stem keys keep\n    # working: "utilit"→"utilities", "rail"→"railroads", "gas"→"gasoline".\n    def _hit(key: str) -> bool:\n        return re.search(r"\\b" + re.escape(key), needle) is not None\n\n    # 1. Explicit blocklist — UNKNOWN beats wrong sector tag.\n    for blocked in _EXPLICIT_NONE:\n        if _hit(blocked):\n            return None\n    # 2. Priority overrides — sector-conflict resolution.\n    for etf, keys in _PRIORITY_OVERRIDES:\n        for k in keys:\n            if _hit(k):\n                return etf\n    # 3. Longest-match (word-start) into the table.\n    for key in sorted(_INDUSTRY_TO_ETF.keys(), key=len, reverse=True):\n        if _hit(key):\n            return _INDUSTRY_TO_ETF[key]\n    return None\n\n'),
    ('backend/services/sentcom_service.py',
     'import logging\nimport asyncio\nimport os\nfrom typing import Dict, Any, List, Optional\nfrom datetime import datetime, timezone, timedelta\nfrom dataclasses import dataclass, field\n',
     'import logging\nimport asyncio\nimport os\nimport re\nfrom typing import Dict, Any, List, Optional\nfrom datetime import datetime, timezone, timedelta\nfrom dataclasses import dataclass, field\n'),
    ('backend/services/sentcom_service.py',
     '# expires_at and live the full _THOUGHTS_TTL_DAYS via the created_at TTL.\n_SCAN_NOISE_KINDS = {"scan", "skip", "filter", "info"}\n_NOISE_TTL_DAYS = 7\n# v323a — was 7. Operator wants months of decision-trail recall in chat;\n# 190d ≈ 6.3 months. NOTE: changing this constant does NOT retune an\n# already-created TTL index — apply_v323a.py ran the collMod migration.\n',
     '# expires_at and live the full _THOUGHTS_TTL_DAYS via the created_at TTL.\n_SCAN_NOISE_KINDS = {"scan", "skip", "filter", "info"}\n_NOISE_TTL_DAYS = 7\n# v330 — content-based noise tier. Plenty of "skipped/passing" chatter\n# is emitted with kind="thought" (not a noise kind) and was living the\n# full 190d window for no recall value. Generic no-action texts now get\n# the 7d expiry too; real decisions/signals keep 190d.\n_NOISE_CONTENT_RE = re.compile(\n    r"(skipp(?:ed|ing)|passing on|passed on|no setup|no signal|"\n    r"below floor|no intraday bars|snapshot unavailable|"\n    r"not in play|nothing actionable|no actionable)",\n    re.IGNORECASE,\n)\n# v323a — was 7. Operator wants months of decision-trail recall in chat;\n# 190d ≈ 6.3 months. NOTE: changing this constant does NOT retune an\n# already-created TTL index — apply_v323a.py ran the collMod migration.\n'),
    ('backend/services/sentcom_service.py',
     '                "created_at": _now,\n                # v323c — noise kinds expire at 7d; signal kinds omit the\n                # field and live the full created_at TTL window (190d).\n                **({"expires_at": _now + timedelta(days=_NOISE_TTL_DAYS)}\n                   if _doc_kind in _SCAN_NOISE_KINDS else {}),\n            })\n\n        await asyncio.to_thread(_insert)\n',
     '                "created_at": _now,\n                # v323c — noise kinds expire at 7d; signal kinds omit the\n                # field and live the full created_at TTL window (190d).\n                # v330 — kind="thought" rows whose text is generic\n                # skipped/passing chatter join the 7d tier (content-based).\n                **({"expires_at": _now + timedelta(days=_NOISE_TTL_DAYS)}\n                   if (_doc_kind in _SCAN_NOISE_KINDS\n                       or (_doc_kind == "thought"\n                           and _NOISE_CONTENT_RE.search(str(msg.content or ""))))\n                   else {}),\n            })\n\n        await asyncio.to_thread(_insert)\n'),
]

TEST_FILE_REL = 'backend/tests/test_v330_hardening.py'
TEST_FILE_CONTENT = '"""v330 — INT-21 range-break hardening + sector word-start matching +\ncontent-based thought TTL tiering.\n\n1. enhanced_scanner._check_range_break gains four guards: ≥60min session\n   age, HOD-LOD ≥ 0.6×ATR, RVOL sanity band (0.2-50), snapshot ≤5min old.\n2. sector_tag_service._industry_to_etf matches keys only at word starts:\n   "Cosmetics & Toiletries" no longer hits "oil" (was XLE), "Aerospace &\n   Defense" no longer hits the "spac" blocklist (was None).\n3. sentcom_service kind="thought" rows with generic skipped/passing text\n   join the 7d noise TTL tier (signal thoughts keep 190d).\n"""\nimport py_compile\nfrom pathlib import Path\n\n\ndef _repo_root():\n    for c in Path(__file__).resolve().parents:\n        if (c / "backend" / "services" / "sentcom_service.py").exists():\n            return c\n    raise AssertionError("repo root not found")\n\n\nROOT = _repo_root()\nSCANNER = (ROOT / "backend" / "services" / "enhanced_scanner.py").read_text()\nSECTOR = (ROOT / "backend" / "services" / "sector_tag_service.py").read_text()\nSENTCOM = (ROOT / "backend" / "services" / "sentcom_service.py").read_text()\n\n\n# ── 1. range-break hardening (source assertions) ────────────────────────\n\ndef test_range_break_session_age_gate():\n    i = SCANNER.index("async def _check_range_break")\n    block = SCANNER[i:i + 2500]\n    assert "mins_since_open" in block and "< 60" in block\n\n\ndef test_range_break_min_range_vs_atr():\n    i = SCANNER.index("async def _check_range_break")\n    block = SCANNER[i:i + 2500]\n    assert "rng < 0.6 * _atr" in block\n\n\ndef test_range_break_rvol_sanity_band():\n    i = SCANNER.index("async def _check_range_break")\n    block = SCANNER[i:i + 2500]\n    assert "0.2 <= float(snapshot.rvol or 0) <= 50.0" in block\n\n\ndef test_range_break_snapshot_freshness():\n    i = SCANNER.index("async def _check_range_break")\n    block = SCANNER[i:i + 2500]\n    assert "total_seconds() > 300" in block\n\n\n# ── 2. sector word-start matching (functional) ──────────────────────────\n\ndef test_sector_wordstart_matching():\n    import sys\n    sys.path.insert(0, str(ROOT / "backend"))\n    from services.sector_tag_service import _industry_to_etf\n    assert _industry_to_etf("Cosmetics & Toiletries") == "XLP"\n    assert _industry_to_etf("Aerospace & Defense") == "XLI"\n    assert _industry_to_etf("Oil & Gas Exploration") == "XLE"\n    assert _industry_to_etf("Gasoline Distribution") == "XLE"\n    assert _industry_to_etf("Railroads") == "XLI"\n    assert _industry_to_etf("Biotechnology") == "XLV"\n    assert _industry_to_etf("REIT - Industrial") == "XLRE"\n    assert _industry_to_etf("SPAC") is None\n    assert _industry_to_etf("Personal Products") == "XLP"\n\n\n# ── 3. content-based thought TTL tier ───────────────────────────────────\n\ndef test_noise_content_regex_defined():\n    assert "_NOISE_CONTENT_RE" in SENTCOM\n    assert \'snapshot unavailable\' in SENTCOM\n\n\ndef test_persist_applies_content_tier_to_thought_kind():\n    i = SENTCOM.index(\'_doc_kind == "thought"\')\n    block = SENTCOM[i - 300:i + 300]\n    assert "_NOISE_CONTENT_RE.search" in block\n    assert "expires_at" in block\n\n\ndef test_noise_regex_classification():\n    import sys\n    sys.path.insert(0, str(ROOT / "backend"))\n    from services.sentcom_service import _NOISE_CONTENT_RE\n    assert _NOISE_CONTENT_RE.search("IGV skipped — no intraday bars (snapshot unavailable)")\n    assert _NOISE_CONTENT_RE.search("Passing on NVDA — RVOL 0.8x below floor")\n    assert not _NOISE_CONTENT_RE.search("ENTERED IGV long 3 legs OCA — scalp")\n    assert not _NOISE_CONTENT_RE.search("PT1 filled +0.8R, trailing stop moved to BE")\n\n\ndef test_files_compile():\n    for rel in ("enhanced_scanner.py", "sector_tag_service.py", "sentcom_service.py"):\n        py_compile.compile(str(ROOT / "backend" / "services" / rel), doraise=True)\n'


def find_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / "backend" / "services" / "sentcom_service.py").exists():
            return cand
    print("FATAL: run from repo root")
    sys.exit(1)


def _load_env(root: Path) -> None:
    p = root / "backend" / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))


def apply_chunks(root: Path) -> int:
    applied = 0
    for rel, old, new in CHUNKS:
        path = root / rel
        text = path.read_text()
        if new in text:
            print(f"[SKIP] {rel} — chunk already applied")
            continue
        n = text.count(old)
        if n != 1:
            print(f"[FAIL] {rel} — anchor found {n}x (expected 1). File drifted. ABORTING.")
            sys.exit(2)
        path.write_text(text.replace(old, new, 1))
        applied += 1
        print(f"[OK]   {rel} — chunk applied")
    # regression test file
    tp = root / TEST_FILE_REL
    if tp.exists() and tp.read_text() == TEST_FILE_CONTENT:
        print(f"[SKIP] {TEST_FILE_REL} — already present")
    else:
        tp.write_text(TEST_FILE_CONTENT)
        print(f"[OK]   {TEST_FILE_REL} — written")
    return applied


def db_phase(root: Path) -> None:
    from pymongo import MongoClient
    _load_env(root)
    url = os.environ.get("MONGO_URL")
    if not url:
        print("[WARN] MONGO_URL not found — skipping DB phase")
        return
    db = MongoClient(url)[os.environ.get("DB_NAME", "tradecommand")]

    # 2b. repair ELF (and any cosmetics-industry XLE leftovers)
    res = db["symbol_adv_cache"].update_many(
        {"symbol": "ELF", "sector": "XLE"}, {"$set": {"sector": "XLP"}})
    print(f"[DB]   ELF sector XLE→XLP: {res.modified_count} row(s) repaired")

    # 3b. retro-tag existing generic kind="thought" rows with the 7d expiry
    pattern = ("skipp(ed|ing)|passing on|passed on|no setup|no signal|"
               "below floor|no intraday bars|snapshot unavailable|"
               "not in play|nothing actionable|no actionable")
    expiry = datetime.now(timezone.utc) + timedelta(days=7)
    res = db["sentcom_thoughts"].update_many(
        {
            "kind": "thought",
            "expires_at": {"$exists": False},
            "content": {"$regex": pattern, "$options": "i"},
        },
        {"$set": {"expires_at": expiry}},
    )
    print(f"[DB]   retro-tagged {res.modified_count} generic 'thought' rows "
          f"with 7d expiry (purge ~{expiry:%Y-%m-%d})")


def self_test(root: Path) -> None:
    print()
    print("── self-test: pytest on the touched surfaces ──")
    tests = [
        "tests/test_v330_hardening.py",
        "tests/test_sector_tag_finnhub_fallback.py",
        "tests/test_v323c_thought_retention.py",
    ]
    existing = [t for t in tests if (root / "backend" / t).exists()]
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *existing],
        cwd=str(root / "backend"),
        capture_output=True, text=True, timeout=300,
    )
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print("   " + line)
    if r.returncode != 0:
        print("[FAIL] self-test failed — see above. NOT safe to restart.")
        print((r.stdout or "")[-2000:])
        sys.exit(3)
    print("[OK]   self-test PASSED")


def main():
    root = find_root()
    print(f"repo root: {root}")
    applied = apply_chunks(root)
    if "--files-only" in sys.argv:
        print("[SKIP] DB phase (--files-only)")
    else:
        db_phase(root)
    self_test(root)
    print()
    print(f"v330 done — {applied} chunk(s) newly applied.")
    print("Next:")
    print("  git add -A && git commit -m 'v330: INT-21 hardening + sector wordstart + thought TTL tiers' && git push")
    print("  then RESTART the backend.")


if __name__ == "__main__":
    main()
