/**
 * FocusModeContext - Unified Resource Prioritization System (Frontend)
 * 
 * Manages system focus modes to optimize resources:
 * - LIVE: Normal trading operations (default)
 * - COLLECTING: Historical data collection priority
 * - TRAINING: AI model training priority
 * - BACKTESTING: Simulation/backtest priority
 * 
 * When a focus mode is active:
 * - Non-essential polling is paused or throttled
 * - UI shows appropriate status indicators
 * - Progress is tracked and displayed
 * 
 * This extends and replaces TrainingModeContext with a more comprehensive solution.
 */

import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import api from '../utils/api';

const FocusModeContext = createContext(null);

// Focus mode definitions
export const FOCUS_MODES = {
  live: {
    id: 'live',
    label: 'Live Trading',
    shortLabel: 'Live',
    icon: '📊',
    color: 'text-green-400',
    bgColor: 'bg-green-500/20',
    borderColor: 'border-green-500/30',
    description: 'Normal trading operations'
  },
  collecting: {
    id: 'collecting',
    label: 'Data Collection',
    shortLabel: 'Collecting',
    icon: '📥',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/20',
    borderColor: 'border-blue-500/30',
    description: 'Historical data collection priority'
  },
  training: {
    id: 'training',
    label: 'AI Training',
    shortLabel: 'Training',
    icon: '🧠',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/20',
    borderColor: 'border-purple-500/30',
    description: 'AI model training priority'
  },
  backtesting: {
    id: 'backtesting',
    label: 'Backtesting',
    shortLabel: 'Backtest',
    icon: '🔬',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/20',
    borderColor: 'border-amber-500/30',
    description: 'Running simulations'
  }
};

// Polling multipliers for each mode (1.0 = normal, higher = slower)
const MODE_POLLING_MULTIPLIERS = {
  live: {
    default: 1.0,
    essential: 1.0,
    background: 1.0
  },
  collecting: {
    default: 5.0,    // 5x slower
    essential: 2.0,  // 2x slower
    background: 10.0 // 10x slower (nearly paused)
  },
  training: {
    default: 10.0,   // 10x slower
    essential: 3.0,  // 3x slower
    background: null // Paused
  },
  backtesting: {
    default: null,   // Paused
    essential: 5.0,  // 5x slower
    background: null // Paused
  }
};

