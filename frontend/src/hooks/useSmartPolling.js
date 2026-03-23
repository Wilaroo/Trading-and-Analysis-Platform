/**
 * useSmartPolling - Visibility-aware, consolidated polling
 * =========================================================
 * 
 * Features:
 * 1. Pauses when tab is hidden (saves resources)
 * 2. Resumes immediately when tab becomes visible
 * 3. Deduplicates concurrent requests
 * 4. Respects training mode (slower polling)
 * 5. Exponential backoff on errors
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { useTrainingMode } from '../contexts';

/**
 * Smart polling hook
 * 
 * @param {Function} fetchFn - Async function to call
 * @param {number} interval - Polling interval in ms
 * @param {Object} options - { enabled, isEssential, onSuccess, onError, immediate }
 */
export const useSmartPolling = (fetchFn, interval, options = {}) => {
  const {
    enabled = true,
    isEssential = false,  // Essential polls continue during training (but slower)
    onSuccess = null,
    onError = null,
    immediate = true,     // Fetch immediately on mount
    key = 'default'       // For deduplication
  } = options;

  const { getPollingInterval, isTrainingActive } = useTrainingMode();
  
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
    
    // Skip if tab is hidden (unless essential)
    if (!visibleRef.current && !isEssential) return;
    
    // Skip non-essential polling during training
    if (isTrainingActive && !isEssential) return;
    
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
  }, [fetchFn, isEssential, isTrainingActive, onSuccess, onError]);

  /**
   * Calculate effective interval with backoff on errors
   */
  const getEffectiveInterval = useCallback(() => {
    // Base interval (may be slowed during training)
    let effectiveInterval = getPollingInterval(interval, isEssential);
    
    // Apply exponential backoff on consecutive errors (max 5x slowdown)
    if (consecutiveErrors > 0) {
      const backoffMultiplier = Math.min(Math.pow(1.5, consecutiveErrors), 5);
      effectiveInterval = effectiveInterval * backoffMultiplier;
    }
    
    return effectiveInterval;
  }, [interval, isEssential, getPollingInterval, consecutiveErrors]);

  /**
   * Start polling timer
   */
  const startPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
    }
    
    const effectiveInterval = getEffectiveInterval();
    
    timerRef.current = setInterval(() => {
      executeFetch();
    }, effectiveInterval);
    
  }, [executeFetch, getEffectiveInterval]);

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
   * Restart polling when interval changes (e.g., training mode changes)
   */
  useEffect(() => {
    if (enabled && timerRef.current) {
      startPolling();
    }
  }, [isTrainingActive, consecutiveErrors]);

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
