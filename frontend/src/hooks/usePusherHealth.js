/**
 * usePusherHealth — shared subscription to /api/ib/pusher-health.
 *
 * Polls the backend once every 8s and fans out the result to every
 * component that calls this hook. This keeps the loud-failure banner,
 * the compact PusherHealthChip, and every freshness badge scattered
 * around V5 all reading from the SAME source of truth without each
 * spawning its own interval.
 */
import { useEffect, useState } from 'react';
import api from '../utils/api';

const POLL_MS = 8000;

// Module-level state — shared across every component using the hook.
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
    const res = await api.get('/api/ib/pusher-health');
    if (res?.data?.success) {
      _state = res.data;
      _notify();
    }
  } catch {
    // Mark as unreachable so banners can flip to DOWN
    _state = { success: false, health: 'red', pusher_dead: true, age_seconds: null };
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

export const usePusherHealth = () => {
  const [data, setData] = useState(_state);

  useEffect(() => {
    _listeners.add(setData);
    _startPoller();
    // When the last listener unmounts, stop the interval (React StrictMode safe).
    return () => {
      _listeners.delete(setData);
      if (_listeners.size === 0) _stopPoller();
    };
  }, []);

  return data;
};

export default usePusherHealth;
