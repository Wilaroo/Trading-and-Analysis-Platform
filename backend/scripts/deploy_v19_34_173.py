"""v19.34.173 — F-grade gate + learning_only flag.

Three small, surgical edits:

1. ``services/opportunity_evaluator.py`` — early gate that calls
   ``setup_grading_service.get_grade_warning(setup_type)`` and rejects
   the alert when the setup_type is graded F over the rolling 30d
   window. Records the drop in ``trade_drops`` with reason code
   ``setup_grade_f_block`` so the operator can see how many alerts
   the gate filtered.

   Env-tunable via ``F_GRADE_POLICY``:
     * ``block`` (default) — reject the alert, no trade.
     * ``micro``           — keep trading at 0.1x, tag
                             ``alert['learning_only']=True``.
     * ``full``            — pre-v173 behaviour (no gate, full sizing).

2. ``services/opportunity_evaluator.py`` — ``build_entry_context``
   propagates the ``learning_only`` flag into ``entry_context`` so
   the field is persisted to ``bot_trades`` on entry.

3. ``services/setup_grading_service.py`` — ``_aggregate_day``
   excludes ``learning_only=True`` trades from grade aggregation.
   Stops the cost-poisoned feedback loop (micro F trades booked
   commission-loss R, polluting their own grade, keeping them F).

Idempotent. Re-running is safe.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # backend/
OE = os.path.join(ROOT, "services", "opportunity_evaluator.py")
SG = os.path.join(ROOT, "services", "setup_grading_service.py")


# ── opportunity_evaluator: F-gate (inserted just after direction extraction) ──
OE_ANCHOR_A_OLD = '''        try:
            symbol = alert.get('symbol')
            setup_type = alert.get('setup_type')
            direction_str = alert.get('direction', 'long')
            direction = TradeDirection.LONG if direction_str == 'long' else TradeDirection.SHORT

            # ── v19.34.44 — Stale Alert TTL (default 30s) ─────────────'''

OE_ANCHOR_A_NEW = '''        try:
            symbol = alert.get('symbol')
            setup_type = alert.get('setup_type')
            direction_str = alert.get('direction', 'long')
            direction = TradeDirection.LONG if direction_str == 'long' else TradeDirection.SHORT

            # ── v19.34.173 — Setup-grade F-gate ──────────────────────
            # Block alerts whose setup_type is graded F over the
            # rolling 30d window. The previous behaviour was
            # observe-only (label-only, no block). Operator confirmed
            # default = block. Env-tunable to "micro" (keep current
            # 0.1x sizing + mark `learning_only=True`) or "full"
            # (ignore grade — pre-v173 behaviour).
            #
            # Trades dropped here land in `trade_drops` with reason
            # code `setup_grade_f_block` so the operator can see how
            # many alerts the gate filtered.
            try:
                import os as _os_fg
                _f_policy = (_os_fg.environ.get("F_GRADE_POLICY", "block") or "block").lower().strip()
                if _f_policy not in ("block", "micro", "full"):
                    _f_policy = "block"
                if _f_policy != "full" and setup_type:
                    from services.setup_grading_service import get_setup_grading_service
                    _grade_svc = get_setup_grading_service()
                    _setup_grade = _grade_svc.get_grade_warning(setup_type)
                    if _setup_grade == "F":
                        if _f_policy == "block":
                            try:
                                bot.record_rejection(
                                    symbol=symbol, setup_type=setup_type,
                                    direction=direction_str,
                                    reason_code="setup_grade_f_block",
                                    context={
                                        "policy": "v19.34.173_f_gate_block",
                                        "rolling_grade": "F",
                                        "f_grade_policy_env": _f_policy,
                                    },
                                )
                            except Exception:
                                pass
                            logger.info(
                                "\U0001F6AB [v19.34.173 F-GATE] Blocking %s %s — setup graded F "
                                "(F_GRADE_POLICY=block). Set F_GRADE_POLICY=micro to "
                                "trade at 0.1x size with learning_only=True flag.",
                                symbol, setup_type,
                            )
                            return None
                        elif _f_policy == "micro":
                            # Continue evaluating; tag the alert so the
                            # downstream sizing path AND the grading
                            # aggregator both know this is a learning-only
                            # micro trade (excluded from avg_R computation
                            # to avoid the commission-poisoned feedback loop).
                            alert["learning_only"] = True
                            logger.info(
                                "\U0001F9EA [v19.34.173 F-MICRO] %s %s graded F — trading as "
                                "learning_only at 0.1x. Excluded from grade aggregation.",
                                symbol, setup_type,
                            )
            except Exception as _fg_err:
                logger.debug(f"v19.34.173 F-gate check error: {_fg_err}")

            # ── v19.34.44 — Stale Alert TTL (default 30s) ─────────────'''


# ── opportunity_evaluator: propagate learning_only into entry_context ──
OE_ANCHOR_B_OLD = '''        # 1. Setup identification
        ctx["scanner_setup_type"] = alert.get("setup_type", "")
        ctx["strategy_name"] = alert.get("strategy_name", "")
        ctx["setup_category"] = alert.get("setup_category", "")
        ctx["score"] = alert.get("score", 0)
        ctx["trigger_probability"] = alert.get("trigger_probability", 0)
        ctx["tape_confirmation"] = alert.get("tape_confirmation", False)
        ctx["priority"] = alert.get("priority", "medium")
        if isinstance(ctx["priority"], type) and hasattr(ctx["priority"], "value"):
            ctx["priority"] = ctx["priority"].value
'''

OE_ANCHOR_B_NEW = '''        # 1. Setup identification
        ctx["scanner_setup_type"] = alert.get("setup_type", "")
        ctx["strategy_name"] = alert.get("strategy_name", "")
        ctx["setup_category"] = alert.get("setup_category", "")
        ctx["score"] = alert.get("score", 0)
        ctx["trigger_probability"] = alert.get("trigger_probability", 0)
        ctx["tape_confirmation"] = alert.get("tape_confirmation", False)
        ctx["priority"] = alert.get("priority", "medium")
        if isinstance(ctx["priority"], type) and hasattr(ctx["priority"], "value"):
            ctx["priority"] = ctx["priority"].value

        # v19.34.173 — propagate learning_only flag from F-micro alerts so
        # setup_grading_service._aggregate_day excludes them from avg_R.
        ctx["learning_only"] = bool(alert.get("learning_only", False))
'''


# ── setup_grading_service: filter learning_only from aggregation ──
SG_ANCHOR_OLD = '''        by_setup: Dict[str, List[Dict[str, Any]]] = {}
        for trade in cursor:
            st = trade.get("setup_type")
            if not st:
                continue
            by_setup.setdefault(st, []).append(trade)'''

SG_ANCHOR_NEW = '''        by_setup: Dict[str, List[Dict[str, Any]]] = {}
        for trade in cursor:
            st = trade.get("setup_type")
            if not st:
                continue
            # v19.34.173 — exclude learning_only micro trades from
            # grade aggregation. These are 0.1x-sized F-graded trades
            # whose realized R is dominated by fixed commission costs
            # (~0.5% of position on a 1-share trade vs <0.05% at full
            # size). Including them in avg_R creates a self-perpetuating
            # feedback loop (F grade keeps trading at micro \u2192 keeps
            # bleeding cost-poisoned R \u2192 stays F).
            #
            # Flag lives at either `trade.learning_only` (top-level on
            # newer rows) OR `trade.entry_context.learning_only`
            # (the propagation path from `build_entry_context`).
            _ec = trade.get("entry_context") or {}
            if trade.get("learning_only") is True or _ec.get("learning_only") is True:
                continue
            by_setup.setdefault(st, []).append(trade)'''


def _backup(path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{path}.bak.v173.{stamp}"
    shutil.copy2(path, dst)
    return dst


def patch_oe():
    with open(OE, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.173 — Setup-grade F-gate" in src:
        print("  - opportunity_evaluator.py already on v173 — skipping")
        return False
    if OE_ANCHOR_A_OLD not in src:
        print(f"ERROR: anchor A not found in {OE}")
        sys.exit(2)
    if OE_ANCHOR_B_OLD not in src:
        print(f"ERROR: anchor B not found in {OE}")
        sys.exit(3)
    _backup(OE)
    src = src.replace(OE_ANCHOR_A_OLD, OE_ANCHOR_A_NEW, 1)
    src = src.replace(OE_ANCHOR_B_OLD, OE_ANCHOR_B_NEW, 1)
    with open(OE, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - opportunity_evaluator.py patched (F-gate + entry_context flag)")
    return True


def patch_sg():
    with open(SG, "r", encoding="utf-8") as f:
        src = f.read()
    if "v19.34.173 — exclude learning_only micro trades" in src:
        print("  - setup_grading_service.py already on v173 — skipping")
        return False
    if SG_ANCHOR_OLD not in src:
        print(f"ERROR: anchor not found in {SG}")
        sys.exit(4)
    _backup(SG)
    src = src.replace(SG_ANCHOR_OLD, SG_ANCHOR_NEW, 1)
    with open(SG, "w", encoding="utf-8") as f:
        f.write(src)
    print("  - setup_grading_service.py patched (learning_only filter)")
    return True


def main():
    print("=" * 60)
    print("v19.34.173 — F-grade gate + learning_only flag")
    print("=" * 60)
    a = patch_oe()
    b = patch_sg()
    print()
    print(f"opportunity_evaluator.py changed:    {a}")
    print(f"setup_grading_service.py changed:    {b}")
    print()
    # parse-check
    import ast
    for p in (OE, SG):
        with open(p, "r", encoding="utf-8") as f:
            ast.parse(f.read())
    print("  - syntax check: OK")
    print()
    print("Default policy: F_GRADE_POLICY=block  (F-graded setups are rejected)")
    print("  Set F_GRADE_POLICY=micro in backend/.env to instead trade at 0.1x")
    print("  with learning_only=True (excluded from grade aggregation).")
    print("  Set F_GRADE_POLICY=full to revert to pre-v173 behaviour.")
    print()
    print("Next:")
    print("  1. git add -A && git commit -m 'v19.34.173: F-grade gate + learning_only' && git push")
    print("  2. Restart backend (fire your .bat)")
    print("  3. After ~30s, watch for the gate firing:")
    print("     grep -c 'v19.34.173 F-GATE' /tmp/backend.log   # blocked alerts")
    print("     grep -c 'setup_grade_f_block' /tmp/backend.log # trade_drops reason")


if __name__ == "__main__":
    main()
