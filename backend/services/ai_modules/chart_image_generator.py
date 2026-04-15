"""
Chart Image Generator — Converts IB OHLCV bars into candlestick chart images
for CNN training and inference.

Uses mplfinance to generate consistent 224x224 dark-theme candlestick charts
with volume bars and moving average overlays.
"""
import io
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf

logger = logging.getLogger(__name__)

# Chart style matching the trading platform's dark theme
CHART_STYLE = mpf.make_mpf_style(
    base_mpf_style='nightclouds',
    marketcolors=mpf.make_marketcolors(
        up='#26a69a', down='#ef5350',
        wick={'up': '#26a69a', 'down': '#ef5350'},
        edge={'up': '#26a69a', 'down': '#ef5350'},
        volume={'up': '#26a69a80', 'down': '#ef535080'},
    ),
    figcolor='#0a0a0a',
    facecolor='#0a0a0a',
    gridstyle='',
    y_on_right=True,
    rc={
        'axes.edgecolor': '#333333',
        'axes.labelcolor': '#999999',
        'xtick.color': '#666666',
        'ytick.color': '#666666',
    }
)

# Image size for CNN input
CNN_IMAGE_SIZE = 224


def bars_to_dataframe(bars: List[Dict], bar_size: str = "1 day") -> Optional[pd.DataFrame]:
    """
    Convert IB historical bars (from MongoDB) to mplfinance-compatible DataFrame.

    Expects bars with: date/timestamp, open, high, low, close, volume
    Returns DataFrame indexed by datetime with OHLCV columns.
    """
    if not bars or len(bars) < 5:
        return None

    records = []
    for b in bars:
        ts = b.get("date") or b.get("timestamp") or b.get("t")
        if isinstance(ts, str):
            try:
                ts = pd.Timestamp(ts)
            except Exception:
                continue
        elif isinstance(ts, (int, float)):
            ts = pd.Timestamp(ts, unit='s')
        elif isinstance(ts, datetime):
            ts = pd.Timestamp(ts)
        else:
            continue

        # Strip timezone for mplfinance compatibility
        if ts.tz is not None:
            ts = ts.tz_localize(None)

        records.append({
            "Date": ts,
            "Open": float(b.get("open", b.get("o", 0))),
            "High": float(b.get("high", b.get("h", 0))),
            "Low": float(b.get("low", b.get("l", 0))),
            "Close": float(b.get("close", b.get("c", 0))),
            "Volume": float(b.get("volume", b.get("v", 0))),
        })

    if len(records) < 5:
        return None

    df = pd.DataFrame(records)
    df = df.sort_values("Date").drop_duplicates(subset=["Date"])
    df = df.set_index("Date")
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = pd.DatetimeIndex(df.index)

    # Drop rows with zero/nan prices
    df = df[(df["Close"] > 0) & (df["Open"] > 0)]
    return df if len(df) >= 5 else None


def generate_chart_image(
    df: pd.DataFrame,
    image_size: int = CNN_IMAGE_SIZE,
    include_volume: bool = True,
    include_emas: bool = True,
) -> Optional[bytes]:
    """
    Generate a candlestick chart image as PNG bytes.

    Args:
        df: OHLCV DataFrame (DatetimeIndex)
        image_size: Output image size (square)
        include_volume: Show volume bars
        include_emas: Show 9/20 EMA overlay

    Returns:
        PNG image bytes, or None on error
    """
    if df is None or len(df) < 5:
        return None

    try:
        # DPI calculation for target pixel size
        dpi = 100
        fig_inches = image_size / dpi

        # Build moving averages
        addplots = []
        if include_emas and len(df) >= 20:
            ema9 = df["Close"].ewm(span=9, adjust=False).mean()
            ema20 = df["Close"].ewm(span=20, adjust=False).mean()
            addplots.append(mpf.make_addplot(ema9, color='#ffd54f', width=0.7))
            addplots.append(mpf.make_addplot(ema20, color='#42a5f5', width=0.7))

        # Generate chart
        buf = io.BytesIO()
        fig, axes = mpf.plot(
            df,
            type='candle',
            style=CHART_STYLE,
            volume=include_volume,
            addplot=addplots if addplots else None,
            figsize=(fig_inches, fig_inches),
            tight_layout=True,
            returnfig=True,
            axisoff=True,  # Clean image for CNN — no axis labels
        )

        fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                    facecolor='#0a0a0a', pad_inches=0.02)
        plt.close(fig)

        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        logger.error(f"Chart generation failed: {e}")
        return None


