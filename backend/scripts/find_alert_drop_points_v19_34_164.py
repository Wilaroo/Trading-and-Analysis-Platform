#!/usr/bin/env python3
"""
v19.34.164-scout — Alert Drop-Point Enumeration (read-only)
============================================================

Static AST scan of the bot's alert-processing path to enumerate every
point where a scanner alert can be silently dropped before reaching the
AI consultation + shadow log.

These are the rejection sites that v164 Patch A needs to instrument with
`db.alert_decisions.insert_one({...})` so the new Funnel can show
operators WHY the bot ignores most scanner alerts.

Scans:
  - backend/services/opportunity_evaluator.py  (evaluate_opportunity)
  - backend/services/trading_bot_service.py    (_evaluate_opportunity wrapper)

For each "return None" / "return False" / "continue" / "raise" inside an
alert-processing function, prints:
  - file:line
  - enclosing function
  - the preceding `if` condition (the actual rejection reason)
  - surrounding ±2 lines of context

Output: human-readable report + JSON summary.

Usage:
    cd ~/Trading-and-Analysis-Platform && source .venv/bin/activate
    PYTHONPATH=backend python backend/scripts/find_alert_drop_points_v19_34_164.py
    PYTHONPATH=backend python backend/scripts/find_alert_drop_points_v19_34_164.py --json
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import defaultdict
from typing import List, Dict, Any

# Resolve repo root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

# Files we know contain alert-drop logic
TARGETS = [
    ("backend/services/opportunity_evaluator.py",
     {"evaluate_opportunity", "_score_setup", "_compute_targets"}),
    ("backend/services/trading_bot_service.py",
     {"_evaluate_opportunity", "_get_trade_alerts", "_consider_alert",
      "_process_alert", "_should_act_on_alert"}),
]

# Drop-statement types we hunt for
DROP_KINDS = {"return_none", "return_false", "continue", "raise"}


class DropFinder(ast.NodeVisitor):
    """Walks function bodies and records every drop site with the
    enclosing `if` condition (if any)."""

    def __init__(self, file_path: str, source_lines: List[str], scope_funcs: set):
        self.file_path = file_path
        self.source_lines = source_lines
        self.scope_funcs = scope_funcs
        self.results: List[Dict[str, Any]] = []
        self._fn_stack: List[str] = []
        self._if_stack: List[ast.If] = []

    # ── function context ────────────────────────────────────────────
    def visit_FunctionDef(self, node):
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    # ── if context (for "the reason") ───────────────────────────────
    def visit_If(self, node):
        self._if_stack.append(node)
        self.generic_visit(node)
        self._if_stack.pop()

    # ── drop sites ──────────────────────────────────────────────────
    def visit_Return(self, node):
        if not self._fn_stack:
            return
        fn = self._fn_stack[-1]
        # Only inside scope functions (top of stack)
        # Climb to the topmost function name (the one we filter on).
        top_fn = self._fn_stack[0]
        if top_fn not in self.scope_funcs:
            return
        kind = None
        if node.value is None or (
            isinstance(node.value, ast.Constant) and node.value.value is None
        ):
            kind = "return_none"
        elif isinstance(node.value, ast.Constant) and node.value.value is False:
            kind = "return_false"
        if kind:
            self._record(node, kind)

    def visit_Continue(self, node):
        if self._fn_stack and self._fn_stack[0] in self.scope_funcs:
            self._record(node, "continue")

    def visit_Raise(self, node):
        if self._fn_stack and self._fn_stack[0] in self.scope_funcs:
            self._record(node, "raise")

    # ── recording ───────────────────────────────────────────────────
    def _record(self, node, kind):
        # Source line of the drop statement
        line = node.lineno
        # Enclosing if condition (innermost)
        cond_src = None
        if self._if_stack:
            cond_node = self._if_stack[-1].test
            try:
                cond_src = ast.unparse(cond_node)
            except Exception:
                cond_src = "<unparseable>"
        # ±2 lines of surrounding source
        lo = max(1, line - 2)
        hi = min(len(self.source_lines), line + 2)
        ctx = []
        for i in range(lo, hi + 1):
            marker = "→" if i == line else " "
            ctx.append(f"{marker} {i:>5}: {self.source_lines[i - 1].rstrip()}")
        self.results.append({
            "file": self.file_path,
            "line": line,
            "fn": " > ".join(self._fn_stack),
            "kind": kind,
            "condition": cond_src,
            "context": "\n".join(ctx),
        })


def categorize_reason(cond: str | None, ctx: str) -> str:
    """Best-effort guess at a stable reason category from condition text.
    These become the `reason` values that v164 Patch A will write to
    `db.alert_decisions`."""
    if not cond:
        return "no_condition_unreached_or_exception_path"
    c = cond.lower()
    blob = (cond + " " + ctx).lower()
    rules = [
        ("quality_score_below_threshold",   ["quality_score", "tqs", "score <", "below.*threshold"]),
        ("rr_below_minimum",                ["risk_reward", "rr_ratio", "risk/reward", "risk_reward_ratio"]),
        ("cooldown_active",                 ["cooldown", "_in_cooldown", "rate_limited"]),
        ("duplicate_symbol_active",         ["already.*open", "duplicate", "already_active", "open_trades"]),
        ("regime_block",                    ["regime", "market_regime", "vix"]),
        ("position_limit_reached",          ["max_position", "position_limit", "max_concurrent"]),
        ("setup_disabled",                  ["disabled", "enabled.*false", "not.*enabled"]),
        ("data_unavailable",                ["no_bars", "bars is none", "no data", "stale", "missing"]),
        ("price_data_stale",                ["price.*stale", "quote.*stale", "ib_quote"]),
        ("size_zero_or_invalid",            ["shares == 0", "shares <", "size.*invalid", "qty <= 0"]),
        ("stop_target_invalid",             ["stop_price", "target_price", "invalid_stop", "invalid_target"]),
        ("safety_block",                    ["safety", "halt", "kill_switch", "paused"]),
        ("not_authorized",                  ["not authorized", "auth", "permission"]),
        ("pre_market_or_post_market",       ["pre_market", "post_market", "rth", "market_open"]),
        ("buying_power_insufficient",       ["buying_power", "cash_available", "insufficient"]),
    ]
    for cat, patterns in rules:
        if any(p in blob for p in patterns):
            return cat
    return "unknown_other"


def main() -> int:
    ap = argparse.ArgumentParser(description="Alert drop-point AST scout")
    ap.add_argument("--json", action="store_true", help="Output JSON only")
    ap.add_argument("--verbose", action="store_true", help="Show context for each site")
    args = ap.parse_args()

    all_results: List[Dict[str, Any]] = []
    for rel_path, scope_funcs in TARGETS:
        full = os.path.join(REPO_ROOT, rel_path)
        if not os.path.exists(full):
            print(f"[WARN] missing: {full}", file=sys.stderr)
            continue
        with open(full, encoding="utf-8") as f:
            src = f.read()
        try:
            tree = ast.parse(src, filename=full)
        except SyntaxError as e:
            print(f"[FATAL] AST parse failed: {full}: {e}", file=sys.stderr)
            continue
        finder = DropFinder(rel_path, src.splitlines(), scope_funcs)
        finder.visit(tree)
        all_results.extend(finder.results)

    # Tag each with a categorized reason
    for r in all_results:
        r["reason_category"] = categorize_reason(r["condition"], r["context"])

    if args.json:
        print(json.dumps(all_results, indent=2))
        return 0

    # ─── Human-readable report ──────────────────────────────────────
    print(f"\n{'=' * 78}")
    print(f"  ALERT DROP-POINT SCOUT  —  v19.34.164")
    print(f"  Total drop sites: {len(all_results)}")
    print(f"{'=' * 78}\n")

    # Reason distribution
    by_reason: Dict[str, int] = defaultdict(int)
    for r in all_results:
        by_reason[r["reason_category"]] += 1
    print("[REASON CATEGORY DISTRIBUTION]")
    for reason, n in sorted(by_reason.items(), key=lambda x: -x[1]):
        pct = 100.0 * n / max(1, len(all_results))
        bar = "█" * int(pct / 2)
        print(f"  {reason:<38} {n:>3} ({pct:5.1f}%)  {bar}")

    # Drops by file & function
    print(f"\n[DROP SITES BY FILE]")
    by_file: Dict[str, List[Dict]] = defaultdict(list)
    for r in all_results:
        by_file[r["file"]].append(r)
    for file_path in sorted(by_file):
        rows = by_file[file_path]
        print(f"\n  {file_path}  ({len(rows)} sites)")
        by_fn: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            by_fn[r["fn"]].append(r)
        for fn, items in by_fn.items():
            print(f"    {fn}:  {len(items)} drops")
            for r in items:
                cond = r["condition"] or "<no enclosing if>"
                cond_short = cond if len(cond) <= 70 else cond[:67] + "..."
                print(f"      L{r['line']:>5}  [{r['kind']}]  "
                      f"reason={r['reason_category']:<32}  if: {cond_short}")
                if args.verbose:
                    print()
                    for ln in r["context"].splitlines():
                        print(f"        {ln}")
                    print()

    # Final guidance
    print(f"\n{'=' * 78}")
    print(f"  v164 INSTRUMENTATION SCOPE ESTIMATE")
    print(f"{'=' * 78}")
    print(f"  Drop sites to instrument:           {len(all_results)}")
    print(f"  Unique reason categories surfaced:  {len(by_reason)}")
    unknown = by_reason.get('unknown_other', 0)
    print(f"  Sites needing manual review:        {unknown}")
    print(f"")
    print(f"  Patch A est. LoC ≈ {len(all_results) * 4} (one 4-line insert per site)")
    print(f"  Plus a thin helper at top of file:  ~25 LoC")
    print(f"  Plus pytest:                        ~50 LoC")
    print(f"  -----------------------------------------")
    print(f"  TOTAL Patch A:                      ~{len(all_results) * 4 + 75} LoC")
    print(f"")
    print(f"  → Re-run with --verbose to see each rejection's condition + context")
    print(f"  → Re-run with --json to feed into a structured tracking sheet")
    print(f"\n[DONE]\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
