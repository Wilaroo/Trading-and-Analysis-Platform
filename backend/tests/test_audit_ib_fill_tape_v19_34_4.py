"""
Tests for the IB fill-tape audit parser (v19.34.4 — 2026-05-04).

Covers:
  - Parser correctness on the TWS paste format (single fill).
  - Multi-fill same-symbol aggregation.
  - FIFO matching: clean LONG round-trip.
  - FIFO matching: short-then-cover (inversion) round-trip.
  - FIFO matching: multi-leg mixed (LONG + SHORT in same day).
  - Carryover detection (sold > bought today).
  - Heavy fragmentation warning.
  - Severity ordering of verdict labels.
"""
import sys
from pathlib import Path

# Ensure backend/ is importable so `scripts.audit_ib_fill_tape` works.
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_ib_fill_tape import (  # noqa: E402
    aggregate_by_symbol,
    fifo_match_legs,
    parse_tape,
    parse_time_to_minutes,
    Fill,
)


def make_fill(symbol, side, qty, price, when="9:30 AM", venue="NASDAQ", fees=0.0):
    return Fill(
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        venue=venue,
        time_str=when,
        time_minutes=parse_time_to_minutes(when),
        account="DUN615665",
        fees=fees,
        amount=qty * price,
    )


def test_parser_handles_single_fill_record():
    sample = """Trades 	Account	Action	 Quantity	Status 	 Price	 Amount		
STX
Sold 38 @ 737.73 on NASDAQ
DUN615665	Sold	38	
Filled
3:57 PM
737.73	
28033.74
Fees: 1.59
"""
    fills = parse_tape(sample)
    assert len(fills) == 1
    f = fills[0]
    assert f.symbol == "STX"
    assert f.side == "SELL"
    assert f.qty == 38
    assert f.price == 737.73
    assert f.venue == "NASDAQ"
    assert f.fees == 1.59
    assert f.account == "DUN615665"
    assert f.amount == 28033.74
    assert f.time_str == "3:57 PM"
    assert f.time_minutes == 15 * 60 + 57


def test_parser_handles_thousand_separator_qty():
    sample = """SOXS
Sold 1600 @ 13.27 on BYX
DUN615665	Sold	1,600	
Filled
3:55 PM
13.27	
21232
Fees: 8.75
"""
    fills = parse_tape(sample)
    assert len(fills) == 1
    assert fills[0].qty == 1600


def test_parser_handles_bot_action_word():
    sample = """GM
Bot 193 @ 75.71 on DRCTEDGE
DUN615665	Bot	193	
Filled
3:51 PM
75.71	
14612.03
Fees: 0.97
"""
    fills = parse_tape(sample)
    assert len(fills) == 1
    assert fills[0].side == "BUY"
    assert fills[0].qty == 193


def test_parser_handles_multiple_records():
    sample = """STX
Sold 38 @ 737.73 on NASDAQ
DUN615665	Sold	38	
Filled
3:57 PM
737.73	
28033.74
Fees: 1.59
STX
Sold 17 @ 737.73 on NASDAQ
DUN615665	Sold	17	
Filled
3:57 PM
737.73	
12541.41
Fees: 0.26
"""
    fills = parse_tape(sample)
    assert len(fills) == 2
    assert all(f.symbol == "STX" for f in fills)
    assert sum(f.qty for f in fills) == 55


def test_fifo_clean_long_round_trip():
    fills = [
        make_fill("AAPL", "BUY", 100, 150.00, "9:30 AM"),
        make_fill("AAPL", "SELL", 100, 152.00, "10:00 AM"),
    ]
    legs, residual = fifo_match_legs(fills)
    assert residual == 0
    assert len(legs) == 1
    assert legs[0].direction == "LONG"
    assert legs[0].qty == 100
    assert legs[0].pnl == 200.0


def test_fifo_short_then_cover_inversion():
    fills = [
        make_fill("XYZ", "SELL", 100, 50.00, "9:30 AM"),
        make_fill("XYZ", "BUY", 100, 49.50, "10:00 AM"),
    ]
    legs, residual = fifo_match_legs(fills)
    assert residual == 0
    assert len(legs) == 1
    assert legs[0].direction == "SHORT"
    assert legs[0].qty == 100
    # Short PnL = open - close = 50.00 - 49.50 = +0.50/share
    assert legs[0].pnl == 50.0


def test_fifo_multi_leg_mixed_long_then_short():
    """Bot opens long, closes long, opens short, covers — typical V/WDC pattern."""
    fills = [
        make_fill("XYZ", "BUY", 100, 100.00, "9:30 AM"),
        make_fill("XYZ", "SELL", 100, 99.50, "9:35 AM"),  # closes long: -50
        make_fill("XYZ", "SELL", 100, 99.00, "9:40 AM"),  # opens short
        make_fill("XYZ", "BUY", 100, 98.50, "9:45 AM"),  # closes short: +50
    ]
    legs, residual = fifo_match_legs(fills)
    assert residual == 0
    assert len(legs) == 2
    assert legs[0].direction == "LONG"
    assert legs[0].pnl == -50.0
    assert legs[1].direction == "SHORT"
    assert legs[1].pnl == 50.0


