"""
test_chat_trade_action_parsing_v19_34_28.py
============================================
Pins the v19.34.28 mid-market hotfix in `chat_server._execute_trade_action`
+ the marker-stripping path in the `chat` endpoint.

Operator-observed bug (2026-05-14 09:46 ET, live trading):
  - Asked the bot to move ICLN stop to $21.80 → ✓ succeeded.
  - Asked the bot to move ONON stop to $35.10 → bot acknowledged
    in the chat bubble but the SL did NOT move on the chart, and the
    raw TRADE_ACTION marker leaked into the user-visible bubble.
  - Difference: ICLN's marker used strict JSON (double quotes);
    ONON's marker used Python-dict syntax (single quotes) AND/OR
    contained a newline inside the {...} block.

The two regex patterns inside chat_server.py both used `.*?` without
the DOTALL flag, so a single newline inside the JSON broke EVERYTHING.
And `json.loads` rejects single-quoted dicts, so even when the regex
matched, parsing died silently.

Fixes asserted here:
  1. Inner regex now uses `[\\s\\S]*?` — matches across newlines.
  2. `ast.literal_eval` fallback handles single-quoted Python-dict
     emissions safely (no exec, no imports).
  3. The strip regex in the chat handler also uses `[\\s\\S]*?` so
     multi-line markers are scrubbed from the user-facing response.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import chat_server  # noqa: E402


# ── A. Marker regex now matches across newlines ─────────────────────

def test_marker_regex_matches_single_line():
    text = 'Done. <<<TRADE_ACTION: {"action": "move_stop", "symbol": "ICLN", "new_stop": 21.80}>>>'
    m = re.search(r'<<<TRADE_ACTION:\s*(\{[\s\S]*?\})\s*>>>', text)
    assert m is not None
    import json
    assert json.loads(m.group(1))["symbol"] == "ICLN"


def test_marker_regex_matches_multi_line():
    """Pre-v19.34.28 this failed silently because `.*?` doesn't span newlines."""
    text = '''Sure. <<<TRADE_ACTION: {
  "action": "move_stop",
  "symbol": "ONON",
  "new_stop": 35.10,
  "reason": "user_requested"
}>>>'''
    m = re.search(r'<<<TRADE_ACTION:\s*(\{[\s\S]*?\})\s*>>>', text)
    assert m is not None
    import json
    assert json.loads(m.group(1))["new_stop"] == 35.10


# ── B. _execute_trade_action — single-quoted fallback ───────────────

def test_execute_trade_action_accepts_double_quoted_json():
    """The happy path that ICLN took."""
    text = 'Done. <<<TRADE_ACTION: {"action": "close", "symbol": "ICLN"}>>>'
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"success": True, "message": "closed"}
        result = chat_server._execute_trade_action(text)
    assert result["success"] is True


def test_execute_trade_action_accepts_single_quoted_python_dict():
    """The ONON case — LLM emitted Python-dict syntax, not strict JSON.
    
    Pre-v19.34.28 this returned `{"success": False, "error": "Invalid trade action format"}`
    silently. Post-fix, `ast.literal_eval` parses it and the action fires."""
    text = "Got it. <<<TRADE_ACTION: {'action': 'move_stop', 'symbol': 'ONON', 'new_stop': 35.10, 'reason': 'user_requested'}>>>"
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"success": True, "applied": ["moved_stop_to_35.1"]}
        result = chat_server._execute_trade_action(text)
    assert result["success"] is True, f"single-quoted dict should parse, got {result}"
    # Verify the new_stop was extracted correctly (not eaten by string ops)
    call_kwargs = mock_post.call_args[1]
    body = call_kwargs.get("json", {})
    assert body["new_stop"] == 35.10
    assert body["symbol"] == "ONON"


def test_execute_trade_action_accepts_multi_line_marker():
    """Multi-line markers should now parse AND fire the action."""
    text = '''Sure. <<<TRADE_ACTION: {
  "action": "move_stop",
  "symbol": "ONON",
  "new_stop": 35.10
}>>>'''
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"success": True}
        result = chat_server._execute_trade_action(text)
    assert result["success"] is True


def test_execute_trade_action_rejects_genuinely_broken_payload():
    """Defensive: garbage inside the braces should still fail cleanly."""
    text = "Done. <<<TRADE_ACTION: {totally-not-a-dict}>>>"
    result = chat_server._execute_trade_action(text)
    assert result is not None
    assert result["success"] is False
    assert "Invalid trade action format" in result["error"]


def test_execute_trade_action_returns_none_for_no_marker():
    """Plain text with no marker should return None (not error)."""
    assert chat_server._execute_trade_action("just chatting, no action") is None


# ── C. Strip regex scrubs multi-line markers from user-facing text ──

def test_strip_regex_handles_multi_line_marker():
    """The user-facing chat bubble must NOT contain the raw marker
    after stripping, even when the marker spans multiple lines."""
    text = '''Got it. <<<TRADE_ACTION: {
  "action": "move_stop",
  "symbol": "ONON",
  "new_stop": 35.10
}>>> Stop will move shortly.'''
    cleaned = re.sub(r'<<<TRADE_ACTION:[\s\S]*?>>>', '', text).strip()
    assert "TRADE_ACTION" not in cleaned, f"marker leaked: {cleaned!r}"
    assert "Got it." in cleaned
    assert "Stop will move shortly." in cleaned


def test_strip_regex_handles_single_quoted_marker():
    text = "Done. <<<TRADE_ACTION: {'action': 'close', 'symbol': 'X'}>>> All set."
    cleaned = re.sub(r'<<<TRADE_ACTION:[\s\S]*?>>>', '', text).strip()
    assert "TRADE_ACTION" not in cleaned
    assert cleaned == "Done.  All set."


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
