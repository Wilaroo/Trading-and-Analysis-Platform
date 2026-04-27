/**
 * CarouselCountdownChip — V5 chart header chip showing the Monday-morning
 * carousel state. Format: `LIVE · AAPL · 02:14 → MSFT`.
 *
 * Hidden outside the 09:10-09:50 ET Monday window.
 */
import React from 'react';
import { Radio } from 'lucide-react';
import { useCarouselStatus } from '../../../hooks/useCarouselStatus';

const fmtMMSS = (secs) => {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
};

export const CarouselCountdownChip = () => {
  const status = useCarouselStatus();
  if (!status.active || !status.currentSymbol) return null;

  return (
    <div
      data-testid="carousel-countdown-chip"
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full ring-1 ring-cyan-500/40 bg-cyan-900/15 v5-mono text-[9px] uppercase tracking-wider text-cyan-300"
      title={`Auto-frame carousel · rotates every 5 min · ${status.totalWatches} watches`}
    >
      <Radio className="w-3 h-3 animate-pulse" />
      <span className="font-bold">LIVE</span>
      <span className="opacity-60">·</span>
      <span data-testid="carousel-current-symbol" className="font-bold text-zinc-100">
        {status.currentSymbol}
      </span>
      {status.nextSymbol && status.nextSymbol !== status.currentSymbol && (
        <>
          <span className="opacity-60">·</span>
          <span
            data-testid="carousel-countdown-secs"
            className="tabular-nums text-zinc-300"
          >
            {fmtMMSS(status.secondsUntilNext)}
          </span>
          <span className="opacity-60">→</span>
          <span data-testid="carousel-next-symbol" className="text-zinc-300">
            {status.nextSymbol}
          </span>
        </>
      )}
    </div>
  );
};

export default CarouselCountdownChip;
