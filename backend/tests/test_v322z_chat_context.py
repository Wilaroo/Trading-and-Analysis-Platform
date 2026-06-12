"""v322z — chat data-trust fixes (2026-06-12 SNDK audit).

Source-anchored verification that chat_server.py:
  1. gives user-mentioned tickers a 6s fetch budget (snapshot + technicals)
     and reports failed fetches to the LLM instead of silence,
  2. injects LIVE bot risk_params (static "$2,500 ... 1.5:1" line gone),
  3. injects the sentcom_thoughts decision trail (global + per-symbol),
  4. rescues lowercase ticker mentions via known-symbol validation,
  5. still compiles.
"""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "chat_server.py").exists():
            return c
    raise AssertionError("repo root not found")


SRC = _repo_root() / "backend" / "chat_server.py"
TEXT = SRC.read_text()


def test_mentioned_ticker_timeout_budget():
    assert TEXT.count("timeout=(6 if _sym in user_mentioned_tickers else 2)") == 1
    assert TEXT.count("timeout=(6 if sym in user_mentioned_tickers else 2)") == 1


def test_fetch_failure_is_reported_not_silent():
    assert "LIVE QUOTE FETCH FAILED for: " in TEXT
    assert "_snap_failed" in TEXT


def test_live_risk_params_replaces_static_line():
    assert "Bot Risk Parameters (LIVE config" in TEXT
    assert '/api/trading-bot/status", timeout=3' in TEXT
    # the old hardcoded context line must be gone
    assert '"Risk Parameters: $2,500 max risk/trade, 1.5:1 min R:R, "' not in TEXT


def test_decision_trail_section_present():
    assert "Bot Decision Trail" in TEXT
    assert 'db["sentcom_thoughts"].find(' in TEXT
    # both the 1h global window and the 24h per-symbol window exist
    assert "timedelta(hours=1)" in TEXT
    assert "timedelta(hours=24)" in TEXT


def test_lowercase_rescue_guarded():
    assert "_known_symbols_cached" in TEXT
    assert "_LOWERCASE_STOPWORDS" in TEXT
    i = TEXT.index("lowercase mention rescue")
    block = TEXT[i:i + 1200]
    # only fires when the uppercase pass found nothing
    assert "if not out:" in block


def test_prompt_risk_rule_defers_to_live():
    assert "use THAT max-risk figure" in TEXT


def test_file_compiles():
    py_compile.compile(str(SRC), doraise=True)
