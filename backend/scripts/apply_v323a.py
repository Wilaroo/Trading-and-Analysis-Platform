#!/usr/bin/env python3
"""
apply_v323a.py — Idempotent applier for v323a r2 (long-memory chat recall, SANITIZED)
=======================================================================
Operator request: "increase decision-trail recall dramatically — last 6
months or more."

HONEST CONSTRAINT: `sentcom_thoughts` has a Mongo TTL index that DELETES
rows after 7 days — thoughts older than that are already gone and cannot
be recovered. This patch makes the memory deep FROM TODAY FORWARD and
wires in the collections that were never pruned:

  1. TTL 7d → 190d (~6.3 months): `_THOUGHTS_TTL_DAYS = 190` in
     sentcom_service.py, PLUS a live `collMod` migration of the existing
     TTL index (create_index alone can't change an existing TTL — the
     code change would silently keep pruning at 7d without the collMod).

  2. Deep per-symbol thought recall in chat: if a mentioned ticker has
     nothing in the last 24h, fall back to its most recent rows over the
     FULL retention window ("when did we last look at X?").

  3. NEW "Symbol Trade Memory" chat section: `bot_trades` has NO TTL —
     it already holds the full multi-month record. For every mentioned
     ticker: closed-trade count, W/L, net P&L, and the last 5 trades
     with setup/close_reason. This gives TRUE 6-month recall today,
     not in 6 months.

  r2 (operator review): the trade memory is SANITIZED inline — the raw
     collection is ~94% pipeline artifacts (sanitize_v2: 1594 raw → 102
     genuine). Phantom sweeps, orphan/reconciliation cleanups, micro
     learning fills, simulated rows and no-exit-price rows are excluded
     before ANY stat reaches the LLM, and the excluded count is
     disclosed in-context so the assistant cannot hallucinate a track
     record that never traded.

Touches backend/services/sentcom_service.py + backend/chat_server.py,
runs the TTL collMod against Mongo, writes
backend/tests/test_v323a_long_recall.py.

SAFE TO RUN MULTIPLE TIMES (marker-guarded; collMod is idempotent).
After commit: restart BOTH the backend AND the chat server (port 8002).

Run from repo root:  .venv/bin/python /tmp/apply_v323a.py
Then: git add -A && git commit -m "v323a: long-memory chat recall (TTL 190d + trade memory)" && git push
(commit BEFORE restarting — StartTrading.bat does `git checkout -- .`)
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "v323a"
TTL_DAYS = 190

# (relative file, chunk name, OLD, NEW) — OLD must appear EXACTLY ONCE.
CHUNKS = [
    (
        "backend/services/sentcom_service.py",
        "ttl_days_190",
        '''THOUGHTS_COLLECTION = "sentcom_thoughts"
_THOUGHTS_TTL_DAYS = 7
''',
        '''THOUGHTS_COLLECTION = "sentcom_thoughts"
# v323a — was 7. Operator wants months of decision-trail recall in chat;
# 190d ≈ 6.3 months. NOTE: changing this constant does NOT retune an
# already-created TTL index — apply_v323a.py ran the collMod migration.
_THOUGHTS_TTL_DAYS = 190
''',
    ),
    (
        "backend/services/sentcom_service.py",
        "ttl_docstring",
        '''    """Create indexes on `sentcom_thoughts` once per process. Idempotent.
    `created_at` TTL prunes 7+ day old rows automatically."""
''',
        '''    """Create indexes on `sentcom_thoughts` once per process. Idempotent.
    `created_at` TTL prunes rows older than `_THOUGHTS_TTL_DAYS` (v323a: 190d)."""
''',
    ),
    (
        "backend/chat_server.py",
        "deep_symbol_trail",
        '''            if _sym_rows:
                _trail_lines.append(f"  {_um} trail (last 24h):")
                for _t in reversed(_sym_rows):
                    _trail_lines.append(
                        f"    [{str(_t.get('timestamp') or '')[11:19]}] "
                        f"{str(_t.get('content') or '')[:110]}")
''',
        '''            if _sym_rows:
                _trail_lines.append(f"  {_um} trail (last 24h):")
                for _t in reversed(_sym_rows):
                    _trail_lines.append(
                        f"    [{str(_t.get('timestamp') or '')[11:19]}] "
                        f"{str(_t.get('content') or '')[:110]}")
            else:
                # v323a — deep recall over the FULL retention window
                # (TTL now 190d): nothing in the last 24h, so surface
                # the most recent older rows ("when did we last look
                # at this name and what did we think?").
                _old_rows = list(db["sentcom_thoughts"].find(
                    {"symbol": _um},
                    {"_id": 0, "content": 1, "timestamp": 1},
                ).sort("timestamp", -1).limit(6))
                if _old_rows:
                    _trail_lines.append(f"  {_um} trail (older — beyond 24h):")
                    for _t in reversed(_old_rows):
                        _trail_lines.append(
                            f"    [{str(_t.get('timestamp') or '')[:16]}] "
                            f"{str(_t.get('content') or '')[:110]}")
''',
    ),
    (
        "backend/chat_server.py",
        "symbol_trade_memory",
        '''        debug["thought_trail_lines"] = len(_trail_lines)
    except Exception as e:
        debug["thought_trail_error"] = str(e)
''',
        '''        debug["thought_trail_lines"] = len(_trail_lines)
    except Exception as e:
        debug["thought_trail_error"] = str(e)

    # 10.8. v323a — Symbol Trade Memory (bot_trades = PERMANENT record)
    # sentcom_thoughts is TTL-pruned, but bot_trades never expires — it
    # already holds the full multi-month history. For every mentioned
    # ticker, inject the closed-trade record so "have we ever traded X /
    # how did our SNDK trades go?" has true long-range recall.
    #
    # SANITIZED (r2): the raw collection is ~94% pipeline artifacts
    # (phantom sweeps, orphan cleanups, reconciliation slices, micro
    # learning fills, simulated rows — sanitize_v2 probe 2026-06-12:
    # 1594 raw closed → 102 genuine). Quoting raw rows would make the
    # assistant hallucinate a track record that never traded. The
    # sanitize_v2 funnel is mirrored inline before ANY stat reaches
    # the LLM, and the artifact count is disclosed so the assistant
    # can say so explicitly.
    try:
        _ARTIFACT_CR = (
            "stale_pending", "phantom", "consolidated", "broker_rejected",
            "execution_exception", "guardrail_veto", "intent_already_pending",
            "rejection_cooldown", "symbol_cooldown", "paper_phase",
            "simulation_phase", "operator_flatten_suppression",
            "emergency_flatten", "orphan", "sweep", "purge", "reconcile",
            "external_flatten", "operator_external",
        )
        _ARTIFACT_SETUP = ("reconciled", "imported", "phantom", "orphan")
        for _um in user_mentioned_tickers:
            _hist = list(db["bot_trades"].find(
                {"symbol": _um, "status": "closed"},
                {"_id": 0, "direction": 1, "setup_type": 1, "net_pnl": 1,
                 "realized_pnl": 1, "pnl": 1, "close_reason": 1,
                 "closed_at": 1, "tqs_grade": 1, "entered_by": 1,
                 "learning_only": 1, "entry_context.learning_only": 1,
                 "notes": 1, "trade_type": 1, "exit_price": 1,
                 "fill_price": 1, "entry_price": 1},
            ).sort("closed_at", -1).limit(120))
            _clean = []
            _artifacts = 0
            for h in _hist:
                _cr = str(h.get("close_reason") or "").lower()
                _st = str(h.get("setup_type") or "").lower()
                _ec = h.get("entry_context") or {}
                try:
                    _xp = float(h.get("exit_price") or 0)
                    _fp = float(h.get("fill_price") or 0)
                    _ep = float(h.get("entry_price") or 0)
                except (TypeError, ValueError):
                    _xp = _fp = _ep = 0.0
                if (
                    str(h.get("entered_by") or "bot_fired") not in ("bot_fired", "bot", "")
                    or h.get("learning_only") is True
                    or _ec.get("learning_only") is True
                    or "[SIMULATED]" in (h.get("notes") or "")
                    or h.get("trade_type") == "shadow"
                    or any(p in _cr for p in _ARTIFACT_CR)
                    or any(p in _st for p in _ARTIFACT_SETUP)
                    or _xp <= 0
                    or (_fp <= 0 and _ep <= 0)
                ):
                    _artifacts += 1
                    continue
                _clean.append(h)
            if not _clean:
                if _artifacts:
                    parts.append(
                        f"Symbol Trade Memory: {_um} has NO genuine closed bot "
                        f"trades on record ({_artifacts} bookkeeping/artifact "
                        f"rows were excluded — never describe those as real "
                        f"trades).")
                continue
            _pnls = []
            for h in _clean:
                _p = h.get("net_pnl")
                if _p in (None, 0):
                    _p = h.get("realized_pnl") if h.get("realized_pnl") not in (None, 0) else h.get("pnl")
                try:
                    _pnls.append(float(_p or 0))
                except (TypeError, ValueError):
                    _pnls.append(0.0)
            _w = sum(1 for p in _pnls if p > 0)
            _mem_lines = [
                f"  {_um}: {len(_clean)} GENUINE closed bot trades "
                f"({_artifacts} artifact/bookkeeping rows excluded), "
                f"{_w}W/{len(_pnls) - _w}L, net ${sum(_pnls):+,.0f}. Last 5:"]
            for h in _clean[:5]:
                _p = h.get("net_pnl") or h.get("realized_pnl") or h.get("pnl") or 0
                _g = f" TQS {h.get('tqs_grade')}" if h.get("tqs_grade") else ""
                _mem_lines.append(
                    f"    {str(h.get('closed_at') or '?')[:10]} "
                    f"{str(h.get('direction') or '?').upper():5s} "
                    f"{str(h.get('setup_type') or '?')[:22]:22s} "
                    f"${float(_p or 0):+,.0f}{_g} "
                    f"({str(h.get('close_reason') or '?')[:22]})")
            parts.append(
                "Symbol Trade Memory (permanent record, SANITIZED to genuine "
                "bot-fired strategy exits — use for 'have we traded X before "
                "/ how did it go'):\\n" + "\\n".join(_mem_lines))
    except Exception as e:
        debug["trade_memory_error"] = str(e)
''',
    ),
]

TEST_REL = Path("backend") / "tests" / "test_v323a_long_recall.py"

TEST_CONTENT = '''"""v323a — long-memory chat recall.

