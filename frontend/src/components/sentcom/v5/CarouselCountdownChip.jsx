/**
 * CarouselCountdownChip — V5 chart header chip showing the Monday-morning
 * carousel state. Two modes:
 *
 *   AUTO mode (operator hasn't overridden):
 *     `LIVE · ‹ AAPL · 02:14 → MSFT ›`
 *     Cyan, animated radio icon, real-time countdown to the next 5-min
 *     rotation. Arrow buttons let the operator skip ahead/back manually
 *     without waiting for the timer — clicking either flips the parent's
 *     `userHasFocusedRef` (via `onManualPick`) so the auto-rotation
 *     pauses for the rest of the session.
 *
 *   PAUSED mode (operator has overridden):
 *     `WATCHES · ‹ AAPL ›`
 *     Zinc tone, no countdown, no radio icon. Arrows still work — the
 *     chip becomes a tiny manual watches-cycler. This is genuinely
 *     useful: even after the operator takes over, they can step through
 *     the bot's gameplan watches with a single click.
 *
 * Hidden entirely outside the 09:10-09:50 ET Monday window.
 */
import React from 'react';
import { Radio, ChevronLeft, ChevronRight } from 'lucide-react';
import { useCarouselStatus } from '../../../hooks/useCarouselStatus';

const fmtMMSS = (secs) => {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
};

export const CarouselCountdownChip = ({ onManualPick, userHasFocused, currentChartSymbol }) => {
  const status = useCarouselStatus();
  if (!status.active || !status.currentSymbol) return null;

  const watches = status.watches || [];
  if (watches.length === 0) return null;

  // In paused mode the cycler navigates relative to the chart's CURRENT
  // symbol so the operator can step `‹/›` from wherever they last
  // landed. In auto mode it navigates from the carousel slot so the
  // arrows respect the schedule.
  let pivotSymbol;
  if (userHasFocused && currentChartSymbol) {
    pivotSymbol = String(currentChartSymbol).toUpperCase();
  } else {
    pivotSymbol = status.currentSymbol;
  }
  const pivotIdx = Math.max(0, watches.findIndex((w) => w.symbol === pivotSymbol));
  const prevSymbol = watches[(pivotIdx - 1 + watches.length) % watches.length].symbol;
  const nextSymbol = watches[(pivotIdx + 1) % watches.length].symbol;

  const skip = (sym) => {
    if (!sym || !onManualPick) return;
    onManualPick(sym);
  };

  // ── AUTO MODE ──────────────────────────────────────────────────
  if (!userHasFocused) {
    return (
      <div
        data-testid="carousel-countdown-chip"
        data-mode="auto"
        className="inline-flex items-center gap-1 px-1 py-0.5 rounded-full ring-1 ring-cyan-500/40 bg-cyan-900/15 v5-mono text-[9px] uppercase tracking-wider text-cyan-300"
        title={`Auto-frame carousel · rotates every 5 min · ${status.totalWatches} watches · click ‹/› to skip ahead manually`}
      >
        <Radio className="w-3 h-3 animate-pulse mx-0.5" />
        <span className="font-bold">LIVE</span>
        <span className="opacity-60">·</span>
        <button
          type="button"
          onClick={() => skip(prevSymbol)}
          data-testid="carousel-prev-btn"
          title={`Skip back to ${prevSymbol} (pauses auto-rotation)`}
          className="text-zinc-400 hover:text-cyan-200 transition-colors px-0.5"
        >
          <ChevronLeft className="w-3 h-3" />
        </button>
        <span data-testid="carousel-current-symbol" className="font-bold text-zinc-100">
          {status.currentSymbol}
        </span>
        <span className="opacity-60">·</span>
        <span data-testid="carousel-countdown-secs" className="tabular-nums text-zinc-300">
          {fmtMMSS(status.secondsUntilNext)}
        </span>
        <span className="opacity-60">→</span>
        <span data-testid="carousel-next-symbol" className="text-zinc-300">
          {status.nextSymbol}
        </span>
        <button
          type="button"
          onClick={() => skip(nextSymbol)}
          data-testid="carousel-next-btn"
          title={`Skip ahead to ${nextSymbol} (pauses auto-rotation)`}
          className="text-zinc-400 hover:text-cyan-200 transition-colors px-0.5"
        >
          <ChevronRight className="w-3 h-3" />
        </button>
      </div>
    );
  }

  // ── PAUSED MODE — operator has manually focused something. ─────
  return (
    <div
      data-testid="carousel-countdown-chip"
      data-mode="paused"
      className="inline-flex items-center gap-1 px-1 py-0.5 rounded-full ring-1 ring-zinc-700/60 bg-zinc-900/40 v5-mono text-[9px] uppercase tracking-wider text-zinc-400"
      title={`Auto-rotation paused (you took over). Click ‹/› to step through the bot's watches manually.`}
    >
      <span className="font-bold">WATCHES</span>
      <span className="opacity-50">·</span>
      <button
        type="button"
        onClick={() => skip(prevSymbol)}
        data-testid="carousel-prev-btn"
        title={`Step to ${prevSymbol}`}
        className="text-zinc-500 hover:text-zinc-200 transition-colors px-0.5"
      >
        <ChevronLeft className="w-3 h-3" />
      </button>
      <span data-testid="carousel-current-symbol" className="font-bold text-zinc-200">
        {pivotSymbol}
      </span>
      <button
        type="button"
        onClick={() => skip(nextSymbol)}
        data-testid="carousel-next-btn"
        title={`Step to ${nextSymbol}`}
        className="text-zinc-500 hover:text-zinc-200 transition-colors px-0.5"
      >
        <ChevronRight className="w-3 h-3" />
      </button>
    </div>
  );
};

export default CarouselCountdownChip;
