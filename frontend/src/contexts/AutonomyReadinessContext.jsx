/**
 * AutonomyReadinessContext — single app-wide poll of `/api/autonomy/readiness`.
 *
 * Mirrors the MarketStateContext pattern (2026-02): one Provider mounted
 * at the top of `App.js` runs the poll, every consumer reads from
 * `useContext` for free. As more surfaces start watching the autonomy
 * verdict (the V5 header chip we want to add next, the ⌘K palette
 * preview, the pre-Monday go-live checklist banner) they all flip in
 * lock-step instead of drifting for up to a poll-cycle.
 *
 * Why 30s by default:
 *   The verdict aggregates 7 sub-checks (account, pusher, live bars,
 *   trophy run, kill switch, EOD, risk consistency). Each sub-check
 *   reads from the same MongoDB the rest of the app polls; 30s is fast
 *   enough to catch a kill-switch trip before the operator notices and
 *   slow enough that the backend doesn't get hammered.
 *
 * Compatibility:
 *   `useAutonomyReadiness()` returns `null` until the first fetch resolves
 *   AND when used outside the Provider — consumers should already render
 *   conditionally. The exposed `{ data, loading, error, refresh }` shape
 *   matches what the existing `AutonomyReadinessCard` was tracking
 *   internally so its internal state can be deleted in a one-line swap.
 */
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const DEFAULT_POLL_MS = 30_000;

const AutonomyReadinessContext = createContext(null);

export const AutonomyReadinessProvider = ({ children, pollMs = DEFAULT_POLL_MS }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Bumped by `refresh()` to force an immediate refetch outside the
  // poll cadence (e.g. after the user toggles the kill-switch).
  const [forceTick, setForceTick] = useState(0);
  const aliveRef = useRef(true);

  const refresh = useCallback(() => setForceTick((t) => t + 1), []);

  useEffect(() => {
    aliveRef.current = true;
    const fetchOnce = async () => {
      try {
        const resp = await fetch(`${BACKEND_URL}/api/autonomy/readiness`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        if (aliveRef.current) {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (aliveRef.current) setError(String(e?.message || e));
      } finally {
        if (aliveRef.current) setLoading(false);
      }
    };
    fetchOnce();
    const id = setInterval(fetchOnce, pollMs);
    return () => { aliveRef.current = false; clearInterval(id); };
  }, [pollMs, forceTick]);

  return (
    <AutonomyReadinessContext.Provider value={{ data, loading, error, refresh }}>
      {children}
    </AutonomyReadinessContext.Provider>
  );
};

/**
 * Read the autonomy-readiness snapshot.
 *
 * Returns `{ data, loading, error, refresh }` from the Provider, or a
 * neutral `{ data: null, loading: true, error: null, refresh: noop }`
 * when used outside a Provider so legacy callers don't crash.
 */
export const useAutonomyReadiness = () => {
  const ctx = useContext(AutonomyReadinessContext);
  return ctx || { data: null, loading: true, error: null, refresh: () => {} };
};

export default AutonomyReadinessContext;
