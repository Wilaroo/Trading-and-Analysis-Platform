/**
 * useMondayMorningAutoLoad — auto-frames the V5 chart on the Weekend
 * Briefing's #1 watch at the open of the trading week.
 *
 * Trigger window:
 *   Monday 09:25 ET → 09:40 ET (15-minute door so a slightly-late page
 *   load still catches the auto-load before the open).
 *
 * Idempotency:
 *   Flagged in localStorage keyed by ISO week (e.g. `wb-autoload-2026-W18`)
 *   so the auto-load fires at most once per week. Reloading the page
 *   inside the window does NOT re-trigger.
 *
 * Side-effect output:
 *   - Calls `setFocusedSymbol(symbol)` which the V5 chart watches.
 *   - Stores `wb-autoloaded-symbol-{week}` in localStorage so the
 *     WeekendBriefingCard can render a "live now" border on the
 *     matching watch card.
 *
 * Disabled cleanly when:
 *   - market state isn't `rth` or hasn't entered the trigger window yet
 *   - briefing has no watches (LLM unavailable Sunday)
 *   - the user has already manually focused another symbol since load
 *     (we don't override an explicit user choice — only fill the void)
 */
import { useEffect, useRef } from 'react';
import { useMarketState } from '../contexts';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const WINDOW_OPEN_HHMM = 9 * 60 + 25;   // 09:25 ET
const WINDOW_CLOSE_HHMM = 9 * 60 + 40;  // 09:40 ET — 15-min door

const lsKey = (iso_week) => `wb-autoload-${iso_week}`;
const lsSymKey = (iso_week) => `wb-autoloaded-symbol-${iso_week}`;

export const useMondayMorningAutoLoad = ({
  setFocusedSymbol,
  userHasFocused,
}) => {
  const snap = useMarketState();
  const checkedRef = useRef(false);

  useEffect(() => {
    if (!snap || !setFocusedSymbol) return;
    if (checkedRef.current) return;

    // Monday only (ET weekday 0). Skip weekends + Tue-Fri.
    if (snap.et_weekday !== 0) return;
    // Inside the 09:25-09:40 ET window.
    const hhmm = snap.et_hhmm ?? -1;
    if (hhmm < WINDOW_OPEN_HHMM || hhmm > WINDOW_CLOSE_HHMM) return;

    // If the user has already focused something explicitly this session,
    // respect that — never override a manual choice.
    if (userHasFocused) {
      checkedRef.current = true;
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${BACKEND_URL}/api/briefings/weekend/latest`);
        if (!resp.ok) return;
        const body = await resp.json();
        const briefing = body?.briefing;
        const wid = briefing?.iso_week;
        if (!wid) return;

        // Once-per-ISO-week guard.
        const flagKey = lsKey(wid);
        if (typeof window !== 'undefined' && window.localStorage.getItem(flagKey)) {
          checkedRef.current = true;
          return;
        }

        const watches = briefing?.gameplan?.watches;
        const top = Array.isArray(watches) && watches.length > 0 ? watches[0] : null;
        const sym = top?.symbol ? String(top.symbol).toUpperCase() : null;
        if (!sym || cancelled) return;

        setFocusedSymbol(sym);
        if (typeof window !== 'undefined') {
          window.localStorage.setItem(flagKey, new Date().toISOString());
          window.localStorage.setItem(lsSymKey(wid), sym);
        }
        checkedRef.current = true;
      } catch {
        /* swallow — auto-load is best-effort */
      }
    })();

    return () => { cancelled = true; };
  }, [snap, setFocusedSymbol, userHasFocused]);
};

/**
 * Read the most recently auto-loaded symbol for the current ISO week.
 * Used by the WeekendBriefingCard to highlight the matching watch card.
 * Returns `null` outside the browser or when no auto-load has happened
 * for the current week.
 */
export const readAutoLoadedSymbol = (iso_week) => {
  if (typeof window === 'undefined' || !iso_week) return null;
  try {
    return window.localStorage.getItem(lsSymKey(iso_week));
  } catch {
    return null;
  }
};

export default useMondayMorningAutoLoad;
