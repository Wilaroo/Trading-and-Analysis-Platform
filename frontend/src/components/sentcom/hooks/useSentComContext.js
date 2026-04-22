import { useCallback, useEffect, useRef, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useDataCache } from '../../../contexts';
import { useWsData } from '../../../contexts/WebSocketDataContext';

export const useSentComContext = (pollInterval = 120000) => {
  const { getCached, setCached } = useDataCache();
  const { sentcomData: wsSentcom } = useWsData();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedContext = getCached('sentcomContext');
  const [context, setContext] = useState(cachedContext?.data || null);
  const [loading, setLoading] = useState(!cachedContext?.data);

  const fetchContext = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/context');
      if (data?.success) {
        setContext(data.context);
        setCached('sentcomContext', data.context, 60000); // 60 second TTL (context changes slowly)
      }
    } catch (err) {
      console.error('Error fetching context:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // WS is primary source — delay initial HTTP fetch to reduce startup burst
    const cached = getCached('sentcomContext');
    if (cached?.data && isFirstMount.current) {
      setContext(cached.data);
      setLoading(false);
    } else {
      const timer = setTimeout(() => fetchContext(), 8000);
      isFirstMount.current = false;
      return () => clearTimeout(timer);
    }
    isFirstMount.current = false;
    
    return safePolling(fetchContext, pollInterval, { immediate: false });
  }, [fetchContext, pollInterval, getCached]);

  // Subscribe to WS market context (supplements polling)
  useEffect(() => {
    if (!wsSentcom?.market_context) return;
    setContext(prev => ({ ...prev, ...wsSentcom.market_context }));
    setLoading(false);
  }, [wsSentcom?.market_context]);

  return { context, loading, refresh: fetchContext };
};
