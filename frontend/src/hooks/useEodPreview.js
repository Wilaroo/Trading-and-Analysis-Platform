/**
 * useEodPreview — shared subscription to /api/diagnostic/eod-preview.
 *
 * Polls every 30s OUTSIDE the EOD window (cheap heartbeat); ramps to
 * every 10s INSIDE the 3:30-4:00 PM ET window so the banner reflects
 * the live state as the operator approaches close.
 *
 * Module-level fan-out so multiple consumers (banner + future tiles)
 * share the single in-flight request.
 *
 * 2026-02-13 v19.34.152
 */
import { useEffect, useState } from 'react';
import api from '../utils/api';

const POLL_MS_OUTSIDE = 30000;
const POLL_MS_INSIDE = 10000;

let _state = null;
let _listeners = new Set();
let _poller = null;
let _currentInterval = POLL_MS_OUTSIDE;

const _notify = () => {
  _listeners.forEach((fn) => {
    try { fn(_state); } catch { /* no-op */ }
  });
};

const _tick = async () => {
  try {
    const res = await api.get('/api/diagnostic/eod-preview');
    if (res?.data?.success) {
      _state = res.data;
      _notify();
      // Adapt interval based on window state.
      const desiredInterval = _state.is_eod_window
        ? POLL_MS_INSIDE : POLL_MS_OUTSIDE;
      if (desiredInterval !== _currentInterval && _poller) {
        clearInterval(_poller);
        _currentInterval = desiredInterval;
        _poller = setInterval(_tick, _currentInterval);
      }
    }
  } catch {
    _state = { success: false, health: 'unknown', notes: ['endpoint unreachable'] };
    _notify();
  }
};

const _startPoller = () => {
  if (_poller) return;
  _tick();
  _poller = setInterval(_tick, _currentInterval);
};

const _stopPoller = () => {
  if (_poller) {
    clearInterval(_poller);
    _poller = null;
  }
};

export const useEodPreview = () => {
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

export default useEodPreview;
