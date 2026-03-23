/**
 * StartupManager - Staged/Tiered Application Loading
 * 
 * Controls what features load and when to prevent backend overload.
 * Features are grouped into waves that load progressively.
 * 
 * Wave 1 (0s):   Core - Health, Auth, Positions
 * Wave 2 (5s):   Trading - Scanner, Alerts, Market Data
 * Wave 3 (15s):  AI - Status indicators, Debate advisor
 * Wave 4 (30s):  Analytics - Report card, Learning connectors
 * Wave 5 (60s):  Background - Historical data, Simulation jobs
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';

// Wave configuration
const STARTUP_WAVES = {
  CORE: { wave: 1, delay: 0, label: 'Core Systems' },
  TRADING: { wave: 2, delay: 5000, label: 'Trading Features' },
  AI: { wave: 3, delay: 15000, label: 'AI Systems' },
  ANALYTICS: { wave: 4, delay: 30000, label: 'Analytics' },
  BACKGROUND: { wave: 5, delay: 60000, label: 'Background Services' },
};

// Feature to wave mapping
const FEATURE_WAVES = {
  // Wave 1 - Core (immediate)
  'health': STARTUP_WAVES.CORE,
  'auth': STARTUP_WAVES.CORE,
  'positions': STARTUP_WAVES.CORE,
  'websocket': STARTUP_WAVES.CORE,
  'focus-mode': STARTUP_WAVES.CORE,
  
  // Wave 2 - Trading (5s delay)
  'scanner': STARTUP_WAVES.TRADING,
  'alerts': STARTUP_WAVES.TRADING,
  'market-data': STARTUP_WAVES.TRADING,
  'sentcom-status': STARTUP_WAVES.TRADING,
  'sentcom-stream': STARTUP_WAVES.TRADING,
  'setups': STARTUP_WAVES.TRADING,
  'dynamic-risk': STARTUP_WAVES.TRADING,
  
  // Wave 3 - AI (15s delay)
  'ai-status': STARTUP_WAVES.AI,
  'ai-debate': STARTUP_WAVES.AI,
  'ai-timeseries': STARTUP_WAVES.AI,
  'ollama': STARTUP_WAVES.AI,
  'ib-status': STARTUP_WAVES.AI,
  
  // Wave 4 - Analytics (30s delay)
  'report-card': STARTUP_WAVES.ANALYTICS,
  'learning-connectors': STARTUP_WAVES.ANALYTICS,
  'strategy-promotion': STARTUP_WAVES.ANALYTICS,
  'shadow-stats': STARTUP_WAVES.ANALYTICS,
  'market-regime': STARTUP_WAVES.ANALYTICS,
  
  // Wave 5 - Background (60s delay)
  'ib-collector': STARTUP_WAVES.BACKGROUND,
  'simulation-jobs': STARTUP_WAVES.BACKGROUND,
  'historical-data': STARTUP_WAVES.BACKGROUND,
  'data-collection': STARTUP_WAVES.BACKGROUND,
  'backtest': STARTUP_WAVES.BACKGROUND,
};

// Polling intervals by priority (in milliseconds)
export const POLLING_INTERVALS = {
  CRITICAL: 5000,      // 5 seconds - positions, active trades
  IMPORTANT: 15000,    // 15 seconds - scanner, alerts
  STANDARD: 30000,     // 30 seconds - AI status, strategy
  RELAXED: 60000,      // 1 minute - report card, learning
  BACKGROUND: 300000,  // 5 minutes - historical stats
  LAZY: 600000,        // 10 minutes - rarely needed data
};

// Feature to polling interval mapping
export const FEATURE_POLLING = {
  // Critical - 5s
  'positions': POLLING_INTERVALS.CRITICAL,
  'active-trades': POLLING_INTERVALS.CRITICAL,
  'alerts': POLLING_INTERVALS.CRITICAL,
  
  // Important - 15s
  'scanner': POLLING_INTERVALS.IMPORTANT,
  'sentcom-status': POLLING_INTERVALS.IMPORTANT,
  'sentcom-stream': POLLING_INTERVALS.IMPORTANT,
  'dynamic-risk': POLLING_INTERVALS.IMPORTANT,
  
  // Standard - 30s
  'ai-status': POLLING_INTERVALS.STANDARD,
  'ai-debate': POLLING_INTERVALS.STANDARD,
  'ai-timeseries': POLLING_INTERVALS.STANDARD,
  'setups': POLLING_INTERVALS.STANDARD,
  'strategy-promotion': POLLING_INTERVALS.STANDARD,
  'focus-mode': POLLING_INTERVALS.STANDARD,
  
  // Relaxed - 60s
  'report-card': POLLING_INTERVALS.RELAXED,
  'learning-connectors': POLLING_INTERVALS.RELAXED,
  'shadow-stats': POLLING_INTERVALS.RELAXED,
  'market-regime': POLLING_INTERVALS.RELAXED,
  'ib-status': POLLING_INTERVALS.RELAXED,
  
  // Background - 5 min
  'ib-collector': POLLING_INTERVALS.BACKGROUND,
  'simulation-jobs': POLLING_INTERVALS.BACKGROUND,
  'historical-data': POLLING_INTERVALS.BACKGROUND,
};

const StartupManagerContext = createContext(null);

export const StartupManagerProvider = ({ children }) => {
  const [currentWave, setCurrentWave] = useState(1);
  const [loadedFeatures, setLoadedFeatures] = useState(new Set(['health', 'auth']));
  const [isStartupComplete, setIsStartupComplete] = useState(false);
  const [startupProgress, setStartupProgress] = useState(0);
  const startTimeRef = useRef(Date.now());
  const timersRef = useRef([]);

  // Initialize startup sequence
  useEffect(() => {
    console.log('[StartupManager] Beginning staged startup...');
    
    // Schedule each wave
    Object.entries(STARTUP_WAVES).forEach(([waveName, config]) => {
      const timer = setTimeout(() => {
        console.log(`[StartupManager] Wave ${config.wave} (${config.label}) starting...`);
        setCurrentWave(config.wave);
        
        // Add all features for this wave
        const waveFeatures = Object.entries(FEATURE_WAVES)
          .filter(([_, waveConfig]) => waveConfig.wave === config.wave)
          .map(([feature]) => feature);
        
        setLoadedFeatures(prev => {
          const newSet = new Set(prev);
          waveFeatures.forEach(f => newSet.add(f));
          return newSet;
        });
        
        // Update progress
        const progress = Math.min(100, Math.round((config.wave / 5) * 100));
        setStartupProgress(progress);
        
        if (config.wave === 5) {
          setTimeout(() => {
            console.log('[StartupManager] Startup complete!');
            setIsStartupComplete(true);
            setStartupProgress(100);
          }, 5000);
        }
      }, config.delay);
      
      timersRef.current.push(timer);
    });

    return () => {
      timersRef.current.forEach(timer => clearTimeout(timer));
    };
  }, []);

  /**
   * Check if a feature is allowed to load/poll
   */
  const isFeatureReady = useCallback((featureId) => {
    // Always allow core features
    if (!FEATURE_WAVES[featureId]) {
      return true; // Unknown features default to allowed
    }
    return loadedFeatures.has(featureId);
  }, [loadedFeatures]);

  /**
   * Get the recommended polling interval for a feature
   */
  const getPollingInterval = useCallback((featureId, defaultInterval = POLLING_INTERVALS.STANDARD) => {
    return FEATURE_POLLING[featureId] || defaultInterval;
  }, []);

  /**
   * Get startup delay for a feature (how long to wait before first poll)
   */
  const getStartupDelay = useCallback((featureId) => {
    const waveConfig = FEATURE_WAVES[featureId];
    if (!waveConfig) return 0;
    return waveConfig.delay;
  }, []);

  /**
   * Force enable a feature (skip wave waiting)
   */
  const forceEnableFeature = useCallback((featureId) => {
    setLoadedFeatures(prev => {
      const newSet = new Set(prev);
      newSet.add(featureId);
      return newSet;
    });
  }, []);

  /**
   * Get time since startup
   */
  const getElapsedTime = useCallback(() => {
    return Date.now() - startTimeRef.current;
  }, []);

  /**
   * Get current wave info
   */
  const getCurrentWaveInfo = useCallback(() => {
    const waveEntry = Object.entries(STARTUP_WAVES).find(([_, config]) => config.wave === currentWave);
    return waveEntry ? { name: waveEntry[0], ...waveEntry[1] } : null;
  }, [currentWave]);

  return (
    <StartupManagerContext.Provider value={{
      // State
      currentWave,
      isStartupComplete,
      startupProgress,
      loadedFeatures: Array.from(loadedFeatures),
      
      // Methods
      isFeatureReady,
      getPollingInterval,
      getStartupDelay,
      forceEnableFeature,
      getElapsedTime,
      getCurrentWaveInfo,
      
      // Constants (for reference)
      WAVES: STARTUP_WAVES,
      INTERVALS: POLLING_INTERVALS,
    }}>
      {children}
    </StartupManagerContext.Provider>
  );
};

