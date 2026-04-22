import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import api, { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useDataCache } from '../../../contexts';
import { useWsData } from '../../../contexts/WebSocketDataContext';

// Hook for Trading Bot status and controls — uses WS botStatus as primary, HTTP as slow backup
export const useTradingBotControl = (pollInterval = 60000) => {
  const { getCached, setCached } = useDataCache();
  const { botStatus: wsBotStatus } = useWsData();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedBotStatus = getCached('botStatus');
  const [botStatus, setBotStatus] = useState(cachedBotStatus?.data || null);
  const [loading, setLoading] = useState(!cachedBotStatus?.data);
  const [actionLoading, setActionLoading] = useState(null);

  const fetchBotStatus = useCallback(async () => {
    try {
      const data = await safeGet('/api/trading-bot/status');
      if (data?.success) {
        setBotStatus(data);
        setCached('botStatus', data, 30000); // 30 second TTL
      }
    } catch (err) {
      console.error('Error fetching bot status:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  const toggleBot = useCallback(async () => {
    setActionLoading('toggle');
    try {
      const endpoint = botStatus?.running ? 'stop' : 'start';
      await api.post(`/api/trading-bot/${endpoint}`);
      await fetchBotStatus();
      toast.success(botStatus?.running ? 'Bot stopped' : 'Bot started');
    } catch (err) {
      console.error('Failed to toggle bot:', err);
      toast.error('Failed to toggle bot');
    }
    setActionLoading(null);
  }, [botStatus?.running, fetchBotStatus]);

  const changeMode = useCallback(async (mode) => {
    setActionLoading('mode');
    try {
      await api.post(`/api/trading-bot/mode/${mode}`);
      await fetchBotStatus();
      toast.success(`Mode changed to ${mode}`);
    } catch (err) {
      console.error('Failed to change mode:', err);
      toast.error('Failed to change mode');
    }
    setActionLoading(null);
  }, [fetchBotStatus]);

  const updateRiskParams = useCallback(async (params) => {
    setActionLoading('risk');
    try {
      const { data } = await api.post('/api/trading-bot/risk-params', params);
      if (data?.success) {
        await fetchBotStatus();
        toast.success('Risk parameters updated');
        return true;
      } else {
        toast.error(data.error || 'Failed to update risk params');
        return false;
      }
    } catch (err) {
      console.error('Failed to update risk params:', err);
      toast.error('Failed to update risk parameters');
      return false;
    } finally {
      setActionLoading(null);
    }
  }, [fetchBotStatus]);

  useEffect(() => {
    // Use cache if available, otherwise delay HTTP fetch — WS is primary source
    const cached = getCached('botStatus');
    if (cached?.data && isFirstMount.current) {
      setBotStatus(cached.data);
      setLoading(false);
    } else {
      // Delay initial HTTP fetch to avoid startup burst — WS will deliver faster
      const timer = setTimeout(() => fetchBotStatus(), 3000);
      isFirstMount.current = false;
      return () => clearTimeout(timer);
    }
    isFirstMount.current = false;
    
    return safePolling(fetchBotStatus, pollInterval, { immediate: false, essential: false });
  }, [fetchBotStatus, pollInterval, getCached]);

  // WS botStatus is the primary data source — instant updates
  useEffect(() => {
    if (wsBotStatus) {
      setBotStatus(prev => ({ ...prev, ...wsBotStatus, success: true }));
      setCached('botStatus', { ...wsBotStatus, success: true }, 30000);
      setLoading(false);
    }
  }, [wsBotStatus, setCached]);

  return { botStatus, loading, actionLoading, toggleBot, changeMode, updateRiskParams, refresh: fetchBotStatus };
};
