/**
 * VolumeProfileOverlay — vertical Volume-at-Price histogram.
 *
 * For SMB-style scalping, knowing where most volume traded (HVN — High
 * Volume Nodes) and where it didn't (LVN — Low Volume Nodes) is the
 * single highest-leverage piece of context after price itself. This
 * overlay walks the visible bars, bins their volume across price
 * levels, and renders horizontal bars from the right edge inward.
 *
 * Architecture mirrors PremarketShadingOverlay:
 *   - Reads the chart from `chartRef`, the bars from `bars` prop.
 *   - Subscribes to the chart's visible-time-range so it recomputes
 *     when the user pans / zooms.
 *   - Uses chart.priceScale('right').priceToCoordinate(price) for
 *     y-mapping so bars stay aligned with candles even on log scales.
 *
 * Distribution model: for each bar we split its volume uniformly
 * across the bins it overlaps in [low, high]. Cheap, no library
 * dependency, and perceptually correct enough for scalping (it
 * matches the canonical "Profile" model used by SMB / Linda Raschke
 * / Volume Profile traders, not the more exotic TPO/Market-Profile
 * variant which requires sub-bar tick data we don't have).
 *
 * The Point-of-Control (POC) — the bin with the largest accumulated
 * volume — is highlighted in amber.
 */
import React, { useEffect, useMemo, useState } from 'react';

const NUM_BINS = 64;
const PROFILE_WIDTH_PX = 110;     // how far inward the profile extends
const RIGHT_GUTTER_PX = 56;       // skip the price-axis on the right
const BAR_OPACITY = 0.55;
const POC_COLOR = '#fbbf24';      // amber — matches premarket shading
const HVN_COLOR = '#06b6d4';      // cyan — same hue as the volume pane

/**
 * Bin the visible bars into a fixed number of price levels and
 * accumulate volume per bin. Returns:
 *   { bins: [{ priceLow, priceHigh, volume }], pocIdx, maxVolume }
 */
const computeProfile = (bars, numBins) => {
  if (!Array.isArray(bars) || bars.length === 0) {
    return { bins: [], pocIdx: -1, maxVolume: 0 };
  }
  let lo = Infinity;
  let hi = -Infinity;
  for (const b of bars) {
    if (Number.isFinite(b.low)  && b.low  < lo) lo = b.low;
    if (Number.isFinite(b.high) && b.high > hi) hi = b.high;
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) {
    return { bins: [], pocIdx: -1, maxVolume: 0 };
  }
  const span = hi - lo;
  const binSize = span / numBins;
  const volumes = new Array(numBins).fill(0);

  for (const b of bars) {
    const v = Number(b.volume) || 0;
    if (v <= 0) continue;
    const blow  = Math.max(lo, Number(b.low));
    const bhigh = Math.min(hi, Number(b.high));
    if (!Number.isFinite(blow) || !Number.isFinite(bhigh) || bhigh < blow) continue;
    // Bin range covered by this bar
    const startIdx = Math.max(0, Math.floor((blow  - lo) / binSize));
    const endIdx   = Math.min(numBins - 1, Math.floor((bhigh - lo) / binSize));
    const span_bins = endIdx - startIdx + 1;
    if (span_bins <= 0) continue;
    const per = v / span_bins;
    for (let i = startIdx; i <= endIdx; i++) volumes[i] += per;
  }

  let pocIdx = -1;
  let maxVolume = 0;
  for (let i = 0; i < numBins; i++) {
    if (volumes[i] > maxVolume) {
      maxVolume = volumes[i];
      pocIdx = i;
    }
  }
  const bins = volumes.map((vol, i) => ({
    priceLow:  lo + i * binSize,
    priceHigh: lo + (i + 1) * binSize,
    volume: vol,
  }));
  return { bins, pocIdx, maxVolume };
};

