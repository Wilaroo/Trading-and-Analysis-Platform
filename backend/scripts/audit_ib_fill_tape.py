#!/usr/bin/env python3
"""
audit_ib_fill_tape.py — v19.34.4 (2026-05-04)

Parses an Interactive Brokers TWS Trades-pane paste (stdin or --input file)
into a structured audit per symbol:

  * fill count, total bought / sold (shares + dollars)
  * fragmentation: number of fills, distinct exchanges, distinct timestamps
  * net position assuming all-day ledger (carryover hint when nonzero)
  * round-trip count (FIFO matching) + realized PnL with explicit
    long-then-cover and short-then-cover legs labeled
  * fees total
  * earliest fill / latest fill / EOD-flatten cluster detection
  * a JSON sidecar (--json) suitable for diffing against Mongo `bot_trades`
  * a markdown report (--out) with severity-sorted verdicts

Usage:
  # stdin:
  cat tape.txt | python audit_ib_fill_tape.py

  # file:
  python audit_ib_fill_tape.py --input tape.txt --out audit.md --json audit.json

  # cross-check against Mongo bot_trades export (operator runs export on Spark):
  python audit_ib_fill_tape.py --input tape.txt \
      --bot-trades-json /path/to/bot_trades_today.json \
      --out audit.md

Verdicts (per symbol):
  - CLEAN_ROUND_TRIP   — net=0, single direction-pair (long→sold OR short→cover)
  - MULTI_LEG_CLEAN    — net=0, multiple round-trips same day (heavy intraday churn)
  - INVERSION          — sold first then bought (short → cover)
  - CARRYOVER_FLAT     — net != 0 (started with shares from prior day, ended flat)
  - OPEN_POSITION      — net != 0 at end of tape (still holding shares)
  - HIGH_FRAGMENTATION — > 30 fills for a single round-trip (broker venue split)

Designed to be safe to run from a fork environment without Mongo / IB
access; produces a self-contained audit artifact.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# Regexes for the TWS paste format.
RE_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
RE_SUMMARY = re.compile(r"^(Sold|Bot|Bought)\s+([\d,]+)\s+@\s+([\d.]+)\s+on\s+(\S+)\s*$")
RE_ACTION_ROW = re.compile(r"^([A-Z]{2,}\d{4,})\s+(Sold|Bot|Bought)\s+([\d,]+)\s*$")
RE_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*(AM|PM)\s*$", re.I)
RE_FEES = re.compile(r"^Fees:\s*([\d.]+)\s*$")
RE_FILLED = re.compile(r"^Filled\s*$")


@dataclass
class Fill:
    symbol: str
    side: str  # "BUY" | "SELL"
    qty: int
    price: float
    venue: str
    time_str: str  # raw "3:57 PM"
    time_minutes: int  # minutes since 00:00 (24h) for ordering
    account: str
    fees: float
    amount: float

    def to_dict(self) -> dict:
        return asdict(self)


def parse_time_to_minutes(time_str: str) -> int:
    m = RE_TIME.match(time_str.strip())
    if not m:
        return -1
    hh, mm, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ampm == "PM" and hh != 12:
        hh += 12
    if ampm == "AM" and hh == 12:
        hh = 0
    return hh * 60 + mm


def parse_qty(s: str) -> int:
    return int(s.replace(",", "").strip())


def parse_tape(text: str) -> list[Fill]:
    """
    State machine: walks lines, accumulates 1 fill per record.

    Records appear as:
      SYMBOL
      Sold|Bot|Bought N @ PRICE on VENUE
      ACCOUNT \\t Sold|Bot|Bought \\t N \\t
      Filled
      H:MM AM/PM
      PRICE \\t
      AMOUNT
      Fees: F
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    fills: list[Fill] = []
    i = 0
    n = len(lines)
    # Skip opening header row(s).
    while i < n and lines[i].startswith(("Trades", "Account", "Action", "Quantity")):
        i += 1

    while i < n:
        # Find a candidate symbol line.
        line = lines[i].strip()
        if not line or not RE_SYMBOL.match(line):
            i += 1
            continue
        symbol = line

        # Look ahead for a summary line.
        if i + 1 >= n:
            break
        summary_line = lines[i + 1].strip()
        sm = RE_SUMMARY.match(summary_line)
        if not sm:
            # Not a real fill record; skip.
            i += 1
            continue

        side_word = sm.group(1)
        # qty_summary = parse_qty(sm.group(2))  # cross-check value, not used
        # price_summary = float(sm.group(3))
        venue = sm.group(4)
        side = "BUY" if side_word in ("Bot", "Bought") else "SELL"

        # Walk forward looking for the action row, time row, price/amount, fees.
        # We allow whitespace-only lines to slip in between.
        cursor = i + 2
        account = ""
        qty = 0
        time_str = ""
        time_min = -1
        price = 0.0
        amount = 0.0
        fees = 0.0
        found_filled = False

        # Action row
        while cursor < n:
            row = lines[cursor].strip()
            if not row:
                cursor += 1
                continue
            ar = RE_ACTION_ROW.match(row)
            if ar:
                account = ar.group(1)
                qty = parse_qty(ar.group(3))
                cursor += 1
                break
            # If we hit another symbol line before finding action, abort.
            if RE_SYMBOL.match(row) and RE_SUMMARY.match(
                lines[cursor + 1].strip() if cursor + 1 < n else ""
            ):
                break
            cursor += 1
        if not account:
            i += 1
            continue

        # "Filled" line (skipping blanks).
        while cursor < n:
            row = lines[cursor].strip()
            if not row:
                cursor += 1
                continue
            if RE_FILLED.match(row):
                found_filled = True
                cursor += 1
                break
            break
        if not found_filled:
            i += 1
            continue

        # Time line
        while cursor < n:
            row = lines[cursor].strip()
            if not row:
                cursor += 1
                continue
            tm = RE_TIME.match(row)
            if tm:
                time_str = row
                time_min = parse_time_to_minutes(row)
                cursor += 1
                break
            break

        # Price line
        while cursor < n:
            row = lines[cursor].strip()
            if not row:
                cursor += 1
                continue
            try:
                price = float(row)
                cursor += 1
                break
            except ValueError:
                break

        # Amount line
        while cursor < n:
            row = lines[cursor].strip()
            if not row:
                cursor += 1
                continue
            try:
                amount = float(row)
                cursor += 1
                break
            except ValueError:
                break

        # Fees line
        while cursor < n:
            row = lines[cursor].strip()
            if not row:
                cursor += 1
                continue
            fm = RE_FEES.match(row)
            if fm:
                fees = float(fm.group(1))
                cursor += 1
                break
            break

        fills.append(
            Fill(
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                venue=venue,
                time_str=time_str,
                time_minutes=time_min,
                account=account,
                fees=fees,
                amount=amount,
            )
        )

        i = cursor

    return fills


