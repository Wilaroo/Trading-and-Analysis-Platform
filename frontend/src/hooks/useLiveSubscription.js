/**
 * useLiveSubscription — Phase 2 frontend hook
 * =============================================
 * Subscribes a symbol to the tick-level live feed on mount, renews a
 * heartbeat every 2 minutes so the backend's 5-min auto-expire sweep
 * never fires for an active component, and unsubscribes on unmount.
 *
 * Usage:
 *     useLiveSubscription(symbol);                  // single symbol
 *     useLiveSubscription(null);                    // no-op (guard clause)
 *     useLiveSubscription(symbol, { enabled: tab === 'live' }); // conditional
 *
 * Safe to call from multiple components for the same symbol — backend
 * ref-counts so ChartPanel + Scanner watching SPY both see live ticks
 * until BOTH unmount.
 *
 * The actual tick data comes in through the existing pusher → backend →
 * frontend pipe (DataFreshnessBadge / quotes_buffer / useCommandCenterData)
 * — this hook just turns the faucet on for the chosen symbol.
 */

import { useEffect, useRef } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const HEARTBEAT_MS = 2 * 60 * 1000;   // 2 min (backend TTL is 5 min)

async function _post(path) {
  try {
    const resp = await fetch(`${BACKEND_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

export function useLiveSubscription(symbol, { enabled = true } = {}) {
  const subscribedRef = useRef(null);

  useEffect(() => {
    if (!enabled || !symbol) return undefined;
    const sym = String(symbol).toUpperCase().trim();
    if (!sym) return undefined;

    let cancelled = false;
    let heartbeatTimer = null;

    const subscribe = async () => {
      const resp = await _post(`/api/live/subscribe/${encodeURIComponent(sym)}`);
      if (cancelled) return;
      if (resp && resp.accepted) {
        subscribedRef.current = sym;
      }
      // Start heartbeat regardless — if subscribe was cap-rejected the
      // heartbeat will no-op and we'll retry via the timer cycle if the
      // cap clears.
      heartbeatTimer = setInterval(() => {
        _post(`/api/live/heartbeat/${encodeURIComponent(sym)}`);
      }, HEARTBEAT_MS);
    };

    subscribe();

    return () => {
      cancelled = true;
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      if (subscribedRef.current) {
        // Fire-and-forget — we don't block unmount on network
        _post(`/api/live/unsubscribe/${encodeURIComponent(subscribedRef.current)}`);
        subscribedRef.current = null;
      }
    };
  }, [symbol, enabled]);
}

/**
 * useLiveSubscriptions — multi-symbol variant for Scanner top-10.
 *
 * Subscribes to every symbol in `symbols` array; when the array changes,
 * diffs and (un)subscribes the delta. Auto-cleanup on unmount.
 */
export function useLiveSubscriptions(symbols, { enabled = true, max = 10 } = {}) {
  const activeRef = useRef(new Set());

  useEffect(() => {
    if (!enabled) return undefined;

    const wanted = new Set(
      (symbols || [])
        .slice(0, max)
        .map((s) => String(s || '').toUpperCase().trim())
        .filter(Boolean)
    );

    const current = activeRef.current;
    const toAdd = [...wanted].filter((s) => !current.has(s));
    const toRemove = [...current].filter((s) => !wanted.has(s));

    toAdd.forEach((s) => {
      _post(`/api/live/subscribe/${encodeURIComponent(s)}`);
      current.add(s);
    });
    toRemove.forEach((s) => {
      _post(`/api/live/unsubscribe/${encodeURIComponent(s)}`);
      current.delete(s);
    });

    const heartbeatTimer = setInterval(() => {
      current.forEach((s) => {
        _post(`/api/live/heartbeat/${encodeURIComponent(s)}`);
      });
    }, HEARTBEAT_MS);

    return () => {
      clearInterval(heartbeatTimer);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(symbols), enabled, max]);

  useEffect(() => {
    // Full cleanup on unmount — un-subscribe the snapshot captured when
    // the component last rendered.
    return () => {
      const current = activeRef.current;
      current.forEach((s) => {
        _post(`/api/live/unsubscribe/${encodeURIComponent(s)}`);
      });
      current.clear();
    };
  }, []);
}

export default useLiveSubscription;
