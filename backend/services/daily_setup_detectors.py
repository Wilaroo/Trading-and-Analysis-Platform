"""
daily_setup_detectors.py  ·  v19.34.95
─────────────────────────────────────────────────────────────────────────────
Pure-function daily-bar detectors for SWING / INVESTMENT / POSITION setups.

Each detector:
  signature: detector(symbol: str, bars: list[dict], **ctx) -> Optional[LiveAlert]
  bars      : daily OHLCV bars (oldest first), each with keys
              date / open / high / low / close / volume
  ctx       : optional kwargs — most importantly `spy_closes` (list[float]) for
              RS-based detectors. Detectors degrade gracefully if absent.

Why a separate module:
  * keeps enhanced_scanner.py from growing further
  * pure-function detectors are unit-testable without async setup
  * lets us register each detector by name in a single dispatch dict

Detectors implemented (20 total — 7 swing + 6 investment + 7 position):
  Swing:
    pocket_pivot, vcp_breakout, three_week_tight, bull_flag_break,
    bear_flag_break, ascending_triangle_break, descending_triangle_break,
    cup_with_high_handle
  Investment:
    weekly_breakout, multi_quarter_base_break, rs_leader_break,
    fifty_two_week_high_break, power_trend_stack
  Position:
    stage_2_breakout, stage_1_to_2_transition, stage_3_to_4_breakdown,
    golden_cross_filtered, death_cross_filtered, two_hundred_day_reclaim,
    two_hundred_day_loss
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from services.enhanced_scanner import LiveAlert

from services.daily_setup_helpers import (
    aggregate_to_weekly,
    atr as calc_atr,
    consolidation_range_pct,
    detect_flat_base,
    ema_series,
    is_breaking_out,
    mansfield_rs,
    pct_change,
    relative_strength_rank,
    rsi,
    sma,
    sma_series,
)


# ─────────────────────────────────────────────────────────────────
# LiveAlert factory — fills the 7 required fields that vanilla
# daily detectors otherwise omit. Without this helper LiveAlert()
# raises TypeError at construction time (latent bug in the existing
# _check_daily_squeeze + cousins, silently swallowed by the
# try/except wrapper in _scan_daily_setups).
# ─────────────────────────────────────────────────────────────────
def make_daily_alert(
    symbol: str,
    setup_type: str,
    direction: str,
    *,
    trigger_price: float,
    stop_loss: float,
    target: float,
    headline: str,
    reasoning: List[str],
    bucket: str,                     # "swing" | "investment" | "position"
    setup_category: str,             # SMB category
    priority: str = "HIGH",          # "HIGH" | "MEDIUM" | "LOW" | "CRITICAL"
    expires_hours: int = 72,
    risk_reward: Optional[float] = None,
):
    """Construct a LiveAlert with daily-bar appropriate defaults.

    Imports LiveAlert/AlertPriority lazily so this module can be loaded
    without dragging in the full enhanced_scanner.
    """
    from services.enhanced_scanner import AlertPriority, LiveAlert

    prio = getattr(AlertPriority, priority, AlertPriority.HIGH)

    if risk_reward is None:
        risk = abs(trigger_price - stop_loss)
        reward = abs(target - trigger_price)
        risk_reward = (reward / risk) if risk > 0 else 0.0

    # trade_style + scan_tier come from the bucket
    style_map = {"swing": "multi_day", "investment": "swing", "position": "position"}
    trade_style = style_map.get(bucket, "multi_day")
    scan_tier = "swing" if bucket == "swing" else "investment"

    now = datetime.now(timezone.utc)
    return LiveAlert(
        id=f"{setup_type}_{symbol}_{direction}_{now.strftime('%Y%m%d_%H%M%S')}",
        symbol=symbol,
        setup_type=setup_type,
        strategy_name=setup_type,
        direction=direction,
        priority=prio,
        current_price=trigger_price,
        trigger_price=trigger_price,
        stop_loss=round(stop_loss, 2),
        target=round(target, 2),
        risk_reward=round(risk_reward, 2),
        trigger_probability=0.6,
        win_probability=0.55,
        minutes_to_trigger=0,
        headline=headline,
        reasoning=reasoning,
        time_window="DAILY",
        market_regime="neutral",
        trade_style=trade_style,
        setup_category=setup_category,
        scan_tier=scan_tier,
        direction_bias=direction,
        expires_at=(now + timedelta(hours=expires_hours)).isoformat(),
    )


# ─────────────────────────────────────────────────────────────────
# Common gates
# ─────────────────────────────────────────────────────────────────
def _avg_volume(bars: List[Dict], n: int = 50) -> Optional[float]:
    if len(bars) < n:
        return None
    return sum(b.get("volume", 0) or 0 for b in bars[-n:]) / n


def _enough(bars: List[Dict], n: int) -> bool:
    return len(bars) >= n


# ═════════════════════════════════════════════════════════════════
# SWING DETECTORS  (8 — runs S1-S8 except S6 which needs earnings)
# ═════════════════════════════════════════════════════════════════
def pocket_pivot(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """O'Neil pocket pivot — first up-day where today's volume exceeds the
    LARGEST down-volume bar of the last 10 sessions AND today's close is
    above the 10-day high (or the 50-day SMA, whichever is higher).
    """
    if not _enough(bars, 51):
        return None
    last10 = bars[-11:-1]                                    # 10 prior sessions
    today = bars[-1]
    if today["close"] <= today["open"]:
        return None
    down_vols = [b["volume"] for b in last10 if b["close"] < b["open"]]
    if not down_vols:
        return None
    if today["volume"] <= max(down_vols):
        return None
    ten_day_high = max(b["high"] for b in last10)
    closes = [b["close"] for b in bars]
    sma_50 = sma(closes, 50) or 0
    if today["close"] < max(ten_day_high, sma_50):
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "pocket_pivot", "long",
        trigger_price=today["close"],
        stop_loss=today["close"] - 2 * last_atr,
        target=today["close"] + 4 * last_atr,
        headline=f"{symbol} POCKET PIVOT — vol > 10d max down-vol, above 10d high",
        reasoning=[
            f"Today's vol {today['volume']:,.0f} > 10d max down-vol {max(down_vols):,.0f}",
            f"Close {today['close']:.2f} > 10-day high {ten_day_high:.2f}",
            f"50-day SMA: {sma_50:.2f} — uptrend intact",
        ],
        bucket="swing", setup_category="consolidation",
    )


def vcp_breakout(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Minervini Volatility Contraction — 3 sequential pullbacks each shallower
    than the prior, then breakout above the most recent pivot on volume.
    """
    if not _enough(bars, 80):
        return None
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    pivots_high = []
    pivots_low = []
    for i in range(5, len(bars) - 5):
        win_h = highs[i - 5:i + 6]
        win_l = lows[i - 5:i + 6]
        if highs[i] == max(win_h):
            pivots_high.append((i, highs[i]))
        if lows[i] == min(win_l):
            pivots_low.append((i, lows[i]))

    if len(pivots_high) < 3 or len(pivots_low) < 3:
        return None

    recent_highs = pivots_high[-3:]
    recent_lows = pivots_low[-3:]

    contractions = []
    for ph, pl in zip(recent_highs, recent_lows):
        hi, lo = ph[1], pl[1]
        if hi <= 0:
            return None
        contractions.append((hi - lo) / hi * 100.0)

    if not (contractions[0] > contractions[1] > contractions[2] and contractions[2] < 15.0):
        return None

    pivot_high_price = recent_highs[-1][1]
    if not is_breaking_out(bars, pivot_high_price, vol_mult=1.4, vol_lookback=50):
        return None
    today = bars[-1]
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "vcp_breakout", "long",
        trigger_price=today["close"],
        stop_loss=pivot_high_price - 0.5 * last_atr,
        target=today["close"] + 3 * (today["close"] - pivot_high_price + last_atr),
        headline=f"{symbol} VCP BREAKOUT — contractions {contractions[0]:.0f}%→{contractions[1]:.0f}%→{contractions[2]:.0f}%",
        reasoning=[
            "Minervini VCP: 3 sequential pullbacks each shallower",
            f"Pivot break: close {today['close']:.2f} > pivot {pivot_high_price:.2f}",
            "Volume confirmation >=1.4x 50d avg",
        ],
        bucket="swing", setup_category="consolidation",
    )