@dataclass
class FifoTrade:
    """One closed leg from FIFO matching."""

    direction: str  # "LONG" | "SHORT"
    qty: int
    open_price: float
    close_price: float
    open_time: str
    close_time: str
    pnl: float


@dataclass
class SymbolAudit:
    symbol: str
    fill_count: int = 0
    bought_qty: int = 0
    sold_qty: int = 0
    bought_dollars: float = 0.0
    sold_dollars: float = 0.0
    fees_total: float = 0.0
    venues: set = field(default_factory=set)
    earliest_time: str = ""
    latest_time: str = ""
    earliest_min: int = 99999
    latest_min: int = -1
    eod_flatten: bool = False
    closed_legs: list[FifoTrade] = field(default_factory=list)
    open_residual_qty: int = 0  # signed: + = long open, - = short open
    fills: list[Fill] = field(default_factory=list)

    @property
    def short_legs(self) -> list[FifoTrade]:
        """All SHORT round-trip legs (sell-short → buy-to-cover pairs)."""
        return [t for t in self.closed_legs if t.direction == "SHORT"]

    @property
    def has_open_short_residual(self) -> bool:
        """End-of-tape residual is a still-open short position."""
        return self.open_residual_qty < 0

    @property
    def net_position(self) -> int:
        return self.bought_qty - self.sold_qty

    @property
    def realized_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_legs)

    @property
    def realized_pnl_after_fees(self) -> float:
        return self.realized_pnl - self.fees_total

    @property
    def has_inversion(self) -> bool:
        """Sold ANY shares before any bought shares — short-then-cover signature."""
        if not self.fills:
            return False
        first_buy = next(
            (f.time_minutes for f in self.fills if f.side == "BUY"), None
        )
        first_sell = next(
            (f.time_minutes for f in self.fills if f.side == "SELL"), None
        )
        if first_buy is None or first_sell is None:
            return False
        return first_sell < first_buy

    def verdict(self) -> str:
        long_legs = sum(1 for t in self.closed_legs if t.direction == "LONG")
        short_legs = sum(1 for t in self.closed_legs if t.direction == "SHORT")

        if self.open_residual_qty > 0:
            # More bought than sold within the tape — bot still holds shares.
            return "OPEN_POSITION_LONG"
        if self.open_residual_qty < 0:
            # More sold than bought within the tape. The most common cause
            # is a prior-day inventory carryover that was flattened today;
            # the bot's IB position is now zero. Audit against bot_trades
            # to confirm — if no row covers those extra sells, they are
            # genuine orphan shares the bot doesn't track.
            return "CARRYOVER_FLATTENED"

        if long_legs > 0 and short_legs > 0:
            return "MULTI_LEG_MIXED"
        if long_legs > 1:
            return "MULTI_LEG_LONG"
        if short_legs > 1:
            return "MULTI_LEG_SHORT"
        if short_legs == 1 and long_legs == 0:
            return "INVERSION_SHORT_COVER"
        if long_legs == 1 and short_legs == 0:
            return "CLEAN_ROUND_TRIP"
        return "UNKNOWN"

    def fragmentation_warning(self) -> Optional[str]:
        if self.fill_count >= 30:
            return f"high_fragmentation_{self.fill_count}_fills"
        if len(self.venues) >= 6:
            return f"venue_spread_{len(self.venues)}_venues"
        return None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "fill_count": self.fill_count,
            "bought_qty": self.bought_qty,
            "sold_qty": self.sold_qty,
            "bought_dollars": round(self.bought_dollars, 2),
            "sold_dollars": round(self.sold_dollars, 2),
            "fees_total": round(self.fees_total, 2),
            "venues": sorted(self.venues),
            "earliest_time": self.earliest_time,
            "latest_time": self.latest_time,
            "eod_flatten": self.eod_flatten,
            "net_position": self.net_position,
            "open_residual_qty": self.open_residual_qty,
            "realized_pnl": round(self.realized_pnl, 2),
            "realized_pnl_after_fees": round(self.realized_pnl_after_fees, 2),
            "has_inversion": self.has_inversion,
            "has_open_short_residual": self.has_open_short_residual,
            "short_leg_count": len(self.short_legs),
            "verdict": self.verdict(),
            "fragmentation_warning": self.fragmentation_warning(),
            "closed_legs": [asdict(t) for t in self.closed_legs],
        }


