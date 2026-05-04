/**
 * useChartTailWs — v19.33 (2026-05-04)
 *
 * WebSocket-pushed chart-tail subscription. Replaces the 5s polling
 * loop on the focused chart with server-pushed bar updates. Latency
 * drops from ~5s avg → ~2s ceiling (the server tick interval), and
 * the client doesn't pay round-trip overhead for empty "no new bars"
 * responses (the server filters those out).
 *
 * Design notes
 * ------------
 * - Auto-reconnects with exponential backoff on transient errors.
 * - Caller passes `onTail(payload)` which receives the SAME payload
 *   shape as REST `/chart-tail`, so existing merge code can be reused
 *   verbatim. `from_ws: true` is stamped server-side for telemetry.
 * - Caller can pass `enabled={false}` to disable the WS entirely
 *   (e.g. when the operator is on a daily timeframe — daily bars
 *   change once per session and don't need streaming).
 * - Hook returns `{ status }` so the chart header can render a "live"
 *   pip (`connected`) vs "polling" pip (`disconnected`).
 *
 * Auto-fallback
 * -------------
 * If the WS connection fails 3 times in a row, the hook gives up and
 * sets `status='fallback'`. The caller should switch back to its
 * existing polling loop in that state. This prevents a spinning
 * reconnect loop from saturating the browser when the server route
 * is down or behind a non-WS-aware proxy.
 */
import { useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

// Convert https://... → wss://...   ;   http://... → ws://...
const _toWsUrl = (httpUrl) => {
  if (!httpUrl) return null;
  if (httpUrl.startsWith('https://')) return 'wss://' + httpUrl.slice('https://'.length);
  if (httpUrl.startsWith('http://'))  return 'ws://'  + httpUrl.slice('http://'.length);
  return null;
};

const _BASE_WS = _toWsUrl(BACKEND_URL);

export function useChartTailWs({
  symbol,
  timeframe,
  since,
  session = 'rth_plus_premarket',
  enabled = true,
  onTail,
  onPing,
}) {
  const [status, setStatus] = useState('idle'); // idle|connecting|connected|disconnected|fallback
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const failureCountRef = useRef(0);
  const sinceRef = useRef(since || 0);
  const onTailRef = useRef(onTail);
  const onPingRef = useRef(onPing);

  // Keep callback refs current without restarting the connection.
  useEffect(() => { onTailRef.current = onTail; }, [onTail]);
  useEffect(() => { onPingRef.current = onPing; }, [onPing]);

  // Track the latest bar `time` so a reconnect can resume from the
  // newest known position rather than the original `since` snapshot.
  useEffect(() => { sinceRef.current = since || sinceRef.current; }, [since]);

  useEffect(() => {
    if (!enabled || !symbol || !timeframe || !_BASE_WS) {
      setStatus('idle');
      return undefined;
    }

    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      const url =
        `${_BASE_WS}/api/sentcom/ws/chart-tail` +
        `?symbol=${encodeURIComponent(symbol)}` +
        `&timeframe=${encodeURIComponent(timeframe)}` +
        `&since=${encodeURIComponent(sinceRef.current || 0)}` +
        `&session=${encodeURIComponent(session)}`;

      let ws;
      try {
        ws = new WebSocket(url);
      } catch (_) {
        failureCountRef.current += 1;
        if (failureCountRef.current >= 3) {
          setStatus('fallback');
          return;
        }
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;
      setStatus('connecting');

      ws.onopen = () => {
        if (cancelled) { try { ws.close(); } catch (_) {} return; }
        failureCountRef.current = 0;
        setStatus('connected');
      };

      ws.onmessage = (evt) => {
        if (cancelled) return;
        let payload;
        try { payload = JSON.parse(evt.data); } catch (_) { return; }
        if (payload?.type === 'ping') {
          onPingRef.current && onPingRef.current(payload);
          return;
        }
        if (payload?.success && (payload.bar_count > 0 || (payload.bars || []).length > 0)) {
          // Update the resume marker before invoking the consumer.
          if (payload.latest_time) {
            sinceRef.current = Math.max(sinceRef.current, Number(payload.latest_time) || 0);
          }
          onTailRef.current && onTailRef.current(payload);
        }
      };

      ws.onerror = () => {
        // onclose follows. Don't double-handle.
      };

      ws.onclose = () => {
        if (cancelled) return;
        wsRef.current = null;
        setStatus('disconnected');
        failureCountRef.current += 1;
        if (failureCountRef.current >= 3) {
          setStatus('fallback');
          return;
        }
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (cancelled) return;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      // Backoff: 1s, 2s, 4s — capped before we give up.
      const delay = Math.min(4000, 1000 * Math.pow(2, failureCountRef.current));
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        try { ws.close(1000, 'unmount'); } catch (_) { /* ignore */ }
      }
    };
    // We INTENTIONALLY don't include onTail/onPing in deps — those are
    // stored in refs. Re-running the effect on every prop callback
    // change would cause a connection thrash.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, timeframe, session, enabled]);

  return { status };
}

export default useChartTailWs;
