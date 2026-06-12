#!/usr/bin/env python3
"""
apply_v322z.py — Idempotent applier for v322z (chat data-trust fixes)
=====================================================================
Driven by the 2026-06-12 chat audit (SNDK conversation). The chat server
already injects 16 context sections, but four recall gaps were found:

  1. COLD-SYMBOL SILENCE (the SNDK bug): user-mentioned tickers are
     hydrated via /api/live/symbol-snapshot + /api/technicals with a 2s
     timeout. A cold symbol must round-trip the pusher RPC to IB and
     routinely needs >2s; on timeout the row was SILENTLY skipped, the
     "never guess prices" rule fired, and the assistant implied it
     doesn't track the symbol. Fix: 6s budget for user-mentioned tickers
     + an explicit "LIVE QUOTE FETCH FAILED for: X" context line.

  2. STALE HARDCODED RISK PARAMS: section 10 injected a static
     "$2,500 max risk/trade, 1.5:1 min R:R" string that drifted from the
     bot's actual config. Fix: fetch live risk_params from
     /api/trading-bot/status; on failure tell the LLM NOT to quote
     numbers. System-prompt risk-cap rule now defers to the live figure.

  3. NO DECISION-TRAIL RECALL: the "Bot thoughts" stream
     (sentcom_thoughts, TTL 7d) was not in context, so "why did you pass
     on ADBE?" was unanswerable. Fix: new section 10.7 injects the last
     1h global trail (12 rows) + last-24h per-symbol trail (8 rows) for
     each user-mentioned ticker.

  4. LOWERCASE MENTIONS MISSED: "thoughts on sndk today?" (all
     lowercase) extracted nothing — regex was uppercase-only. Fix: when
     NO uppercase candidate is found, run a lowercase pass validated
     against a cached known-symbol set (ib_historical_data.distinct)
     AND an English stopword list, so "it"/"on"/"all" never promote.

  Minor: closed-trades context now sorts by closed_at (was created_at);
  bot-tracked trade lines now carry TQS grade + trade_style so the chat
  matches the position card.

Touches ONLY backend/chat_server.py + writes
backend/tests/test_v322z_chat_context.py.

SAFE TO RUN MULTIPLE TIMES (guarded by the v322z marker).
After commit, RESTART THE CHAT SERVER (port 8002) to pick it up.

Run from repo root:  .venv/bin/python /tmp/apply_v322z.py
Then: git add -A && git commit -m "v322z: chat data-trust fixes" && git push
(commit BEFORE restarting — StartTrading.bat does `git checkout -- .`)
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "v322z"

# Each entry: (name, OLD, NEW). OLD must appear EXACTLY ONCE.
CHUNKS = []

# ── 1. known-symbol cache helper + stopwords (before the extractor) ────────
CHUNKS.append(("known_symbol_helper", '''def _extract_user_mentioned_tickers(user_message: Optional[str], limit: int = 5) -> list:
''', '''# ── v322z — known-symbol cache for lowercase ticker extraction ──────────────
_KNOWN_SYMBOLS_CACHE: dict = {"at": 0.0, "symbols": set()}

# Lowercase English words that collide with real tickers — never promote
# these from a lowercase pass ("it" → IT, "on" → ON, "all" → ALL, ...).
_LOWERCASE_STOPWORDS = {
    "a", "an", "all", "am", "and", "any", "are", "as", "at", "be", "big",
    "bid", "but", "buy", "by", "can", "day", "did", "do", "for", "get",
    "go", "good", "had", "has", "he", "her", "him", "his", "hold", "how",
    "if", "in", "is", "it", "its", "just", "key", "last", "let", "like",
    "long", "low", "main", "make", "may", "me", "min", "more", "most",
    "my", "new", "next", "no", "not", "now", "of", "off", "ok", "on",
    "one", "or", "our", "out", "over", "own", "per", "post", "pre",
    "real", "run", "see", "sell", "so", "some", "stop", "take", "than",
    "that", "the", "them", "then", "they", "this", "to", "top", "trade",
    "two", "up", "us", "very", "was", "we", "well", "were", "what",
    "when", "who", "why", "will", "with", "yes", "you", "your",
}


def _known_symbols_cached(ttl_s: float = 3600.0) -> set:
    """v322z — cached set of symbols the platform has bar data for.
    Validates lowercase ticker mentions ("thoughts on sndk?") without
    promoting plain English words to tickers. Best-effort: returns an
    empty set on failure, which simply disables the lowercase pass."""
    now = time.time()
    if _KNOWN_SYMBOLS_CACHE["symbols"] and now - _KNOWN_SYMBOLS_CACHE["at"] < ttl_s:
        return _KNOWN_SYMBOLS_CACHE["symbols"]
    try:
        syms = set(db["ib_historical_data"].distinct("symbol"))
        if syms:
            _KNOWN_SYMBOLS_CACHE["symbols"] = syms
            _KNOWN_SYMBOLS_CACHE["at"] = now
    except Exception as e:
        logger.debug(f"v322z known-symbol cache refresh failed: {e}")
    return _KNOWN_SYMBOLS_CACHE["symbols"]


def _extract_user_mentioned_tickers(user_message: Optional[str], limit: int = 5) -> list:
'''))

# ── 2. lowercase mention rescue inside the extractor ───────────────────────
CHUNKS.append(("lowercase_rescue", '''        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break
    return out
''', '''        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break

    # ── v322z — lowercase mention rescue ("thoughts on sndk today?") ──
    # The uppercase-only regex missed entirely-lowercase messages. Only
    # runs when NO uppercase candidate was found, and every candidate
    # must clear the stopword list AND exist in the known-symbol set.
    if not out:
        known = _known_symbols_cached()
        if known:
            for match in re.findall(r"\\b[a-z][a-z0-9.]{1,4}\\b", user_message or ""):
                if match in _LOWERCASE_STOPWORDS:
                    continue
                token = match.upper()
                if token in denylist or token in seen or token not in known:
                    continue
                seen.add(token)
                out.append(token)
                if len(out) >= limit:
                    break
    return out
'''))

# ── 3. lazy-reconcile projection gains grade/style fields ──────────────────
CHUNKS.append(("lazy_projection", '''                            "setup_type": 1,
                            "shares": 1,
                            "status": 1,
                            "created_at": 1,
                        },
''', '''                            "setup_type": 1,
                            "shares": 1,
                            "status": 1,
                            "created_at": 1,
                            # v322z — grade/style so chat matches the card
                            "tqs_grade": 1,
                            "unified_grade": 1,
                            "trade_style": 1,
                        },
'''))

# ── 4. lazy-reconcile dict carries grade/style ─────────────────────────────
CHUNKS.append(("lazy_dict", '''                        "shares": int(abs(qty)) or bt_doc.get("shares", 0),
                        "_lazy_reconciled": True,
''', '''                        "shares": int(abs(qty)) or bt_doc.get("shares", 0),
                        "tqs_grade": bt_doc.get("tqs_grade") or bt_doc.get("unified_grade") or "",
                        "trade_style": bt_doc.get("trade_style") or "",
                        "_lazy_reconciled": True,
'''))

# ── 5. bot-trade context lines show TQS grade + style ──────────────────────
CHUNKS.append(("bot_lines_grade", '''                    setup = bt.get("setup_type", "")
                    shares = bt.get("shares", 0)
                    target_str = ", ".join([f"${t:.2f}" for t in targets[:2]]) if targets else "none"
                    bot_lines.append(
                        f"  {sym} ({d}): {shares} shares, entry=${entry:.2f}, "
                        f"stop=${stop:.2f}, targets=[{target_str}] — {setup}"
                    )
''', '''                    setup = bt.get("setup_type", "")
                    shares = bt.get("shares", 0)
                    # v322z — surface TQS grade + trade style so the chat
                    # describes the trade the same way the position card does.
                    grade = bt.get("tqs_grade") or bt.get("unified_grade") or ""
                    style = bt.get("trade_style") or ""
                    extra = (f", TQS {grade}" if grade else "") + (f", {style}" if style else "")
                    target_str = ", ".join([f"${t:.2f}" for t in targets[:2]]) if targets else "none"
                    bot_lines.append(
                        f"  {sym} ({d}): {shares} shares, entry=${entry:.2f}, "
                        f"stop=${stop:.2f}, targets=[{target_str}] — {setup}{extra}"
                    )
'''))

# ── 6. closed-trades context sorted by closed_at ───────────────────────────
CHUNKS.append(("closed_sort", '''                   "close_reason": 1, "created_at": 1})
            .sort("created_at", -1)
            .limit(15)
''', '''                   "close_reason": 1, "created_at": 1, "closed_at": 1})
            .sort("closed_at", -1)  # v322z — recency of CLOSE, not creation
            .limit(15)
'''))

# ── 7. live risk params instead of the stale hardcoded string ──────────────
CHUNKS.append(("live_risk_params", '''    # 10. Bot risk parameters
    try:
        parts.append(
            "Risk Parameters: $2,500 max risk/trade, 1.5:1 min R:R, "
            "50% max position size, 10 max open positions, 1% max daily loss"
        )
    except Exception:
        pass
''', '''    # 10. Bot risk parameters — v322z: LIVE from the trading bot's actual
    # config instead of a hardcoded string. The old static "$2,500 max
    # risk/trade, 1.5:1 min R:R" line drifted from reality and the
    # assistant recited it as gospel (SNDK conversation, 2026-06-12).
    try:
        _rp = {}
        try:
            _rp_resp = requests.get(
                "http://127.0.0.1:8001/api/trading-bot/status", timeout=3)
            if _rp_resp.status_code == 200:
                _rp = (_rp_resp.json() or {}).get("risk_params") or {}
        except Exception:
            _rp = {}
        if _rp:
            _rp_bits = []
            if _rp.get("max_risk_per_trade") is not None:
                _rp_bits.append(f"max risk/trade ${float(_rp['max_risk_per_trade']):,.0f}")
            if _rp.get("min_risk_reward") is not None:
                _rp_bits.append(f"min R:R {_rp['min_risk_reward']}:1")
            if _rp.get("max_open_positions") is not None:
                _rp_bits.append(f"max open positions {_rp['max_open_positions']}")
            if _rp.get("max_daily_loss") is not None:
                _rp_bits.append(f"max daily loss ${float(_rp['max_daily_loss']):,.0f}")
            if _rp_bits:
                parts.append(
                    "Bot Risk Parameters (LIVE config — quote THESE numbers, "
                    "they override any defaults): " + ", ".join(_rp_bits))
        if not _rp:
            parts.append(
                "Bot Risk Parameters: live config fetch failed — do NOT quote "
                "specific risk numbers; say the live config is temporarily "
                "unavailable.")
    except Exception:
        pass
'''))

# ── 8. snapshot loop: 6s for mentioned tickers + explicit failure line ─────
CHUNKS.append(("snapshot_failures", '''        _snap_lines = []
        # Bumped from 10 → 15 so the user-mentioned tickers don't get
        # truncated when the operator already has 6+ open positions.
        for _sym in _live_snapshot_targets[:15]:
            try:
                _r = _live_req.get(
                    f"http://127.0.0.1:8001/api/live/symbol-snapshot/{_sym}",
                    timeout=2,
                )
                if _r.status_code == 200:
                    _d = _r.json()
                    if _d.get("success"):
                        _price = _d.get("latest_price")
                        _chg = _d.get("change_pct")
                        _bar_ts = _d.get("latest_bar_time") or "unknown"
                        _state = _d.get("market_state") or "?"
                        _src = _d.get("source") or "?"
                        if _price is not None and _chg is not None:
                            _sign = "+" if _chg >= 0 else ""
                            _snap_lines.append(
                                f"  {_sym} ${_price:.2f} {_sign}{_chg:.2f}% "
                                f"(bar {_bar_ts}, {_state}, {_src})"
                            )
            except Exception:
                pass
''', '''        _snap_lines = []
        _snap_failed = []  # v322z — user-mentioned symbols whose fetch failed
        # Bumped from 10 → 15 so the user-mentioned tickers don't get
        # truncated when the operator already has 6+ open positions.
        for _sym in _live_snapshot_targets[:15]:
            _got_line = False
            try:
                # v322z — user-mentioned tickers get a 6s budget: a cold
                # symbol (not held/subscribed) must round-trip the pusher
                # RPC to IB and routinely needs >2s. 2s stays for the
                # held/index bulk so a dead pusher can't stall the chat.
                _r = _live_req.get(
                    f"http://127.0.0.1:8001/api/live/symbol-snapshot/{_sym}",
                    timeout=(6 if _sym in user_mentioned_tickers else 2),
                )
                if _r.status_code == 200:
                    _d = _r.json()
                    if _d.get("success"):
                        _price = _d.get("latest_price")
                        _chg = _d.get("change_pct")
                        _bar_ts = _d.get("latest_bar_time") or "unknown"
                        _state = _d.get("market_state") or "?"
                        _src = _d.get("source") or "?"
                        if _price is not None and _chg is not None:
                            _sign = "+" if _chg >= 0 else ""
                            _snap_lines.append(
                                f"  {_sym} ${_price:.2f} {_sign}{_chg:.2f}% "
                                f"(bar {_bar_ts}, {_state}, {_src})"
                            )
                            _got_line = True
            except Exception:
                pass
            if not _got_line and _sym in user_mentioned_tickers:
                _snap_failed.append(_sym)
        if _snap_failed:
            # v322z — tell the LLM the fetch FAILED instead of silence.
            # Silence + the "never guess prices" rule made the assistant
            # imply it doesn't track the symbol at all (SNDK incident).
            parts.append(
                "LIVE QUOTE FETCH FAILED for: " + ", ".join(_snap_failed)
                + " — the live data fetch timed out or errored; the symbol "
                  "itself may be fine. Say the live quote fetch failed just "
                  "now and to ask again in a moment — do NOT imply the "
                  "symbol is untracked or unknown."
            )
'''))

# ── 9. decision-trail section (before section 11) ──────────────────────────
CHUNKS.append(("decision_trail", '''    # 11. Technical indicators for held positions (RSI, VWAP, EMAs, squeeze, etc.)
''', '''    # 10.7. v322z — Bot decision trail (sentcom_thoughts recall)
    # The operator watches the "Bot thoughts" stream in the UI, but the
    # chat assistant had NO access to it — "why did you pass on ADBE?"
    # was unanswerable. Inject the recent global trail plus a deeper
    # per-symbol trail for tickers the operator just mentioned.
    try:
        _trail_lines = []
        _cut_1h = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        _glob_thoughts = list(db["sentcom_thoughts"].find(
            {"timestamp": {"$gte": _cut_1h}},
            {"_id": 0, "content": 1, "symbol": 1, "timestamp": 1},
        ).sort("timestamp", -1).limit(12))
        for _t in reversed(_glob_thoughts):
            _trail_lines.append(
                f"  [{str(_t.get('timestamp') or '')[11:19]}] "
                f"{str(_t.get('content') or '')[:110]}")
        _cut_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        for _um in user_mentioned_tickers:
            _sym_rows = list(db["sentcom_thoughts"].find(
                {"symbol": _um, "timestamp": {"$gte": _cut_24h}},
                {"_id": 0, "content": 1, "timestamp": 1},
            ).sort("timestamp", -1).limit(8))
            if _sym_rows:
                _trail_lines.append(f"  {_um} trail (last 24h):")
                for _t in reversed(_sym_rows):
                    _trail_lines.append(
                        f"    [{str(_t.get('timestamp') or '')[11:19]}] "
                        f"{str(_t.get('content') or '')[:110]}")
        if _trail_lines:
            parts.append(
                "Bot Decision Trail (my own recent evaluations/passes/fills — "
                "use these to answer 'why did you pass/enter/skip X'):\\n"
                + "\\n".join(_trail_lines))
        debug["thought_trail_lines"] = len(_trail_lines)
    except Exception as e:
        debug["thought_trail_error"] = str(e)

    # 11. Technical indicators for held positions (RSI, VWAP, EMAs, squeeze, etc.)
'''))

# ── 10. technicals fetch: 6s budget for mentioned tickers ──────────────────
CHUNKS.append(("technicals_timeout", '''                resp = requests.get(f"http://127.0.0.1:8001/api/technicals/{sym}", timeout=2)
''', '''                # v322z — 6s budget for user-mentioned tickers (cold-symbol
                # technicals can exceed 2s), 2s for the held/index bulk.
                resp = requests.get(
                    f"http://127.0.0.1:8001/api/technicals/{sym}",
                    timeout=(6 if sym in user_mentioned_tickers else 2),
                )
'''))

# ── 11. system-prompt risk-cap rule defers to live config ──────────────────
CHUNKS.append(("prompt_risk_rule", '''- Per-trade risk cap: `max(0.01 × equity, $2,500)`. Example: at $237K equity, max risk ≈ $2,370 → use $2,500. At $400K equity, max risk = $4,000.
''', '''- Per-trade risk cap: when the LIVE DATA includes "Bot Risk Parameters (LIVE config)", use THAT max-risk figure — it is the bot's actual setting. Only if the live line is missing, fall back to `max(0.01 × equity, $2,500)`.
'''))


TEST_REL = Path("backend") / "tests" / "test_v322z_chat_context.py"

TEST_CONTENT = '''"""v322z — chat data-trust fixes (2026-06-12 SNDK audit).

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
'''


def _repo_root() -> Path:
    for c in (Path.cwd(), Path.home() / "Trading-and-Analysis-Platform"):
        if (c / "backend" / "chat_server.py").exists():
            return c
    print("ERROR: could not locate repo root."); sys.exit(1)


def main() -> None:
    root = _repo_root()
    path = root / "backend" / "chat_server.py"
    text = path.read_text()

    if MARKER in text:
        print("⏭  chat_server.py already patched (no-op).")
    else:
        # Pre-flight: every anchor must match exactly once BEFORE writing.
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
        print(f"✓ v322z applied to chat_server.py ({len(CHUNKS)} chunks)")

    import py_compile
    py_compile.compile(str(path), doraise=True)
    print("✓ chat_server.py compiles")

    test_path = root / TEST_REL
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST_CONTENT)
    print(f"✓ wrote {TEST_REL}")

    print("\nNext:")
    print("  .venv/bin/python -m pytest backend/tests/test_v322z_chat_context.py -q")
    print('  git add -A && git commit -m "v322z: chat data-trust fixes" && git push')
    print("  RESTART the chat server process (port 8002) to pick up the change.")
    print("  (commit BEFORE restarting — StartTrading.bat does git checkout -- .)")


if __name__ == "__main__":
    main()
