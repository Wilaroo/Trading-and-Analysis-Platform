import { useCallback, useEffect, useRef, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useDataCache } from '../../../contexts';
import { useWsData } from '../../../contexts/WebSocketDataContext';

export const useSentComAlerts = (pollInterval = 60000) => {
  const { getCached, setCached } = useDataCache();
  const { scannerAlerts: wsAlerts } = useWsData();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedAlerts = getCached('sentcomAlerts');
  const [alerts, setAlerts] = useState(cachedAlerts?.data || []);
  const [loading, setLoading] = useState(!cachedAlerts?.data);

  const fetchAlerts = useCallback(async () => {
    try {
      // Bumped 5 → 20 (2026-04-30 v15) — operator flagged that the
      // alerts panel could only ever surface 5 setups, masking the
      // breadth of scanner output during fast tape sessions.
      const data = await safeGet('/api/sentcom/alerts?limit=20');
      if (data?.success) {
        setAlerts(data.alerts || []);
        setCached('sentcomAlerts', data.alerts || [], 15000); // 15 second TTL (alerts update frequently)
      }
    } catch (err) {
      console.error('Error fetching alerts:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // WS is primary source — small delay to reduce startup burst
    const cached = getCached('sentcomAlerts');
    if (cached?.data && isFirstMount.current) {
      setAlerts(cached.data);
      setLoading(false);
    } else {
      const timer = setTimeout(() => fetchAlerts(), 2000);
      isFirstMount.current = false;
      return () => clearTimeout(timer);
    }
    isFirstMount.current = false;
    
    return safePolling(fetchAlerts, pollInterval, { immediate: false, essential: true });
  }, [fetchAlerts, pollInterval, getCached]);

  // Subscribe to WS scanner alerts (supplements polling)
  useEffect(() => {
    if (!wsAlerts || wsAlerts.length === 0) return;
    // Bumped 5 → 20 to match the REST limit (2026-04-30 v15).
    setAlerts(wsAlerts.slice(0, 20));
    setLoading(false);
  }, [wsAlerts]);

  return { alerts, loading, refresh: fetchAlerts };
};