/**
 * Hook to access startup manager
 */
export const useStartupManager = () => {
  const context = useContext(StartupManagerContext);
  if (!context) {
    // Return safe defaults if not wrapped in provider
    return {
      currentWave: 5,
      isStartupComplete: true,
      startupProgress: 100,
      loadedFeatures: [],
      isFeatureReady: () => true,
      getPollingInterval: () => POLLING_INTERVALS.STANDARD,
      getStartupDelay: () => 0,
      forceEnableFeature: () => {},
      getElapsedTime: () => 0,
      getCurrentWaveInfo: () => null,
      WAVES: STARTUP_WAVES,
      INTERVALS: POLLING_INTERVALS,
    };
  }
  return context;
};

/**
 * Hook for components that need to wait for their feature wave
 * Returns { isReady, pollingInterval }
 */
export const useFeatureGate = (featureId) => {
  const { isFeatureReady, getPollingInterval, getStartupDelay, isStartupComplete } = useStartupManager();
  const [isReady, setIsReady] = useState(false);
  const [hasInitialized, setHasInitialized] = useState(false);

  useEffect(() => {
    if (isFeatureReady(featureId)) {
      // Add a small random jitter to prevent all features in a wave from starting at exactly the same time
      const jitter = Math.random() * 2000; // 0-2 second random delay
      const timer = setTimeout(() => {
        setIsReady(true);
        setHasInitialized(true);
      }, hasInitialized ? 0 : jitter);
      
      return () => clearTimeout(timer);
    }
  }, [featureId, isFeatureReady, hasInitialized]);

  return {
    isReady,
    isStartupComplete,
    pollingInterval: getPollingInterval(featureId),
    startupDelay: getStartupDelay(featureId),
  };
};

export default StartupManagerContext;
