/**
 * useStreamSocket — v19.34.184 (Mission Control)
 *
 * WebSocket client for `/api/ws/stream` — the live pipeline bus. The bus is
 * always persisting to `sentcom_thoughts`; this socket is just the live push
 * channel and only does work while mounted.
 *
 *   • Auto-reconnects with exponential backoff (1s,2s,4s; →fallback after 3).
 *   • Sends a `subscribe` message on open (lanes + severities + raw/aggregate).
 *   • Resends subscription whenever it changes (no reconnect thrash).
 *   • Dispatches batched `events` frames and `scan_pulse` frames to callbacks.
 *
 * Returns `{ status }` for the header heartbeat pip.
 */
import { useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const _toWsUrl = (httpUrl) => {
  if (!httpUrl) return null;
  if (httpUrl.startsWith('https://')) return 'wss://' + httpUrl.slice('https://'.length);
  if (httpUrl.startsWith('http://')) return 'ws://' + httpUrl.slice('http://'.length);
  return null;
};

const _BASE_WS = _toWsUrl(BACKEND_URL);

export function useStreamSocket({ enabled = true, sub, onEvents, onPulse }) {
  const [status, setStatus] = useState('idle'); // idle|connecting|connected|disconnected|fallback
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const failureCountRef = useRef(0);
  const onEventsRef = useRef(onEvents);
  const onPulseRef = useRef(onPulse);
  const subRef = useRef(sub);

  useEffect(() => { onEventsRef.current = onEvents; }, [onEvents]);
  useEffect(() => { onPulseRef.current = onPulse; }, [onPulse]);

  // Push subscription changes over the open socket without reconnecting.
  useEffect(() => {
    subRef.current = sub;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && sub) {
      try { ws.send(JSON.stringify({ action: 'subscribe', ...sub })); } catch (_) { /* ignore */ }
    }
  }, [sub]);

  useEffect(() => {
    if (!enabled || !_BASE_WS) { setStatus('idle'); return undefined; }
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      let ws;
      try { ws = new WebSocket(`${_BASE_WS}/api/ws/stream`); }
      catch (_) {
        failureCountRef.current += 1;
        if (failureCountRef.current >= 3) { setStatus('fallback'); return; }
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;
      setStatus('connecting');

      ws.onopen = () => {
        if (cancelled) { try { ws.close(); } catch (_) {} return; }
        failureCountRef.current = 0;
        setStatus('connected');
        if (subRef.current) {
          try { ws.send(JSON.stringify({ action: 'subscribe', ...subRef.current })); } catch (_) { /* ignore */ }
        }
      };

      ws.onmessage = (evt) => {
        if (cancelled) return;
        let payload;
        try { payload = JSON.parse(evt.data); } catch (_) { return; }
        if (payload?.type === 'events' && Array.isArray(payload.events)) {
          onEventsRef.current && onEventsRef.current(payload.events);
        } else if (payload?.type === 'scan_pulse') {
          onPulseRef.current && onPulseRef.current(payload);
        }
        // connected / subscribed / server_ping / pong are ignored.
      };

      ws.onerror = () => { /* onclose follows */ };

      ws.onclose = () => {
        if (cancelled) return;
        wsRef.current = null;
        setStatus('disconnected');
        failureCountRef.current += 1;
        if (failureCountRef.current >= 3) { setStatus('fallback'); return; }
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (cancelled) return;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      const delay = Math.min(4000, 1000 * Math.pow(2, failureCountRef.current));
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) { try { ws.close(1000, 'unmount'); } catch (_) { /* ignore */ } }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return { status };
}

export default useStreamSocket;
