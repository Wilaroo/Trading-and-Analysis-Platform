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
      // 2026-04-30 v16: operator wants every setup/idea visible — no
      // artificial cap. 500 is the backend's hard ceiling (sentcom.py
      // get_alerts) which is effectively unlimited for any RTH session.
      const data = await safeGet('/api/sentcom/alerts?limit=500');
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
    // 2026-04-30 v16: No cap — operator wants every setup visible to
    // tweak/grow the scanner faster. WebSocketDataContext upstream
    // already trims old alerts so unbounded growth is not a concern.
    setAlerts(wsAlerts);
    setLoading(false);
  }, [wsAlerts]);

  return { alerts, loading, refresh: fetchAlerts };
};