def test_fifo_partial_fills_aggregate():
    """Heavy venue fragmentation should still match correctly across partials."""
    fills = [
        make_fill("BKNG", "BUY", 30, 169.38, "9:35 AM", venue="ARCA"),
        make_fill("BKNG", "BUY", 9, 169.32, "9:35 AM", venue="NASDAQ"),
        make_fill("BKNG", "BUY", 20, 169.32, "9:35 AM", venue="ARCA"),
        make_fill("BKNG", "SELL", 30, 166.10, "11:48 AM", venue="NASDAQ"),
        make_fill("BKNG", "SELL", 29, 166.10, "11:48 AM", venue="BATS"),
    ]
    legs, residual = fifo_match_legs(fills)
    assert residual == 0
    assert len(legs) == 3  # 30 → 30, 9 → 9, 20 → 20 = 3 legs
    assert sum(leg.qty for leg in legs) == 59
    total_pnl = sum(leg.pnl for leg in legs)
    # Approximate check: ~3 down × 59 shares ≈ -190
    assert total_pnl < -150


def test_carryover_flattened_verdict_when_sold_more_than_bought():
    """STX-style: prior-day inventory carryover got flushed today."""
    fills = [
        make_fill("STX", "BUY", 100, 735.0, "9:32 AM"),
        make_fill("STX", "SELL", 113, 737.0, "3:57 PM"),  # 13 extra sells
    ]
    audits = aggregate_by_symbol(fills)
    a = audits["STX"]
    assert a.bought_qty == 100
    assert a.sold_qty == 113
    assert a.net_position == -13
    assert a.open_residual_qty == -13
    assert a.verdict() == "CARRYOVER_FLATTENED"


def test_open_position_long_verdict_when_bought_more_than_sold():
    fills = [
        make_fill("ZZZ", "BUY", 100, 50.0, "9:30 AM"),
        make_fill("ZZZ", "SELL", 50, 51.0, "10:00 AM"),
    ]
    audits = aggregate_by_symbol(fills)
    a = audits["ZZZ"]
    assert a.open_residual_qty == 50
    assert a.verdict() == "OPEN_POSITION_LONG"


def test_high_fragmentation_warning():
    fills = []
    for i in range(35):
        fills.append(make_fill("BKNG", "BUY", 10, 169.0, "9:35 AM",
                               venue=f"V{i % 4}"))
    fills.append(make_fill("BKNG", "SELL", 350, 168.0, "11:48 AM"))
    audits = aggregate_by_symbol(fills)
    a = audits["BKNG"]
    assert a.fragmentation_warning() is not None
    assert "high_fragmentation" in a.fragmentation_warning()


def test_eod_flatten_detected_for_355pm_or_later():
    fills = [
        make_fill("X", "BUY", 100, 50.0, "9:30 AM"),
        make_fill("X", "SELL", 100, 50.5, "3:55 PM"),
    ]
    audits = aggregate_by_symbol(fills)
    assert audits["X"].eod_flatten is True


def test_eod_flatten_not_set_for_pre_355pm_close():
    fills = [
        make_fill("X", "BUY", 100, 50.0, "9:30 AM"),
        make_fill("X", "SELL", 100, 50.5, "11:48 AM"),
    ]
    audits = aggregate_by_symbol(fills)
    assert audits["X"].eod_flatten is False


def test_real_tape_fixture_parses_to_expected_totals():
    fixture = Path(__file__).parent.parent.parent / "memory" / "audit" / "2026-05-04_ib_fill_tape.txt"
    if not fixture.exists():
        return  # skip if fixture missing in fork environments
    text = fixture.read_text()
    fills = parse_tape(text)
    audits = aggregate_by_symbol(fills)
    assert len(fills) == 328, f"expected 328 fills, parser returned {len(fills)}"
    assert len(audits) == 21, f"expected 21 symbols, got {len(audits)}"
    # STX must be flagged as carryover-flattened (sold > bought today).
    assert audits["STX"].verdict() == "CARRYOVER_FLATTENED"
    assert audits["STX"].open_residual_qty == -17
    # Every other symbol should be net-zero at end-of-tape.
    for sym, a in audits.items():
        if sym == "STX":
            continue
        assert a.net_position == 0, f"{sym} expected net 0, got {a.net_position}"


def test_total_realized_pnl_sign_matches_losing_day():
    fixture = Path(__file__).parent.parent.parent / "memory" / "audit" / "2026-05-04_ib_fill_tape.txt"
    if not fixture.exists():
        return
    text = fixture.read_text()
    fills = parse_tape(text)
    audits = aggregate_by_symbol(fills)
    total_realized = sum(a.realized_pnl for a in audits.values())
    # 2026-05-04 was a -$14k day; just bound it loosely so a parser regression
    # that flips the sign or off by an order of magnitude trips this.
    assert total_realized < -10_000
    assert total_realized > -20_000