def three_week_tight(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Minervini 3-week-tight: three consecutive weekly closes within ±1.5%
    of each other while price is above rising 50-day SMA.
    """
    if not _enough(bars, 60):
        return None
    weekly = aggregate_to_weekly(bars)
    if len(weekly) < 4:
        return None
    last3 = [w["close"] for w in weekly[-3:]]
    pivot = max(last3)
    if min(last3) <= 0:
        return None
    drift = (pivot - min(last3)) / pivot * 100.0
    if drift > 1.5:
        return None
    closes = [b["close"] for b in bars]
    sma_50 = sma(closes, 50) or 0
    sma_50_prev = sma(closes[:-5], 50) or 0
    if closes[-1] <= sma_50 or sma_50 <= sma_50_prev:
        return None
    today = bars[-1]
    range_high = max(w["high"] for w in weekly[-3:])
    if today["close"] < range_high * 0.999:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "three_week_tight", "long",
        trigger_price=today["close"],
        stop_loss=min(w["low"] for w in weekly[-3:]),
        target=today["close"] + 3 * last_atr,
        headline=f"{symbol} 3-WEEK-TIGHT — drift {drift:.2f}% in last 3 wks, breaking range high",
        reasoning=[
            f"3 weekly closes within {drift:.2f}% of each other",
            f"Above rising 50-day SMA: {sma_50:.2f}",
            f"Breaking 3-week range high {range_high:.2f}",
        ],
        bucket="swing", setup_category="consolidation",
    )


def bull_flag_break(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """5-15 day flag after a 10%+ pole rally in <=10 days; break above flag high."""
    if not _enough(bars, 40):
        return None
    today = bars[-1]
    # Pole: 10-day window ending ~15 days ago, gain >= 10%
    pole_end = bars[-16] if len(bars) >= 16 else None
    pole_start = bars[-25] if len(bars) >= 25 else None
    if pole_end is None or pole_start is None:
        return None
    pole_gain = pct_change(pole_end["close"], pole_start["close"])
    if pole_gain < 10.0:
        return None
    flag = bars[-15:]
    flag_high = max(b["high"] for b in flag[:-1])
    flag_low = min(b["low"] for b in flag[:-1])
    if flag_high <= 0:
        return None
    flag_range_pct = (flag_high - flag_low) / flag_high * 100.0
    if flag_range_pct > pole_gain * 0.5:
        return None
    if today["close"] <= flag_high:
        return None
    if not is_breaking_out(bars, flag_high, vol_mult=1.3, vol_lookback=20):
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "bull_flag_break", "long",
        trigger_price=today["close"],
        stop_loss=flag_low - 0.25 * last_atr,
        target=today["close"] + (pole_end["close"] - pole_start["close"]),
        headline=f"{symbol} BULL FLAG BREAK — pole +{pole_gain:.1f}%, flag range {flag_range_pct:.1f}%",
        reasoning=[
            f"Pole gain {pole_gain:.1f}% over 10 sessions",
            f"Flag range {flag_range_pct:.1f}% (< half pole)",
            f"Break above flag high {flag_high:.2f}",
        ],
        bucket="swing", setup_category="trend_momentum",
    )


def bear_flag_break(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Mirror of bull_flag_break — flag after a 10%+ pole drop, break below flag low."""
    if not _enough(bars, 40):
        return None
    today = bars[-1]
    pole_end = bars[-16] if len(bars) >= 16 else None
    pole_start = bars[-25] if len(bars) >= 25 else None
    if pole_end is None or pole_start is None:
        return None
    pole_drop = pct_change(pole_start["close"], pole_end["close"])
    if pole_drop < 10.0:
        return None
    flag = bars[-15:]
    flag_high = max(b["high"] for b in flag[:-1])
    flag_low = min(b["low"] for b in flag[:-1])
    if flag_high <= 0:
        return None
    flag_range_pct = (flag_high - flag_low) / flag_high * 100.0
    if flag_range_pct > pole_drop * 0.5:
        return None
    if today["close"] >= flag_low:
        return None
    # break-down volume confirmation (inverse of breakout)
    avg_v = _avg_volume(bars, 20) or 0
    if avg_v > 0 and today["volume"] < 1.3 * avg_v:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "bear_flag_break", "short",
        trigger_price=today["close"],
        stop_loss=flag_high + 0.25 * last_atr,
        target=today["close"] - (pole_start["close"] - pole_end["close"]),
        headline=f"{symbol} BEAR FLAG BREAK — pole -{pole_drop:.1f}%, flag range {flag_range_pct:.1f}%",
        reasoning=[
            f"Pole drop {pole_drop:.1f}% over 10 sessions",
            f"Flag range {flag_range_pct:.1f}% (< half pole)",
            f"Break below flag low {flag_low:.2f}",
        ],
        bucket="swing", setup_category="trend_momentum",
    )


