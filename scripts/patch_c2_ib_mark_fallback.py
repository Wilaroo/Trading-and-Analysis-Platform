#!/usr/bin/env python3
"""
patch_c2_ib_mark_fallback.py  —  2026-06-22  (SentCom / DGX Spark)

Fixes the FROZEN open-trade marks (operator diag_c 2026-06-22: 17/25 holds had
current_price pinned at entry → UPL stuck at $0.00) WITHOUT fighting the pusher
L1-subscription cap.

ROOT CAUSE: held names that lose a pusher quote slot get a stale per-symbol
_pushed_at, so position_manager.update_open_positions staleness-guards them out
of the mark update (line ~749 `continue`), leaving current_price frozen at fill.

FIX: IB pushes `marketPrice` + `unrealizedPNL` for EVERY open position every
cycle regardless of L1 quote subscription (sentcom_service already trusts this
source). One surgical edit to backend/services/position_manager.py adds a new
method `_apply_ib_position_marks(bot)` and calls it at the END of
update_open_positions. For any open trade whose mark the quote path could NOT
refresh (missing, or still pinned at fill → UPL≈0) it stamps current_price = IB
marketPrice and recomputes unrealized_pnl / pnl_pct with the EXACT existing
formula. Purely additive — stops still evaluate on the real-time quote path and
fire server-side at IB; this only corrects the stored mark/UPL that the UPL
display, L7 thesis-invalidation and the kill-switch read.

BEHAVIOR NOTE: once these marks are real, the kill-switch's unrealized-P&L sum
reflects the held names' TRUE (possibly negative) drawdown instead of $0. That
is correct risk accounting. Env kill-switch: POSITION_IB_MARK_FALLBACK=0 to
disable instantly.

SAFE: span+sha256 guarded; idempotent; backs up .c2.bak; AST-compiles before
committing. Aborts on drift with a rebase hint. FAIL-OPEN: any error or no
pusher → no-op.

    .venv/bin/python scripts/patch_c2_ib_mark_fallback.py --check
    .venv/bin/python scripts/patch_c2_ib_mark_fallback.py
    .venv/bin/python scripts/patch_c2_ib_mark_fallback.py --rollback
"""
import hashlib
import os
import sys
import ast
import shutil

CANDIDATE_PATHS = [
    "backend/services/position_manager.py",
    "services/position_manager.py",
    os.path.join(os.path.dirname(__file__), "..", "backend", "services", "position_manager.py"),
]

MARKER = "(C2) IB-MARK FALLBACK"
PRE_SHA = "8b3288ec667a4f79abfc5c7a77b1e178f3b583069909700bdff2ae0ef7463866"

OLD = (
    '        except Exception as _e:\n'
    '            logger.debug(f"[v19.34.2 STALE-RESUB] post-loop handler swallowed: {_e}")\n'
    '\n'
    '\n'
    '    # \u2500\u2500\u2500 v19.34 (2026-05-04) \u2014 Mid-bar tick stop-eval \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
    '    async def evaluate_single_trade_against_quote('
)

