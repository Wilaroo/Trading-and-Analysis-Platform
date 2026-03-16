/**
 * DataCacheContext - Persistent data cache for tab switching
 * 
 * This context maintains data across tab switches to prevent
 * re-fetching all data when users navigate between Command Center and NIA.
 * 
 * Features:
 * - Persists data across tab switches (no remount)
 * - Time-based cache expiration
 * - Stale-while-revalidate pattern
 * - Background refresh when returning to a tab
 */

import React, { createContext, useContext, useState, useCallback, useRef } from 'react';

const DataCacheContext = createContext(null);

// Cache entry structure
const createCacheEntry = (data, ttlMs = 30000) => ({
  data,
  timestamp: Date.now(),
  ttlMs,
  isStale: false,
});

export const DataCacheProvider = ({ children }) => {
  // Cache storage for different data types
  const [cache, setCache] = useState({
    // Command Center / SentCom data
    sentcomStatus: null,
    sentcomPositions: null,
    sentcomSetups: null,
    sentcomAlerts: null,
    sentcomStream: null,
    botStatus: null,
    
    // NIA data
    niaOverview: null,
    niaLearningProgress: null,
    niaPromotionCandidates: null,
    niaSimulationJobs: null,
    niaReportCard: null,
    niaCollectionStats: null,
  });
  
  // Track last active tab to know when to refresh
  const lastActiveTab = useRef(null);
  
  // Get cached data if not expired
  const getCached = useCallback((key) => {
    const entry = cache[key];
    if (!entry) return null;
    
    const age = Date.now() - entry.timestamp;
    if (age > entry.ttlMs) {
      // Mark as stale but still return data (stale-while-revalidate)
      return { ...entry, isStale: true };
    }
    return entry;
  }, [cache]);
  
  // Set cache data
  const setCached = useCallback((key, data, ttlMs = 30000) => {
    setCache(prev => ({
      ...prev,
      [key]: createCacheEntry(data, ttlMs),
    }));
  }, []);
  
  // Batch set multiple cache entries
  const setCachedBatch = useCallback((updates) => {
    setCache(prev => {
      const newCache = { ...prev };
      Object.entries(updates).forEach(([key, { data, ttlMs = 30000 }]) => {
        newCache[key] = createCacheEntry(data, ttlMs);
      });
      return newCache;
    });
  }, []);
  
  // Clear specific cache entries
  const clearCache = useCallback((keys) => {
    if (!keys) {
      // Clear all
      setCache({
        sentcomStatus: null,
        sentcomPositions: null,
        sentcomSetups: null,
        sentcomAlerts: null,
        sentcomStream: null,
        botStatus: null,
        niaOverview: null,
        niaLearningProgress: null,
        niaPromotionCandidates: null,
        niaSimulationJobs: null,
        niaReportCard: null,
        niaCollectionStats: null,
      });
    } else {
      setCache(prev => {
        const newCache = { ...prev };
        keys.forEach(key => { newCache[key] = null; });
        return newCache;
      });
    }
  }, []);
  
  // Check if we need to refresh data when switching tabs
  const shouldRefresh = useCallback((currentTab) => {
    const changed = lastActiveTab.current !== currentTab;
    lastActiveTab.current = currentTab;
    return changed;
  }, []);
  
  // Get cache age for a key (for UI display)
  const getCacheAge = useCallback((key) => {
    const entry = cache[key];
    if (!entry) return null;
    return Math.floor((Date.now() - entry.timestamp) / 1000); // seconds
  }, [cache]);
  
  return (
    <DataCacheContext.Provider value={{
      getCached,
      setCached,
      setCachedBatch,
      clearCache,
      shouldRefresh,
      getCacheAge,
      cache, // Direct access for debugging
    }}>
      {children}
    </DataCacheContext.Provider>
  );
};

export const useDataCache = () => {
  const context = useContext(DataCacheContext);
  if (!context) {
    throw new Error('useDataCache must be used within a DataCacheProvider');
  }
  return context;
};

/**
 * Hook for cached API fetching with stale-while-revalidate pattern
 * 
 * @param {string} cacheKey - Key to store data under
 * @param {Function} fetchFn - Async function to fetch data
 * @param {Object} options - { ttlMs, pollInterval, enabled }
 */
export const useCachedFetch = (cacheKey, fetchFn, options = {}) => {
  const { ttlMs = 30000, pollInterval = null, enabled = true } = options;
  const { getCached, setCached } = useDataCache();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);
  
  // Get cached data immediately
  const cached = getCached(cacheKey);
  const data = cached?.data ?? null;
  const isStale = cached?.isStale ?? true;
  
  // Fetch function that updates cache
  const refresh = useCallback(async (force = false) => {
    if (!enabled) return;
    
    // Skip if we have fresh data and not forcing
    if (!force && cached && !cached.isStale) {
      return cached.data;
    }
    
    setLoading(true);
    setError(null);
    
    try {
      const result = await fetchFn();
      setCached(cacheKey, result, ttlMs);
      return result;
    } catch (err) {
      setError(err);
      console.error(`Cache fetch error for ${cacheKey}:`, err);
      return null;
    } finally {
      setLoading(false);
    }
  }, [cacheKey, fetchFn, ttlMs, enabled, cached, setCached]);
  
  // Setup polling if interval provided
  React.useEffect(() => {
    if (!enabled) return;
    
    // Initial fetch if no cached data
    if (!cached) {
      refresh();
    } else if (cached.isStale) {
      // Background refresh if stale
      refresh();
    }
    
    // Setup polling
    if (pollInterval) {
      intervalRef.current = setInterval(() => refresh(), pollInterval);
    }
    
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [enabled, pollInterval, refresh, cached]);
  
  return {
    data,
    loading: loading && !data, // Only show loading if no cached data
    refreshing: loading && !!data, // Show refreshing if we have cached data
    error,
    isStale,
    refresh,
  };
};

export default DataCacheContext;
