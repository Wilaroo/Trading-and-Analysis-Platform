#!/usr/bin/env python3
"""
apply_v335.py — EOD T-2 ESCALATION + ALL STALE-ATTR EOD PATHS → POLICY
=======================================================================
PROBE VERDICT (diag_eod_pusher, 2026-06-12 post-close): v334b held the
multi_day book at the 15:45 main pass, but the 15:47 T-2 force-MKT
escalation flattened ORCL (multi_day/opening_drive) and SMCI
(multi_day/fashionably_late) anyway — it selected victims via the STALE
per-trade `close_at_eod` attribute (default True), the exact attribute
v19.34.245/v334b deprecated for the main path.

FIX — 4 consumers of the stale attr now route through
should_close_at_eod() (the policy authority):
  1. _eod_t_minus_2_escalate  — the actual flattener (CRITICAL)
  2. _eod_t_minus_1_alert     — no more false CRITICAL on legit holds
  3. EOD status endpoint      — correct intraday/swing-holding UI counts
  4. morning readiness        — overnight holds no longer flagged "stuck"
     (without this, CPB/PENN/DKNG trip a RED morning report tomorrow)

SAFE TO RUN MULTIPLE TIMES (idempotent). No DB phase.
Run from repo root:   .venv/bin/python /tmp/apply_v335.py
Then: git add -A && git commit -m "v335: EOD T-2/T-1/status/readiness via policy authority" && git push
Then RESTART the backend.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHUNKS = [
    ('backend/services/position_manager.py',
     '        still_open = [\n            (tid, t) for tid, t in list(bot._open_trades.items())\n            if getattr(t, "close_at_eod", True)\n        ]\n',
     '        # v335 — select via the POLICY authority, not the stale per-trade\n        # attr (probe 2026-06-12: T-2 force-MKT flattened ORCL/SMCI\n        # multi_day holds at 15:47 via close_at_eod_attr=True while the\n        # v334b policy path correctly held them at 15:45).\n        from services.order_policy_registry import should_close_at_eod as _scae_t2\n        still_open = [\n            (tid, t) for tid, t in list(bot._open_trades.items())\n            if _scae_t2(t)\n        ]\n'),
    ('backend/services/position_manager.py',
     '        tracked_open = [\n            t for t in bot._open_trades.values()\n            if getattr(t, "close_at_eod", True)\n        ]\n',
     '        # v335 — policy authority (stale per-trade attr falsely alarmed\n        # on legit overnight holds carried post-v334b).\n        from services.order_policy_registry import should_close_at_eod as _scae_t1\n        tracked_open = [\n            t for t in bot._open_trades.values()\n            if _scae_t1(t)\n        ]\n'),
    ('backend/routers/trading_bot.py',
     '    for trade in _trading_bot._open_trades.values():\n        if getattr(trade, "close_at_eod", True):\n            intraday_queued += 1\n',
     '    # v335 — policy authority, not the stale per-trade attr\n    from services.order_policy_registry import should_close_at_eod as _scae_status\n    for trade in _trading_bot._open_trades.values():\n        if _scae_status(trade):\n            intraday_queued += 1\n'),
    ('backend/services/morning_readiness_service.py',
     '    for tid, trade in (bot._open_trades or {}).items():\n        close_at_eod = getattr(trade, "close_at_eod", True)\n',
     '    # v335 — policy authority, not the stale per-trade attr (multi_day\n    # holds carried overnight post-v334b were falsely flagged "stuck").\n    from services.order_policy_registry import should_close_at_eod as _scae_morning\n    for tid, trade in (bot._open_trades or {}).items():\n        close_at_eod = _scae_morning(trade)\n'),
]

TEST_REL = 'backend/tests/test_v335_eod_policy_consumers.py'
TEST_CONTENT = '"""v335 — EVERY EOD path selects victims via the policy authority\n(should_close_at_eod), not the stale per-trade `close_at_eod` attribute.\n\nProbe evidence (diag_eod_pusher, 2026-06-12): the 15:45 v162 main pass\n(policy-based since v334b) correctly held multi_day positions, but the\n15:47 T-2 force-MKT escalation read `getattr(t, "close_at_eod", True)`\nand flattened ORCL (multi_day/opening_drive) and SMCI\n(multi_day/fashionably_late) anyway. Same stale-attr bug class in the\nT-1 alert, the EOD status endpoint, and morning readiness.\n"""\nimport asyncio\nfrom pathlib import Path\nfrom types import SimpleNamespace\nimport sys\n\n\ndef _repo_root():\n    for c in Path(__file__).resolve().parents:\n        if (c / "backend" / "services" / "position_manager.py").exists():\n            return c\n    raise AssertionError("repo root not found")\n\n\nROOT = _repo_root()\nsys.path.insert(0, str(ROOT / "backend"))\n\nfrom services.position_manager import PositionManager  # noqa: E402\n\n\ndef _t(symbol, style, setup=None):\n    # close_at_eod=True on EVERY trade — the stale attr the old code read.\n    # Policy must override it for long-horizon styles/setups.\n    return SimpleNamespace(symbol=symbol, trade_style=style, setup_type=setup,\n                           setup_variant=None, timeframe=None,\n                           close_at_eod=True, direction=None)\n\n\ndef _bot(trades):\n    async def _broadcast(_evt):\n        pass\n    return SimpleNamespace(\n        _open_trades={f"tid_{t.symbol}": t for t in trades},\n        _db=None,\n        _broadcast_event=_broadcast,\n        _eod_t_minus_2_fired_today=None,\n        _eod_t_minus_1_alerted_today=None,\n    )\n\n\nMIXED = [\n    _t("ORCL", "multi_day", "opening_drive"),        # explicit hold (06-12 victim)\n    _t("SMCI", "multi_day", "fashionably_late"),     # explicit hold (06-12 victim)\n    _t("CRS", "trade_2_hold", "daily_breakout"),     # v334b setup-horizon hold\n    _t("AAL", "intraday", "fashionably_late"),       # legit close\n    _t("CZR", "trade_2_hold", "orb"),                # legit close (orb→intraday)\n]\n\n\n# ── 1. T-2 force-MKT escalation ──────────────────────────────────────────\n\ndef test_t2_escalate_skips_policy_holds():\n    pm = PositionManager.__new__(PositionManager)\n    closed = []\n\n    async def _close(tid, bot, reason=None, **kw):\n        closed.append(bot._open_trades[tid].symbol)\n        return True\n    pm.close_trade = _close\n\n    bot = _bot(MIXED)\n    res = asyncio.run(pm._eod_t_minus_2_escalate(bot))\n    assert sorted(closed) == ["AAL", "CZR"], closed\n    assert sorted(res["escalated"]) == ["AAL", "CZR"]\n    assert res["errors"] == []\n\n\ndef test_t2_escalate_noop_when_only_holds():\n    pm = PositionManager.__new__(PositionManager)\n\n    async def _close(tid, bot, reason=None, **kw):\n        raise AssertionError("close_trade must not be called for holds")\n    pm.close_trade = _close\n\n    bot = _bot([_t("ORCL", "multi_day", "opening_drive"),\n                _t("CRS", "trade_2_hold", "daily_breakout")])\n    res = asyncio.run(pm._eod_t_minus_2_escalate(bot))\n    assert res.get("noop") is True\n    assert res["escalated"] == []\n\n\ndef test_t2_escalate_idempotent_per_day():\n    pm = PositionManager.__new__(PositionManager)\n    calls = []\n\n    async def _close(tid, bot, reason=None, **kw):\n        calls.append(tid)\n        return True\n    pm.close_trade = _close\n\n    bot = _bot([_t("AAL", "intraday")])\n    asyncio.run(pm._eod_t_minus_2_escalate(bot))\n    res2 = asyncio.run(pm._eod_t_minus_2_escalate(bot))\n    assert res2.get("noop") is True\n    assert len(calls) == 1\n\n\n# ── 2. T-1 alert ─────────────────────────────────────────────────────────\n\ndef test_t1_alert_silent_when_only_holds():\n    pm = PositionManager.__new__(PositionManager)\n    pm._ib_position_snapshot_safe = lambda: []\n\n    bot = _bot([_t("ORCL", "multi_day", "opening_drive"),\n                _t("CRS", "trade_2_hold", "stage_2_breakout")])\n    broadcasts = []\n\n    async def _broadcast(evt):\n        broadcasts.append(evt)\n    bot._broadcast_event = _broadcast\n\n    asyncio.run(pm._eod_t_minus_1_alert(bot))\n    assert broadcasts == []          # no false CRITICAL for legit holds\n    assert bot._eod_t_minus_1_alerted_today is not None\n\n\ndef test_t1_alert_fires_for_intraday_straggler():\n    pm = PositionManager.__new__(PositionManager)\n    pm._ib_position_snapshot_safe = lambda: []\n\n    bot = _bot([_t("ORCL", "multi_day", "opening_drive"),\n                _t("AAL", "intraday")])\n    broadcasts = []\n\n    async def _broadcast(evt):\n        broadcasts.append(evt)\n    bot._broadcast_event = _broadcast\n\n    asyncio.run(pm._eod_t_minus_1_alert(bot))\n    assert len(broadcasts) == 1\n    assert broadcasts[0]["tracked_open"] == ["AAL"]   # holds excluded\n\n\n# ── 3. morning readiness — holds carried overnight are NOT "stuck" ──────\n\ndef test_morning_readiness_holds_not_stuck():\n    from services.morning_readiness_service import _check_open_positions_clean\n    holds = [_t("CPB", "multi_day", "daily_breakout"),\n             _t("PENN", "multi_day", "daily_breakout"),\n             _t("DKNG", "multi_day", "squeeze")]\n    for h in holds:\n        h.opened_at = "2026-06-12T15:00:00+00:00"   # opened YESTERDAY\n    bot = _bot(holds)\n    res = _check_open_positions_clean(None, bot=bot)\n    assert res["status"] != "red", res\n    assert not res.get("stuck_positions"), res\n\n\n# ── 4. source-level: no stale-attr selection left at the 4 sites ─────────\n\ndef test_no_stale_attr_selection_in_eod_paths():\n    pm_src = (ROOT / "backend/services/position_manager.py").read_text()\n    assert \'if getattr(t, "close_at_eod", True)\' not in pm_src\n    rt_src = (ROOT / "backend/routers/trading_bot.py").read_text()\n    assert "_scae_status" in rt_src\n    mr_src = (ROOT / "backend/services/morning_readiness_service.py").read_text()\n    assert "_scae_morning" in mr_src\n    assert \'close_at_eod = getattr(trade, "close_at_eod", True)\' not in mr_src\n'


def find_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / "backend" / "services" / "position_manager.py").exists():
            return cand
    print("FATAL: run from repo root")
    sys.exit(1)


def main():
    root = find_root()
    print(f"repo root: {root}")
    if not CHUNKS:
        print("[FATAL] CHUNKS is empty — refusing to run an empty patcher (v334 lesson).")
        sys.exit(9)

    applied = 0
    for rel, old, new in CHUNKS:
        path = root / rel
        text = path.read_text()
        if new in text:
            print(f"[SKIP] {rel} — already applied")
            continue
        n = text.count(old)
        if n != 1:
            print(f"[FAIL] {rel} — anchor found {n}x. ABORTING.")
            sys.exit(2)
        path.write_text(text.replace(old, new, 1))
        applied += 1
        print(f"[OK]   {rel} — chunk applied")
    tp = root / TEST_REL
    if not (tp.exists() and tp.read_text() == TEST_CONTENT):
        tp.write_text(TEST_CONTENT)
        applied += 1
        print(f"[OK]   {TEST_REL} — written")
    else:
        print(f"[SKIP] {TEST_REL} — already present")

    print()
    print("── self-test: pytest ──")
    tests = ["tests/test_v335_eod_policy_consumers.py",
             "tests/test_v334_policy_resolution.py",
             "tests/test_eod_naked_flatten_guard_v301.py",
             "tests/test_eod_force_flatten_bracketed_v302.py",
             "tests/test_v332_regime_demotion.py"]
    existing = [t for t in tests if (root / "backend" / t).exists()]
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", *existing],
                       cwd=str(root / "backend"),
                       capture_output=True, text=True, timeout=300)
    for line in (r.stdout or "").strip().splitlines()[-3:]:
        print("   " + line)
    if r.returncode != 0:
        print("[FAIL] self-test failed — NOT safe to restart.")
        print((r.stdout or "")[-2000:])
        sys.exit(3)
    print("[OK]   self-test PASSED")
    print()
    print(f"v335 done — {applied} item(s) newly applied.")
    print("  git add -A && git commit -m 'v335: EOD T-2/T-1/status/readiness via policy authority' && git push")
    print("  RESTART the backend.")


if __name__ == "__main__":
    main()
