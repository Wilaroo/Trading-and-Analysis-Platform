import { useCallback, useEffect, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';

// Hook for Market Session status
export const useMarketSession = (pollInterval = 120000) => {
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
    // Delay initial fetch — market session status changes once per session
    const timer = setTimeout(() => fetchSession(), 9000);
    const cleanup = safePolling(fetchSession, pollInterval, { immediate: false });
    return () => { clearTimeout(timer); cleanup(); };
  }, [fetchSession, pollInterval]);

  return { session, loading, refresh: fetchSession };
};