def find_unmatched_short_activity(
    audits: dict[str, SymbolAudit],
    bot_trades_summary: Optional[dict] = None,
) -> list[dict]:
    """v19.34.16 — flag Sell Short / Buy to Cover transactions that have
    NO matching `bot_trades` row.

    Returns one dict per unmatched symbol. Two unmatched classes:
      • `unmatched_short_round_trip` — tape shows a SHORT FIFO leg
        (sell-short → buy-to-cover) but `bot_trades` has zero rows
        with direction=short for the symbol.
      • `unmatched_open_short` — tape ends with `open_residual_qty < 0`
        (still-open short position at end-of-tape) and the bot has no
        open short row for the symbol.

    When `bot_trades_summary` is None, only tape-level signals are
    used (residual-short symbols are flagged as suspicious-no-record).
    """
    findings: list[dict] = []
    for sym, a in audits.items():
        bs = (bot_trades_summary or {}).get(sym) or {}
        # Allow either a list of directions or a CSV string in the
        # summary. Operator export script may shape it either way.
        directions_raw = bs.get("directions") or bs.get("direction") or []
        if isinstance(directions_raw, str):
            bot_dirs = {d.strip().lower() for d in directions_raw.split(",") if d.strip()}
        else:
            bot_dirs = {str(d).lower() for d in directions_raw if d}

        # Class 1: SHORT round-trip(s) on tape, no matching short bot row.
        if a.short_legs:
            if bot_trades_summary is None:
                findings.append({
                    "symbol": sym,
                    "kind": "unmatched_short_round_trip_no_bot_data",
                    "short_leg_count": len(a.short_legs),
                    "qty_total": sum(t.qty for t in a.short_legs),
                    "realized_pnl": round(sum(t.pnl for t in a.short_legs), 2),
                    "detail": "bot_trades_summary not provided — cannot cross-check",
                })
            elif "short" not in bot_dirs:
                findings.append({
                    "symbol": sym,
                    "kind": "unmatched_short_round_trip",
                    "short_leg_count": len(a.short_legs),
                    "qty_total": sum(t.qty for t in a.short_legs),
                    "realized_pnl": round(sum(t.pnl for t in a.short_legs), 2),
                    "bot_directions": sorted(bot_dirs),
                    "detail": (
                        f"{sym}: tape has {len(a.short_legs)} SHORT "
                        f"round-trip(s) but bot_trades has no direction=short row. "
                        "This is exactly the class of leak v19.34.15a is "
                        "designed to prevent."
                    ),
                })

        # Class 2: residual short open at end-of-tape, no matching bot row.
        if a.has_open_short_residual:
            if bot_trades_summary is None or "short" not in bot_dirs:
                findings.append({
                    "symbol": sym,
                    "kind": "unmatched_open_short",
                    "residual_qty": a.open_residual_qty,
                    "detail": (
                        f"{sym}: tape ends with {a.open_residual_qty:+d} sh "
                        "(still-open short) and bot has no matching short row. "
                        "Run `POST /api/trading-bot/reconcile-share-drift` "
                        "to reconcile."
                    ),
                })

    return findings


