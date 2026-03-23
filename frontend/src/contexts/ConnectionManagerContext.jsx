/**
 * ConnectionManager - Resilient Connection Handling
 * ==================================================
 * 
 * Provides:
 * 1. Auto-reconnect with exponential backoff
 * 2. Connection health monitoring
 * 3. Graceful degradation
 * 4. Visibility-aware connections (pause when tab hidden)
 * 5. Connection state broadcasting
 */

import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { useAppState } from './AppStateContext';

const ConnectionManagerContext = createContext(null);

// Reconnect settings
const RECONNECT_BASE_DELAY = 1000;  // 1 second
const RECONNECT_MAX_DELAY = 30000;  // 30 seconds max
const RECONNECT_MAX_ATTEMPTS = 10;
const HEALTH_CHECK_INTERVAL = 30000; // 30 seconds

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

export const ConnectionManagerProvider = ({ children }) => {
  const { updateConnection } = useAppState();
  
  // WebSocket refs
  const wsRef = useRef(null);
  const wsReconnectAttempts = useRef(0);
  const wsReconnectTimer = useRef(null);
  
  // Health check refs
  const healthCheckTimer = useRef(null);
  
  // Visibility state
  const [isVisible, setIsVisible] = useState(true);
  
  // Connection states (local for quick access)
  const [wsConnected, setWsConnected] = useState(false);
  const [ibConnected, setIbConnected] = useState(false);
  const [backendConnected, setBackendConnected] = useState(true);

  /**
   * Calculate reconnect delay with exponential backoff
   */
  const getReconnectDelay = (attempts) => {
    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(2, attempts),
      RECONNECT_MAX_DELAY
    );
    // Add jitter to prevent thundering herd
    return delay + Math.random() * 1000;
  };

  /**
   * Connect to WebSocket with auto-reconnect
   */
  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return; // Already connected
    }
    
    // Don't connect if tab is hidden
    if (!isVisible) {
      console.log('[ConnectionManager] Tab hidden, deferring WS connection');
      return;
    }

    const wsUrl = `${API_URL.replace('http', 'ws')}/api/ws/quotes`;
    console.log('[ConnectionManager] Connecting to WebSocket:', wsUrl);
    
    try {
      wsRef.current = new WebSocket(wsUrl);
      
      wsRef.current.onopen = () => {
        console.log('[ConnectionManager] WebSocket connected');
        wsReconnectAttempts.current = 0;
        setWsConnected(true);
        updateConnection('websocket', { connected: true, reconnecting: false });
      };
      
      wsRef.current.onclose = (event) => {
        console.log('[ConnectionManager] WebSocket closed:', event.code, event.reason);
        setWsConnected(false);
        updateConnection('websocket', { connected: false });
        
        // Auto-reconnect if not intentional close and tab is visible
        if (event.code !== 1000 && isVisible) {
          scheduleReconnect();
        }
      };
      
      wsRef.current.onerror = (error) => {
        console.error('[ConnectionManager] WebSocket error:', error);
        setWsConnected(false);
        updateConnection('websocket', { connected: false });
      };
      
      wsRef.current.onmessage = (event) => {
        // Handle incoming messages - broadcast to subscribers
        try {
          const data = JSON.parse(event.data);
          // Dispatch custom event for components to listen
          window.dispatchEvent(new CustomEvent('ws-message', { detail: data }));
        } catch (e) {
          // Ignore parse errors
        }
      };
      
    } catch (error) {
      console.error('[ConnectionManager] Failed to create WebSocket:', error);
      scheduleReconnect();
    }
  }, [isVisible, updateConnection]);

  /**
   * Schedule WebSocket reconnection with backoff
   */
  const scheduleReconnect = useCallback(() => {
    if (wsReconnectAttempts.current >= RECONNECT_MAX_ATTEMPTS) {
      console.error('[ConnectionManager] Max reconnect attempts reached');
      updateConnection('websocket', { connected: false, reconnecting: false });
      return;
    }
    
    const delay = getReconnectDelay(wsReconnectAttempts.current);
    console.log(`[ConnectionManager] Scheduling reconnect in ${delay}ms (attempt ${wsReconnectAttempts.current + 1})`);
    
    updateConnection('websocket', { reconnecting: true });
    
    wsReconnectTimer.current = setTimeout(() => {
      wsReconnectAttempts.current++;
      connectWebSocket();
    }, delay);
  }, [connectWebSocket, updateConnection]);

  /**
   * Check backend health
   */
  const checkBackendHealth = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/health`, {
        method: 'GET',
        timeout: 5000
      });
      const healthy = response.ok;
      setBackendConnected(healthy);
      updateConnection('mongodb', { connected: healthy });
      return healthy;
    } catch (error) {
      console.warn('[ConnectionManager] Backend health check failed:', error);
      setBackendConnected(false);
      updateConnection('mongodb', { connected: false });
      return false;
    }
  }, [updateConnection]);

  /**
   * Check IB connection status
   */
  const checkIBConnection = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/ib/status`);
      const data = await response.json();
      const connected = data.connected || false;
      setIbConnected(connected);
      updateConnection('ib', { connected });
      return connected;
    } catch (error) {
      console.warn('[ConnectionManager] IB status check failed:', error);
      setIbConnected(false);
      updateConnection('ib', { connected: false });
      return false;
    }
  }, [updateConnection]);

  /**
   * Run all health checks
   */
  const runHealthChecks = useCallback(async () => {
    if (!isVisible) return; // Skip if tab hidden
    
    await Promise.all([
      checkBackendHealth(),
      checkIBConnection()
    ]);
  }, [isVisible, checkBackendHealth, checkIBConnection]);

  /**
   * Handle visibility change
   */
  useEffect(() => {
    const handleVisibilityChange = () => {
      const visible = document.visibilityState === 'visible';
      setIsVisible(visible);
      
      if (visible) {
        console.log('[ConnectionManager] Tab visible - resuming connections');
        // Reconnect WebSocket if needed
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          connectWebSocket();
        }
        // Run health checks
        runHealthChecks();
      } else {
        console.log('[ConnectionManager] Tab hidden - pausing reconnects');
        // Clear reconnect timer when hidden
        if (wsReconnectTimer.current) {
          clearTimeout(wsReconnectTimer.current);
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [connectWebSocket, runHealthChecks]);

  /**
   * Initialize connections on mount
   */
  useEffect(() => {
    // Initial connection
    connectWebSocket();
    runHealthChecks();
    
    // Periodic health checks
    healthCheckTimer.current = setInterval(runHealthChecks, HEALTH_CHECK_INTERVAL);
    
    return () => {
      // Cleanup
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounting');
      }
      if (wsReconnectTimer.current) {
        clearTimeout(wsReconnectTimer.current);
      }
      if (healthCheckTimer.current) {
        clearInterval(healthCheckTimer.current);
      }
    };
  }, []);

  /**
   * Send message via WebSocket
   */
  const sendWsMessage = useCallback((message) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
      return true;
    }
    console.warn('[ConnectionManager] Cannot send - WebSocket not connected');
    return false;
  }, []);

  /**
   * Force reconnect all connections
   */
  const reconnectAll = useCallback(() => {
    console.log('[ConnectionManager] Forcing reconnection of all connections');
    
    // Close existing WebSocket
    if (wsRef.current) {
      wsRef.current.close();
    }
    wsReconnectAttempts.current = 0;
    
    // Reconnect
    connectWebSocket();
    runHealthChecks();
  }, [connectWebSocket, runHealthChecks]);

  /**
   * Subscribe to WebSocket messages
   */
  const subscribeToWs = useCallback((handler) => {
    const listener = (event) => handler(event.detail);
    window.addEventListener('ws-message', listener);
    return () => window.removeEventListener('ws-message', listener);
  }, []);

  return (
    <ConnectionManagerContext.Provider value={{
      // Connection states
      wsConnected,
      ibConnected,
      backendConnected,
      isVisible,
      
      // Actions
      connectWebSocket,
      sendWsMessage,
      subscribeToWs,
      reconnectAll,
      checkIBConnection,
      checkBackendHealth,
      runHealthChecks,
      
      // WebSocket ref for advanced usage
      wsRef
    }}>
      {children}
    </ConnectionManagerContext.Provider>
  );
};

/**
 * Hook to access connection manager
 */
export const useConnectionManager = () => {
  const context = useContext(ConnectionManagerContext);
  if (!context) {
    return {
      wsConnected: false,
      ibConnected: false,
      backendConnected: false,
      isVisible: true,
      connectWebSocket: () => {},
      sendWsMessage: () => false,
      subscribeToWs: () => () => {},
      reconnectAll: () => {},
      checkIBConnection: () => Promise.resolve(false),
      checkBackendHealth: () => Promise.resolve(false),
      runHealthChecks: () => {},
      wsRef: { current: null }
    };
  }
  return context;
};

export default ConnectionManagerContext;
