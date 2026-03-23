/**
 * TrainingModeContext - Central control for training mode
 * 
 * When AI training is active, non-essential polling should be reduced/paused
 * to prevent browser resource exhaustion (ERR_INSUFFICIENT_RESOURCES) and
 * reduce backend load.
 * 
 * Usage:
 * - Components check `isTrainingActive` before starting polling
 * - Use `getPollingInterval(baseInterval)` to get adjusted interval
 * - Training components call `setTrainingActive(true/false)` 
 */

import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';

const TrainingModeContext = createContext(null);

// Polling multiplier when training is active (10x slower)
const TRAINING_SLOWDOWN_MULTIPLIER = 10;

// Minimum polling interval during training (60 seconds)
const MIN_TRAINING_INTERVAL = 60000;

// Maximum polling interval during training (5 minutes)
const MAX_TRAINING_INTERVAL = 300000;

export const TrainingModeProvider = ({ children }) => {
  // Core training state
  const [isTrainingActive, setIsTrainingActive] = useState(false);
  const [trainingType, setTrainingType] = useState(null); // 'full-universe', 'single', etc.
  const [trainingStartTime, setTrainingStartTime] = useState(null);
  const [trainingProgress, setTrainingProgress] = useState(null);
  
  // Track components that are currently polling
  const activePollers = useRef(new Set());
  
  // Subscribers to training state changes
  const subscribers = useRef(new Set());

  /**
   * Start training mode - all components will slow down polling
   */
  const startTraining = useCallback((type = 'unknown') => {
    console.log(`[TrainingMode] Starting training mode: ${type}`);
    setIsTrainingActive(true);
    setTrainingType(type);
    setTrainingStartTime(Date.now());
    
    // Notify all subscribers
    subscribers.current.forEach(cb => cb(true, type));
  }, []);

  /**
   * End training mode - components resume normal polling
   */
  const endTraining = useCallback(() => {
    console.log('[TrainingMode] Ending training mode');
    setIsTrainingActive(false);
    setTrainingType(null);
    setTrainingStartTime(null);
    setTrainingProgress(null);
    
    // Notify all subscribers
    subscribers.current.forEach(cb => cb(false, null));
  }, []);

  /**
   * Update training progress (for UI display)
   */
  const updateProgress = useCallback((progress) => {
    setTrainingProgress(progress);
  }, []);

  /**
   * Get adjusted polling interval based on training state
   * 
   * @param {number} baseInterval - Normal polling interval in ms
   * @param {boolean} isEssential - If true, less slowdown is applied
   * @returns {number} Adjusted interval
   */
  const getPollingInterval = useCallback((baseInterval, isEssential = false) => {
    if (!isTrainingActive) {
      return baseInterval;
    }
    
    // Essential polling gets 3x slowdown, non-essential gets 10x
    const multiplier = isEssential ? 3 : TRAINING_SLOWDOWN_MULTIPLIER;
    const adjusted = baseInterval * multiplier;
    
    // Clamp to reasonable bounds
    return Math.min(Math.max(adjusted, MIN_TRAINING_INTERVAL), MAX_TRAINING_INTERVAL);
  }, [isTrainingActive]);

  /**
   * Check if a component should poll right now
   * Returns false if training is active and component should skip this cycle
   */
  const shouldPoll = useCallback((componentId, isEssential = false) => {
    if (!isTrainingActive) {
      return true;
    }
    
    // Essential components always poll (but at reduced rate via getPollingInterval)
    if (isEssential) {
      return true;
    }
    
    // Non-essential components skip polling during training
    return false;
  }, [isTrainingActive]);

  /**
   * Register a polling component (for debugging/monitoring)
   */
  const registerPoller = useCallback((componentId) => {
    activePollers.current.add(componentId);
    return () => activePollers.current.delete(componentId);
  }, []);

  /**
   * Subscribe to training state changes
   */
  const subscribe = useCallback((callback) => {
    subscribers.current.add(callback);
    return () => subscribers.current.delete(callback);
  }, []);

  /**
   * Get current training stats
   */
  const getTrainingStats = useCallback(() => {
    return {
      isActive: isTrainingActive,
      type: trainingType,
      startTime: trainingStartTime,
      elapsedMs: trainingStartTime ? Date.now() - trainingStartTime : 0,
      progress: trainingProgress,
      activePollers: Array.from(activePollers.current),
    };
  }, [isTrainingActive, trainingType, trainingStartTime, trainingProgress]);

  // Auto-check training status from backend periodically
  useEffect(() => {
    const checkTrainingStatus = async () => {
      try {
        const response = await fetch('/api/ai-modules/timeseries/training-status');
        const data = await response.json();
        
        if (data.success && data.training_mode) {
          const backendActive = data.training_mode.training_active;
          
          // Sync with backend state
          if (backendActive && !isTrainingActive) {
            startTraining(data.training_mode.training_type || 'backend');
          } else if (!backendActive && isTrainingActive) {
            endTraining();
          }
        }
      } catch (e) {
        // Silent fail - this is just a sync check
      }
    };

    // Check immediately and then every 30 seconds
    checkTrainingStatus();
    const interval = setInterval(checkTrainingStatus, 30000);
    
    return () => clearInterval(interval);
  }, [isTrainingActive, startTraining, endTraining]);

  return (
    <TrainingModeContext.Provider value={{
      // State
      isTrainingActive,
      trainingType,
      trainingProgress,
      
      // Actions
      startTraining,
      endTraining,
      updateProgress,
      
      // Helpers
      getPollingInterval,
      shouldPoll,
      registerPoller,
      subscribe,
      getTrainingStats,
    }}>
      {children}
    </TrainingModeContext.Provider>
  );
};

/**
 * Hook to access training mode context
 */
export const useTrainingMode = () => {
  const context = useContext(TrainingModeContext);
  if (!context) {
    // Return a default implementation if not wrapped in provider
    // This prevents crashes during initial setup
    return {
      isTrainingActive: false,
      trainingType: null,
      trainingProgress: null,
      startTraining: () => {},
      endTraining: () => {},
      updateProgress: () => {},
      getPollingInterval: (base) => base,
      shouldPoll: () => true,
      registerPoller: () => () => {},
      subscribe: () => () => {},
      getTrainingStats: () => ({ isActive: false }),
    };
  }
  return context;
};

/**
 * Hook for components that poll - automatically adjusts interval during training
 * 
 * @param {Function} callback - Function to call on each poll
 * @param {number} baseInterval - Normal polling interval in ms
 * @param {Object} options - { componentId, isEssential, enabled }
 */
export const useTrainingAwarePolling = (callback, baseInterval, options = {}) => {
  const { componentId = 'unknown', isEssential = false, enabled = true } = options;
  const { getPollingInterval, shouldPoll, registerPoller, isTrainingActive } = useTrainingMode();
  
  const intervalRef = useRef(null);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    // Register this poller
    const unregister = registerPoller(componentId);
    
    return () => {
      unregister();
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [componentId, registerPoller]);

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

    // Get adjusted interval
    const interval = getPollingInterval(baseInterval, isEssential);
    
    // Create poll function
    const poll = () => {
      if (shouldPoll(componentId, isEssential)) {
        callbackRef.current();
      }
    };

    // Initial poll
    poll();

    // Set up interval
    intervalRef.current = setInterval(poll, interval);

    // Log interval change during training
    if (isTrainingActive) {
      console.log(`[TrainingMode] ${componentId}: interval ${baseInterval}ms -> ${interval}ms`);
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [enabled, baseInterval, isEssential, componentId, getPollingInterval, shouldPoll, isTrainingActive]);
};

export default TrainingModeContext;