def fifo_match_legs(fills: list[Fill]) -> tuple[list[FifoTrade], int]:
    """
    Walk fills in chronological order. Maintain a signed inventory deque:
      - positive entries = long lots (qty, open_price, open_time)
      - negative entries = short lots (qty, open_price, open_time)
    On each fill, match against the existing inventory in FIFO order
    closing legs whose direction is opposite to the incoming fill;
    any remainder opens a new lot.

    Returns (closed_legs, signed_open_residual).
    """
    inventory: deque[tuple[int, float, str]] = deque()  # signed qty, price, time
    closed: list[FifoTrade] = []

    sorted_fills = sorted(fills, key=lambda f: f.time_minutes)

    for f in sorted_fills:
        incoming_qty = f.qty if f.side == "BUY" else -f.qty
        while incoming_qty != 0 and inventory:
            head_qty, head_price, head_time = inventory[0]
            if (incoming_qty > 0) == (head_qty > 0):
                # Same direction — append, don't match.
                break
            match_qty = min(abs(incoming_qty), abs(head_qty))
            # Determine direction of the leg being closed:
            if head_qty > 0:
                # Long lot, sold by incoming SELL.
                pnl = match_qty * (f.price - head_price)
                direction = "LONG"
                open_price = head_price
                close_price = f.price
                open_time = head_time
                close_time = f.time_str
            else:
                # Short lot, covered by incoming BUY.
                pnl = match_qty * (head_price - f.price)
                direction = "SHORT"
                open_price = head_price
                close_price = f.price
                open_time = head_time
                close_time = f.time_str
            closed.append(
                FifoTrade(
                    direction=direction,
                    qty=match_qty,
                    open_price=round(open_price, 4),
                    close_price=round(close_price, 4),
                    open_time=open_time,
                    close_time=close_time,
                    pnl=round(pnl, 2),
                )
            )
            new_head = head_qty + (match_qty if head_qty < 0 else -match_qty)
            if new_head == 0:
                inventory.popleft()
            else:
                inventory[0] = (new_head, head_price, head_time)
            incoming_qty += match_qty if incoming_qty < 0 else -match_qty

        if incoming_qty != 0:
            inventory.append((incoming_qty, f.price, f.time_str))

    residual = sum(q for q, _, _ in inventory)
    return closed, residual


