/**
 * PreMarketModeBanner — v19.31.14 (2026-05-04)
 *
 * Operator pain-point: between 7:00 ET and 9:30 ET the Scanner is
 * intentionally silent (it's only building/refreshing watchlists,
 * not firing setups), but the panel just shows "Scanner idle" or
 * an empty list. New operators panic — "is the scanner broken?"
 *
 * This banner appears during the pre-market window (7:00–9:30 ET)
 * and explains that silence is intentional. It auto-hides at the
 * 9:30 ET open (with a 30s tick to keep the time fresh).
 *
 * Pure presentational + a 30s clock tick — no API calls.
 */
import React, { useEffect, useState } from 'react';

const ET_FORMATTER = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  hour: 'numeric',
  minute: 'numeric',
  hour12: false,
});

const _etPartsNow = (now = new Date()) => {
  const parts = ET_FORMATTER.formatToParts(now);
  const get = (t) => Number(parts.find(p => p.type === t)?.value || 0);
  return { h: get('hour'), m: get('minute') };
};

/**
 * @returns {'premarket'|'rth_open'|'rth'|'after'|'closed'} time-of-day classification
 */
const classifyEtMinute = (now = new Date()) => {
  const { h, m } = _etPartsNow(now);
  const total = h * 60 + m;
  // ET windows. Weekday-only enforcement is delegated to the parent
  // (the panel itself is hidden when markets are closed via the broader
  // session-state plumbing).
  if (total >= 7 * 60 && total < 9 * 60 + 30) return 'premarket';
  if (total >= 9 * 60 + 30 && total < 16 * 60) return 'rth';
  if (total >= 16 * 60 && total < 20 * 60) return 'after';
  return 'closed';
};

const _fmtCountdown = (now = new Date()) => {
  const { h, m } = _etPartsNow(now);
  const minutesUntilOpen = (9 * 60 + 30) - (h * 60 + m);
  if (minutesUntilOpen <= 0) return null;
  const hh = Math.floor(minutesUntilOpen / 60);
  const mm = minutesUntilOpen % 60;
  if (hh > 0) return `${hh}h ${mm}m to open`;
  return `${mm}m to open`;
};

/**
 * Renders only when in the 7:00–9:30 ET pre-market window.
 * Returns null otherwise so it has zero footprint outside the window.
 */
export default function PreMarketModeBanner() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    // 30s tick — enough granularity for the countdown without being
    // a perf burden. The component re-renders only twice a minute.
    const id = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(id);
  }, []);

  const phase = classifyEtMinute(now);
  if (phase !== 'premarket') return null;

  const countdown = _fmtCountdown(now);

  return (
    <div
      data-testid="v5-scanner-premarket-banner"
      data-phase="premarket"
      className="flex items-start gap-2 px-3 py-2 border-b border-amber-900/40 bg-gradient-to-r from-amber-950/40 via-amber-950/30 to-transparent"
    >
      <span
        aria-hidden
        className="mt-0.5 inline-flex w-2 h-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.65)] animate-pulse shrink-0"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="v5-mono text-[11px] uppercase tracking-widest font-bold text-amber-300">
            Pre-Market Mode
          </span>
          {countdown && (
            <span
              data-testid="v5-scanner-premarket-countdown"
              className="v5-mono text-[11px] text-amber-400/80 tabular-nums"
            >
              · {countdown}
            </span>
          )}
        </div>
        <div className="mt-0.5 v5-mono text-[12px] text-amber-200/85 leading-snug">
          Scanner is building watchlists from overnight gaps, news, and
          regime probes. Setup alerts begin at the 9:30 ET open — silence
          here is intentional.
        </div>
      </div>
    </div>
  );
}

// Exported for unit tests (kept off the default to keep the tree tiny).
export { classifyEtMinute, _fmtCountdown };