def ascending_triangle_break(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Flat horizontal resistance + rising lows over 15-40 sessions, break out."""
    if not _enough(bars, 50):
        return None
    seg = bars[-40:]
    highs = [b["high"] for b in seg]
    lows = [b["low"] for b in seg]
    res = max(highs[:-1])
    # Count touches near resistance (within 1% of res)
    touches = sum(1 for h in highs if abs(h - res) / res < 0.01)
    if touches < 3:
        return None
    # Rising lows — first-third low vs last-third low
    first_third = lows[: len(lows) // 3]
    last_third = lows[-len(lows) // 3 :]
    if not first_third or not last_third:
        return None
    if min(last_third) <= min(first_third) * 1.01:
        return None
    today = bars[-1]
    if today["close"] <= res:
        return None
    if not is_breaking_out(bars, res, vol_mult=1.3, vol_lookback=20):
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    triangle_height = res - min(lows)
    return make_daily_alert(
        symbol, "ascending_triangle_break", "long",
        trigger_price=today["close"],
        stop_loss=res - 0.5 * last_atr,
        target=today["close"] + triangle_height,
        headline=f"{symbol} ASC TRIANGLE BREAK — {touches} touches @ {res:.2f}",
        reasoning=[
            f"Flat resistance {res:.2f} touched {touches}×",
            f"Rising lows: {min(first_third):.2f} → {min(last_third):.2f}",
            "Close above resistance on ≥1.3× vol",
        ],
        bucket="swing", setup_category="consolidation",
    )


def descending_triangle_break(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Flat horizontal support + falling highs, break down."""
    if not _enough(bars, 50):
        return None
    seg = bars[-40:]
    highs = [b["high"] for b in seg]
    lows = [b["low"] for b in seg]
    sup = min(lows[:-1])
    touches = sum(1 for low in lows if abs(low - sup) / sup < 0.01)
    if touches < 3:
        return None
    first_third = highs[: len(highs) // 3]
    last_third = highs[-len(highs) // 3 :]
    if not first_third or not last_third:
        return None
    if max(last_third) >= max(first_third) * 0.99:
        return None
    today = bars[-1]
    if today["close"] >= sup:
        return None
    avg_v = _avg_volume(bars, 20) or 0
    if avg_v > 0 and today["volume"] < 1.3 * avg_v:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    triangle_height = max(highs) - sup
    return make_daily_alert(
        symbol, "descending_triangle_break", "short",
        trigger_price=today["close"],
        stop_loss=sup + 0.5 * last_atr,
        target=today["close"] - triangle_height,
        headline=f"{symbol} DESC TRIANGLE BREAK — {touches} touches @ {sup:.2f}",
        reasoning=[
            f"Flat support {sup:.2f} touched {touches}×",
            f"Falling highs: {max(first_third):.2f} → {max(last_third):.2f}",
            "Close below support on >=1.3x vol",
        ],
        bucket="swing", setup_category="consolidation",
    )


def cup_with_high_handle(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """O'Neil cup-with-handle. Cup 7-65 weeks, depth 12-33%, handle in upper half,
    handle drift ≤12%. Trigger: break above handle high."""
    if not _enough(bars, 50):
        return None
    weekly = aggregate_to_weekly(bars)
    if len(weekly) < 9:
        return None
    cup_min_weeks, cup_max_weeks = 7, min(65, len(weekly) - 2)
    today = bars[-1]
    found = None
    for cup_len in range(cup_min_weeks, cup_max_weeks + 1):
        if len(weekly) < cup_len + 2:
            break
        cup = weekly[-(cup_len + 2):-2]
        handle = weekly[-2:]
        cup_high = max(w["high"] for w in cup)
        cup_low = min(w["low"] for w in cup)
        depth = (cup_high - cup_low) / cup_high * 100.0
        if not (12.0 <= depth <= 33.0):
            continue
        handle_low = min(w["low"] for w in handle)
        if handle_low < (cup_high + cup_low) / 2:
            continue
        handle_high = max(w["high"] for w in handle)
        handle_drift = (handle_high - handle_low) / handle_high * 100.0
        if handle_drift > 12.0:
            continue
        if today["close"] > handle_high:
            found = {"cup_high": cup_high, "depth": depth, "handle_high": handle_high, "handle_low": handle_low}
            break
    if not found:
        return None
    if not is_breaking_out(bars, found["handle_high"], vol_mult=1.5, vol_lookback=50):
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "cup_with_high_handle", "long",
        trigger_price=today["close"],
        stop_loss=found["handle_low"] - 0.5 * last_atr,
        target=today["close"] + (found["cup_high"] - found["handle_low"]) * 1.5,
        headline=f"{symbol} CUP-W-HANDLE — depth {found['depth']:.1f}%, breaking handle {found['handle_high']:.2f}",
        reasoning=[
            f"Cup depth {found['depth']:.1f}% (O'Neil 12-33% spec)",
            "Handle in upper half - bullish accumulation",
            f"Breaking handle high {found['handle_high']:.2f} on ≥1.5× vol",
        ],
        bucket="swing", setup_category="consolidation",
    )


# ═════════════════════════════════════════════════════════════════
# INVESTMENT DETECTORS  (5)
# ═════════════════════════════════════════════════════════════════
def weekly_breakout(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Break of 26-week base on weekly bars with weekly volume ≥2× 13-wk avg."""
    if not _enough(bars, 140):
        return None
    weekly = aggregate_to_weekly(bars)
    if len(weekly) < 27:
        return None
    today = bars[-1]
    base = weekly[-27:-1]               # prior 26 weeks
    base_high = max(w["high"] for w in base)
    if today["close"] <= base_high:
        return None
    avg_weekly_vol = sum(w["volume"] for w in weekly[-14:-1]) / 13
    cur_week_vol = weekly[-1]["volume"]
    if avg_weekly_vol > 0 and cur_week_vol < 2.0 * avg_weekly_vol:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    base_low = min(w["low"] for w in base)
    return make_daily_alert(
        symbol, "weekly_breakout", "long",
        trigger_price=today["close"],
        stop_loss=base_high - 1.5 * last_atr,
        target=today["close"] + (base_high - base_low),
        headline=f"{symbol} WEEKLY BREAKOUT — 26-wk base high {base_high:.2f} taken",
        reasoning=[
            f"Breaking 26-week base high {base_high:.2f}",
            f"Weekly volume {cur_week_vol:,.0f} ≥ 2× 13wk avg {avg_weekly_vol:,.0f}",
            "Investment-tier trade; expected hold 2-6 weeks",
        ],
        bucket="investment", setup_category="trend_momentum",
        expires_hours=24 * 7,
    )


def multi_quarter_base_break(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Flat 130-day (≈6mo) base, range ≤30%, break on ≥1.5× 50d avg vol."""
    if not _enough(bars, 140):
        return None
    base = detect_flat_base(bars[:-1], min_bars=120, max_bars=180, max_range_pct=30.0)
    if not base:
        return None
    today = bars[-1]
    if today["close"] <= base["high"]:
        return None
    avg_v = _avg_volume(bars[:-1], 50) or 0
    if avg_v > 0 and today["volume"] < 1.5 * avg_v:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "multi_quarter_base_break", "long",
        trigger_price=today["close"],
        stop_loss=base["high"] - 1.5 * last_atr,
        target=today["close"] + (base["high"] - base["low"]) * 1.5,
        headline=f"{symbol} MULTI-QTR BASE BREAK — {base['length']}d base, range {base['range_pct']:.1f}%",
        reasoning=[
            f"{base['length']}-day flat base, range {base['range_pct']:.1f}%",
            f"Breaking base high {base['high']:.2f}",
            "Volume ≥1.5× 50d avg",
        ],
        bucket="investment", setup_category="consolidation",
        expires_hours=24 * 14,
    )


def rs_leader_break(symbol: str, bars: List[Dict], spy_closes: Optional[List[float]] = None, **_) -> Optional["LiveAlert"]:
    """Mansfield RS vs SPY in top decile (rank ≥90) over 26 weeks AND price
    breaking 20-day high. Degrades to top-decile vs own price drift if SPY missing.
    """
    if not _enough(bars, 140):
        return None
    closes = [b["close"] for b in bars]
    if spy_closes and len(spy_closes) >= 131:
        rank = relative_strength_rank(closes, spy_closes, lookback=130)
    else:
        return None
    if rank is None or rank < 90.0:
        return None
    today = bars[-1]
    twenty_day_high = max(b["high"] for b in bars[-21:-1])
    if today["close"] <= twenty_day_high:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "rs_leader_break", "long",
        trigger_price=today["close"],
        stop_loss=twenty_day_high - 1.5 * last_atr,
        target=today["close"] + 5 * last_atr,
        headline=f"{symbol} RS LEADER BREAK — Mansfield RS rank {rank:.0f}",
        reasoning=[
            f"Mansfield RS rank {rank:.0f}/100 vs SPY over 26 weeks",
            f"Breaking 20-day high {twenty_day_high:.2f}",
            "Investment-tier leader",
        ],
        bucket="investment", setup_category="trend_momentum",
        expires_hours=24 * 7,
    )


def fifty_two_week_high_break(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Darvas-style 52-week-high break on ≥1.5× 50d avg vol."""
    if not _enough(bars, 240):
        return None
    today = bars[-1]
    yr_high = max(b["high"] for b in bars[-251:-1])
    if today["close"] <= yr_high:
        return None
    avg_v = _avg_volume(bars[:-1], 50) or 0
    if avg_v > 0 and today["volume"] < 1.5 * avg_v:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "fifty_two_week_high_break", "long",
        trigger_price=today["close"],
        stop_loss=yr_high - 2 * last_atr,
        target=today["close"] + 6 * last_atr,
        headline=f"{symbol} 52-WEEK HIGH BREAK — new high above {yr_high:.2f}",
        reasoning=[
            f"New 52-week high above {yr_high:.2f}",
            "Volume ≥1.5× 50d avg confirms institutional accumulation",
            "Investment-tier momentum trade",
        ],
        bucket="investment", setup_category="trend_momentum",
        expires_hours=24 * 14,
    )


def power_trend_stack(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Minervini stocking: price > 10ema > 20ema > 50sma > 150sma > 200sma,
    200sma rising for ≥30 sessions. Trigger on FIRST day all conditions hold."""
    if not _enough(bars, 240):
        return None
    closes = [b["close"] for b in bars]
    e10 = ema_series(closes, 10)
    e20 = ema_series(closes, 20)
    s50 = sma_series(closes, 50)
    s150 = sma_series(closes, 150)
    s200 = sma_series(closes, 200)

    def _stack(i: int) -> bool:
        vals = [closes[i], e10[i], e20[i], s50[i], s150[i], s200[i]]
        if any(v is None for v in vals):
            return False
        return vals[0] > vals[1] > vals[2] > vals[3] > vals[4] > vals[5]

    if not _stack(-1):
        return None
    if _stack(-2):
        return None  # only fire on transition
    if s200[-1] is None or s200[-31] is None or s200[-1] <= s200[-31]:
        return None
    today = bars[-1]
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "power_trend_stack", "long",
        trigger_price=today["close"],
        stop_loss=s50[-1] - 1.5 * last_atr,
        target=today["close"] + 8 * last_atr,
        headline=f"{symbol} POWER TREND STACK — first day full Minervini alignment",
        reasoning=[
            f"Stack: {today['close']:.2f} > 10ema > 20ema > 50sma > 150sma > 200sma",
            "200sma rising for 30+ sessions",
            "Investment / position trade — hold weeks to months",
        ],
        bucket="investment", setup_category="trend_momentum",
        expires_hours=24 * 14,
    )


# ═════════════════════════════════════════════════════════════════
# POSITION DETECTORS  (7)
# ═════════════════════════════════════════════════════════════════
def _thirty_week_sma_series(bars: List[Dict]) -> List[Optional[float]]:
    """30-week SMA computed on daily bars (≈150 trading days)."""
    closes = [b["close"] for b in bars]
    return sma_series(closes, 150)


def stage_2_breakout(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Weinstein Stage 2 — price above rising 30-week SMA, breaking 30-week base."""
    if not _enough(bars, 200):
        return None
    today = bars[-1]
    s30w = _thirty_week_sma_series(bars)
    if s30w[-1] is None or s30w[-21] is None:
        return None
    if today["close"] <= s30w[-1]:
        return None
    if s30w[-1] <= s30w[-21]:
        return None
    base = bars[-150:-1]
    base_high = max(b["high"] for b in base)
    if today["close"] <= base_high:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "stage_2_breakout", "long",
        trigger_price=today["close"],
        stop_loss=s30w[-1] - last_atr,
        target=today["close"] + 8 * last_atr,
        headline=f"{symbol} STAGE-2 BREAKOUT — above rising 30w SMA, breaking 30w base",
        reasoning=[
            f"Close {today['close']:.2f} > rising 30w SMA {s30w[-1]:.2f}",
            f"Breaking 30-week base high {base_high:.2f}",
            "Weinstein Stage 2 — multi-month conviction trade",
        ],
        bucket="position", setup_category="trend_momentum",
        expires_hours=24 * 30,
    )


def stage_1_to_2_transition(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Sideways for 20+ weeks (Stage 1), today closes above 30-week SMA for the
    first time in 30+ sessions, with 30w SMA flattening/turning up."""
    if not _enough(bars, 200):
        return None
    today = bars[-1]
    s30w = _thirty_week_sma_series(bars)
    if any(v is None for v in [s30w[-1], s30w[-2], s30w[-31]]):
        return None
    if today["close"] <= s30w[-1]:
        return None
    # Was below 30w SMA for last 30 sessions
    for i in range(-31, -1):
        if bars[i]["close"] > (s30w[i] or 0):
            return None
    # 30w SMA flattening (slope close to zero or turning up)
    slope = (s30w[-1] - s30w[-31]) / abs(s30w[-31] or 1)
    if slope < -0.02:
        return None  # still declining strongly = Stage 1, not transition
    # Sideways 20+ weeks = 100 days range tight
    range_pct = consolidation_range_pct(bars[-101:-1], 100) or 999
    if range_pct > 25.0:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "stage_1_to_2_transition", "long",
        trigger_price=today["close"],
        stop_loss=s30w[-1] - last_atr,
        target=today["close"] + 6 * last_atr,
        headline=f"{symbol} STAGE 1→2 TRANSITION — first close above 30w SMA in 30+ sessions",
        reasoning=[
            f"First close above 30w SMA {s30w[-1]:.2f} after 30+ sessions below",
            f"100-day range {range_pct:.1f}% (Stage 1 basing)",
            "30w SMA flattening/turning up",
        ],
        bucket="position", setup_category="trend_momentum",
        expires_hours=24 * 30,
    )


def stage_3_to_4_breakdown(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """Was Stage 2 for 20+ weeks, then sideways/lower 8-15 weeks (Stage 3),
    today closes below 30w SMA on volume."""
    if not _enough(bars, 250):
        return None
    today = bars[-1]
    s30w = _thirty_week_sma_series(bars)
    if any(v is None for v in [s30w[-1], s30w[-60], s30w[-150]]):
        return None
    if today["close"] >= s30w[-1]:
        return None
    # Stage 2 prior: 30w SMA rising for 100+ days, ending ~60 days ago
    if s30w[-60] <= s30w[-150]:
        return None
    # Distribution: 8-15 weeks of sideways/lower (40-75 sessions)
    distribution_range = consolidation_range_pct(bars[-75:-1], 70) or 999
    if distribution_range > 25.0:
        return None
    # Vol confirm
    avg_v = _avg_volume(bars[:-1], 50) or 0
    if avg_v > 0 and today["volume"] < 1.3 * avg_v:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "stage_3_to_4_breakdown", "short",
        trigger_price=today["close"],
        stop_loss=s30w[-1] + last_atr,
        target=today["close"] - 8 * last_atr,
        headline=f"{symbol} STAGE 3→4 BREAKDOWN — first close below 30w SMA after distribution",
        reasoning=[
            f"Close {today['close']:.2f} < 30w SMA {s30w[-1]:.2f}",
            f"Prior Stage 2 trend + Stage 3 distribution ({distribution_range:.1f}% range)",
            "Vol confirmation ≥1.3× 50d avg",
        ],
        bucket="position", setup_category="trend_momentum",
        expires_hours=24 * 30,
    )


def golden_cross_filtered(symbol: str, bars: List[Dict], spy_closes: Optional[List[float]] = None, **_) -> Optional["LiveAlert"]:
    """50-day SMA crosses above 200-day SMA while price is in Weinstein Stage 2
    (above rising 30w SMA) AND Mansfield RS > 0 vs SPY (if SPY available)."""
    if not _enough(bars, 220):
        return None
    closes = [b["close"] for b in bars]
    s50 = sma_series(closes, 50)
    s200 = sma_series(closes, 200)
    if any(v is None for v in [s50[-1], s50[-2], s200[-1], s200[-2]]):
        return None
    # Cross today: s50 was <= s200 yesterday, > today
    if not (s50[-2] <= s200[-2] and s50[-1] > s200[-1]):
        return None
    s30w = _thirty_week_sma_series(bars)
    if s30w[-1] is None or s30w[-21] is None:
        return None
    if closes[-1] <= s30w[-1] or s30w[-1] <= s30w[-21]:
        return None
    if spy_closes and len(spy_closes) >= 131:
        rs = mansfield_rs(closes, spy_closes, lookback=130)
        if rs is None or rs <= 0:
            return None
    today = bars[-1]
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "golden_cross_filtered", "long",
        trigger_price=today["close"],
        stop_loss=s50[-1] - 1.5 * last_atr,
        target=today["close"] + 10 * last_atr,
        headline=f"{symbol} FILTERED GOLDEN CROSS — 50sma↑200sma + Stage 2 + RS>0",
        reasoning=[
            f"50-day SMA crossed above 200-day SMA: {s50[-1]:.2f} > {s200[-1]:.2f}",
            f"Stage 2: close > rising 30w SMA {s30w[-1]:.2f}",
            "Mansfield RS > 0 (outperforming SPY)" if spy_closes else "RS filter skipped (SPY data unavailable)",
        ],
        bucket="position", setup_category="trend_momentum",
        expires_hours=24 * 30,
    )


def death_cross_filtered(symbol: str, bars: List[Dict], spy_closes: Optional[List[float]] = None, **_) -> Optional["LiveAlert"]:
    """50-day SMA crosses below 200-day SMA while price is below 30w SMA
    AND Mansfield RS < 0 (underperforming SPY)."""
    if not _enough(bars, 220):
        return None
    closes = [b["close"] for b in bars]
    s50 = sma_series(closes, 50)
    s200 = sma_series(closes, 200)
    if any(v is None for v in [s50[-1], s50[-2], s200[-1], s200[-2]]):
        return None
    if not (s50[-2] >= s200[-2] and s50[-1] < s200[-1]):
        return None
    s30w = _thirty_week_sma_series(bars)
    if s30w[-1] is None or s30w[-21] is None:
        return None
    if closes[-1] >= s30w[-1] or s30w[-1] >= s30w[-21]:
        return None
    if spy_closes and len(spy_closes) >= 131:
        rs = mansfield_rs(closes, spy_closes, lookback=130)
        if rs is None or rs >= 0:
            return None
    today = bars[-1]
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "death_cross_filtered", "short",
        trigger_price=today["close"],
        stop_loss=s50[-1] + 1.5 * last_atr,
        target=today["close"] - 10 * last_atr,
        headline=f"{symbol} FILTERED DEATH CROSS — 50sma↓200sma + Stage 4 + RS<0",
        reasoning=[
            f"50-day SMA crossed below 200-day SMA: {s50[-1]:.2f} < {s200[-1]:.2f}",
            f"Stage 4: close < declining 30w SMA {s30w[-1]:.2f}",
            "Mansfield RS < 0 (underperforming SPY)" if spy_closes else "RS filter skipped (SPY data unavailable)",
        ],
        bucket="position", setup_category="trend_momentum",
        expires_hours=24 * 30,
    )


