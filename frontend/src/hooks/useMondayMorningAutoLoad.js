/**
 * useMondayMorningAutoLoad — auto-frames the V5 chart on the Weekend
 * Briefing's top watches every Monday morning, 09:10 → 09:50 ET.
 *
 * Mode: rotating carousel.
 * ------------------------
 * The 40-minute pre-open window is divided into 5-minute slots (8 slots
 * total: 09:10, :15, :20, :25, :30, :35, :40, :45). Each slot maps to
 * `watches[slot_index % watches.length]` so even with 3 watches the
 * operator sees each one a couple of times before the open.
 *
 * Idempotency:
 *   We track the last-loaded symbol in `localStorage[wb-autoloaded-symbol-{ISO_WEEK}]`
 *   so a page reload mid-carousel resumes on the right watch instead of
 *   restarting from #0. We do NOT use a "fired once" flag — that would
 *   break the carousel.
 *
 * Side-effect output:
 *   - `setFocusedSymbol(symbol)` whenever the carousel index ticks.
 *   - localStorage marker reads back via `readAutoLoadedSymbol(week)`
 *     so the WeekendBriefingCard can render a "LIVE" chip on the
 *     currently-framed watch card. Updates as the carousel rotates.
 *
 * Disabled when:
 *   - market state isn't Monday in the 09:10-09:50 ET window
 *   - briefing has no watches (LLM unavailable)
 *   - the operator has already manually focused a symbol since page
 *     load (the carousel never overrides explicit choices)
 */
import { useEffect, useRef } from 'react';
import { useMarketState } from '../contexts';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const CAROUSEL_OPEN_HHMM = 9 * 60 + 10;   // 09:10 ET
const CAROUSEL_CLOSE_HHMM = 9 * 60 + 50;  // 09:50 ET
const SLOT_MINUTES = 5;

const lsSymKey = (iso_week) => `wb-autoloaded-symbol-${iso_week}`;
const lsPausedKey = (iso_week) => `wb-paused-${iso_week}`;

/**
 * Compute the ISO week id from browser local time, ET-bucketed.
 * Mirrors the backend's `_iso_week()` so the localStorage keys line up
 * across the autoload + carousel + manual-pause surfaces.
 */
const isoWeekFromBrowser = () => {
  try {
    // Convert local time → ET wall clock so Mon 23:00 ET (Tue 04:00 UTC)
    // still bucketed into the Mon-Fri trading week.
    const et = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
    const target = new Date(Date.UTC(et.getFullYear(), et.getMonth(), et.getDate()));
    const dayNum = target.getUTCDay() || 7;          // Mon=1..Sun=7
    target.setUTCDate(target.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
    const weekNo = Math.ceil(((target - yearStart) / 86_400_000 + 1) / 7);
    return `${target.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`;
  } catch {
    return null;
  }
};

export { isoWeekFromBrowser };

export const useMondayMorningAutoLoad = ({
  setFocusedSymbol,
  userHasFocused,
}) => {
  const snap = useMarketState();
  const briefingRef = useRef(null);
  const lastIndexRef = useRef(-1);
  // Cache the briefing fetch — refetch at most every 10 minutes.
  const lastFetchAtRef = useRef(0);

  useEffect(() => {
    if (!snap || !setFocusedSymbol) return undefined;
    if (userHasFocused) return undefined;
    if (snap.et_weekday !== 0) return undefined;            // Monday only
    const hhmm = snap.et_hhmm ?? -1;
    if (hhmm < CAROUSEL_OPEN_HHMM || hhmm > CAROUSEL_CLOSE_HHMM) return undefined;

    const slotIndex = Math.floor((hhmm - CAROUSEL_OPEN_HHMM) / SLOT_MINUTES);

    // Re-fetch briefing at most every 10 minutes inside the window —
    // the briefing rarely changes mid-Monday-morning so cache it.
    const refetchNeeded = (Date.now() - lastFetchAtRef.current) > 10 * 60 * 1000;
    let cancelled = false;

    const apply = (briefing) => {
      if (cancelled) return;
      const wid = briefing?.iso_week;
      const watches = briefing?.gameplan?.watches;
      if (!wid || !Array.isArray(watches) || watches.length === 0) return;

      const sym = String(watches[slotIndex % watches.length]?.symbol || '').toUpperCase();
      if (!sym) return;

      // Only fire the setter when the slot actually advances —
      // otherwise we'd churn the chart every market-state poll.
      if (slotIndex === lastIndexRef.current) return;
      lastIndexRef.current = slotIndex;

      setFocusedSymbol(sym);
      try {
        if (typeof window !== 'undefined') {
          window.localStorage.setItem(lsSymKey(wid), sym);
        }
      } catch { /* localStorage may be disabled — non-fatal */ }
    };

    if (refetchNeeded || !briefingRef.current) {
      lastFetchAtRef.current = Date.now();
      (async () => {
        try {
          const resp = await fetch(`${BACKEND_URL}/api/briefings/weekend/latest`);
          if (!resp.ok) return;
          const body = await resp.json();
          briefingRef.current = body?.briefing || null;
          apply(briefingRef.current);
        } catch {
          /* swallow — carousel is best-effort */
        }
      })();
    } else {
      apply(briefingRef.current);
    }

    return () => { cancelled = true; };
  }, [snap, setFocusedSymbol, userHasFocused]);
};

/**
 * Read the most recently auto-loaded symbol for a given ISO week.
 * Used by the WeekendBriefingCard to render the "LIVE" chip on the
 * currently-framed watch card. Returns `null` outside the browser or
 * when no auto-load has happened for the week.
 */
export const readAutoLoadedSymbol = (iso_week) => {
  if (typeof window === 'undefined' || !iso_week) return null;
  try {
    return window.localStorage.getItem(lsSymKey(iso_week));
  } catch {
    return null;
  }
};

/**
 * Persist + read the "operator has overridden the carousel" flag for
 * the current ISO week. Mirrors `lsSymKey` so the manual pause survives
 * page reloads — once the operator clicks anything, the carousel won't
 * silently steal focus on a refresh before the order is placed.
 */
export const readPausedFlag = (iso_week) => {
  if (typeof window === 'undefined' || !iso_week) return false;
  try {
    return !!window.localStorage.getItem(lsPausedKey(iso_week));
  } catch {
    return false;
  }
};

export const writePausedFlag = (iso_week) => {
  if (typeof window === 'undefined' || !iso_week) return;
  try {
    window.localStorage.setItem(lsPausedKey(iso_week), new Date().toISOString());
  } catch { /* ignore */ }
};

export default useMondayMorningAutoLoad;
