/**
 * useSmartPolling - Visibility-aware, consolidated polling
 * =========================================================
 * 
 * Features:
 * 1. Pauses when tab is hidden (saves resources)
 * 2. Resumes immediately when tab becomes visible
 * 3. Deduplicates concurrent requests
 * 4. Respects Focus Mode (pauses/slows polling based on mode)
 * 5. Exponential backoff on errors
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { useFocusMode } from '../contexts';

/**
 * Smart polling hook - Focus Mode aware
 * 
 * @param {Function} fetchFn - Async function to call
 * @param {number} interval - Polling interval in ms
 * @param {Object} options - { enabled, category, onSuccess, onError, immediate, componentId }
 */
export const useSmartPolling = (fetchFn, interval, options = {}) => {
  const {
    enabled = true,
    category = 'default',  // 'essential', 'default', or 'background'
    onSuccess = null,
    onError = null,
    immediate = true,     // Fetch immediately on mount
    componentId = 'unknown' // For logging
  } = options;

  const { getAdjustedInterval, shouldPoll, focusMode, isLive } = useFocusMode();
  
  const [isPolling, setIsPolling] = useState(false);
  const [lastPollTime, setLastPollTime] = useState(null);
  const [error, setError] = useState(null);
  const [consecutiveErrors, setConsecutiveErrors] = useState(0);
  
  const timerRef = useRef(null);
  const fetchingRef = useRef(false);
  const mountedRef = useRef(true);
  const visibleRef = useRef(document.visibilityState === 'visible');

  /**
   * Execute the fetch with error handling
   */
  const executeFetch = useCallback(async () => {
    // Skip if already fetching (deduplication)
    if (fetchingRef.current) return;
    
    // Skip if tab is hidden (unless essential category)
    if (!visibleRef.current && category !== 'essential') return;
    
    // Skip if polling is paused for this category in current focus mode
    if (!shouldPoll(category)) {
      return;
    }
    
    fetchingRef.current = true;
    setIsPolling(true);
    
    try {
      const result = await fetchFn();
      
      if (mountedRef.current) {
        setError(null);
        setConsecutiveErrors(0);
        setLastPollTime(Date.now());
        onSuccess?.(result);
      }
    } catch (e) {
      if (mountedRef.current) {
        setError(e);
        setConsecutiveErrors(prev => prev + 1);
        onError?.(e);
      }
    } finally {
      if (mountedRef.current) {
        fetchingRef.current = false;
        setIsPolling(false);
      }
    }
  }, [fetchFn, category, shouldPoll, onSuccess, onError]);

  /**
   * Calculate effective interval with backoff on errors
   */
  const getEffectiveInterval = useCallback(() => {
    // Get interval adjusted for current focus mode
    let effectiveInterval = getAdjustedInterval(interval, category);
    
    // If null, polling is paused
    if (effectiveInterval === null) {
      return null;
    }
    
    // Apply exponential backoff on consecutive errors (max 5x slowdown)
    if (consecutiveErrors > 0) {
      const backoffMultiplier = Math.min(Math.pow(1.5, consecutiveErrors), 5);
      effectiveInterval = effectiveInterval * backoffMultiplier;
    }
    
    return effectiveInterval;
  }, [interval, category, getAdjustedInterval, consecutiveErrors]);

  /**
   * Start polling timer
   */
  const startPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
    }
    
    const effectiveInterval = getEffectiveInterval();
    
    // If null, polling is paused
    if (effectiveInterval === null) {
      console.log(`[SmartPolling] ${componentId}: Polling paused in ${focusMode} mode`);
      return;
    }
    
    // Log interval change if not in live mode
    if (!isLive && effectiveInterval !== interval) {
      console.log(`[SmartPolling] ${componentId}: Interval ${interval}ms -> ${effectiveInterval}ms (${focusMode} mode)`);
    }
    
    timerRef.current = setInterval(() => {
      executeFetch();
    }, effectiveInterval);
    
  }, [executeFetch, getEffectiveInterval, componentId, focusMode, isLive, interval]);

  /**
   * Handle visibility changes
   */
  useEffect(() => {
    const handleVisibilityChange = () => {
      visibleRef.current = document.visibilityState === 'visible';
      
      if (visibleRef.current && enabled) {
        // Tab became visible - fetch immediately and restart polling
        executeFetch();
        startPolling();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [enabled, executeFetch, startPolling]);

  /**
   * Main effect - start/stop polling
   */
  useEffect(() => {
    mountedRef.current = true;
    
    if (!enabled) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    
    // Immediate fetch on mount
    if (immediate) {
      executeFetch();
    }
    
    // Start polling
    startPolling();
    
    return () => {
      mountedRef.current = false;
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, immediate, executeFetch, startPolling]);

  /**
   * Restart polling when focus mode changes or error count changes
   */
  useEffect(() => {
    if (enabled && timerRef.current) {
      startPolling();
    }
  }, [focusMode, consecutiveErrors, enabled, startPolling]);

  /**
   * Manual trigger
   */
  const poll = useCallback(() => {
    executeFetch();
  }, [executeFetch]);

  return {
    isPolling,
    lastPollTime,
    error,
    consecutiveErrors,
    poll,  // Manual trigger
    effectiveInterval: getEffectiveInterval()
  };
};

/**
 * Hook for one-time fetch with caching
 * Doesn't poll, just fetches once and caches
 */
export const useFetchOnce = (fetchFn, options = {}) => {
  const { enabled = true, cacheKey = null } = options;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (!enabled || fetchedRef.current) return;
    
    const doFetch = async () => {
      setLoading(true);
      try {
        const result = await fetchFn();
        setData(result);
        fetchedRef.current = true;
      } catch (e) {
        setError(e);
      } finally {
        setLoading(false);
      }
    };
    
    doFetch();
  }, [enabled, fetchFn]);

  const refetch = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchFn();
      setData(result);
      return result;
    } catch (e) {
      setError(e);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [fetchFn]);

  return { data, loading, error, refetch };
};

export default useSmartPolling;
