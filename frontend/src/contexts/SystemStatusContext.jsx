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

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

export const SystemStatusProvider = ({ children }) => {
  // Individual service statuses
  const [statuses, setStatuses] = useState(() => {
    const initial = {};
    Object.keys(SERVICES).forEach(key => {
      initial[key] = { status: STATUS.UNKNOWN, lastCheck: null, message: null };
    });
    return initial;
  });
  
  // WebSocket state (managed externally, updated here)
  const wsConnectedRef = useRef(false);
  
  // Visibility tracking
  const isVisibleRef = useRef(document.visibilityState === 'visible');
  
  // Check interval ref
  const checkIntervalRef = useRef(null);

  /**
   * Update a single service status
   */
  const updateStatus = useCallback((serviceId, status, message = null) => {
    setStatuses(prev => ({
      ...prev,
      [serviceId]: {
        status,
        lastCheck: Date.now(),
        message
      }
    }));
  }, []);

  /**
   * Update WebSocket connection state (called from WebSocket hook)
   */
  const setWebSocketConnected = useCallback((connected) => {
    wsConnectedRef.current = connected;
    updateStatus('quotesStream', connected ? STATUS.CONNECTED : STATUS.DISCONNECTED);
  }, [updateStatus]);

  /**
   * Check a single service
   */
  const checkService = useCallback(async (serviceId) => {
    const service = SERVICES[serviceId];
    if (!service?.checkEndpoint) return;
    
    try {
      const response = await fetch(`${API_URL}${service.checkEndpoint}`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });
      
      if (response.ok) {
        const data = await response.json();
        // Different services have different response formats
        let connected = false;
        let message = null;
        
        if (serviceId === 'ibGateway') {
          connected = data.connected === true;
          message = data.account_id ? `Account: ${data.account_id}` : null;
        } else if (serviceId === 'ollama') {
          // /api/assistant/check-ollama returns { available: true/false }
          connected = data.available === true;
          message = data.model ? `Model: ${data.model}` : null;
        } else if (serviceId === 'ibDataPusher') {
          // /api/ib/pushed-data returns { connected: true/false, last_update: ... }
          connected = data.connected === true;
          if (data.last_update) {
            const lastUpdate = new Date(data.last_update);
            const ageSeconds = (Date.now() - lastUpdate.getTime()) / 1000;
            // Consider stale if no update in 60 seconds
            connected = connected && ageSeconds < 60;
          }
        } else {
          connected = data.status === 'healthy' || data.status === 'ok' || data.healthy || response.ok;
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
   * Check all services
   */
  const checkAllServices = useCallback(async () => {
    // Skip if tab is hidden
    if (!isVisibleRef.current) return;
    
    // Check backend first (if backend is down, others will fail)
    try {
      const healthResponse = await fetch(`${API_URL}/api/health`);
      if (healthResponse.ok) {
        updateStatus('backend', STATUS.CONNECTED);
        updateStatus('mongodb', STATUS.CONNECTED); // If backend is up, DB is connected
        
        // Check other services in parallel
        await Promise.all([
          checkService('ibGateway'),
          checkService('ibDataPusher'),
          checkService('ollama'),
        ]);
      } else {
        updateStatus('backend', STATUS.DISCONNECTED);
        updateStatus('mongodb', STATUS.UNKNOWN);
      }
    } catch (error) {
      updateStatus('backend', STATUS.ERROR, error.message);
      updateStatus('mongodb', STATUS.UNKNOWN);
    }
  }, [checkService, updateStatus]);

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

  // Initial check and polling — short delay to let StartupModal complete first
  useEffect(() => {
    // Delay initial check by 3s - StartupModal verifies services during startup
    const initialDelay = setTimeout(() => {
      checkAllServices();
    }, 3000);
    
    // Poll every 60 seconds (reduced from 30s — WebSocket handles real-time updates)
    checkIntervalRef.current = setInterval(() => {
      if (isVisibleRef.current) {
        checkAllServices();
      }
    }, 60000);
    
    return () => {
      clearTimeout(initialDelay);
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
