/**
 * AppStateContext - Centralized Resilient State Management
 * =========================================================
 * 
 * This context provides:
 * 1. Persistent state that survives tab switches
 * 2. LocalStorage backup for critical data
 * 3. Automatic rehydration on mount
 * 4. Stale-while-revalidate pattern
 * 5. Connection state tracking
 * 
 * Usage:
 *   const { getData, setData, isStale } = useAppState();
 *   const marketData = getData('marketContext');
 */

import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';

const AppStateContext = createContext(null);

// Keys that should persist to localStorage (critical data)
const PERSISTENT_KEYS = [
  'marketContext',
  'marketRegime', 
  'accountSummary',
  'positions',
  'botStatus',
  'userPreferences',
  'lastSelectedTab',
  'watchlist'
];

// TTL for different data types (in ms)
const DATA_TTL = {
  marketContext: 30000,      // 30 seconds
  marketRegime: 60000,       // 1 minute
  accountSummary: 30000,     // 30 seconds
  positions: 10000,          // 10 seconds (more volatile)
  botStatus: 5000,           // 5 seconds
  quotes: 2000,              // 2 seconds (real-time)
  scannerAlerts: 10000,      // 10 seconds
  trainingHistory: 300000,   // 5 minutes (rarely changes)
  default: 30000             // 30 seconds default
};

// Storage key prefix
const STORAGE_PREFIX = 'sentcom_state_';

export const AppStateProvider = ({ children }) => {
  // In-memory state store
  const stateRef = useRef(new Map());
  const timestampRef = useRef(new Map());
  const subscribersRef = useRef(new Map());
  
  // Connection states
  const [connections, setConnections] = useState({
    ib: { connected: false, lastCheck: null, reconnecting: false },
    websocket: { connected: false, lastCheck: null, reconnecting: false },
    mongodb: { connected: true, lastCheck: null },  // Assume connected initially
  });
  
  // Force re-render trigger
  const [, forceUpdate] = useState(0);

  /**
   * Load persistent data from localStorage on mount
   */
  useEffect(() => {
    PERSISTENT_KEYS.forEach(key => {
      try {
        const stored = localStorage.getItem(STORAGE_PREFIX + key);
        if (stored) {
          const { data, timestamp } = JSON.parse(stored);
          stateRef.current.set(key, data);
          timestampRef.current.set(key, timestamp);
        }
      } catch (e) {
        console.warn(`[AppState] Failed to load ${key} from storage:`, e);
      }
    });
    console.log('[AppState] Rehydrated from localStorage:', Array.from(stateRef.current.keys()));
  }, []);

  /**
   * Get data from state
   * Returns cached data immediately (stale-while-revalidate)
   */
  const getData = useCallback((key, defaultValue = null) => {
    return stateRef.current.get(key) ?? defaultValue;
  }, []);

  /**
   * Set data in state with automatic persistence
   */
  const setData = useCallback((key, data) => {
    const now = Date.now();
    stateRef.current.set(key, data);
    timestampRef.current.set(key, now);
    
    // Persist to localStorage if it's a persistent key
    if (PERSISTENT_KEYS.includes(key)) {
      try {
        localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify({
          data,
          timestamp: now
        }));
      } catch (e) {
        console.warn(`[AppState] Failed to persist ${key}:`, e);
      }
    }
    
    // Notify subscribers
    const subs = subscribersRef.current.get(key);
    if (subs) {
      subs.forEach(callback => callback(data));
    }
    
    // Trigger re-render for components using this data
    forceUpdate(n => n + 1);
  }, []);

  /**
   * Check if data is stale (past TTL)
   */
  const isStale = useCallback((key) => {
    const timestamp = timestampRef.current.get(key);
    if (!timestamp) return true;
    
    const ttl = DATA_TTL[key] || DATA_TTL.default;
    return Date.now() - timestamp > ttl;
  }, []);

  /**
   * Get data age in milliseconds
   */
  const getDataAge = useCallback((key) => {
    const timestamp = timestampRef.current.get(key);
    if (!timestamp) return Infinity;
    return Date.now() - timestamp;
  }, []);

  /**
   * Subscribe to data changes
   */
  const subscribe = useCallback((key, callback) => {
    if (!subscribersRef.current.has(key)) {
      subscribersRef.current.set(key, new Set());
    }
    subscribersRef.current.get(key).add(callback);
    
    // Return unsubscribe function
    return () => {
      subscribersRef.current.get(key)?.delete(callback);
    };
  }, []);

  /**
   * Batch update multiple keys
   */
  const batchUpdate = useCallback((updates) => {
    const now = Date.now();
    Object.entries(updates).forEach(([key, data]) => {
      stateRef.current.set(key, data);
      timestampRef.current.set(key, now);
      
      if (PERSISTENT_KEYS.includes(key)) {
        try {
          localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify({
            data,
            timestamp: now
          }));
        } catch (e) {
          // Ignore storage errors
        }
      }
    });
    forceUpdate(n => n + 1);
  }, []);

  /**
   * Clear specific key or all state
   */
  const clearData = useCallback((key = null) => {
    if (key) {
      stateRef.current.delete(key);
      timestampRef.current.delete(key);
      localStorage.removeItem(STORAGE_PREFIX + key);
    } else {
      stateRef.current.clear();
      timestampRef.current.clear();
      PERSISTENT_KEYS.forEach(k => localStorage.removeItem(STORAGE_PREFIX + k));
    }
    forceUpdate(n => n + 1);
  }, []);

  /**
   * Update connection state
   */
  const updateConnection = useCallback((type, state) => {
    setConnections(prev => ({
      ...prev,
      [type]: { ...prev[type], ...state, lastCheck: Date.now() }
    }));
  }, []);

  /**
   * Get all connection states
   */
  const getConnections = useCallback(() => connections, [connections]);

  /**
   * Check if any critical connection is down
   */
  const hasConnectionIssue = useCallback(() => {
    return !connections.ib.connected || !connections.websocket.connected;
  }, [connections]);

  return (
    <AppStateContext.Provider value={{
      // Data operations
      getData,
      setData,
      isStale,
      getDataAge,
      subscribe,
      batchUpdate,
      clearData,
      
      // Connection management
      connections,
      updateConnection,
      getConnections,
      hasConnectionIssue,
      
      // Constants
      DATA_TTL,
      PERSISTENT_KEYS
    }}>
      {children}
    </AppStateContext.Provider>
  );
};