def aggregate_by_symbol(fills: list[Fill]) -> dict[str, SymbolAudit]:
    by_sym: dict[str, SymbolAudit] = defaultdict(lambda: SymbolAudit(symbol=""))
    for f in fills:
        a = by_sym[f.symbol]
        a.symbol = f.symbol
        a.fills.append(f)
        a.fill_count += 1
        a.fees_total += f.fees
        a.venues.add(f.venue)
        if f.side == "BUY":
            a.bought_qty += f.qty
            a.bought_dollars += f.amount
        else:
            a.sold_qty += f.qty
            a.sold_dollars += f.amount
        if f.time_minutes >= 0:
            if f.time_minutes < a.earliest_min:
                a.earliest_min = f.time_minutes
                a.earliest_time = f.time_str
            if f.time_minutes > a.latest_min:
                a.latest_min = f.time_minutes
                a.latest_time = f.time_str
        # 3:55 PM = 15:55 = 955 minutes
        if f.time_minutes >= 955 and f.time_minutes <= 16 * 60:
            a.eod_flatten = True

    for a in by_sym.values():
        legs, residual = fifo_match_legs(a.fills)
        a.closed_legs = legs
        a.open_residual_qty = residual

    return dict(by_sym)


def render_markdown(audits: dict[str, SymbolAudit], bot_trades_summary: Optional[dict] = None) -> str:
    """
    Severity-sorted markdown report. OPEN_POSITION first, then mixed, then clean.
    """
    severity_order = {
        "OPEN_POSITION_LONG": 0,
        "CARRYOVER_FLATTENED": 1,
        "MULTI_LEG_MIXED": 2,
        "INVERSION_SHORT_COVER": 3,
        "MULTI_LEG_LONG": 4,
        "MULTI_LEG_SHORT": 4,
        "CLEAN_ROUND_TRIP": 5,
        "UNKNOWN": 6,
    }

    rows = list(audits.values())
    rows.sort(key=lambda a: (severity_order.get(a.verdict(), 5), -a.fill_count))

    total_buy = sum(a.bought_dollars for a in rows)
    total_sell = sum(a.sold_dollars for a in rows)
    total_pnl = sum(a.realized_pnl for a in rows)
    total_fees = sum(a.fees_total for a in rows)
    total_fills = sum(a.fill_count for a in rows)
    total_open_residual = sum(a.open_residual_qty for a in rows if a.open_residual_qty != 0)

    out = []
    out.append("# IB Fill Tape Audit — 2026-05-04")
    out.append("")
    out.append("**Account: DUN615665 (PAPER — DU* prefix)**")
    out.append("")

    # Operator-findings block: surfaces the highest-signal items first.
    findings: list[str] = []

    # Carryover hint: if any symbol has -residual it likely means prior-day
    # inventory was flushed today.
    carryovers = [a for a in rows if a.verdict() == "CARRYOVER_FLATTENED"]
    if carryovers:
        findings.append(
            "**Prior-day carryover flushed today** — "
            + ", ".join(
                f"{a.symbol} ({a.open_residual_qty:+d}sh)" for a in carryovers
            )
            + ". These extra sells likely came from positions held overnight. "
            "Cross-check `bot_trades` for this symbol with `executed_at < today_start_ET` "
            "to confirm the bot owned them. If the bot has no record, they are "
            "**genuine orphan shares** that need a `POST /api/trading-bot/reconcile` "
            "before the bot can report on the round-trip PnL accurately."
        )

    # Open positions still alive at end-of-tape.
    opens = [a for a in rows if a.verdict() == "OPEN_POSITION_LONG"]
    if opens:
        findings.append(
            "**Still-open at end-of-tape** — "
            + ", ".join(f"{a.symbol} ({a.open_residual_qty:+d}sh)" for a in opens)
            + ". Verify against `/api/sentcom/positions` snapshot."
        )

    # Heavy fragmentation: ≥30 fills per symbol or ≥7 venues per symbol.
    fragged = [a for a in rows if a.fragmentation_warning()]
    if fragged:
        findings.append(
            "**Heavy fragmentation** (broker venue split) — "
            + ", ".join(
                f"{a.symbol} ({a.fill_count}f / {len(a.venues)}v)" for a in fragged
            )
            + ". The bot's `bot_trades` row should aggregate these into a single "
            "fill record per execution; if Mongo shows separate rows per venue "
            "fragment for the same parent order, the executor's fill-aggregation "
            "is broken."
        )

    # Biggest losers / winners.
    sorted_by_pnl = sorted(rows, key=lambda a: a.realized_pnl)
    losers = [a for a in sorted_by_pnl if a.realized_pnl < -250][:5]
    winners = [a for a in sorted_by_pnl if a.realized_pnl > 0][-3:][::-1]
    if losers:
        findings.append(
            "**Top losers (gross)** — "
            + ", ".join(f"{a.symbol} ${a.realized_pnl:+,.0f}" for a in losers)
        )
    if winners:
        findings.append(
            "**Winners (gross)** — "
            + ", ".join(f"{a.symbol} ${a.realized_pnl:+,.0f}" for a in winners)
        )

    # Inversion (short-cover) symbols — these are short setups the bot took.
    invs = [a for a in rows if a.verdict() == "INVERSION_SHORT_COVER" or
            (a.verdict() == "MULTI_LEG_SHORT" and any(t.direction == "SHORT" for t in a.closed_legs))]
    if invs:
        findings.append(
            "**Short-direction trades today** — "
            + ", ".join(f"{a.symbol}" for a in invs)
            + ". Confirm `direction='short'` on the matching `bot_trades` rows; "
            "v19.29 added a 30s direction-stability gate so a SHORT row materialized "
            "right after a LONG eval should NOT exist."
        )

    if findings:
        out.append("## Operator findings")
        out.append("")
        for f in findings:
            out.append(f"- {f}")
        out.append("")

    out.append("## Summary")
    out.append("")
    out.append(f"- **Total fills**: {total_fills}")
    out.append(f"- **Symbols traded**: {len(rows)}")
    out.append(f"- **Total bought**: ${total_buy:,.2f}")
    out.append(f"- **Total sold**: ${total_sell:,.2f}")
    out.append(f"- **Realized PnL (FIFO, gross of fees)**: ${total_pnl:+,.2f}")
    out.append(f"- **Total fees**: ${total_fees:,.2f}")
    out.append(f"- **Net realized after fees**: ${total_pnl - total_fees:+,.2f}")
    out.append(f"- **Symbols with non-zero residual**: "
               f"{sum(1 for a in rows if a.open_residual_qty != 0)} "
               f"(net residual shares: {total_open_residual:+d})")
    out.append("")
    out.append("## Verdict counts")
    out.append("")
    verdict_counts: dict[str, int] = defaultdict(int)
    for a in rows:
        verdict_counts[a.verdict()] += 1
    for v, c in sorted(verdict_counts.items(), key=lambda kv: severity_order.get(kv[0], 5)):
        out.append(f"- `{v}`: {c}")
    out.append("")
    out.append("## Per-symbol audit (severity sorted)")
    out.append("")
    out.append("| Symbol | Verdict | Fills | Bought | Sold | Net | Realized PnL | Fees | Earliest | Latest | EOD-flat? | Frag warn |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---|---|:---:|---|")
    for a in rows:
        frag = a.fragmentation_warning() or "-"
        out.append(
            f"| **{a.symbol}** | `{a.verdict()}` | {a.fill_count} "
            f"| {a.bought_qty:,} | {a.sold_qty:,} | {a.net_position:+d} "
            f"| ${a.realized_pnl:+,.2f} | ${a.fees_total:,.2f} "
            f"| {a.earliest_time} | {a.latest_time} "
            f"| {'✓' if a.eod_flatten else '-'} | {frag} |"
        )
    out.append("")
    out.append("## Per-symbol leg detail")
    out.append("")
    for a in rows:
        out.append(f"### {a.symbol} — `{a.verdict()}`")
        out.append("")
        out.append(f"- Bought: **{a.bought_qty:,}sh** for **${a.bought_dollars:,.2f}** "
                   f"(avg ${a.bought_dollars / a.bought_qty:.4f})" if a.bought_qty > 0
                   else "- Bought: 0sh")
        out.append(f"- Sold: **{a.sold_qty:,}sh** for **${a.sold_dollars:,.2f}** "
                   f"(avg ${a.sold_dollars / a.sold_qty:.4f})" if a.sold_qty > 0
                   else "- Sold: 0sh")
        out.append(f"- Net position end-of-tape: **{a.net_position:+d}sh** "
                   f"(open residual: {a.open_residual_qty:+d}sh)")
        out.append(f"- Realized PnL: **${a.realized_pnl:+,.2f}** (after fees: "
                   f"${a.realized_pnl_after_fees:+,.2f})")
        out.append(f"- Fees: **${a.fees_total:,.2f}**")
        out.append(f"- Fragmentation: {a.fill_count} fills across {len(a.venues)} "
                   f"venues — {', '.join(sorted(a.venues))}")
        out.append(f"- Time window: {a.earliest_time} → {a.latest_time}")
        if a.eod_flatten:
            out.append("- **Touched EOD-flatten window** (≥3:55 PM)")
        if a.has_inversion:
            out.append("- **Sold before buying — short-direction round-trip**")
        if a.closed_legs:
            out.append("")
            out.append("  | Direction | Qty | Open @ | Close @ | Open Time | Close Time | PnL |")
            out.append("  |---|---:|---:|---:|---|---|---:|")
            for leg in a.closed_legs:
                out.append(
                    f"  | {leg.direction} | {leg.qty:,} | ${leg.open_price:.4f} "
                    f"| ${leg.close_price:.4f} | {leg.open_time} | {leg.close_time} "
                    f"| ${leg.pnl:+,.2f} |"
                )
        out.append("")

    if bot_trades_summary:
        out.append("## Cross-check vs `bot_trades` (Mongo)")
        out.append("")
        out.append("Operator-supplied `bot_trades` export was loaded. Per-symbol diff:")
        out.append("")
        out.append("| Symbol | Tape verdict | Bot rows | Bot sum qty | Tape sum qty | Match? |")
        out.append("|---|---|---:|---:|---:|:---:|")
        for sym, a in sorted(audits.items()):
            bs = bot_trades_summary.get(sym)
            if not bs:
                out.append(f"| **{sym}** | `{a.verdict()}` | 0 | 0 | "
                           f"{max(a.bought_qty, a.sold_qty)} | ⚠ NO BOT ROWS |")
                continue
            match = bs.get("total_qty", 0) == max(a.bought_qty, a.sold_qty)
            out.append(
                f"| **{sym}** | `{a.verdict()}` | {bs.get('row_count', 0)} "
                f"| {bs.get('total_qty', 0):,} | {max(a.bought_qty, a.sold_qty):,} "
                f"| {'✓' if match else '✗'} |"
            )
        # symbols in bot_trades but missing from tape
        unmatched = sorted(set(bot_trades_summary.keys()) - set(audits.keys()))
        if unmatched:
            out.append("")
            out.append(f"### ⚠ Symbols in `bot_trades` but NOT in IB tape ({len(unmatched)})")
            out.append("")
            for s in unmatched:
                bs = bot_trades_summary[s]
                out.append(f"- `{s}` — {bs.get('row_count', 0)} bot rows, "
                           f"total qty {bs.get('total_qty', 0)}. Possible phantom or "
                           f"non-paper row.")

    # v19.34.16 — Unmatched Sell Short / Buy to Cover detection.
    short_findings = find_unmatched_short_activity(audits, bot_trades_summary)
    if short_findings:
        out.append("")
        out.append(f"## ⚠ Unmatched Short Activity ({len(short_findings)})")
        out.append("")
        out.append("Sell Short / Buy to Cover transactions on the tape that "
                   "have **no matching `bot_trades` row**. This is exactly "
                   "the leak class the v19.34.15a Naked-position safety net "
                   "is designed to prevent.")
        out.append("")
        out.append("| Symbol | Kind | Detail |")
        out.append("|---|---|---|")
        for f in short_findings:
            _det = (f.get('detail') or '').replace('|', r'\|')
            out.append(f"| **{f['symbol']}** | `{f['kind']}` | {_det} |")

    out.append("")
    out.append("---")
    out.append(f"_Report generated {datetime.now().isoformat(timespec='seconds')}_")
    return "\n".join(out)


