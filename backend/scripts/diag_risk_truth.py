#!/usr/bin/env python3
"""
diag_risk_truth.py — read-only truth report for position-cap and
daily-loss enforcement. Confirms which value actually binds live trades
and where each number comes from.

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform/backend
    python scripts/diag_risk_truth.py            # uses local API
    python scripts/diag_risk_truth.py --raw      # also dumps raw JSON

It hits three endpoints and lays them side by side:
  • /api/trading-bot/effective-limits   (the reconciler — THE truth)
  • /api/safety/status                  (kill-switch caps)
  • /api/trading-bot/llm-rules          (the advisory caps the chat-AI shows)

Nothing here mutates anything.
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("DIAG_API_BASE", "http://localhost:8001")
RAW = "--raw" in sys.argv


def _get(path):
    url = f"{BASE}{path}"
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {e}", "_url": url}


def _fmt(v):
    if v is None:
        return "UNSET"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


def main():
    eff = _get("/api/trading-bot/effective-limits")
    safety = _get("/api/safety/status")
    llm = _get("/api/trading-bot/llm-rules")

    print("=" * 68)
    print(f"RISK TRUTH REPORT   ({BASE})")
    print("=" * 68)

    # ---- POSITION CAP ----
    print("\n■ POSITION CAP — which number actually refuses new entries?")
    sources = (eff or {}).get("sources", {})
    effective = (eff or {}).get("effective", {})
    bot_pos = sources.get("bot", {}).get("max_open_positions")
    safety_pos = sources.get("safety", {}).get("max_positions")
    eff_pos = effective.get("max_open_positions")
    llm_pos = (llm or {}).get("position_count_cap")
    print(f"   bot.max_open_positions        (Mongo bot_state) : {_fmt(bot_pos)}")
    print(f"   safety.max_positions          (env kill-switch) : {_fmt(safety_pos)}")
    print(f"   llm-rules.position_count_cap  (advisory display): {_fmt(llm_pos)}")
    print(f"   ──> EFFECTIVE (binding, strictest)              : {_fmt(eff_pos)}  ⟵ THE TRUTH")

    # ---- DAILY LOSS ----
    print("\n■ DAILY LOSS — which limit actually halts the bot today?")
    bot_dl_usd = sources.get("bot", {}).get("max_daily_loss")
    bot_dl_pct = sources.get("bot", {}).get("max_daily_loss_pct")
    safety_dl_usd = sources.get("safety", {}).get("max_daily_loss_usd")
    safety_dl_pct = sources.get("safety", {}).get("max_daily_loss_pct")
    dyn_dl_pct = sources.get("dynamic_risk", {}).get("max_daily_loss_pct")
    eff_dl_usd = effective.get("max_daily_loss_usd")
    eff_dl_pct = effective.get("max_daily_loss_pct")
    llm_dl = (llm or {}).get("daily_loss_budget")
    print(f"   bot.max_daily_loss / pct      (Mongo)           : ${_fmt(bot_dl_usd)} / {_fmt(bot_dl_pct)}%")
    print(f"   safety.max_daily_loss_usd/pct (env kill-switch) : ${_fmt(safety_dl_usd)} / {_fmt(safety_dl_pct)}%")
    print(f"   dynamic_risk.max_daily_loss_pct (default)       : {_fmt(dyn_dl_pct)}%")
    print(f"   llm-rules.daily_loss_budget   (advisory)        : ${_fmt(llm_dl)}")
    print(f"   ──> EFFECTIVE USD (binding, strictest)          : ${_fmt(eff_dl_usd)}  ⟵ THE TRUTH")
    print(f"   ──> EFFECTIVE PCT (binding, strictest)          : {_fmt(eff_dl_pct)}%")

    # ---- CONFLICTS ----
    conflicts = (eff or {}).get("conflicts", [])
    print("\n■ CONFLICTS the reconciler flagged:")
    if conflicts:
        for c in conflicts:
            print(f"   • {c}")
    else:
        print("   (none — all sources agree)")

    # ---- VERDICT ----
    print("\n■ VERDICT")
    if eff_pos is not None:
        print(f"   The bot will REFUSE the {int(eff_pos) + 1}th position (cap = {_fmt(eff_pos)}).")
    if eff_dl_usd is not None:
        print(f"   The bot will HALT after a ${_fmt(eff_dl_usd)} realized daily loss.")
    print("   To make the cap 25, BOTH bot.max_open_positions AND safety.max_positions")
    print("   must be >= 25 (effective = the SMALLER of the two). See the action note.")

    if RAW:
        print("\n" + "=" * 68 + "\nRAW JSON\n" + "=" * 68)
        print("\n--- effective-limits ---\n" + json.dumps(eff, indent=2))
        print("\n--- safety/status ---\n" + json.dumps(safety, indent=2))
        print("\n--- llm-rules ---\n" + json.dumps(llm, indent=2))

    for label, payload in (("effective-limits", eff), ("safety", safety), ("llm-rules", llm)):
        if isinstance(payload, dict) and payload.get("_error"):
            print(f"\n⚠ {label} fetch failed: {payload['_error']}")


if __name__ == "__main__":
    main()
