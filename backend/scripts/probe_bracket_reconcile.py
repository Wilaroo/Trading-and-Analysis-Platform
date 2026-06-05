#!/usr/bin/env python3
"""
probe_bracket_reconcile.py  (read-only)
=======================================
Traces the INTRADAY_BRACKET_V2 path end-to-end: from a setup's SSOT
exit_archetype → the runner/target bracket geometry → the live order
legs actually attached at IB on each open position.

Answers two operator questions:
  1. "Is the runner/target geometry the bot WOULD place for setup X
      actually what I expect?"  → `--setup X` dry trace (no live data).
  2. "Did every open position actually get its bracket attached and
      reconciled — or is anything NAKED / missing its runner?"
      → default live trace over /api/trading-bot/trades/open.

How the trace resolves geometry (same code the live bot runs):
  setup_type
    └─ services.setup_taxonomy.exit_archetype_prior()  → archetype
         └─ smart_stop_service.ARCHETYPE_STOP_RULES[arch]  → SetupStopRules
              └─ SmartStopService._create_scale_out_plan(...)  → leg plan
                   (fixed targets + optional trailing RUNNER reservation)

Live reconciliation (per open trade):
  • PROTECTED vs NAKED  — is a stop_order_id attached?
  • target legs present — target_order_id(s) / target_ever_attached
  • runner expectation  — archetype reserves leave_runner_pct > 0 ?
  • bracket_attach_count + last_bracket_attach_at telemetry
  • recent lifecycle events from /api/trading-bot/bracket-history

Read-only. Safe to run any time (live mode best DURING/after RTH while
positions are open).

Usage:
  # dry geometry trace for one (or several) setups — no backend needed:
  python3 probe_bracket_reconcile.py --setup tidal_wave --setup fading_bounce
  python3 probe_bracket_reconcile.py --setup tidal_wave --entry 100 --atr 1.5 --shares 400

  # live reconciliation of all open positions:
  python3 probe_bracket_reconcile.py --base http://localhost:8001
  curl -s <raw-url> | python3 - --base http://localhost:8001
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Make `services.*` importable when run from anywhere inside the repo.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _c(txt, code):
    return f"\033[{code}m{txt}\033[0m" if sys.stdout.isatty() else str(txt)


def _green(t): return _c(t, "32")
def _red(t):   return _c(t, "31")
def _yellow(t): return _c(t, "33")
def _bold(t):  return _c(t, "1")


def _get(base, path):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=20) as r:
        return json.loads(r.read().decode())


# ─────────────────────────── geometry trace ───────────────────────────

def resolve_geometry(setup_type: str, entry: float, atr: float, shares: int,
                     direction: str = "long"):
    """Resolve archetype + bracket geometry + scale-out plan via the SSOT."""
    from services.setup_taxonomy import exit_archetype_prior
    from services.smart_stop_service import ARCHETYPE_STOP_RULES, get_smart_stop_service

    arch = exit_archetype_prior(setup_type)
    rules = ARCHETYPE_STOP_RULES.get(arch)
    plan = []
    if rules is not None and entry and atr:
        svc = get_smart_stop_service()
        try:
            plan = svc._create_scale_out_plan(entry, direction, atr, rules, shares)
        except Exception as e:  # pragma: no cover - defensive
            plan = [{"error": f"plan build failed: {e}"}]
    return arch, rules, plan


def print_geometry(setup_type, entry, atr, shares, direction):
    arch, rules, plan = resolve_geometry(setup_type, entry, atr, shares, direction)
    print(f"\n{_bold('━' * 64)}")
    print(f"{_bold(setup_type)}  →  exit_archetype = {_bold(arch)}")
    print(f"{_bold('━' * 64)}")
    if rules is None:
        print(_red(f"  no ARCHETYPE_STOP_RULES entry for '{arch}' — using legacy map"))
        return
    runner_pct = getattr(rules, "leave_runner_pct", 0.0)
    print(f"  initial stop      : {rules.initial_stop_atr_mult:.2f}× ATR")
    print(f"  trailing mode     : {getattr(rules.trailing_mode, 'value', rules.trailing_mode)} "
          f"({rules.trailing_atr_mult:.2f}× ATR)")
    print(f"  breakeven at      : {rules.breakeven_r_target:.2f}R")
    print(f"  scale-out targets : {rules.scale_out_r_targets}")
    print(f"  partial slice     : {getattr(rules, 'partial_exit_pct', 0.0) * 100:.0f}%")
    runner_txt = (_green(f"{runner_pct * 100:.0f}% (trails, no fixed target)")
                  if runner_pct > 0 else _yellow("none (full fixed-target exit)"))
    print(f"  runner reserved   : {runner_txt}")
    print(f"  {rules.description}")
    if plan:
        print(f"\n  scale-out plan  (entry=${entry:g}  atr=${atr:g}  shares={shares}  {direction}):")
        for leg in plan:
            if leg.get("runner"):
                print(f"    • RUNNER          {leg['shares']:>5} sh ({leg['exit_pct'] * 100:.0f}%) "
                      f"— {_green('trail remainder')}")
            elif "error" in leg:
                print(_red(f"    • {leg['error']}"))
            else:
                print(f"    • L{leg['level']} @ {leg['r_target']:.1f}R  "
                      f"${leg['target_price']:.2f}  {leg['shares']:>5} sh "
                      f"({leg['exit_pct'] * 100:.0f}%)")
    expects_runner = runner_pct > 0
    return arch, expects_runner


# ─────────────────────────── live reconcile ───────────────────────────

def _first(d, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], 0):
            return v
    return default


def reconcile_live(base: str):
    from services.setup_taxonomy import exit_archetype_prior
    from services.smart_stop_service import ARCHETYPE_STOP_RULES

    try:
        payload = _get(base, "/api/trading-bot/trades/open")
    except Exception as e:
        print(_red(f"✖ could not reach {base}/api/trading-bot/trades/open: {e}"))
        return 2
    trades = payload.get("trades", []) if isinstance(payload, dict) else []
    print(f"\n{_bold('LIVE BRACKET RECONCILIATION')}  —  {len(trades)} open position(s)\n")
    if not trades:
        print("  (no open positions)")
        return 0

    naked, mismatched, ok = 0, 0, 0
    for t in trades:
        sym = t.get("symbol", "?")
        setup = t.get("setup_type") or t.get("setup_variant") or "?"
        direction = str(_first(t, "direction", default="long")).lower()
        arch = exit_archetype_prior(setup)
        rules = ARCHETYPE_STOP_RULES.get(arch)
        expects_runner = bool(rules and getattr(rules, "leave_runner_pct", 0.0) > 0)

        stop_id = _first(t, "stop_order_id")
        tgt_ids = t.get("target_order_ids") or []
        tgt_id = _first(t, "target_order_id")
        n_targets = len(tgt_ids) if tgt_ids else (1 if tgt_id else 0)
        tgt_ever = bool(t.get("target_ever_attached"))
        attach_n = int(t.get("bracket_attach_count") or 0)

        # Verdict
        flags = []
        if not stop_id:
            flags.append(_red("NAKED (no stop)"))
            naked += 1
        if n_targets == 0 and not tgt_ever:
            flags.append(_yellow("no target leg"))
        if not flags:
            ok += 1
            verdict = _green("PROTECTED")
        else:
            if stop_id:
                mismatched += 1
            verdict = " · ".join(flags)

        runner_note = (_green("runner-expected") if expects_runner
                       else "fixed-target")
        print(f"  {_bold(sym):<14} {setup:<22} {direction:<5} "
              f"arch={arch:<13} {runner_note}")
        print(f"      stop_order_id={stop_id or '—'}  targets={n_targets} "
              f"(ever={tgt_ever})  attach_count={attach_n}  → {verdict}")

    print(f"\n  {_green(str(ok) + ' protected')}  ·  "
          f"{_yellow(str(mismatched) + ' partial/mismatch')}  ·  "
          f"{_red(str(naked) + ' NAKED')}")

    # Recent lifecycle trail (best-effort).
    try:
        hist = _get(base, "/api/trading-bot/bracket-history?limit=12")
        events = hist.get("events") or hist.get("history") or []
        if events:
            print(f"\n  {_bold('recent bracket lifecycle:')}")
            for ev in events[:12]:
                phase = ev.get("phase") or ev.get("event") or "?"
                s = ev.get("symbol", "?")
                ok_ev = ev.get("success")
                tag = _green("ok") if ok_ev else (_red("fail") if ok_ev is False else "·")
                print(f"      {s:<10} {phase:<26} {tag}")
    except Exception:
        pass

    return 1 if (naked or mismatched) else 0


def main():
    ap = argparse.ArgumentParser(description="INTRADAY_BRACKET_V2 reconciliation trace")
    ap.add_argument("--setup", action="append", default=[],
                    help="dry geometry trace for a setup (repeatable)")
    ap.add_argument("--entry", type=float, default=100.0)
    ap.add_argument("--atr", type=float, default=1.5)
    ap.add_argument("--shares", type=int, default=400)
    ap.add_argument("--direction", default="long", choices=["long", "short"])
    ap.add_argument("--base", default="http://localhost:8001",
                    help="backend base URL for live reconciliation")
    ap.add_argument("--live", action="store_true",
                    help="force live reconciliation even if --setup given")
    args = ap.parse_args()

    rc = 0
    if args.setup:
        for s in args.setup:
            print_geometry(s, args.entry, args.atr, args.shares, args.direction)
        if not args.live:
            return rc
    rc = reconcile_live(args.base)
    return rc


if __name__ == "__main__":
    sys.exit(main())