def load_bot_trades_summary(path: Path) -> dict:
    """
    Operator-supplied JSON export from Spark Mongo:
      mongo --quiet --eval 'db.bot_trades.aggregate([
        {$match:{closed_at:{$gte:ISODate("2026-05-04T00:00:00Z")}}},
        {$group:{_id:"$symbol",row_count:{$sum:1},total_qty:{$sum:"$shares"}}}
      ]).toArray()' > bot_trades_today.json
    Or any list-of-{symbol,row_count,total_qty}.
    """
    raw = json.loads(path.read_text())
    if isinstance(raw, list):
        return {r.get("symbol") or r.get("_id"): r for r in raw}
    return raw


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, help="Path to IB tape paste (default: stdin)")
    ap.add_argument("--out", type=Path, help="Markdown report output path")
    ap.add_argument("--json", type=Path, dest="json_out", help="JSON sidecar output path")
    ap.add_argument("--bot-trades-json", type=Path, help="Spark Mongo export for cross-check")
    args = ap.parse_args(argv)

    if args.input:
        text = args.input.read_text()
    else:
        text = sys.stdin.read()

    fills = parse_tape(text)
    if not fills:
        print("ERROR: no fills parsed from tape", file=sys.stderr)
        return 2

    audits = aggregate_by_symbol(fills)

    bt = None
    if args.bot_trades_json and args.bot_trades_json.exists():
        bt = load_bot_trades_summary(args.bot_trades_json)

    md = render_markdown(audits, bot_trades_summary=bt)
    if args.out:
        args.out.write_text(md)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(md)

    if args.json_out:
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "fill_count": len(fills),
            "symbols": {s: a.to_dict() for s, a in audits.items()},
            "unmatched_short_activity": find_unmatched_short_activity(audits, bt),
        }
        args.json_out.write_text(json.dumps(payload, indent=2))
        print(f"wrote {args.json_out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