def generate_training_images_from_bars(
    db,
    setup_type: str,
    bar_size: str,
    window_size: int = 50,
    max_symbols: int = None,
    min_bars_per_symbol: int = 100,
    max_bars_per_symbol: int = 0,
    max_samples: int = 0,
) -> List[Dict]:
    """
    Generate labeled training images from IB historical bars.

    For each symbol, slides a window across the bar history and:
      1. Generates a candlestick chart image for the window
      2. Labels the pattern using setup_pattern_detector
      3. Computes forward return for WIN/LOSS label
      4. Returns list of {image_bytes, label, win, forward_return, symbol, bar_size}

    Args:
        db: MongoDB database
        setup_type: The setup type to generate images for (e.g., "BREAKOUT")
        bar_size: Bar timeframe (e.g., "1 day", "5 mins")
        window_size: Number of candles per image
        max_symbols: Limit number of symbols (None = all)
        min_bars_per_symbol: Minimum bars needed to generate images
        max_bars_per_symbol: Max bars to use per symbol (0 = unlimited).
            Use most recent bars to keep images relevant.
        max_samples: Stop after collecting this many total samples (0 = unlimited).
            Prevents OOM when many symbols have deep history.

    Returns:
        List of training sample dicts
    """
    from services.ai_modules.setup_training_config import SETUP_TRAINING_PROFILES

    # Get forecast horizon for this setup/bar_size
    forecast_horizon = 5  # default
    noise_threshold = 0.003
    profiles = SETUP_TRAINING_PROFILES.get(setup_type, [])
    for p in profiles:
        if p["bar_size"] == bar_size:
            forecast_horizon = p.get("forecast_horizon", 5)
            noise_threshold = p.get("noise_threshold", 0.003)
            break

    bars_col = db["ib_historical_data"]

    # Get distinct symbols with enough bars
    pipeline = [
        {"$match": {"bar_size": bar_size}},
        {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": min_bars_per_symbol}}},
        {"$sort": {"count": -1}},
    ]
    if max_symbols:
        pipeline.append({"$limit": max_symbols})

    symbols = [doc["_id"] for doc in bars_col.aggregate(pipeline)]
    logger.info(f"CNN image generation: {len(symbols)} symbols for {setup_type}/{bar_size} (window={window_size})")

    training_samples = []
    for sym_idx, symbol in enumerate(symbols):
        if sym_idx % 50 == 0:
            logger.info(f"  Processing symbol {sym_idx + 1}/{len(symbols)}: {symbol}")

        # Check if we've hit the total sample cap
        if max_samples > 0 and len(training_samples) >= max_samples:
            logger.info(f"  Reached max_samples={max_samples}, stopping image generation")
            break

        # Fetch bars for this symbol, sorted by date ascending
        cursor = bars_col.find(
            {"symbol": symbol, "bar_size": bar_size},
            {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
        ).sort("date", 1)

        # If max_bars_per_symbol is set, take only the most recent N bars
        if max_bars_per_symbol > 0:
            all_bars_raw = list(cursor)
            all_bars = all_bars_raw[-max_bars_per_symbol:]
            del all_bars_raw
        else:
            all_bars = list(cursor)

        if len(all_bars) < window_size + forecast_horizon:
            continue

        # Slide window across bars
        # Adaptive step: wider step for symbols with more bars to control image count.
        # Target ~500 windows max per symbol to avoid OOM on image accumulation.
        max_windows_per_symbol = 500
        total_possible = len(all_bars) - window_size - forecast_horizon
        base_step = max(window_size // 4, 5)  # 25% overlap
        if total_possible > max_windows_per_symbol * base_step:
            step = max(total_possible // max_windows_per_symbol, base_step)
        else:
            step = base_step
        for i in range(0, len(all_bars) - window_size - forecast_horizon, step):
            window_bars = all_bars[i: i + window_size]
            future_bars = all_bars[i + window_size: i + window_size + forecast_horizon]

            # Compute forward return
            entry_price = window_bars[-1].get("close", 0)
            if entry_price <= 0 or not future_bars:
                continue

            # Max favorable and unfavorable excursion in forecast window
            future_closes = [b.get("close", 0) for b in future_bars if b.get("close", 0) > 0]
            if not future_closes:
                continue

            forward_return = (future_closes[-1] - entry_price) / entry_price

            # Label: WIN / LOSS / SCRATCH
            direction = "long"
            for p in profiles:
                if p["bar_size"] == bar_size and p.get("direction") == "short":
                    direction = "short"
                    break

            if direction == "short":
                forward_return = -forward_return

            if forward_return > noise_threshold:
                outcome = "WIN"
            elif forward_return < -noise_threshold:
                outcome = "LOSS"
            else:
                outcome = "SCRATCH"

            # Generate chart image
            df = bars_to_dataframe(window_bars, bar_size)
            if df is None:
                continue

            image_bytes = generate_chart_image(df, CNN_IMAGE_SIZE)
            if image_bytes is None:
                continue

            training_samples.append({
                "image_bytes": image_bytes,
                "setup_type": setup_type,
                "bar_size": bar_size,
                "outcome": outcome,
                "forward_return": round(forward_return, 6),
                "symbol": symbol,
                "window_start": str(window_bars[0].get("date", "")),
                "window_end": str(window_bars[-1].get("date", "")),
                "entry_price": entry_price,
            })

    logger.info(f"CNN image generation complete: {len(training_samples)} samples for {setup_type}/{bar_size}")
    win_count = sum(1 for s in training_samples if s["outcome"] == "WIN")
    loss_count = sum(1 for s in training_samples if s["outcome"] == "LOSS")
    scratch_count = sum(1 for s in training_samples if s["outcome"] == "SCRATCH")
    logger.info(f"  WIN: {win_count}, LOSS: {loss_count}, SCRATCH: {scratch_count}")

    return training_samples


def image_bytes_to_tensor(image_bytes: bytes):
    """Convert PNG bytes to a preprocessed PyTorch tensor for CNN input."""
    from PIL import Image
    from services.ai_modules.chart_pattern_cnn import get_image_transform

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    transform = get_image_transform()
    return transform(img)


def generate_live_chart_tensor(db, symbol: str, bar_size: str, window_size: int = 50):
    """
    Generate a chart image tensor for live inference.
    Pulls the most recent `window_size` bars for the symbol.

    Returns:
        (tensor, metadata) or (None, None) if insufficient data
    """
    bars_col = db["ib_historical_data"]

    cursor = bars_col.find(
        {"symbol": symbol, "bar_size": bar_size},
        {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
    ).sort("date", -1).limit(window_size)

    bars = list(cursor)
    if len(bars) < 10:
        return None, None

    # Reverse to chronological order
    bars.reverse()

    df = bars_to_dataframe(bars, bar_size)
    if df is None:
        return None, None

    image_bytes = generate_chart_image(df, CNN_IMAGE_SIZE)
    if image_bytes is None:
        return None, None

    tensor = image_bytes_to_tensor(image_bytes)

    metadata = {
        "symbol": symbol,
        "bar_size": bar_size,
        "window_size": len(bars),
        "latest_bar": str(bars[-1].get("date", "")),
    }
    return tensor, metadata
