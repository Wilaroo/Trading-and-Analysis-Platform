/**
 * MarketStateContext — single app-wide poll of `/api/market-state`.
 *
 * Why a context:
 * --------------
 * Multiple surfaces consume the canonical market-state snapshot:
 *   - SENTCOM wordmark moon (SentCom.jsx)
 *   - DataFreshnessBadge chip moon (DataFreshnessBadge.jsx)
 *   - MarketStateBanner inside FreshnessInspector (MarketStateBanner.jsx)
 *
 * If each consumer runs its own `useMarketState` hook we end up with N
 * round-trips per minute (one per mounted consumer). With a single
 * context-mounted Provider we make exactly 1 fetch per 60s no matter
 * how many surfaces are open simultaneously, and they all flip in
 * lock-step on state boundaries (no risk of one being amber while
 * another is grey for up to 60s during an RTH→extended transition).
 *
 * Drop-in API: `useMarketState()` keeps the exact same return shape as
 * the old hook — components that already imported it via
 * `frontend/src/hooks/useMarketState.js` keep working unchanged because
 * that file now re-exports from this context. Backwards compatible.
 */
import React, { createContext, useContext, useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const DEFAULT_POLL_MS = 60_000;

const MarketStateContext = createContext(null);

export const MarketStateProvider = ({ children, pollMs = DEFAULT_POLL_MS }) => {
  const [snap, setSnap] = useState(null);

  useEffect(() => {
    let alive = true;
    const fetchOnce = async () => {
      try {
        const resp = await fetch(`${BACKEND_URL}/api/market-state`);
        if (!resp.ok) return;
        const body = await resp.json();
        if (alive && body?.success) setSnap(body);
      } catch { /* swallow — leave stale snapshot */ }
    };
    fetchOnce();
    const id = setInterval(fetchOnce, pollMs);
    return () => { alive = false; clearInterval(id); };
  }, [pollMs]);

  return (
    <MarketStateContext.Provider value={snap}>
      {children}
    </MarketStateContext.Provider>
  );
};

/**
 * Read the current market-state snapshot.
 *
 * Returns `null` until the first fetch resolves, then the full snapshot
 * dict from /api/market-state. Returns null when used outside a Provider
 * so callers can render conditionally without crashing the tree.
 */
export const useMarketState = () => {
  return useContext(MarketStateContext);
};

export default MarketStateContext;