def two_hundred_day_reclaim(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """First close above 200-day SMA after ≥30 sessions below it, on ≥1.5× vol."""
    if not _enough(bars, 230):
        return None
    closes = [b["close"] for b in bars]
    s200 = sma_series(closes, 200)
    if s200[-1] is None:
        return None
    today = bars[-1]
    if today["close"] <= s200[-1]:
        return None
    # Last 30 sessions all below
    for i in range(-31, -1):
        if s200[i] is None or bars[i]["close"] > s200[i]:
            return None
    avg_v = _avg_volume(bars[:-1], 50) or 0
    if avg_v > 0 and today["volume"] < 1.5 * avg_v:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "two_hundred_day_reclaim", "long",
        trigger_price=today["close"],
        stop_loss=s200[-1] - last_atr,
        target=today["close"] + 6 * last_atr,
        headline=f"{symbol} 200DMA RECLAIM — first close above {s200[-1]:.2f} in 30+ sessions",
        reasoning=[
            f"First close above 200-day SMA {s200[-1]:.2f} after 30+ sessions below",
            "Volume ≥1.5× 50d avg",
            "Multi-month trend reversal candidate",
        ],
        bucket="position", setup_category="trend_momentum",
        expires_hours=24 * 30,
    )


def two_hundred_day_loss(symbol: str, bars: List[Dict], **_) -> Optional["LiveAlert"]:
    """First close below 200-day SMA after ≥30 sessions above it, on ≥1.3× vol."""
    if not _enough(bars, 230):
        return None
    closes = [b["close"] for b in bars]
    s200 = sma_series(closes, 200)
    if s200[-1] is None:
        return None
    today = bars[-1]
    if today["close"] >= s200[-1]:
        return None
    for i in range(-31, -1):
        if s200[i] is None or bars[i]["close"] < s200[i]:
            return None
    avg_v = _avg_volume(bars[:-1], 50) or 0
    if avg_v > 0 and today["volume"] < 1.3 * avg_v:
        return None
    last_atr = calc_atr(bars, 14) or (today["close"] * 0.02)
    return make_daily_alert(
        symbol, "two_hundred_day_loss", "short",
        trigger_price=today["close"],
        stop_loss=s200[-1] + last_atr,
        target=today["close"] - 6 * last_atr,
        headline=f"{symbol} 200DMA LOSS — first close below {s200[-1]:.2f} in 30+ sessions",
        reasoning=[
            f"First close below 200-day SMA {s200[-1]:.2f} after 30+ sessions above",
            "Volume ≥1.3× 50d avg",
            "Multi-month trend reversal candidate (short side)",
        ],
        bucket="position", setup_category="trend_momentum",
        expires_hours=24 * 30,
    )


