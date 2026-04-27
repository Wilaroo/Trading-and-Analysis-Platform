/**
 * useCarouselStatus — sibling of `useMondayMorningAutoLoad`, but instead
 * of *driving* the chart it just *reports* on what the carousel is doing.
 *
 * Returns:
 *   {
 *     active: bool,                 // inside the 09:10-09:50 ET Mon window
 *     currentSymbol: string|null,   // watch the chart should be on
 *     nextSymbol: string|null,      // watch the chart will rotate to next
 *     secondsUntilNext: number,     // 0..300, ticks every second
 *     totalWatches: number,
 *   }
 *
 * Used by `<CarouselCountdownChip>` in the V5 chart header so the
 * operator sees `LIVE · AAPL · 02:14 → MSFT` and knows when the rotation
 * is about to flip.
 */
import { useEffect, useRef, useState } from 'react';
import { useMarketState } from '../contexts';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const CAROUSEL_OPEN_HHMM = 9 * 60 + 10;
const CAROUSEL_CLOSE_HHMM = 9 * 60 + 50;
const SLOT_MINUTES = 5;

const _emptyStatus = {
  active: false,
  currentSymbol: null,
  nextSymbol: null,
  secondsUntilNext: 0,
  totalWatches: 0,
};

export const useCarouselStatus = () => {
  const snap = useMarketState();
  const [briefing, setBriefing] = useState(null);
  const [tick, setTick] = useState(0);  // 1Hz tick to refresh the countdown
  const lastFetchAtRef = useRef(0);

  // 1Hz heartbeat — only runs while we're actually inside the window so
  // we don't burn cycles all day.
  const inWindow = !!snap
    && snap.et_weekday === 0
    && (snap.et_hhmm ?? -1) >= CAROUSEL_OPEN_HHMM
    && (snap.et_hhmm ?? -1) <= CAROUSEL_CLOSE_HHMM;

  useEffect(() => {
    if (!inWindow) return undefined;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [inWindow]);

  // Briefing fetch — cached for 10 min inside the window. Mirrors the
  // autoload hook's cache so we don't double-fetch the same endpoint.
  useEffect(() => {
    if (!inWindow) return;
    if ((Date.now() - lastFetchAtRef.current) < 10 * 60 * 1000) return;
    lastFetchAtRef.current = Date.now();
    let alive = true;
    (async () => {
      try {
        const resp = await fetch(`${BACKEND_URL}/api/briefings/weekend/latest`);
        if (!resp.ok) return;
        const body = await resp.json();
        if (alive) setBriefing(body?.briefing || null);
      } catch { /* swallow */ }
    })();
    return () => { alive = false; };
  }, [inWindow]);

  if (!inWindow) return _emptyStatus;

  const watches = briefing?.gameplan?.watches;
  if (!Array.isArray(watches) || watches.length === 0) {
    return { ..._emptyStatus, active: true };
  }

  const hhmm = snap.et_hhmm ?? 0;
  const slotIndex = Math.floor((hhmm - CAROUSEL_OPEN_HHMM) / SLOT_MINUTES);
  const minutesIntoSlot = (hhmm - CAROUSEL_OPEN_HHMM) % SLOT_MINUTES;
  // Compose seconds-elapsed in the current slot from the wall clock.
  // We have minute resolution from `et_hhmm`; the seconds component is
  // approximated from a real-time clock so the countdown is smooth.
  const realSeconds = new Date().getSeconds();
  const secondsIntoSlot = (minutesIntoSlot * 60) + realSeconds;
  const secondsUntilNext = Math.max(0, SLOT_MINUTES * 60 - secondsIntoSlot);

  const currentSymbol = String(watches[slotIndex % watches.length]?.symbol || '').toUpperCase();
  const nextSymbol = String(watches[(slotIndex + 1) % watches.length]?.symbol || '').toUpperCase();

  // `tick` referenced so React knows to re-render every second — the
  // actual countdown is recomputed from wall-clock above.
  void tick;

  return {
    active: true,
    currentSymbol: currentSymbol || null,
    nextSymbol: nextSymbol || null,
    secondsUntilNext,
    totalWatches: watches.length,
  };
};

export default useCarouselStatus;