NEW = (
    '        except Exception as _e:\n'
    '            logger.debug(f"[v19.34.2 STALE-RESUB] post-loop handler swallowed: {_e}")\n'
    '\n'
    '        # 2026-06-22 (C2) IB-MARK FALLBACK call — apply IB authoritative marks\n'
    '        # to held trades whose L1 quote was stale/missing this cycle.\n'
    '        try:\n'
    '            self._apply_ib_position_marks(bot)\n'
    '        except Exception as _ibm_err:\n'
    '            logger.debug(f"(C2) IB-mark fallback skipped: {_ibm_err}")\n'
    '\n'
    '    def _apply_ib_position_marks(self, bot) -> int:\n'
    '        """(C2 2026-06-22) IB-MARK FALLBACK — stamp IB\'s authoritative\n'
    '        marketPrice / unrealizedPNL onto open bot trades whose pushed L1\n'
    '        quote was stale/missing, so UPL, L7 thesis-invalidation and the\n'
    '        kill-switch see a live mark even for held names that lost a pusher\n'
    '        quote slot (operator diag_c 2026-06-22: 17/25 holds FROZEN at entry,\n'
    '        UPL=0). IB pushes a mark for EVERY position every cycle regardless of\n'
    '        L1 subscription, so this bypasses the pusher sub cap entirely\n'
    '        (sentcom_service already trusts the same source). Only corrects marks\n'
    '        the quote path could NOT refresh (missing, or still pinned at fill);\n'
    '        never overrides a mark the quote path moved this cycle. Stops are\n'
    '        unaffected — they evaluate on the real-time quote path and fire\n'
    '        server-side at IB. Env-gated (POSITION_IB_MARK_FALLBACK, default on).\n'
    '        Returns the number of trades marked; never raises into the caller."""\n'
    '        import os as _ibm_os\n'
    '        if _ibm_os.environ.get("POSITION_IB_MARK_FALLBACK", "1").lower() in ("0", "false", "no"):\n'
    '            return 0\n'
    '        try:\n'
    '            from routers.ib import _pushed_ib_data, is_pusher_connected\n'
    '            from services.trading_bot_service import TradeStatus, TradeDirection\n'
    '        except Exception:\n'
    '            return 0\n'
    '        if not is_pusher_connected():\n'
    '            return 0\n'
    '        marks = {}\n'
    '        for _p in (_pushed_ib_data.get("positions") or []):\n'
    '            _sym = (_p.get("symbol") or "").upper()\n'
    '            _qty = float(_p.get("position", 0) or 0)\n'
    '            if not _sym or abs(_qty) < 0.001:\n'
    '                continue\n'
    '            _mp = float(_p.get("marketPrice", _p.get("market_price", 0)) or 0)\n'
    '            if _mp > 0:\n'
    '                marks[(_sym, "long" if _qty > 0 else "short")] = _mp\n'
    '        if not marks:\n'
    '            return 0\n'
    '        fixed = 0\n'
    '        for trade in list(getattr(bot, "_open_trades", {}).values()):\n'
    '            try:\n'
    '                if trade.status != TradeStatus.OPEN:\n'
    '                    continue\n'
    '                fill = float(getattr(trade, "fill_price", 0) or 0)\n'
    '                cur = float(getattr(trade, "current_price", 0) or 0)\n'
    '                # Only fix marks the quote path could not refresh: missing, or\n'
    '                # still pinned at fill (UPL frozen at ~0). Never clobber a mark\n'
    '                # the live quote already moved this cycle.\n'
    '                if cur > 0 and fill > 0 and abs(cur - fill) > 1e-6:\n'
    '                    continue\n'
    '                _dir = "long" if trade.direction == TradeDirection.LONG else "short"\n'
    '                mp = marks.get((trade.symbol.upper(), _dir))\n'
    '                if not mp or fill <= 0:\n'
    '                    continue\n'
    '                rs = float(getattr(trade, "remaining_shares", 0) or 0)\n'
    '                trade.current_price = mp\n'
    '                trade.unrealized_pnl = (mp - fill) * rs if _dir == "long" else (fill - mp) * rs\n'
    '                orig_shares = float(getattr(trade, "original_shares", 0) or 0)\n'
    '                if orig_shares > 0:\n'
    '                    trade.pnl_pct = ((trade.unrealized_pnl + float(getattr(trade, "realized_pnl", 0) or 0)) / (orig_shares * fill)) * 100\n'
    '                fixed += 1\n'
    '            except Exception:\n'
    '                continue\n'
    '        if fixed:\n'
    '            logger.info(f"(C2) IB-mark fallback: stamped live IB mark on {fixed} held trade(s) with stale/frozen quotes")\n'
    '        return fixed\n'
    '\n'
    '    # \u2500\u2500\u2500 v19.34 (2026-05-04) \u2014 Mid-bar tick stop-eval \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
    '    async def evaluate_single_trade_against_quote('
)


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _find_path():
    p = next((c for c in CANDIDATE_PATHS if os.path.isfile(c)), None)
    if not p:
        print("ERROR: position_manager.py not found. Run from the repo root.")
        sys.exit(2)
    return os.path.abspath(p)


def rollback():
    path = _find_path()
    bak = path + ".c2.bak"
    if not os.path.isfile(bak):
        print(f"No backup at {bak} — nothing to roll back.")
        sys.exit(1)
    shutil.copy2(bak, path)
    print(f"Rolled back {path} from {bak}.")


def main(check_only=False):
    path = _find_path()
    content = open(path, encoding="utf-8").read()
    print(f"Target: {path}")
    print(f"PRE  whole-file sha256: {_sha(content)}")

    if MARKER in content:
        print("  idempotent marker present — already applied. \u2705")
        return
    if content.count(OLD) != 1:
        print(f"  ABORT — anchor not unique (count={content.count(OLD)}). No changes written.")
        print("    rebase: grep -n -B1 -A8 'STALE-RESUB] post-loop handler swallowed' "
              "backend/services/position_manager.py")
        sys.exit(1)
    actual = _sha(OLD)
    if actual != PRE_SHA:
        print(f"  ABORT — span sha drift.\n      expected {PRE_SHA}\n      actual   {actual}\n"
              "    No changes written. Paste the grep above and I'll rebase.")
        sys.exit(1)

    new_content = content.replace(OLD, NEW, 1)
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        print(f"  ABORT — patched content failed to parse: {e}. No changes written.")
        sys.exit(1)

    if check_only:
        print("  --check OK: span verified; patched file AST-compiles.")
        print(f"  PREDICTED POST whole-file sha256: {_sha(new_content)}")
        print("  (no changes written)")
        return

    bak = path + ".c2.bak"
    shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  span verified ({PRE_SHA[:12]}\u2026) -> added _apply_ib_position_marks + call.")
    print(f"Backup written: {bak}")
    print(f"POST whole-file sha256: {_sha(new_content)}")
    print("\u2705 patch_c2 applied. Restart the backend: ./start_backend.sh --force")
    print("   Kill switch: POSITION_IB_MARK_FALLBACK=0 in backend/.env to disable.")


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback()
    else:
        main(check_only=("--check" in sys.argv))