1. sentcom_thoughts TTL extended 7d → 190d (constant; the live index was
   migrated via collMod by apply_v323a.py).
2. Chat: per-symbol deep thought recall over the full retention window
   when the last 24h is empty.
3. Chat: "Symbol Trade Memory" section from bot_trades (no TTL — true
   multi-month recall available immediately).
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "chat_server.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
CHAT = (ROOT / "backend" / "chat_server.py").read_text()
SENT = (ROOT / "backend" / "services" / "sentcom_service.py").read_text()


def test_ttl_extended_to_190d():
    assert "_THOUGHTS_TTL_DAYS = 190" in SENT
    assert "_THOUGHTS_TTL_DAYS = 7\\n" not in SENT


def test_deep_symbol_trail_fallback():
    assert "trail (older — beyond 24h)" in CHAT
    i = CHAT.index("deep recall over the FULL retention window")
    block = CHAT[i:i + 900]
    assert 'db["sentcom_thoughts"].find(' in block


def test_symbol_trade_memory_section():
    assert "Symbol Trade Memory" in CHAT
    i = CHAT.index("10.8. v323a")
    block = CHAT[i:i + 7000]
    assert 'db["bot_trades"].find(' in block
    # provenance-filtered: adopted/reconciled rows must not pollute recall
    assert '"bot_fired", "bot", ""' in block


