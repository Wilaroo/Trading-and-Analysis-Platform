/**
 * useMarketState — thin React hook around the canonical
 * `/api/market-state` endpoint (services/market_state.py — single source of
 * truth shared with live_bar_cache TTLs, backfill_readiness, account_guard,
 * enhanced_scanner gating).
 *
 * Buckets only flip on hour boundaries so the default 60s poll is plenty.
 * Returns `null` until first fetch resolves so consumers can render
 * nothing instead of guessing a default.
 */
import { useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const DEFAULT_POLL_MS = 60_000;

export const useMarketState = (pollMs = DEFAULT_POLL_MS) => {
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

  return snap;
};

export default useMarketState;