/**
 * Hook to access app state
 */
export const useAppState = () => {
  const context = useContext(AppStateContext);
  if (!context) {
    console.warn('[useAppState] Used outside of AppStateProvider, returning stub');
    return {
      getData: () => null,
      setData: () => {},
      isStale: () => true,
      getDataAge: () => Infinity,
      subscribe: () => () => {},
      batchUpdate: () => {},
      clearData: () => {},
      connections: {},
      updateConnection: () => {},
      getConnections: () => ({}),
      hasConnectionIssue: () => false,
      DATA_TTL: {},
      PERSISTENT_KEYS: []
    };
  }
  return context;
};

/**
 * Hook for fetching data with caching
 * Implements stale-while-revalidate pattern
 */
export const useCachedData = (key, fetchFn, options = {}) => {
  const { getData, setData, isStale, getDataAge } = useAppState();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fetchingRef = useRef(false);
  
  const { 
    enabled = true,
    refetchInterval = null,  // Auto-refetch interval
    staleTime = null,        // Override default TTL
    onSuccess = null,
    onError = null
  } = options;

  // Get cached data immediately
  const cachedData = getData(key);
  const dataAge = getDataAge(key);
  const stale = staleTime ? dataAge > staleTime : isStale(key);

  // Fetch function with deduplication
  const refetch = useCallback(async (force = false) => {
    if (!enabled) return;
    if (fetchingRef.current && !force) return; // Prevent concurrent fetches
    
    // Don't fetch if data is fresh (unless forced)
    if (!force && !stale && cachedData !== null) {
      return cachedData;
    }
    
    fetchingRef.current = true;
    setLoading(true);
    setError(null);
    
    try {
      const data = await fetchFn();
      setData(key, data);
      onSuccess?.(data);
      return data;
    } catch (e) {
      console.error(`[useCachedData] Error fetching ${key}:`, e);
      setError(e);
      onError?.(e);
      // Return stale data on error (resilience)
      return cachedData;
    } finally {
      setLoading(false);
      fetchingRef.current = false;
    }
  }, [enabled, stale, cachedData, fetchFn, key, setData, onSuccess, onError]);

  // Initial fetch if stale
  useEffect(() => {
    if (enabled && (stale || cachedData === null)) {
      refetch();
    }
  }, [enabled]); // Only on mount/enabled change

  // Auto-refetch interval
  useEffect(() => {
    if (!enabled || !refetchInterval) return;
    
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') {
        refetch();
      }
    }, refetchInterval);
    
    return () => clearInterval(interval);
  }, [enabled, refetchInterval, refetch]);

  return {
    data: cachedData,
    loading: loading && cachedData === null, // Only show loading if no cached data
    isRefreshing: loading && cachedData !== null,
    error,
    isStale: stale,
    dataAge,
    refetch
  };
};

export default AppStateContext;
