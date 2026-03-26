/**
 * WebSocketDataContext
 * ====================
 * Centralized store for all WebSocket-pushed data.
 * Components subscribe to specific data types instead of polling REST endpoints.
 *
 * Usage:
 *   const { botStatus, botTrades, scannerAlerts, confidenceGate } = useWsData();
 *
 * Replaces prop-drilling WS data through the entire component tree.
 */
import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';

const WebSocketDataContext = createContext(null);

export function WebSocketDataProvider({ children, wsMessage }) {
  // All WS data types stored centrally
  const [data, setData] = useState({
    quotes: {},
    ibStatus: null,
    botStatus: null,
    botTrades: [],
    scannerStatus: null,
    scannerAlerts: [],
    smartWatchlist: [],
    coachingNotifications: [],
    confidenceGate: null,
    trainingStatus: null,
    marketRegime: null,
    filterThoughts: [],
    sentcomStream: [],
  });

  // Track last update timestamps for each type
  const lastUpdate = useRef({});

  // Process incoming WS messages
  const processMessage = useCallback((message) => {
    if (!message || !message.type) return;

    const now = Date.now();
    lastUpdate.current[message.type] = now;

    setData(prev => {
      switch (message.type) {
        case 'quotes':
          return { ...prev, quotes: { ...prev.quotes, ...message.data } };

        case 'ib_status':
          return { ...prev, ibStatus: message.data };

        case 'bot_status':
          return { ...prev, botStatus: message.data };

        case 'bot_trades':
          return { ...prev, botTrades: message.data || [] };

        case 'scanner_status':
          return { ...prev, scannerStatus: message.data };

        case 'scanner_alerts':
          return { ...prev, scannerAlerts: message.data || [] };

        case 'smart_watchlist':
          return { ...prev, smartWatchlist: message.data || [] };

        case 'coaching_notifications': {
          const existingIds = new Set(prev.coachingNotifications.map(n => n.id));
          const newNotifs = (message.data || []).filter(n => !existingIds.has(n.id));
          return { ...prev, coachingNotifications: [...newNotifs, ...prev.coachingNotifications].slice(0, 50) };
        }

        case 'confidence_gate':
          return { ...prev, confidenceGate: message.data };

        case 'training_status':
          return { ...prev, trainingStatus: message.data };

        case 'market_regime':
          return { ...prev, marketRegime: message.data };

        case 'filter_thoughts':
          return { ...prev, filterThoughts: message.data || [] };

        case 'sentcom_stream':
          return { ...prev, sentcomStream: message.data || [] };

        default:
          return prev;
      }
    });
  }, []);

  // Process messages from App's WS handler
  useEffect(() => {
    if (wsMessage) processMessage(wsMessage);
  }, [wsMessage, processMessage]);

  return (
    <WebSocketDataContext.Provider value={{ ...data, lastUpdate: lastUpdate.current }}>
      {children}
    </WebSocketDataContext.Provider>
  );
}

/**
 * Hook to access all WS data or specific types.
 *
 * Usage:
 *   const { botStatus, botTrades } = useWsData();
 *   const wsData = useWsData();  // All data
 */
export function useWsData() {
  const context = useContext(WebSocketDataContext);
  if (!context) {
    // Return empty defaults if used outside provider (graceful fallback)
    return {
      quotes: {},
      ibStatus: null,
      botStatus: null,
      botTrades: [],
      scannerStatus: null,
      scannerAlerts: [],
      smartWatchlist: [],
      coachingNotifications: [],
      confidenceGate: null,
      trainingStatus: null,
      marketRegime: null,
      filterThoughts: [],
      sentcomStream: [],
      lastUpdate: {},
    };
  }
  return context;
}

export default WebSocketDataContext;
