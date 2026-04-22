import { useCallback, useEffect, useRef, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useDataCache } from '../../../contexts';

export const useSentComSetups = (pollInterval = 120000) => {
  const { getCached, setCached } = useDataCache();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedSetups = getCached('sentcomSetups');
  const [setups, setSetups] = useState(cachedSetups?.data || []);
  const [loading, setLoading] = useState(!cachedSetups?.data);

  const fetchSetups = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/setups');
      if (data?.success) {
        setSetups(data.setups || []);
        setCached('sentcomSetups', data.setups || [], 30000); // 30 second TTL
      }
    } catch (err) {
      console.error('Error fetching setups:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // Delay initial fetch to reduce startup burst
    const cached = getCached('sentcomSetups');
    if (cached?.data && isFirstMount.current) {
      setSetups(cached.data);
      setLoading(false);
    } else {
      const timer = setTimeout(() => fetchSetups(), 5000);
      isFirstMount.current = false;
      return () => clearTimeout(timer);
    }
    isFirstMount.current = false;
    
    return safePolling(fetchSetups, pollInterval, { immediate: false });
  }, [fetchSetups, pollInterval, getCached]);

  return { setups, loading, refresh: fetchSetups };
};
