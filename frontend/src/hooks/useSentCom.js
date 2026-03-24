/**
 * useSentCom.js - Extracted hooks from SentCom.jsx
 * 
 * These hooks handle data fetching and state management for the SentCom component.
 * Extracted for better code organization and reusability.
 * 
 * Migrated from raw fetch() to centralized api utility (P2.3)
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { toast } from 'sonner';
import { useDataCache } from '../contexts';
import api, { safeGet, safePost } from '../utils/api';

/**
 * Hook for AI Insights data (shadow decisions, predictions, etc.)
 */
export const useAIInsights = (pollInterval = 60000) => {
  const [shadowDecisions, setShadowDecisions] = useState([]);
  const [shadowPerformance, setShadowPerformance] = useState(null);
  const [timeseriesStatus, setTimeseriesStatus] = useState(null);
  const [predictionAccuracy, setPredictionAccuracy] = useState(null);
  const [recentPredictions, setRecentPredictions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchInsights = useCallback(async () => {
    try {
      const [decisionsData, performanceData, timeseriesData, accuracyData, predictionsData] = await Promise.all([
        safeGet('/api/ai-modules/shadow/decisions?limit=10'),
        safeGet('/api/ai-modules/shadow/performance?days=7'),
        safeGet('/api/ai-modules/timeseries/status'),
        safeGet('/api/ai-modules/timeseries/prediction-accuracy?days=30'),
        safeGet('/api/ai-modules/timeseries/predictions?limit=10')
      ]);

      // Handle rate limiting (safeGet returns null on 429)
      if ([decisionsData, performanceData, timeseriesData, accuracyData, predictionsData].some(d => d === null)) {
        return;
      }

      if (decisionsData.success) setShadowDecisions(decisionsData.decisions || []);
      if (performanceData.success) setShadowPerformance(performanceData.performance || null);
      if (timeseriesData.success) setTimeseriesStatus(timeseriesData.status || null);
      if (accuracyData.success) setPredictionAccuracy(accuracyData.accuracy || null);
      if (predictionsData.success) setRecentPredictions(predictionsData.predictions || []);
    } catch (err) {
      console.error('Error fetching AI insights:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInsights();
    const interval = setInterval(fetchInsights, pollInterval);
    return () => clearInterval(interval);
  }, [fetchInsights, pollInterval]);

  return { shadowDecisions, shadowPerformance, timeseriesStatus, predictionAccuracy, recentPredictions, loading, refresh: fetchInsights };
};

/**
 * Hook for market session status (pre-market, open, closed, etc.)
 */
export const useMarketSession = (pollInterval = 30000) => {
  const [session, setSession] = useState({ name: 'LOADING', is_open: false });
  const [loading, setLoading] = useState(true);

  const fetchSession = useCallback(async () => {
    try {
      const data = await safeGet('/api/market-context/session/status');
      if (data?.success && data.session) {
        setSession(data.session);
      }
    } catch (err) {
      console.error('Error fetching market session:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSession();
    const interval = setInterval(fetchSession, pollInterval);
    return () => clearInterval(interval);
  }, [fetchSession, pollInterval]);

  return { session, loading, refresh: fetchSession };
};

/**
 * Hook for SentCom status with caching
 */
export const useSentComStatus = (pollInterval = 60000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  const cachedStatus = getCached('sentcomStatus');
  const [status, setStatus] = useState(cachedStatus?.data || null);
  const [loading, setLoading] = useState(!cachedStatus?.data);
  const [error, setError] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/status');
      if (data?.success) {
        setStatus(data.status);
        setCached('sentcomStatus', data.status, 30000);
      }
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    const cached = getCached('sentcomStatus');
    if (cached?.data && isFirstMount.current) {
      setStatus(cached.data);
      setLoading(false);
      if (cached.isStale) {
        fetchStatus();
      }
    } else {
      fetchStatus();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, pollInterval, getCached]);

  return { status, loading, error, refresh: fetchStatus };
};

/**
 * Hook for SentCom stream of consciousness messages
 */
export const useSentComStream = (pollInterval = 45000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  const cachedStream = getCached('sentcomStream');
  const [messages, setMessages] = useState(cachedStream?.data || []);
  const [loading, setLoading] = useState(!cachedStream?.data);
  const lastFetchRef = useRef({ ids: '', chatCount: 0 });

  const fetchStream = useCallback(async () => {
    try {
      const [streamData, chatData] = await Promise.all([
        safeGet('/api/sentcom/stream?limit=50'),
        safeGet('/api/sentcom/chats?limit=20')
      ]);

      // Handle rate limiting
      if (streamData === null || chatData === null) return;

      const streamMessages = (streamData.success && streamData.messages) || [];
      const chatMessages = (chatData.success && chatData.chats) || [];

      const currentIds = streamMessages.map(m => m.id).join(',');
      const currentChatCount = chatMessages.length;
      
      if (currentIds !== lastFetchRef.current.ids || currentChatCount !== lastFetchRef.current.chatCount) {
        lastFetchRef.current = { ids: currentIds, chatCount: currentChatCount };

        const combined = [
          ...streamMessages.map(m => ({ ...m, source: 'stream' })),
          ...chatMessages.filter(c => c.response).map(c => ({
            id: `chat-${c.id}`,
            type: 'chat_response',
            content: c.response?.content?.substring(0, 200) + (c.response?.content?.length > 200 ? '...' : ''),
            metadata: { query: c.query?.substring(0, 50), full_response: c.response?.content },
            timestamp: c.timestamp,
            source: 'chat'
          }))
        ].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 30);

        setMessages(combined);
        setCached('sentcomStream', combined, 20000);
      }
    } catch (err) {
      console.error('Error fetching SentCom stream:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    const cached = getCached('sentcomStream');
    if (cached?.data && isFirstMount.current) {
      setMessages(cached.data);
      setLoading(false);
      if (cached.isStale) {
        fetchStream();
      }
    } else {
      fetchStream();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchStream, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStream, pollInterval, getCached]);

  return { messages, loading, refresh: fetchStream };
};

/**
 * Hook for SentCom positions with caching
 */
export const useSentComPositions = (pollInterval = 30000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  const cachedPositions = getCached('sentcomPositions');
  const [positions, setPositions] = useState(cachedPositions?.data || []);
  const [loading, setLoading] = useState(!cachedPositions?.data);

  const fetchPositions = useCallback(async () => {
    try {
      const data = await safeGet('/api/ib/pushed-data');
      if (data === null) return; // Rate limited
      
      if (data.positions) {
        const positionsArray = Object.values(data.positions);
        setPositions(positionsArray);
        setCached('sentcomPositions', positionsArray, 15000);
      }
    } catch (err) {
      console.error('Error fetching positions:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    const cached = getCached('sentcomPositions');
    if (cached?.data && isFirstMount.current) {
      setPositions(cached.data);
      setLoading(false);
      if (cached.isStale) {
        fetchPositions();
      }
    } else {
      fetchPositions();
    }
    isFirstMount.current = false;
    
    const interval = setInterval(fetchPositions, pollInterval);
    return () => clearInterval(interval);
  }, [fetchPositions, pollInterval, getCached]);

  return { positions, loading, refresh: fetchPositions };
};

/**
 * Hook for active trading setups
 */
export const useSentComSetups = (pollInterval = 30000) => {
  const [setups, setSetups] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchSetups = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/setups?limit=10');
      if (data === null) return;
      
      if (data.success) {
        setSetups(data.setups || []);
      }
    } catch (err) {
      console.error('Error fetching setups:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSetups();
    const interval = setInterval(fetchSetups, pollInterval);
    return () => clearInterval(interval);
  }, [fetchSetups, pollInterval]);

  return { setups, loading, refresh: fetchSetups };
};

/**
 * Hook for market context data
 */
export const useSentComContext = (pollInterval = 30000) => {
  const [context, setContext] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchContext = useCallback(async () => {
    try {
      const data = await safeGet('/api/market-context/snapshot');
      if (data === null) return;
      
      if (data.success) {
        setContext(data);
      }
    } catch (err) {
      console.error('Error fetching market context:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchContext();
    const interval = setInterval(fetchContext, pollInterval);
    return () => clearInterval(interval);
  }, [fetchContext, pollInterval]);

  return { context, loading, refresh: fetchContext };
};

/**
 * Hook for active alerts
 */
export const useSentComAlerts = (pollInterval = 5000) => {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchAlerts = useCallback(async () => {
    try {
      const data = await safeGet('/api/ib/alerts/enhanced?limit=10');
      if (data === null) return;
      
      if (data.alerts) {
        setAlerts(data.alerts);
      }
    } catch (err) {
      // Silently handle - alerts are optional
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, pollInterval);
    return () => clearInterval(interval);
  }, [fetchAlerts, pollInterval]);

  return { alerts, loading, refresh: fetchAlerts };
};

/**
 * Hook for chat history management
 */
export const useChatHistory = () => {
  const [chats, setChats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeSession, setActiveSession] = useState(null);

  const fetchChats = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/chats?limit=50');
      if (data === null) return;
      
      if (data.success) {
        setChats(data.chats || []);
      }
    } catch (err) {
      console.error('Error fetching chat history:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const createSession = useCallback(async () => {
    try {
      const { data } = await api.post('/api/sentcom/session');
      if (data.success) {
        setActiveSession(data.session_id);
        return data.session_id;
      }
    } catch (err) {
      console.error('Error creating session:', err);
    }
    return null;
  }, []);

  useEffect(() => {
    fetchChats();
  }, [fetchChats]);

  return { chats, loading, activeSession, setActiveSession, createSession, refresh: fetchChats };
};

/**
 * Hook for trading bot control
 */
export const useTradingBotControl = (pollInterval = 5000) => {
  const [botStatus, setBotStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await safeGet('/api/trading-bot/status');
      if (data === null) return;
      
      if (data.success) {
        setBotStatus(data.status);
      }
    } catch (err) {
      // Silently handle
    } finally {
      setLoading(false);
    }
  }, []);

  const toggleBot = useCallback(async (enabled) => {
    setActionLoading(true);
    try {
      const endpoint = enabled ? 'start' : 'stop';
      const { data } = await api.post(`/api/trading-bot/${endpoint}`);
      if (data.success) {
        await fetchStatus();
        toast.success(`Trading bot ${enabled ? 'started' : 'stopped'}`);
      } else {
        toast.error(data.message || 'Failed to toggle bot');
      }
    } catch (err) {
      toast.error('Failed to toggle trading bot');
    } finally {
      setActionLoading(false);
    }
  }, [fetchStatus]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, pollInterval]);

  return { botStatus, loading, actionLoading, toggleBot, refresh: fetchStatus };
};

/**
 * Hook for IB connection status
 */
export const useIBConnectionStatus = (pollInterval = 3000) => {
  const [ibConnected, setIbConnected] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await safeGet('/api/ib/pushed-data');
      setIbConnected(data?.connected || false);
    } catch (err) {
      setIbConnected(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, pollInterval]);

  return { ibConnected, loading };
};

/**
 * Hook for AI modules status and control
 */
export const useAIModules = (pollInterval = 10000) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await safeGet('/api/ai-modules/status');
      if (data?.success) {
        setStatus(data.status);
      }
    } catch (err) {
      console.error('Error fetching AI modules status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const toggleModule = useCallback(async (moduleName, enabled) => {
    setActionLoading(moduleName);
    try {
      const { data } = await api.post(`/api/ai-modules/toggle/${moduleName}`, { enabled });
      if (data.success) {
        await fetchStatus();
        toast.success(`${moduleName.replace('_', ' ')} ${enabled ? 'enabled' : 'disabled'}`);
      }
    } catch (err) {
      console.error('Error toggling module:', err);
      toast.error('Failed to toggle module');
    } finally {
      setActionLoading(null);
    }
  }, [fetchStatus]);

  const setGlobalShadowMode = useCallback(async (shadowMode) => {
    setActionLoading('shadow');
    try {
      const { data } = await api.post('/api/ai-modules/shadow-mode', { shadow_mode: shadowMode });
      if (data.success) {
        await fetchStatus();
        toast.success(`Shadow mode ${shadowMode ? 'enabled' : 'disabled'}`);
      }
    } catch (err) {
      console.error('Error setting shadow mode:', err);
      toast.error('Failed to set shadow mode');
    } finally {
      setActionLoading(null);
    }
  }, [fetchStatus]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, pollInterval);
    return () => clearInterval(interval);
  }, [fetchStatus, pollInterval]);

  return { status, loading, actionLoading, toggleModule, setGlobalShadowMode, refresh: fetchStatus };
};