export const VolumeProfileOverlay = ({ chartRef, bars, visible = true }) => {
  const [version, setVersion] = useState(0);  // bump to force re-project
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 });

  // Compute the price-binned profile once per `bars` change. Cheap
  // (~1ms for 1000 bars) and prevents recomputing during pan/zoom.
  const { bins, pocIdx, maxVolume } = useMemo(
    () => computeProfile(bars, NUM_BINS),
    [bars]
  );

  // Trigger re-projection on chart pan/zoom + container resize. We
  // can't memoize the y-coordinates because they depend on the chart's
  // CURRENT scale, which is hidden state inside lightweight-charts.
  useEffect(() => {
    const chart = chartRef?.current;
    if (!chart) return undefined;

    const bump = () => setVersion(v => v + 1);

    let unsubVisible = null;
    try {
      const ts = chart.timeScale();
      ts.subscribeVisibleTimeRangeChange(bump);
      unsubVisible = () => {
        try { ts.unsubscribeVisibleTimeRangeChange(bump); } catch (_) { /* noop */ }
      };
    } catch (_) { /* noop */ }

    // Track container resize so the bars stretch correctly.
    let ro = null;
    try {
      const el = chart.chartElement?.() || null;
      if (el) {
        ro = new ResizeObserver(() => {
          const r = el.getBoundingClientRect();
          setContainerSize({ w: r.width, h: r.height });
          bump();
        });
        ro.observe(el);
        const r = el.getBoundingClientRect();
        setContainerSize({ w: r.width, h: r.height });
      }
    } catch (_) { /* noop */ }

    return () => {
      if (unsubVisible) unsubVisible();
      if (ro) try { ro.disconnect(); } catch (_) { /* noop */ }
    };
  }, [chartRef]);

  // Project each bin into pixel space using the chart's right price
  // scale. Skips bins whose price is off-screen.
  const projected = useMemo(() => {
    if (!visible || !bins.length || maxVolume <= 0) return [];
    const chart = chartRef?.current;
    if (!chart) return [];
    let series = null;
    try {
      // priceToCoordinate is on the candle series (lightweight-charts v5).
      // We fish the first series with a price scale via chart.priceScale.
      const ps = chart.priceScale('right');
      if (!ps) return [];
      // Need a series ref — the chart exposes series via the closure
      // above (passed in by ChartPanel). Fall back to series-less mode
      // if not available.
      // eslint-disable-next-line no-underscore-dangle
      series = chart.__candleSeriesForVolumeProfile || null;
    } catch (_) { /* noop */ }
    if (!series) return [];

    const out = [];
    for (let i = 0; i < bins.length; i++) {
      const b = bins[i];
      if (b.volume <= 0) continue;
      let yTop, yBot;
      try {
        yTop = series.priceToCoordinate(b.priceHigh);
        yBot = series.priceToCoordinate(b.priceLow);
      } catch (_) {
        yTop = yBot = null;
      }
      if (yTop == null || yBot == null) continue;
      const top    = Math.min(yTop, yBot);
      const height = Math.max(1, Math.abs(yBot - yTop) - 0.5);
      const ratio = b.volume / maxVolume;
      const width = Math.max(1, ratio * PROFILE_WIDTH_PX);
      out.push({ top, height, width, isPoc: i === pocIdx, idx: i });
    }
    return out;
  // version triggers re-projection on pan/zoom; containerSize on resize
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bins, maxVolume, pocIdx, version, containerSize, visible, chartRef]);

  if (!visible) return null;

  return (
    <div
      data-testid="chart-volume-profile"
      className="pointer-events-none absolute inset-0"
    >
      {projected.map((p) => (
        <div
          key={p.idx}
          className="absolute"
          style={{
            right: `${RIGHT_GUTTER_PX}px`,
            top: `${p.top}px`,
            height: `${p.height}px`,
            width: `${p.width}px`,
            background: p.isPoc ? POC_COLOR : HVN_COLOR,
            opacity: p.isPoc ? 0.85 : BAR_OPACITY,
          }}
          title={p.isPoc ? 'Point of Control (highest volume)' : undefined}
        />
      ))}
    </div>
  );
};

export default VolumeProfileOverlay;
