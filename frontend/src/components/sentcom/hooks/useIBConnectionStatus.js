import { useCallback, useEffect, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useWsData } from '../../../contexts/WebSocketDataContext';

// Hook for IB Connection status — uses WS ibStatus as primary, HTTP polling as slow backup
export const useIBConnectionStatus = (pollInterval = 60000) => {
  const { ibStatus: wsIbStatus } = useWsData();
  const [ibConnected, setIbConnected] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await safeGet('/api/ib/pushed-data');
      setIbConnected(data.connected || false);
    } catch (err) {
      setIbConnected(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // WS ibStatus is the primary source — skip immediate HTTP fetch.
    // Fetch once after a short delay as fallback if WS hasn't delivered yet.
    const timer = setTimeout(() => {
      fetchStatus();
    }, 5000);
    return () => clearTimeout(timer);
  }, [fetchStatus]);

  // WS ibStatus is the primary data source — instant updates, no polling needed
  useEffect(() => {
    if (wsIbStatus) {
      setIbConnected(wsIbStatus.connected || false);
      setLoading(false);
    }
  }, [wsIbStatus]);

  // HTTP polling only as a slow fallback (every 60s)
  useEffect(() => {
    return safePolling(fetchStatus, pollInterval, { essential: false, immediate: false });
  }, [fetchStatus, pollInterval]);

  return { ibConnected, loading };
};
