/**
 * ChartFloatingPriceLabel — v19.34.51 (Feb 2026).
 *
 * Floats a small price badge anchored to the right of the most recent
 * candle. Replaces the default lightweight-charts horizontal dashed
 * "current price" line + right-axis label, which:
 *   1. drew a full-width dashed line that competed with entry/SL/PT
 *      IPriceLine overlays for visual attention
 *   2. parked the price label way off to the right axis, far from the
 *      actual candle, so the operator's eye had to traverse the entire
 *      chart width to read it
 *
 * The badge:
 *   - Anchors x = right edge of the latest bar (timeToCoordinate)
 *   - Anchors y = priceToCoordinate(latest close)
 *   - Color: emerald if up vs prev close, rose if down, zinc if flat
 *   - Renders only when there's at least one bar AND chart is initialized
 *   - Re-renders on visible-time-range change + on bars update
 *
 * Visibility is automatic — no toggle. The badge stays out of the way
 * (small, semi-translucent) and disappears when the latest bar scrolls
 * off-screen.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

const fmtUsd = (v) => {
  if (v == null || !Number.isFinite(v)) return '—';
  // Match the chart's existing 2-decimal precision for stocks.
  if (Math.abs(v) >= 1000) return v.toFixed(2);
  if (Math.abs(v) >= 10) return v.toFixed(2);
  return v.toFixed(2);
};

export const ChartFloatingPriceLabel = ({
  chartRef,
  candleSeriesRef,
  bars,
}) => {
  const [pos, setPos] = useState(null); // { x, y, price, prevClose }
  const containerRef = useRef(null);

  const recompute = useCallback(() => {
    const chart = chartRef?.current;
    const series = candleSeriesRef?.current;
    if (!chart || !series || !bars || bars.length === 0) {
      setPos(null);
      return;
    }
    const last = bars[bars.length - 1];
    const prev = bars.length > 1 ? bars[bars.length - 2] : null;
    if (!last || last.close == null || last.time == null) {
      setPos(null);
      return;
    }
    try {
      const ts = chart.timeScale();
      const x = ts.timeToCoordinate(last.time);
      const y = series.priceToCoordinate(last.close);
      if (x == null || y == null) {
        setPos(null);
        return;
      }
      setPos({
        x,
        y,
        price: last.close,
        prevClose: prev?.close ?? last.open ?? last.close,
      });
    } catch (_) {
      setPos(null);
    }
  }, [chartRef, candleSeriesRef, bars]);

  // Recompute on bars / chart-range / resize. The lightweight-charts
  // timeScale fires `subscribeVisibleTimeRangeChange` on pan, zoom, AND
  // bar updates — so this single subscription covers all the cases
  // where the latest bar's pixel position can shift.
  useEffect(() => {
    recompute();
    const chart = chartRef?.current;
    if (!chart) return undefined;
    let unsub = null;
    try {
      const ts = chart.timeScale();
      const handler = () => recompute();
      ts.subscribeVisibleTimeRangeChange(handler);
      unsub = () => {
        try { ts.unsubscribeVisibleTimeRangeChange(handler); } catch (_) { /* noop */ }
      };
    } catch (_) { /* noop */ }
    // Also recompute on window resize (chart auto-resizes but the
    // subscription doesn't always fire fast enough for the badge).
    const onResize = () => recompute();
    window.addEventListener('resize', onResize);
    return () => {
      if (unsub) unsub();
      window.removeEventListener('resize', onResize);
    };
  }, [recompute, chartRef]);

  if (!pos) return null;

  const direction =
    pos.prevClose == null
      ? 'flat'
      : pos.price > pos.prevClose
        ? 'up'
        : pos.price < pos.prevClose
          ? 'down'
          : 'flat';

  const colors = {
    up:   { bg: 'rgba(16, 185, 129, 0.92)', border: '#10b981', text: '#ecfdf5' },
    down: { bg: 'rgba(244, 63, 94, 0.92)',  border: '#f43f5e', text: '#fff1f2' },
    flat: { bg: 'rgba(82, 82, 91, 0.92)',   border: '#71717a', text: '#fafafa' },
  }[direction];

  // Place the badge just to the RIGHT of the candle (8px gap) and
  // vertically centered on the close price.
  const left = pos.x + 8;
  const top = pos.y - 11; // half of the badge's ~22px height

  return (
    <div
      ref={containerRef}
      className="pointer-events-none absolute"
      data-testid="chart-floating-price-label"
      style={{
        left: `${left}px`,
        top: `${top}px`,
        zIndex: 25,
      }}
    >
      <div
        className="px-2 py-0.5 rounded-md font-mono text-[14px] font-bold tabular-nums shadow-lg whitespace-nowrap"
        style={{
          background: colors.bg,
          color: colors.text,
          border: `1px solid ${colors.border}`,
          backdropFilter: 'blur(2px)',
        }}
      >
        {fmtUsd(pos.price)}
      </div>
    </div>
  );
};

export default ChartFloatingPriceLabel;
