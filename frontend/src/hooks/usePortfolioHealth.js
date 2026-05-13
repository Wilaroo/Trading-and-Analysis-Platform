/**
 * usePortfolioHealth — shared subscription to
 * /api/diagnostic/ib-pusher-position-health.
 *
 * Distinct from `usePusherHealth` (which polls pipeline heartbeat).
 * This hook polls per-position payload quality so the V5 status strip
 * can show whether `updatePortfolio()` is actually delivering
 * unrealizedPNL / marketPrice / avgCost on every live position.
 *
 * Polled every 30s — payload diagnostic is heavier than heartbeat and
 * doesn't need sub-second freshness. Module-level fan-out shares the
 * single in-flight request across every consumer of the hook.
 *
 * 2026-02-13 v19.34.150b
 */
import { useEffect, useState } from 'react';
import api from '../utils/api';

const POLL_MS = 30000;

let _state = null;
let _listeners = new Set();
let _poller = null;

const _notify = () => {
  _listeners.forEach((fn) => {
    try { fn(_state); } catch { /* no-op */ }
  });
};

const _tick = async () => {
  try {
    const res = await api.get('/api/diagnostic/ib-pusher-position-health');
    if (res?.data?.success) {
      _state = res.data;
      _notify();
    }
  } catch {
    _state = { success: false, health: 'unknown', diagnosis: ['endpoint unreachable'] };
    _notify();
  }
};

const _startPoller = () => {
  if (_poller) return;
  _tick();
  _poller = setInterval(_tick, POLL_MS);
};

const _stopPoller = () => {
  if (_poller) {
    clearInterval(_poller);
    _poller = null;
  }
};

export const usePortfolioHealth = () => {
  const [data, setData] = useState(_state);

  useEffect(() => {
    _listeners.add(setData);
    _startPoller();
    return () => {
      _listeners.delete(setData);
      if (_listeners.size === 0) _stopPoller();
    };
  }, []);

  return data;
};

export default usePortfolioHealth;
