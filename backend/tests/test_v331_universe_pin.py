"""v331 — manual universe pin (operator-pinned symbols, e.g. day-one IPOs).

`symbol_adv_cache.manual_universe_pin: true` rows are:
  1. always in get_universe / get_universe_ranked regardless of ADV;
  2. immune to unqualifiable promotion (Layer 0, before mega-cap check);
  3. auto-included in the pusher L1 priority list.
`pin_symbol(db, sym, reason)` / `unpin_symbol(db, sym)` manage the flag.
First use: SPCX (IPO'd 2026-06-12) — no daily bars → no ADV row → was
invisible to every scan (chicken-and-egg: collection only targets cached
symbols).
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "services" / "symbol_universe.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
SRC = (ROOT / "backend" / "services" / "symbol_universe.py").read_text()


def test_pin_clause_in_get_universe():
    i = SRC.index("def get_universe(")
    block = SRC[i:SRC.index("def get_universe_ranked(")]
    assert '{"manual_universe_pin": True}' in block
    assert '"$or"' in block


def test_pin_clause_in_get_universe_ranked():
    i = SRC.index("def get_universe_ranked(")
    block = SRC[i:SRC.index("def get_universe_for_bar_size(")]
    assert '{"manual_universe_pin": True}' in block


def test_pin_immunity_in_mark_unqualifiable():
    i = SRC.index("def mark_unqualifiable(")
    block = SRC[i:SRC.index("def reset_unqualifiable(")]
    assert 'doc.get("manual_universe_pin")' in block
    assert '"protected_by": "manual_universe_pin"' in block


def test_pin_flows_to_pusher_l1():
    i = SRC.index("def get_pusher_l1_recommendations(")
    block = SRC[i:SRC.index("def get_universe_stats(")]
    assert '"manual_universe_pin": True' in block


def test_pin_helpers_exist():
    assert "def pin_symbol(" in SRC
    assert "def unpin_symbol(" in SRC


def test_file_compiles():
    py_compile.compile(str(ROOT / "backend" / "services" / "symbol_universe.py"),
                       doraise=True)