export const FocusModeProvider = ({ children }) => {
  // Core state
  const [focusMode, setFocusMode] = useState('live');
  const [modeStartTime, setModeStartTime] = useState(null);
  const [modeContext, setModeContext] = useState({});
  const [activeJobId, setActiveJobId] = useState(null);
  
  // Progress tracking
  const [progress, setProgress] = useState({
    percent: 0,
    message: '',
    currentStep: 0,
    totalSteps: 0,
    details: {}
  });
  
  // Loading state for mode changes
  const [isChangingMode, setIsChangingMode] = useState(false);
  
  // Subscribers for mode changes
  const subscribers = useRef(new Set());
  
  // Persist mode to localStorage
  useEffect(() => {
    const stored = localStorage.getItem('sentcom_focus_mode');
    if (stored) {
      try {
        const data = JSON.parse(stored);
        // Only restore non-live modes if they were recent (last 30 minutes)
        if (data.mode !== 'live' && data.timestamp) {
          const elapsed = Date.now() - data.timestamp;
          if (elapsed < 30 * 60 * 1000) {
            setFocusMode(data.mode);
            setModeStartTime(data.startTime ? new Date(data.startTime) : null);
            setModeContext(data.context || {});
          }
        }
      } catch (e) {
        console.warn('[FocusMode] Failed to restore state:', e);
      }
    }
  }, []);
  
  // Save mode to localStorage when it changes
  useEffect(() => {
    localStorage.setItem('sentcom_focus_mode', JSON.stringify({
      mode: focusMode,
      startTime: modeStartTime?.toISOString(),
      context: modeContext,
      timestamp: Date.now()
    }));
  }, [focusMode, modeStartTime, modeContext]);
  
  /**
   * Set the focus mode
   */
  const setMode = useCallback(async (mode, context = {}, jobId = null) => {
    if (!FOCUS_MODES[mode]) {
      console.error(`[FocusMode] Invalid mode: ${mode}`);
      return { success: false, error: `Invalid mode: ${mode}` };
    }
    
    const oldMode = focusMode;
    
    console.log(`[FocusMode] Changing: ${oldMode} -> ${mode}`);
    setIsChangingMode(true);
    
    try {
      // Notify backend - use un-throttled fetch for instant response
      // Mode switches are user-initiated actions that should never queue behind polling
      const directFetch = window.fetch;
      const API_URL = process.env.REACT_APP_BACKEND_URL || '';
      const res = await directFetch(`${API_URL}/api/focus-mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, context, job_id: jobId })
      });
      const response = { data: await res.json() };
      
      if (response.data?.success) {
        setFocusMode(mode);
        setModeStartTime(mode !== 'live' ? new Date() : null);
        setModeContext(context);
        setActiveJobId(jobId);
        
        // Reset progress when changing modes
        setProgress({
          percent: 0,
          message: `Starting ${FOCUS_MODES[mode].label}...`,
          currentStep: 0,
          totalSteps: 0,
          details: {}
        });
        
        // Notify subscribers
        subscribers.current.forEach(cb => {
          try {
            cb(oldMode, mode, context);
          } catch (e) {
            console.error('[FocusMode] Subscriber error:', e);
          }
        });
        
        console.log(`[FocusMode] Changed to ${mode}`, response.data);
        return { success: true, ...response.data };
      }
      
      return { success: false, error: 'Failed to set mode' };
    } catch (e) {
      console.error('[FocusMode] Error setting mode:', e);
      return { success: false, error: e.message };
    } finally {
      setIsChangingMode(false);
    }
  }, [focusMode]);
  
  /**
   * Reset to live mode
   */
  const resetToLive = useCallback(async (result = null) => {
    console.log('[FocusMode] Resetting to live mode');
    const response = await setMode('live');
    if (result) {
      response.completedTaskResult = result;
    }
    return response;
  }, [setMode]);
  
  /**
   * Update progress for the current task
   */
  const updateProgress = useCallback((updates) => {
    setProgress(prev => ({
      ...prev,
      ...updates,
      details: {
        ...prev.details,
        ...(updates.details || {})
      }
    }));
  }, []);
  
  /**
   * Get polling interval multiplier for current mode
   */
  const getPollingMultiplier = useCallback((category = 'default') => {
    const multipliers = MODE_POLLING_MULTIPLIERS[focusMode] || MODE_POLLING_MULTIPLIERS.live;
    return multipliers[category] ?? multipliers.default ?? 1.0;
  }, [focusMode]);
  
  /**
   * Get adjusted polling interval
   */
  const getAdjustedInterval = useCallback((baseInterval, category = 'default') => {
    const multiplier = getPollingMultiplier(category);
    if (multiplier === null) {
      return null; // Paused
    }
    return Math.round(baseInterval * multiplier);
  }, [getPollingMultiplier]);
  
  /**
   * Check if polling should run for a category
   */
  const shouldPoll = useCallback((category = 'default') => {
    const multiplier = getPollingMultiplier(category);
    return multiplier !== null;
  }, [getPollingMultiplier]);
  
  /**
   * Check if currently in a focus mode (not live)
   */
  const isInFocusMode = useCallback(() => {
    return focusMode !== 'live';
  }, [focusMode]);
  
  /**
   * Get elapsed time in current mode
   */
  const getElapsedTime = useCallback(() => {
    if (!modeStartTime) return 0;
    return Math.floor((Date.now() - modeStartTime.getTime()) / 1000);
  }, [modeStartTime]);
  
  /**
   * Subscribe to mode changes
   */
  const subscribe = useCallback((callback) => {
    subscribers.current.add(callback);
    return () => subscribers.current.delete(callback);
  }, []);
  
  /**
   * Get current status object
   */
  const getStatus = useCallback(() => {
    return {
      mode: focusMode,
      modeConfig: FOCUS_MODES[focusMode],
      isLive: focusMode === 'live',
      startTime: modeStartTime,
      elapsedSeconds: getElapsedTime(),
      context: modeContext,
      jobId: activeJobId,
      progress,
      isChangingMode
    };
  }, [focusMode, modeStartTime, getElapsedTime, modeContext, activeJobId, progress, isChangingMode]);
  
  // Sync with backend periodically
  useEffect(() => {
    const syncWithBackend = async () => {
      try {
        const response = await api.get('/api/focus-mode');
        if (response.data?.success) {
          const backendMode = response.data.mode;
          
          // If backend is in a different mode, sync to it
          if (backendMode && backendMode !== focusMode) {
            console.log(`[FocusMode] Syncing with backend: ${focusMode} -> ${backendMode}`);
            setFocusMode(backendMode);
            if (response.data.start_time) {
              setModeStartTime(new Date(response.data.start_time));
            }
            if (response.data.context) {
              setModeContext(response.data.context);
            }
            if (response.data.job_id) {
              setActiveJobId(response.data.job_id);
            }
            if (response.data.progress) {
              setProgress(prev => ({
                ...prev,
                ...response.data.progress
              }));
            }
          }
        }
      } catch (e) {
        // Silent fail for sync
      }
    };
    
    // Delay initial sync to let startup modal finish first
    const initialDelay = setTimeout(syncWithBackend, 5000);
    
    // Sync every 5 seconds — focus mode is now auto-managed by backend
    // (training/backtest/collection auto-activate, job completion auto-restores)
    const interval = setInterval(syncWithBackend, 5000);
    return () => {
      clearTimeout(initialDelay);
      clearInterval(interval);
    };
  }, [focusMode]);
  
  return (
    <FocusModeContext.Provider value={{
      // State
      focusMode,
      modeConfig: FOCUS_MODES[focusMode],
      isLive: focusMode === 'live',
      isInFocusMode,
      modeStartTime,
      modeContext,
      activeJobId,
      progress,
      isChangingMode,
      
      // Actions
      setMode,
      resetToLive,
      updateProgress,
      
      // Polling helpers
      getPollingMultiplier,
      getAdjustedInterval,
      shouldPoll,
      getElapsedTime,
      
      // Utilities
      subscribe,
      getStatus,
      
      // Constants
      FOCUS_MODES
    }}>
      {children}
    </FocusModeContext.Provider>
  );
};

/**
 * Hook to access focus mode context
 */
export const useFocusMode = () => {
  const context = useContext(FocusModeContext);
  if (!context) {
    // Return safe defaults if not wrapped in provider
    return {
      focusMode: 'live',
      modeConfig: FOCUS_MODES.live,
      isLive: true,
      isInFocusMode: () => false,
      modeStartTime: null,
      modeContext: {},
      activeJobId: null,
      progress: { percent: 0, message: '' },
      isChangingMode: false,
      setMode: async () => ({ success: false }),
      resetToLive: async () => ({ success: false }),
      updateProgress: () => {},
      getPollingMultiplier: () => 1.0,
      getAdjustedInterval: (base) => base,
      shouldPoll: () => true,
      getElapsedTime: () => 0,
      subscribe: () => () => {},
      getStatus: () => ({ mode: 'live', isLive: true }),
      FOCUS_MODES
    };
  }
  return context;
};

/**
 * Hook for focus-aware polling
 * Automatically adjusts interval based on current focus mode
 */
export const useFocusAwarePolling = (callback, baseInterval, options = {}) => {
  const { category = 'default', enabled = true, componentId = 'unknown' } = options;
  const { getAdjustedInterval, shouldPoll, focusMode } = useFocusMode();
  
  const intervalRef = useRef(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  
  useEffect(() => {
    if (!enabled) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }
    
    // Clear existing interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }
    
    // Check if we should poll at all
    if (!shouldPoll(category)) {
      console.log(`[FocusMode] ${componentId}: Polling paused in ${focusMode} mode`);
      return;
    }
    
    // Get adjusted interval
    const adjustedInterval = getAdjustedInterval(baseInterval, category);
    
    if (adjustedInterval === null) {
      console.log(`[FocusMode] ${componentId}: Polling disabled`);
      return;
    }
    
    // Log interval change
    if (adjustedInterval !== baseInterval) {
      console.log(`[FocusMode] ${componentId}: Interval ${baseInterval}ms -> ${adjustedInterval}ms`);
    }
    
    // Initial poll
    callbackRef.current();
    
    // Set up interval
    intervalRef.current = setInterval(() => {
      callbackRef.current();
    }, adjustedInterval);
    
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [enabled, baseInterval, category, focusMode, getAdjustedInterval, shouldPoll, componentId]);
};

export default FocusModeContext;
