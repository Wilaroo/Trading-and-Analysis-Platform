import { useCallback, useEffect, useRef, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useDataCache } from '../../../contexts';
import { useWsData } from '../../../contexts/WebSocketDataContext';

// 2026-05-07 v19.34.37 — anti-flicker grace period.
// If the WS pushed alerts within the last WS_FRESHNESS_MS, consider WS
// authoritative and ignore REST poll updates (which historically returned
// a smaller set than WS due to a backend cap mismatch). Pre-fix the REST
// poll fired every 60s and clobbered the rich 9-card WS state with a
// 5-card REST state, which the operator perceived as cards "blipping in
// and out" every 10-12 seconds.
const WS_FRESHNESS_MS = 30_000;

export const useSentComAlerts = (pollInterval = 60000) => {
  const { getCached, setCached } = useDataCache();
  const { scannerAlerts: wsAlerts } = useWsData();
  const isFirstMount = useRef(true);
  const lastWsUpdateAt = useRef(0);

  // Initialize from cache if available
  const cachedAlerts = getCached('sentcomAlerts');
  const [alerts, setAlerts] = useState(cachedAlerts?.data || []);
  const [loading, setLoading] = useState(!cachedAlerts?.data);

  const fetchAlerts = useCallback(async () => {
    try {
      // 2026-05-07 v19.34.37 — skip REST overwrite when WS is fresh.
      // The WS push is the primary source and carries the full alert
      // list. REST is a resilience fallback only — it should never
      // downgrade fresh WS state to a smaller (or stale) snapshot.
      if (Date.now() - lastWsUpdateAt.current < WS_FRESHNESS_MS) {
        return;
      }
      // 2026-04-30 v16: operator wants every setup/idea visible — no
      // artificial cap. 500 is the backend's hard ceiling (sentcom.py
      // get_alerts) which is effectively unlimited for any RTH session.
      const data = await safeGet('/api/sentcom/alerts?limit=500');
      if (data?.success) {
        setAlerts(data.alerts || []);
        setCached('sentcomAlerts', data.alerts || [], 15000); // 15 second TTL
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

  // Subscribe to WS scanner alerts (primary source)
  useEffect(() => {
    if (!wsAlerts || wsAlerts.length === 0) return;
    lastWsUpdateAt.current = Date.now();
    // 2026-04-30 v16: No cap — operator wants every setup visible to
    // tweak/grow the scanner faster. WebSocketDataContext upstream
    // already trims old alerts so unbounded growth is not a concern.
    setAlerts(wsAlerts);
    setLoading(false);
  }, [wsAlerts]);

  return { alerts, loading, refresh: fetchAlerts };
};