# ─────────────────────────────────────────────────────────────────
# Dispatch table — used by enhanced_scanner._scan_daily_setups
# ─────────────────────────────────────────────────────────────────
DAILY_DETECTORS = {
    # Swing
    "pocket_pivot": pocket_pivot,
    "vcp_breakout": vcp_breakout,
    "three_week_tight": three_week_tight,
    "bull_flag_break": bull_flag_break,
    "bear_flag_break": bear_flag_break,
    "ascending_triangle_break": ascending_triangle_break,
    "descending_triangle_break": descending_triangle_break,
    "cup_with_high_handle": cup_with_high_handle,
    # Investment
    "weekly_breakout": weekly_breakout,
    "multi_quarter_base_break": multi_quarter_base_break,
    "rs_leader_break": rs_leader_break,
    "fifty_two_week_high_break": fifty_two_week_high_break,
    "power_trend_stack": power_trend_stack,
    # Position
    "stage_2_breakout": stage_2_breakout,
    "stage_1_to_2_transition": stage_1_to_2_transition,
    "stage_3_to_4_breakdown": stage_3_to_4_breakdown,
    "golden_cross_filtered": golden_cross_filtered,
    "death_cross_filtered": death_cross_filtered,
    "two_hundred_day_reclaim": two_hundred_day_reclaim,
    "two_hundred_day_loss": two_hundred_day_loss,
}
