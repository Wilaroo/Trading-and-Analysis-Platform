/**
 * TrainingModeContext - DEPRECATED - Thin wrapper around FocusModeContext
 * 
 * This context is maintained for backwards compatibility.
 * New components should use `useFocusMode` from FocusModeContext directly.
 * 
 * The actual polling logic and mode management is now handled by FocusModeContext.
 */

import React, { createContext, useContext, useCallback, useEffect } from 'react';
import { useFocusMode, FOCUS_MODES } from './FocusModeContext';
import { setTrainingActive } from '../utils/safePolling';

const TrainingModeContext = createContext(null);

export const TrainingModeProvider = ({ children }) => {
  // Delegate to FocusModeContext
  const focusMode = useFocusMode();
  
  // Map training mode to focus mode
  const isTrainingActive = focusMode.focusMode === 'training';
  const trainingType = isTrainingActive ? focusMode.modeContext?.trainingType : null;
  const trainingProgress = focusMode.progress;

  // Sync the global safePolling flag with training state
  useEffect(() => {
    setTrainingActive(isTrainingActive);
    return () => setTrainingActive(false);
  }, [isTrainingActive]);

  /**
   * Start training mode - sets focus mode to 'training'
   */
  const startTraining = useCallback(async (type = 'unknown') => {
    console.log(`[TrainingMode] Starting training mode: ${type}`);
    await focusMode.setMode('training', { trainingType: type });
  }, [focusMode]);

  /**
   * End training mode - resets to 'live' mode
   */
  const endTraining = useCallback(async () => {
    console.log('[TrainingMode] Ending training mode');
    await focusMode.resetToLive();
  }, [focusMode]);

  /**
   * Update training progress
   */
  const updateProgress = useCallback((progress) => {
    focusMode.updateProgress(progress);
  }, [focusMode]);

  /**
   * Get adjusted polling interval based on focus mode
   * Maps the old API to the new FocusMode API
   */
  const getPollingInterval = useCallback((baseInterval, isEssential = false) => {
    const category = isEssential ? 'essential' : 'default';
    const adjusted = focusMode.getAdjustedInterval(baseInterval, category);
    return adjusted === null ? 300000 : adjusted; // Return 5 min if paused (backwards compat)
  }, [focusMode]);

  /**
   * Check if a component should poll right now
   */
  const shouldPoll = useCallback((componentId, isEssential = false) => {
    const category = isEssential ? 'essential' : 'default';
    return focusMode.shouldPoll(category);
  }, [focusMode]);

  /**
   * Register a polling component (stub for backwards compat)
   */
  const registerPoller = useCallback((componentId) => {
    // No-op in new architecture
    return () => {};
  }, []);

  /**
   * Subscribe to training state changes
   */
  const subscribe = useCallback((callback) => {
    return focusMode.subscribe((oldMode, newMode, context) => {
      const wasTraining = oldMode === 'training';
      const isTraining = newMode === 'training';
      if (wasTraining !== isTraining) {
        callback(isTraining, context?.trainingType);
      }
    });
  }, [focusMode]);

  /**
   * Get current training stats
   */
  const getTrainingStats = useCallback(() => {
    return {
      isActive: isTrainingActive,
      type: trainingType,
      startTime: focusMode.modeStartTime,
      elapsedMs: focusMode.getElapsedTime() * 1000,
      progress: trainingProgress,
      activePollers: [],
    };
  }, [isTrainingActive, trainingType, focusMode, trainingProgress]);

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
 * @deprecated Use useFocusMode from FocusModeContext instead
 */
export const useTrainingMode = () => {
  const context = useContext(TrainingModeContext);
  if (!context) {
    // Return a default implementation if not wrapped in provider
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
 * @deprecated Use useFocusAwarePolling from FocusModeContext instead
 */
export const useTrainingAwarePolling = (callback, baseInterval, options = {}) => {
  const { componentId = 'unknown', isEssential = false, enabled = true } = options;
  const { getPollingInterval, shouldPoll, isTrainingActive } = useTrainingMode();
  
  useEffect(() => {
    if (!enabled) return;

    // Get adjusted interval
    const interval = getPollingInterval(baseInterval, isEssential);
    
    // Create poll function
    const poll = () => {
      if (shouldPoll(componentId, isEssential)) {
        callback();
      }
    };

    // Initial poll
    poll();

    // Set up interval
    const intervalId = setInterval(poll, interval);

    // Log interval change during training
    if (isTrainingActive) {
      console.log(`[TrainingMode] ${componentId}: interval ${baseInterval}ms -> ${interval}ms`);
    }

    return () => clearInterval(intervalId);
  }, [enabled, baseInterval, isEssential, componentId, getPollingInterval, shouldPoll, isTrainingActive, callback]);
};

export default TrainingModeContext;
