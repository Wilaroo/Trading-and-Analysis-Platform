import { useCallback, useEffect, useRef, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useDataCache } from '../../../contexts';
import { useWsData } from '../../../contexts/WebSocketDataContext';

export const useSentComStatus = (pollInterval = 120000) => {  // HTTP backup only, WS is primary
  const { getCached, setCached } = useDataCache();
  const { sentcomData: wsSentcom } = useWsData();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedStatus = getCached('sentcomStatus');
  const [status, setStatus] = useState(cachedStatus?.data || null);
  const [loading, setLoading] = useState(!cachedStatus?.data);
  const [error, setError] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/status');
      if (data?.success) {
        setStatus(data.status);
        setCached('sentcomStatus', data.status, 30000); // 30 second TTL
      }
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // WS is primary source — delay initial HTTP fetch to reduce startup burst
    const cached = getCached('sentcomStatus');
    if (cached?.data && isFirstMount.current) {
      setStatus(cached.data);
      setLoading(false);
    } else {
      const timer = setTimeout(() => fetchStatus(), 6000);
      isFirstMount.current = false;
      return () => clearTimeout(timer);
    }
    isFirstMount.current = false;
    
    return safePolling(fetchStatus, pollInterval, { immediate: false });
  }, [fetchStatus, pollInterval, getCached]);

  // Subscribe to WS SentCom status updates (supplements polling)
  useEffect(() => {
    if (!wsSentcom?.status) return;
    setStatus(wsSentcom.status);
    setCached('sentcomStatus', wsSentcom.status, 30000);
    setLoading(false);
  }, [wsSentcom?.status, setCached]);

  return { status, loading, error, refresh: fetchStatus };
};
