import { useCallback, useEffect, useRef, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useDataCache } from '../../../contexts';
import { useWsData } from '../../../contexts/WebSocketDataContext';

export const useSentComPositions = (pollInterval = 60000) => {  // HTTP backup only, WS is primary
  const { getCached, setCached } = useDataCache();
  const { sentcomData: wsSentcom } = useWsData();
  const isFirstMount = useRef(true);
  
  // Initialize from cache if available
  const cachedPositions = getCached('sentcomPositions');
  const [positions, setPositions] = useState(cachedPositions?.data?.positions || []);
  const [totalPnl, setTotalPnl] = useState(cachedPositions?.data?.totalPnl || 0);
  const [loading, setLoading] = useState(!cachedPositions?.data);

  const fetchPositions = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/positions');
      if (data?.success) {
        setPositions(data.positions || []);
        setTotalPnl(data.total_pnl || 0);
        setCached('sentcomPositions', { positions: data.positions || [], totalPnl: data.total_pnl || 0 }, 15000); // 15 second TTL (positions update more frequently)
      }
    } catch (err) {
      console.error('Error fetching positions:', err);
    } finally {
      setLoading(false);
    }
  }, [setCached]);

  useEffect(() => {
    // WS is primary source — delay initial HTTP fetch to reduce startup burst
    const cached = getCached('sentcomPositions');
    if (cached?.data && isFirstMount.current) {
      setPositions(cached.data.positions || []);
      setTotalPnl(cached.data.totalPnl || 0);
      setLoading(false);
    } else {
      const timer = setTimeout(() => fetchPositions(), 4000);
      isFirstMount.current = false;
      return () => clearTimeout(timer);
    }
    isFirstMount.current = false;
    
    return safePolling(fetchPositions, pollInterval, { immediate: false, essential: true });
  }, [fetchPositions, pollInterval, getCached]);

  // Subscribe to WS positions data (supplements polling)
  useEffect(() => {
    if (!wsSentcom?.positions) return;
    const p = wsSentcom.positions;
    if (p.positions) {
      const positionsArray = Array.isArray(p.positions) ? p.positions : Object.values(p.positions);
      setPositions(positionsArray);
      if (p.total_pnl !== undefined) setTotalPnl(p.total_pnl);
      setCached('sentcomPositions', { positions: positionsArray, totalPnl: p.total_pnl || totalPnl }, 15000);
      setLoading(false);
    }
  }, [wsSentcom?.positions, setCached, totalPnl]);

  return { positions, totalPnl, loading, refresh: fetchPositions };
};
