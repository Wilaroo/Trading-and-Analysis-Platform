import { useState, useEffect, useCallback, useRef } from 'react';
import { getWebSocketUrl } from '../utils/api';

// ===================== WEBSOCKET HOOK =====================
export const useWebSocket = (onMessage) => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const heartbeatIntervalRef = useRef(null);
  const onMessageRef = useRef(onMessage);
  // Pending promise callbacks for train requests keyed by a request nonce
  const trainCallbacksRef = useRef({});

  // Keep onMessage ref updated
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const startHeartbeat = useCallback((ws) => {
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
    }
    heartbeatIntervalRef.current = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ action: 'ping' }));
        } catch (e) {
          console.warn('Heartbeat ping failed:', e);
        }
      }
    }, 25000);
  }, []);

  const stopHeartbeat = useCallback(() => {
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    try {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      
      const wsUrl = getWebSocketUrl();
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        startHeartbeat(ws);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          // Ignore keepalive messages
          if (data.type === 'pong' || data.type === 'server_ping' || data.type === 'connected') {
            if (data.type === 'connected' || data.type === 'server_ping') {
              setLastUpdate(new Date());
            }
            return;
          }

          // Handle train responses — resolve pending promises
          if (data.type === 'train_queued' || data.type === 'train_error') {
            const callbacks = trainCallbacksRef.current;
            // Match by setup_type or train_type
            const key = data.setup_type || data.train_type || '_pending';
            if (callbacks[key]) {
              callbacks[key](data);
              delete callbacks[key];
            }
            // Also forward to onMessage so components can listen
          }

          setLastUpdate(new Date());
          if (onMessageRef.current) {
            onMessageRef.current(data);
          }
        } catch (e) {
          console.error('Error parsing WebSocket message:', e);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        stopHeartbeat();
        if (event.code !== 1000) {
          reconnectTimeoutRef.current = setTimeout(connect, 3000);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setIsConnected(false);
      };
    } catch (e) {
      console.error('Failed to create WebSocket:', e);
      setIsConnected(false);
    }
  }, [startHeartbeat, stopHeartbeat]);

  useEffect(() => {
    connect();
    return () => {
      stopHeartbeat();
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect, stopHeartbeat]);

  const subscribe = useCallback((symbols) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'subscribe', symbols }));
    }
  }, []);

  const unsubscribe = useCallback((symbols) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'unsubscribe', symbols }));
    }
  }, []);

  /**
   * Send an arbitrary JSON message over the WebSocket.
   * Returns a Promise that resolves when the server sends back
   * a train_queued / train_error response matching the callbackKey.
   *
   * @param {object} msg - JSON message to send (must include action)
   * @param {string} callbackKey - key to match the response (e.g. setup_type)
   * @param {number} timeout - ms to wait before rejecting (default 15s)
   */
  const sendTrainCommand = useCallback((msg, callbackKey, timeout = 15000) => {
    return new Promise((resolve, reject) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'));
        return;
      }
      const key = callbackKey || '_pending';
      // Set up callback
      trainCallbacksRef.current[key] = (response) => {
        clearTimeout(timer);
        resolve(response);
      };
      // Timeout fallback
      const timer = setTimeout(() => {
        delete trainCallbacksRef.current[key];
        reject(new Error('WebSocket train command timed out'));
      }, timeout);
      // Send the message
      wsRef.current.send(JSON.stringify(msg));
    });
  }, []);

  return { isConnected, lastUpdate, subscribe, unsubscribe, sendTrainCommand };
};

export default useWebSocket;