def test_trade_memory_is_sanitized():
    # r2 — raw bot_trades is ~94% artifacts; the chat must never quote them.
    i = CHAT.index("10.8. v323a")
    block = CHAT[i:i + 7000]
    assert "_ARTIFACT_CR" in block
    assert '"phantom"' in block and '"orphan"' in block
    assert "learning_only" in block
    assert "[SIMULATED]" in block
    assert "GENUINE closed bot trades" in block
    assert "rows excluded" in block


def test_files_compile():
    py_compile.compile(str(ROOT / "backend" / "chat_server.py"), doraise=True)
    py_compile.compile(str(ROOT / "backend" / "services" / "sentcom_service.py"), doraise=True)
'''


def _repo_root() -> Path:
    for c in (Path.cwd(), Path.home() / "Trading-and-Analysis-Platform"):
        if (c / "backend" / "chat_server.py").exists():
            return c
    print("ERROR: could not locate repo root."); sys.exit(1)


def _migrate_ttl(root: Path) -> None:
    """Retune the LIVE TTL index — the code change alone keeps pruning at 7d."""
    env = {}
    env_path = root / "backend" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    mongo_url = env.get("MONGO_URL")
    if not mongo_url:
        print("⚠ MONGO_URL not found in backend/.env — TTL collMod SKIPPED. Run manually:")
        print(f'  db.runCommand({{collMod:"sentcom_thoughts",index:{{name:"created_at_ttl",expireAfterSeconds:{TTL_DAYS*86400}}}}})')
        return
    try:
        from pymongo import MongoClient
        dbm = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[env.get("DB_NAME", "tradecommand")]
        col = dbm["sentcom_thoughts"]
        n = col.estimated_document_count()
        try:
            dbm.command({"collMod": "sentcom_thoughts",
                         "index": {"name": "created_at_ttl",
                                   "expireAfterSeconds": TTL_DAYS * 86400}})
            print(f"✓ live TTL index migrated to {TTL_DAYS}d "
                  f"(collection holds {n:,} rows ≈ last 7d of thoughts)")
            est = n * TTL_DAYS // 7 if n else 0
            print(f"  est. steady-state at {TTL_DAYS}d: ~{est:,} rows — fine for Mongo "
                  f"(symbol+created_at indexes already exist).")
        except Exception as e:
            # index may not exist yet — create at the new TTL
            col.create_index("created_at", expireAfterSeconds=TTL_DAYS * 86400,
                             name="created_at_ttl")
            print(f"✓ TTL index created fresh at {TTL_DAYS}d ({e.__class__.__name__} on collMod)")
    except Exception as e:
        print(f"⚠ TTL collMod failed ({e}) — run manually in mongosh:")
        print(f'  db.runCommand({{collMod:"sentcom_thoughts",index:{{name:"created_at_ttl",expireAfterSeconds:{TTL_DAYS*86400}}}}})')


def main() -> None:
    root = _repo_root()

    by_file = {}
    for rel, name, old, new in CHUNKS:
        by_file.setdefault(rel, []).append((name, old, new))

    for rel, chunks in by_file.items():
        path = root / rel
        text = path.read_text()
        if f"{MARKER} —" in text or f"{MARKER}:" in text or "_THOUGHTS_TTL_DAYS = 190" in text:
            print(f"⏭  {rel} already patched (no-op).")
            continue
        problems = []
        for name, old, _new in chunks:
            n = text.count(old)
            if n != 1:
                problems.append(f"  ✗ {rel} chunk {name!r}: anchor matched {n}× (expected 1)")
        if problems:
            print("ANCHOR DRIFT — NO changes made to", rel)
            print("\n".join(problems))
            sys.exit(1)
        for name, old, new in chunks:
            text = text.replace(old, new)
            print(f"✓ applied chunk: {rel} :: {name}")
        path.write_text(text)

    import py_compile
    py_compile.compile(str(root / "backend" / "chat_server.py"), doraise=True)
    py_compile.compile(str(root / "backend" / "services" / "sentcom_service.py"), doraise=True)
    print("✓ both files compile")

    _migrate_ttl(root)

    test_path = root / TEST_REL
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST_CONTENT)
    print(f"✓ wrote {TEST_REL}")

    print("\nNext:")
    print("  .venv/bin/python -m pytest backend/tests/test_v323a_long_recall.py -q")
    print('  git add -A && git commit -m "v323a: long-memory chat recall (TTL 190d + trade memory)" && git push')
    print("  RESTART backend AND chat server (port 8002).")
    print("  (commit BEFORE restarting — StartTrading.bat does git checkout -- .)")


if __name__ == "__main__":
    main()
