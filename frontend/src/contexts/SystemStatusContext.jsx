/**
 * SystemStatusContext - Unified System Status Management
 * =======================================================
 * 
 * Single source of truth for ALL connection/service statuses.
 * Provides:
 * 1. Centralized status tracking for all services
 * 2. Status dot indicators for inline use
 * 3. Overall system health calculation
 * 4. Auto-refresh of statuses
 */

import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';

const SystemStatusContext = createContext(null);

// Direct fetch that bypasses the request throttler — health checks must never be queued
const API_URL = process.env.REACT_APP_BACKEND_URL || '';
async function directGet(path) {
  try {
    const res = await fetch(`${API_URL}${path}`, { signal: AbortSignal.timeout(20000) });
    if (res.ok) return await res.json();
    return null;
  } catch {
    return null;
  }
}

// Service definitions
const SERVICES = {
  quotesStream: {
    id: 'quotesStream',
    name: 'Quotes Stream',
    description: 'Real-time market data via WebSocket',
    critical: true,
    checkEndpoint: null, // Checked via WebSocket state
  },
  ibGateway: {
    id: 'ibGateway', 
    name: 'IB Gateway',
    description: 'Interactive Brokers connection',
    critical: true,
    checkEndpoint: '/api/ib/status',
  },
  ibDataPusher: {
    id: 'ibDataPusher',
    name: 'IB Data Pusher', 
    description: 'Local script pushing IB data',
    critical: false,
    checkEndpoint: '/api/ib/pushed-data', // Check if pusher has sent data recently
  },
  ollama: {
    id: 'ollama',
    name: 'Ollama AI',
    description: 'AI chat and analysis',
    critical: false,
    checkEndpoint: '/api/assistant/check-ollama',
  },
  backend: {
    id: 'backend',
    name: 'Backend',
    description: 'API server',
    critical: true,
    checkEndpoint: '/api/health',
  },
  mongodb: {
    id: 'mongodb',
    name: 'Database',
    description: 'MongoDB connection',
    critical: true,
    checkEndpoint: null, // Checked via backend health
  },
};

// Status types
const STATUS = {
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected',
  CONNECTING: 'connecting',
  ERROR: 'error',
  UNKNOWN: 'unknown',
};

