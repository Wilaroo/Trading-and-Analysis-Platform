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

  // Keep onMessage ref updated
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const startHeartbeat = useCallback((ws) => {
    // Clear any existing heartbeat
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
    }
    
    // Send ping every 25 seconds to keep connection alive
    // (Most proxies timeout at 30-60 seconds)
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
      const wsUrl = getWebSocketUrl();
      console.log('Connecting to WebSocket:', wsUrl);
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected');
        setIsConnected(true);
        // Start heartbeat to keep connection alive
        startHeartbeat(ws);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          // Ignore pong responses (heartbeat acknowledgments)
          if (data.type === 'pong') {
            return;
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
        console.log('WebSocket disconnected, code:', event.code, 'reason:', event.reason);
        setIsConnected(false);
        stopHeartbeat();
        // Reconnect after 3 seconds
        reconnectTimeoutRef.current = setTimeout(connect, 3000);
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

  return { isConnected, lastUpdate, subscribe, unsubscribe };
};

export default useWebSocket;
