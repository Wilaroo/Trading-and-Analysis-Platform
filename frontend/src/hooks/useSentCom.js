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
import { useWsData } from '../contexts/WebSocketDataContext';

/**
 * Hook for AI Insights data (shadow decisions, predictions, etc.)
 */
export const useAIInsights = () => {
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
    fetchInsights(); // Initial fetch only — data changes infrequently
  }, [fetchInsights]);

  return { shadowDecisions, shadowPerformance, timeseriesStatus, predictionAccuracy, recentPredictions, loading, refresh: fetchInsights };
};

/**
 * Hook for market session status (pre-market, open, closed, etc.)
 */
export const useMarketSession = () => {
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
    fetchSession(); // Initial fetch only — session changes infrequently
  }, [fetchSession]);

  return { session, loading, refresh: fetchSession };
};

/**
 * Hook for SentCom status with caching
 */
export const useSentComStatus = () => {
  const { getCached, setCached } = useDataCache();
  const { sentcomData: wsSentcom } = useWsData();
  
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
    if (cached?.data) {
      setStatus(cached.data);
      setLoading(false);
      if (cached.isStale) fetchStatus();
    } else {
      fetchStatus();
    }
  }, [fetchStatus, getCached]);

  // Subscribe to WS SentCom status updates (replaces 60s polling)
  useEffect(() => {
    if (!wsSentcom?.status) return;
    setStatus(wsSentcom.status);
    setCached('sentcomStatus', wsSentcom.status, 30000);
    setLoading(false);
  }, [wsSentcom?.status, setCached]);

  return { status, loading, error, refresh: fetchStatus };
};

/**
 * Hook for SentCom stream of consciousness messages
 */
export const useSentComStream = () => {
  const { getCached, setCached } = useDataCache();
  const { sentcomData: wsSentcom } = useWsData();
  
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
    if (cached?.data) {
      setMessages(cached.data);
      setLoading(false);
      if (cached.isStale) fetchStream();
    } else {
      fetchStream();
    }
  }, [fetchStream, getCached]);

  // Subscribe to WS SentCom stream (replaces 45s polling)
  useEffect(() => {
    if (!wsSentcom?.stream || !Array.isArray(wsSentcom.stream)) return;
    const streamMessages = wsSentcom.stream.map(m => ({ ...m, source: 'stream' }));
    if (streamMessages.length > 0) {
      setMessages(prev => {
        const merged = [...streamMessages, ...prev.filter(p => p.source === 'chat')];
        const unique = merged.filter((m, i, arr) => arr.findIndex(x => x.id === m.id) === i);
        return unique.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 30);
      });
      setLoading(false);
    }
  }, [wsSentcom?.stream]);

  return { messages, loading, refresh: fetchStream };
};

/**
 * Hook for SentCom positions with caching
 */
export const useSentComPositions = () => {
  const { getCached, setCached } = useDataCache();
  const { sentcomData: wsSentcom } = useWsData();
  
  const cachedPositions = getCached('sentcomPositions');
  const [positions, setPositions] = useState(cachedPositions?.data || []);
  const [loading, setLoading] = useState(!cachedPositions?.data);

  const fetchPositions = useCallback(async () => {
    try {
      const data = await safeGet('/api/ib/pushed-data');
      if (data === null) return;
      
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
    if (cached?.data) {
      setPositions(cached.data);
      setLoading(false);
      if (cached.isStale) fetchPositions();
    } else {
      fetchPositions();
    }
  }, [fetchPositions, getCached]);

  // Subscribe to WS positions data (replaces 30s polling)
  useEffect(() => {
    if (!wsSentcom?.positions) return;
    const p = wsSentcom.positions;
    if (p.positions) {
      const positionsArray = Object.values(p.positions);
      setPositions(positionsArray);
      setCached('sentcomPositions', positionsArray, 15000);
      setLoading(false);
    }
  }, [wsSentcom?.positions, setCached]);

  return { positions, loading, refresh: fetchPositions };
};

/**
 * Hook for active trading setups
 */
export const useSentComSetups = () => {
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
    fetchSetups(); // Initial fetch only — setups change infrequently
  }, [fetchSetups]);

  return { setups, loading, refresh: fetchSetups };
};

/**
 * Hook for market context data
 */
export const useSentComContext = () => {
  const [context, setContext] = useState(null);
  const [loading, setLoading] = useState(true);
  const { sentcomData: wsSentcom } = useWsData();

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
    fetchContext(); // Initial fetch only
  }, [fetchContext]);

  // Subscribe to WS market context (replaces 30s polling)
  useEffect(() => {
    if (!wsSentcom?.market_context) return;
    setContext(prev => ({ ...prev, ...wsSentcom.market_context, success: true }));
    setLoading(false);
  }, [wsSentcom?.market_context]);

  return { context, loading, refresh: fetchContext };
};

/**
 * Hook for active alerts
 */
export const useSentComAlerts = (pollInterval = 5000) => {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const { scannerAlerts } = useWsData();

  // Use WebSocket data when available
  useEffect(() => {
    if (scannerAlerts && scannerAlerts.length > 0) {
      setAlerts(scannerAlerts);
      setLoading(false);
    }
  }, [scannerAlerts]);

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

  // Initial REST fetch only — WebSocket handles subsequent updates
  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

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
  const { botStatus: wsBotStatus } = useWsData();

  // Use WebSocket data when available
  useEffect(() => {
    if (wsBotStatus) {
      setBotStatus(wsBotStatus);
      setLoading(false);
    }
  }, [wsBotStatus]);

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

  // Initial REST fetch only — WebSocket handles subsequent updates
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return { botStatus, loading, actionLoading, toggleBot, refresh: fetchStatus };
};

/**
 * Hook for IB connection status
 */
export const useIBConnectionStatus = (pollInterval = 3000) => {
  const [ibConnected, setIbConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const { ibStatus } = useWsData();

  // Use WebSocket data when available
  useEffect(() => {
    if (ibStatus) {
      setIbConnected(ibStatus.ib_connected || ibStatus.connected || false);
      setLoading(false);
    }
  }, [ibStatus]);

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

  // Initial REST fetch only — WebSocket handles subsequent updates
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return { ibConnected, loading };
};

/**
 * Hook for AI modules status and control
 */
export const useAIModules = () => {
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
    fetchStatus(); // Initial fetch only — refresh after toggle actions
  }, [fetchStatus]);

  return { status, loading, actionLoading, toggleModule, setGlobalShadowMode, refresh: fetchStatus };
};