export const SystemStatusProvider = ({ children }) => {
  // Individual service statuses
  const [statuses, setStatuses] = useState(() => {
    const initial = {};
    Object.keys(SERVICES).forEach(key => {
      initial[key] = { status: STATUS.UNKNOWN, lastCheck: null, message: null };
    });
    return initial;
  });
  
  // Consecutive failure tracking — only go red after 5 failures
  const failureCountRef = useRef({});
  const FAILURE_THRESHOLD = 5;
  
  // WebSocket state (managed externally, updated here)
  const wsConnectedRef = useRef(false);
  
  // Visibility tracking
  const isVisibleRef = useRef(document.visibilityState === 'visible');
  
  // Check interval ref
  const checkIntervalRef = useRef(null);

  /**
   * Update a single service status — with consecutive failure protection
   */
  const updateStatus = useCallback((serviceId, status, message = null) => {
    if (status === STATUS.DISCONNECTED || status === STATUS.ERROR) {
      // Increment failure counter
      failureCountRef.current[serviceId] = (failureCountRef.current[serviceId] || 0) + 1;
      // Only mark red after FAILURE_THRESHOLD consecutive failures
      if (failureCountRef.current[serviceId] < FAILURE_THRESHOLD) {
        return; // Keep previous status (green/unknown) — don't flash red
      }
    } else {
      // Reset failure counter on success
      failureCountRef.current[serviceId] = 0;
    }
    
    setStatuses(prev => ({
      ...prev,
      [serviceId]: {
        status,
        lastCheck: Date.now(),
        message
      }
    }));
  }, []);

  // Ref for checkAllServices to avoid dependency issues
  const checkAllServicesRef = useRef(null);

  /**
   * Update WebSocket connection state (called from WebSocket hook)
   */
  const setWebSocketConnected = useCallback((connected) => {
    wsConnectedRef.current = connected;
    updateStatus('quotesStream', connected ? STATUS.CONNECTED : STATUS.DISCONNECTED);
    // When WS connects, immediately re-check all other services (they're likely up too)
    if (connected && checkAllServicesRef.current) {
      setTimeout(() => checkAllServicesRef.current?.(), 500);
    }
  }, [updateStatus]);

  /**
   * Check a single service
   */
  const checkService = useCallback(async (serviceId) => {
    const service = SERVICES[serviceId];
    if (!service?.checkEndpoint) return;
    
    try {
      const data = await directGet(service.checkEndpoint);
      
      if (data) {
        let connected = false;
        let message = null;
        
        if (serviceId === 'ibGateway') {
          connected = data.connected === true;
          message = data.account_id ? `Account: ${data.account_id}` : null;
        } else if (serviceId === 'ollama') {
          connected = data.available === true;
          message = data.model ? `Model: ${data.model}` : null;
        } else if (serviceId === 'ibDataPusher') {
          connected = data.connected === true;
          if (data.last_update) {
            const lastUpdate = new Date(data.last_update);
            const ageSeconds = (Date.now() - lastUpdate.getTime()) / 1000;
            connected = connected && ageSeconds < 120;  // 120s tolerance for startup/network delays
          }
        } else {
          connected = data.status === 'healthy' || data.status === 'ok' || data.healthy || true;
        }
        
        updateStatus(serviceId, connected ? STATUS.CONNECTED : STATUS.DISCONNECTED, message);
      } else {
        updateStatus(serviceId, STATUS.DISCONNECTED);
      }
    } catch (error) {
      updateStatus(serviceId, STATUS.ERROR, error.message);
    }
  }, [updateStatus]);

  /**
   * Check a single service and report whether the HTTP call itself succeeded
   * (i.e. the backend responded). Used by checkAllServices for self-healing.
   */
  const checkServiceAndReport = useCallback(async (serviceId) => {
    const service = SERVICES[serviceId];
    if (!service?.checkEndpoint) return false;
    
    try {
      const data = await directGet(service.checkEndpoint);
      
      if (data) {
        let connected = false;
        let message = null;
        
        if (serviceId === 'ibGateway') {
          connected = data.connected === true;
          message = data.account_id ? `Account: ${data.account_id}` : null;
        } else if (serviceId === 'ollama') {
          connected = data.available === true;
          message = data.model ? `Model: ${data.model}` : null;
        } else if (serviceId === 'ibDataPusher') {
          connected = data.connected === true;
          if (data.last_update) {
            const lastUpdate = new Date(data.last_update);
            const ageSeconds = (Date.now() - lastUpdate.getTime()) / 1000;
            connected = connected && ageSeconds < 120;
          }
        } else {
          connected = data.status === 'healthy' || data.status === 'ok' || data.healthy || true;
        }
        
        updateStatus(serviceId, connected ? STATUS.CONNECTED : STATUS.DISCONNECTED, message);
        return true; // Backend responded — proof of life
      } else {
        updateStatus(serviceId, STATUS.DISCONNECTED);
        return false;
      }
    } catch (error) {
      updateStatus(serviceId, STATUS.ERROR, error.message);
      return false;
    }
  }, [updateStatus]);

  /**
   * Check all services — self-healing: if /api/health fails but other
   * backend-routed checks succeed, the backend is provably alive.
   */
  const checkAllServices = useCallback(async () => {
    // Skip if tab is hidden
    if (!isVisibleRef.current) return;
    
    // 1. Try the primary health endpoint
    let healthOk = false;
    try {
      const data = await directGet('/api/health');
      healthOk = !!(data && (data.status === 'healthy' || data.status === 'ok'));
    } catch {
      healthOk = false;
    }
    
    if (healthOk) {
      updateStatus('backend', STATUS.CONNECTED);
      updateStatus('mongodb', STATUS.CONNECTED);
    }
    
    // 2. Always check other services — they also prove backend reachability
    let anyOtherSucceeded = false;
    const results = await Promise.allSettled([
      checkServiceAndReport('ibGateway'),
      checkServiceAndReport('ibDataPusher'),
      checkServiceAndReport('ollama'),
    ]);
    anyOtherSucceeded = results.some(r => r.status === 'fulfilled' && r.value === true);
    
    // 3. Self-healing: if health failed but another backend-routed API succeeded,
    //    the backend IS alive — reset failure counter and mark connected.
    if (!healthOk) {
      if (anyOtherSucceeded) {
        // Proof of life — backend responded to a different route
        failureCountRef.current['backend'] = 0;
        updateStatus('backend', STATUS.CONNECTED);
        updateStatus('mongodb', STATUS.CONNECTED);
      } else {
        // Genuine failure — let the threshold logic in updateStatus decide
        updateStatus('backend', STATUS.DISCONNECTED);
        updateStatus('mongodb', STATUS.UNKNOWN);
      }
    }
  }, [checkServiceAndReport, updateStatus]);

  /**
   * Get overall system health
   */
  const getOverallHealth = useCallback(() => {
    const criticalServices = Object.entries(SERVICES)
      .filter(([_, service]) => service.critical)
      .map(([key]) => key);
    
    const criticalStatuses = criticalServices.map(key => statuses[key]?.status);
    
    const allCriticalConnected = criticalStatuses.every(s => s === STATUS.CONNECTED);
    const anyCriticalError = criticalStatuses.some(s => s === STATUS.ERROR || s === STATUS.DISCONNECTED);
    const anyConnecting = criticalStatuses.some(s => s === STATUS.CONNECTING);
    
    if (allCriticalConnected) return 'healthy';
    if (anyConnecting) return 'connecting';
    if (anyCriticalError) return 'degraded';
    return 'unknown';
  }, [statuses]);

  /**
   * Get status for a specific service
   */
  const getServiceStatus = useCallback((serviceId) => {
    return statuses[serviceId] || { status: STATUS.UNKNOWN, lastCheck: null, message: null };
  }, [statuses]);

  /**
   * Check if a specific feature's dependencies are met
   */
  const isFeatureAvailable = useCallback((requiredServices) => {
    return requiredServices.every(serviceId => 
      statuses[serviceId]?.status === STATUS.CONNECTED
    );
  }, [statuses]);

  // Track visibility
  useEffect(() => {
    const handleVisibilityChange = () => {
      const wasHidden = !isVisibleRef.current;
      isVisibleRef.current = document.visibilityState === 'visible';
      
      // Refresh when tab becomes visible
      if (isVisibleRef.current && wasHidden) {
        checkAllServices();
      }
    };
    
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [checkAllServices]);

  // Initial check and polling — aggressive during startup, then relaxed
  useEffect(() => {
    // Keep ref in sync for WS-triggered re-checks
    checkAllServicesRef.current = checkAllServices;
    
    // Aggressive startup checks: every 5s for the first 30s
    let startupChecks = 0;
    const maxStartupChecks = 6; // 6 checks × 5s = 30s
    
    const startupTimer = setInterval(() => {
      startupChecks++;
      if (isVisibleRef.current) {
        checkAllServices();
      }
      if (startupChecks >= maxStartupChecks) {
        clearInterval(startupTimer);
      }
    }, 5000);
    
    // Then settle to every 90 seconds
    checkIntervalRef.current = setInterval(() => {
      if (isVisibleRef.current) {
        checkAllServices();
      }
    }, 90000);
    
    return () => {
      clearInterval(startupTimer);
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
      }
    };
  }, [checkAllServices]);

  return (
    <SystemStatusContext.Provider value={{
      // Status data
      statuses,
      SERVICES,
      STATUS,
      
      // Actions
      updateStatus,
      setWebSocketConnected,
      checkService,
      checkAllServices,
      
      // Helpers
      getOverallHealth,
      getServiceStatus,
      isFeatureAvailable,
    }}>
      {children}
    </SystemStatusContext.Provider>
  );
};

/**
 * Hook to access system status
 */
export const useSystemStatus = () => {
  const context = useContext(SystemStatusContext);
  if (!context) {
    // Return stub if used outside provider
    return {
      statuses: {},
      SERVICES: {},
      STATUS: { CONNECTED: 'connected', DISCONNECTED: 'disconnected' },
      updateStatus: () => {},
      setWebSocketConnected: () => {},
      checkService: () => {},
      checkAllServices: () => {},
      getOverallHealth: () => 'unknown',
      getServiceStatus: () => ({ status: 'unknown' }),
      isFeatureAvailable: () => false,
    };
  }
  return context;
};

/**
 * Hook to check if IB is connected
 */
export const useIBConnected = () => {
  const { getServiceStatus, STATUS } = useSystemStatus();
  const status = getServiceStatus('ibGateway');
  return status.status === STATUS.CONNECTED;
};

/**
 * Hook to check if AI is available
 */
export const useAIAvailable = () => {
  const { getServiceStatus, STATUS } = useSystemStatus();
  const status = getServiceStatus('ollama');
  return status.status === STATUS.CONNECTED;
};

export default SystemStatusContext;
