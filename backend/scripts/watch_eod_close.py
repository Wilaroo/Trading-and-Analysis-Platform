#!/usr/bin/env python3
"""
watch_eod_close.py — v19.34.161 (Feb 2026)

Real-time EOD auto-close monitor. Streams the v153 ghost-flatten loop
end-to-end on one terminal so the operator can watch position count
drop from N → 0 with per-symbol close-reason annotations as the
3:45 PM ET trigger fires.

What it shows in a single full-screen view (refreshes every 1s):

    ┌── EOD WATCHER · 14:42:13 ET ────────── trigger @ 15:45:00 ET (T-63m) ──┐
    │ Open positions: 24    Closed today: 0    Bracket-blocked: 0           │
    ├── Open ──────────────────────────────────────────────────────────────┤
    │  USO       vwap_fade_long       long  300sh  +$ 12.4   stop ✓ tgt ✗  │
    │  BP        mean_reversion_long  long  500sh  -$  4.1   stop ✓ tgt ✓  │
    │  ...                                                                  │
    ├── Recent closes (last 15 min, real reasons only) ─────────────────────┤
    │  15:44:12  CHWY    operator_external_flatten   +$216.48                │
    │  15:43:58  HII     eod_auto_close              +$1,206                 │
    │  ...                                                                  │
    ├── Backend EOD log tail (last 12 lines matching) ──────────────────────┤
    │  15:45:00  position_manager  [v153] EOD ghost-flatten loop starting…  │
    │  15:45:01  position_manager  flattening USO …                          │
    │  ...                                                                  │
    └───────────────────────────────────────────────────────────────────────┘

Read-only — does NOT issue any orders. Just polls the API + tails the
backend log file.

Usage:
    PYTHONPATH=backend python backend/scripts/watch_eod_close.py
    PYTHONPATH=backend python backend/scripts/watch_eod_close.py --no-clear   # don't clear screen (logs scroll)
    PYTHONPATH=backend python backend/scripts/watch_eod_close.py --interval 1 # refresh cadence
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request


# ── helpers ──
NY_OFFSET_HOURS = -4  # naive ET; close enough for an at-glance display

EOD_TRIGGER_MIN = 15 * 60 + 45 * 60  # 15:45 ET in seconds-from-midnight (3:45 PM)

LOG_PATH_DEFAULT = "/tmp/backend.log"
LOG_KEYWORDS = re.compile(
    r"eod|flatten|ghost|cancel|close_reason|position_manager|"
    r"bracket_attach|reg.?t|201|reconcil|phantom",
    re.IGNORECASE,
)

# Bookkeeping reasons we'll DIM so real closes pop visually.
BOOKKEEPING_REASONS = re.compile(
    r"phantom|consolidated|reconciled|shrunk_to_zero|zombie|"
    r"oca_closed_external|external_close|wrong_direction|"
    r"manual_state_reset|manual_pre_open",
    re.IGNORECASE,
)


# ── colour helpers (ANSI, no deps) ──
class C:
    R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"; B = "\033[34m"
    M = "\033[35m"; W = "\033[37m"; DIM = "\033[2m"; BOLD = "\033[1m"
    RESET = "\033[0m"


def now_et_seconds() -> int:
    """Seconds-from-midnight in (naive) US/Eastern. We compute this
    without pytz/zoneinfo because the DGX environment is minimal."""
    utc_now = datetime.now(timezone.utc)
    et_hour = (utc_now.hour + NY_OFFSET_HOURS) % 24
    return et_hour * 3600 + utc_now.minute * 60 + utc_now.second


def fmt_minutes(seconds: int) -> str:
    sign = "+" if seconds >= 0 else "-"
    s = abs(seconds)
    return f"{sign}{s // 60}m{s % 60:02d}s"


def fmt_pnl(p) -> str:
    if p is None:
        return "       —"
    try:
        n = float(p)
    except Exception:
        return "       —"
    sign = "+" if n >= 0 else "-"
    return f"{sign}${abs(n):7,.2f}"


def fetch_open(api_base: str):
    try:
        req = Request(f"{api_base}/api/trading-bot/trades/open",
                      headers={"Accept": "application/json"})
        with urlopen(req, timeout=2) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e), "trades": [], "count": 0}


def fetch_closed_recent(api_base: str, since_minutes: int = 30):
    try:
        req = Request(
            f"{api_base}/api/trading-bot/trades/closed?limit=50",
            headers={"Accept": "application/json"},
        )
        with urlopen(req, timeout=2) as r:
            data = json.loads(r.read())
    except Exception:
        return []
    trades = data.get("trades", [])
    # Filter to last N minutes by closed_at when possible.
    cutoff = time.time() - since_minutes * 60
    out = []
    for t in trades:
        ca = t.get("closed_at") or ""
        try:
            ts = datetime.fromisoformat(str(ca).replace("Z", "+00:00")).timestamp()
            if ts >= cutoff:
                out.append((ts, t))
        except Exception:
            out.append((time.time(), t))  # unparseable → assume recent
    out.sort(key=lambda x: x[0], reverse=True)
    return out[:15]


def tail_log_lines(log_path: str, tail: deque, max_bytes: int = 32_000):
    """Append new LOG_KEYWORD-matching lines from the log to `tail`."""
    if not Path(log_path).exists():
        return
    try:
        st = os.stat(log_path)
        offset = getattr(tail, "_offset", max(0, st.st_size - max_bytes))
        if offset > st.st_size:  # log rotated
            offset = 0
        with open(log_path, "rb") as f:
            f.seek(offset)
            chunk = f.read(st.st_size - offset)
            tail._offset = st.st_size
        for line in chunk.decode("utf-8", errors="replace").splitlines():
            if LOG_KEYWORDS.search(line):
                tail.append(line)
    except Exception:
        return


# ── renderer ──
def render(api_base: str, log_path: str, log_tail: deque, clear_screen: bool):
    cols = shutil.get_terminal_size(fallback=(120, 30)).columns
    et_sec = now_et_seconds()
    et_hh = et_sec // 3600
    et_mm = (et_sec % 3600) // 60
    et_ss = et_sec % 60
    delta = EOD_TRIGGER_MIN - et_sec

    open_data = fetch_open(api_base)
    closed_recent = fetch_closed_recent(api_base, since_minutes=30)

    # Refresh the log tail.
    tail_log_lines(log_path, log_tail)

    # Build header.
    n_open = open_data.get("count", 0)
    n_closed = len(closed_recent)
    real_closes = sum(1 for _, t in closed_recent
                      if not BOOKKEEPING_REASONS.search(str(t.get("close_reason") or "")))

    trigger_str = (f"trigger @ 15:45:00 ET  ({fmt_minutes(delta)})"
                   if delta > 0 else
                   f"{C.G}EOD TRIGGERED ({fmt_minutes(delta)}){C.RESET}")

    out = []
    if clear_screen:
        out.append("\033[2J\033[H")  # clear + home

    bar = "─" * (cols - 2)
    out.append(f"┌── {C.BOLD}EOD WATCHER{C.RESET} · {et_hh:02d}:{et_mm:02d}:{et_ss:02d} ET ── {trigger_str} {bar[:cols - 60]}┐")
    open_colour = C.R if n_open >= 20 else (C.Y if n_open > 0 else C.G)
    out.append(
        f"│ Open: {open_colour}{n_open:>3}{C.RESET}   "
        f"Closed (last 30m): {n_closed:>3}  (real: {real_closes}, noise: {n_closed - real_closes})"
        f"   API: {C.G if 'error' not in open_data else C.R}{'OK' if 'error' not in open_data else 'ERR'}{C.RESET}"
    )
    if 'error' in open_data:
        out.append(f"│ {C.R}{open_data['error']}{C.RESET}")
    out.append(f"├── {C.BOLD}Open positions ({n_open}){C.RESET} {bar}")

    if not open_data.get("trades"):
        out.append(f"│ {C.G}— no open positions —{C.RESET}")
    else:
        for t in open_data.get("trades", []):
            sym = (t.get("symbol") or "?")[:6]
            setup = (t.get("setup_type") or "—")[:24]
            side = (t.get("direction") or "?")[:4]
            shares = t.get("shares") or t.get("position_size") or "—"
            upnl = t.get("unrealized_pnl") or t.get("current_pnl")
            stop_set = bool(t.get("stop_order_id") or (t.get("brackets") and t["brackets"].get("stop_order_id")))
            tgt_set  = bool(t.get("target_order_ids") or (t.get("brackets") and t["brackets"].get("target_order_ids")))
            stop_str = f"{C.G}stop✓{C.RESET}" if stop_set else f"{C.R}stop✗{C.RESET}"
            tgt_str  = f"{C.G}tgt✓{C.RESET}" if tgt_set else f"{C.R}tgt✗{C.RESET}"
            out.append(
                f"│  {sym:<6} {setup:<24} {side:<5} {str(shares):>5}sh  "
                f"{fmt_pnl(upnl)}   {stop_str} {tgt_str}"
            )

    out.append(f"├── {C.BOLD}Recent closes (last 30m){C.RESET} {bar}")
    if not closed_recent:
        out.append(f"│ {C.DIM}— no closes yet —{C.RESET}")
    else:
        for ts, t in closed_recent:
            ts_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            sym = (t.get("symbol") or "?")[:6]
            reason = (t.get("close_reason") or "?")[:32]
            pnl = t.get("realized_pnl") or t.get("net_pnl")
            is_noise = bool(BOOKKEEPING_REASONS.search(reason))
            tag_col = C.DIM if is_noise else (C.G if (pnl or 0) >= 0 else C.R)
            out.append(
                f"│  {tag_col}{ts_str}  {sym:<6}  {reason:<32}  {fmt_pnl(pnl)}{C.RESET}"
            )

    out.append(f"├── {C.BOLD}Backend log tail (EOD-related){C.RESET} {bar}")
    if not log_tail:
        out.append(f"│ {C.DIM}— no matching log lines yet (path={log_path}) —{C.RESET}")
    else:
        for line in list(log_tail)[-12:]:
            # truncate
            if len(line) > cols - 4:
                line = line[:cols - 7] + "..."
            out.append(f"│ {line}")

    out.append(f"└{bar}┘")
    out.append(f"{C.DIM}q+Enter to quit · refresh {1 if clear_screen else 'streaming'}s{C.RESET}")

    sys.stdout.write("\n".join(out) + "\n")
    sys.stdout.flush()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8001", help="Backend API base URL")
    p.add_argument("--log", default=LOG_PATH_DEFAULT, help=f"Backend log path (default {LOG_PATH_DEFAULT})")
    p.add_argument("--interval", type=float, default=1.0, help="Refresh seconds (default 1.0)")
    p.add_argument("--no-clear", action="store_true", help="Don't clear screen on each tick (scrolling mode)")
    args = p.parse_args()

    log_tail = deque(maxlen=200)
    try:
        while True:
            render(args.api, args.log, log_tail, clear_screen=not args.no_clear)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        sys.stdout.write("\nwatcher stopped.\n")


if __name__ == "__main__":
    main()
