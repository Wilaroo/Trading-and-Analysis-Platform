"""v323a — long-memory chat recall.

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
    assert "_THOUGHTS_TTL_DAYS = 7\n" not in SENT


def test_deep_symbol_trail_fallback():
    assert "trail (older — beyond 24h)" in CHAT
    i = CHAT.index("deep recall over the FULL retention window")
    block = CHAT[i:i + 900]
    assert 'db["sentcom_thoughts"].find(' in block


def test_symbol_trade_memory_section():
    assert "Symbol Trade Memory" in CHAT
    i = CHAT.index("10.8. v323a")
    block = CHAT[i:i + 2600]
    assert 'db["bot_trades"].find(' in block
    # provenance-filtered: adopted/reconciled rows must not pollute recall
    assert '"bot_fired", "bot", ""' in block


def test_files_compile():
    py_compile.compile(str(ROOT / "backend" / "chat_server.py"), doraise=True)
    py_compile.compile(str(ROOT / "backend" / "services" / "sentcom_service.py"), doraise=True)
