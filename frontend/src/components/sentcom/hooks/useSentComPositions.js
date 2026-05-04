import { useCallback, useEffect, useRef, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';
import { useDataCache } from '../../../contexts';
import { useWsData } from '../../../contexts/WebSocketDataContext';

// 2026-05-04 v19.31.7 — surface realized PnL alongside unrealized + closed-today
// list for the HUD's CLOSE TODAY tile. Backend now returns
// total_realized_pnl / total_unrealized_pnl / total_pnl_today / closed_today[].
const _empty = {
  positions: [],
  totalPnl: 0,
  totalUnrealizedPnl: 0,
  totalRealizedPnl: 0,
  totalPnlToday: 0,
  closedToday: [],
  closedTodayCount: 0,
  winsToday: 0,
  lossesToday: 0,
};

export const useSentComPositions = (pollInterval = 60000) => {  // HTTP backup only, WS is primary
  const { getCached, setCached } = useDataCache();
  const { sentcomData: wsSentcom } = useWsData();
  const isFirstMount = useRef(true);

  const cachedPositions = getCached('sentcomPositions');
  const [positions, setPositions] = useState(cachedPositions?.data?.positions || _empty.positions);
  const [totalPnl, setTotalPnl] = useState(cachedPositions?.data?.totalPnl ?? _empty.totalPnl);
  const [totalUnrealizedPnl, setTotalUnrealizedPnl] = useState(
    cachedPositions?.data?.totalUnrealizedPnl ?? _empty.totalUnrealizedPnl
  );
  const [totalRealizedPnl, setTotalRealizedPnl] = useState(
    cachedPositions?.data?.totalRealizedPnl ?? _empty.totalRealizedPnl
  );
  const [totalPnlToday, setTotalPnlToday] = useState(
    cachedPositions?.data?.totalPnlToday ?? _empty.totalPnlToday
  );
  const [closedToday, setClosedToday] = useState(cachedPositions?.data?.closedToday || _empty.closedToday);
  const [winsToday, setWinsToday] = useState(cachedPositions?.data?.winsToday ?? _empty.winsToday);
  const [lossesToday, setLossesToday] = useState(cachedPositions?.data?.lossesToday ?? _empty.lossesToday);
  const [loading, setLoading] = useState(!cachedPositions?.data);

  const _applyPayload = useCallback((data) => {
    if (!data) return;
    const positionsArr = Array.isArray(data.positions)
      ? data.positions
      : (data.positions ? Object.values(data.positions) : []);
    setPositions(positionsArr);
    setTotalPnl(data.total_pnl ?? 0);
    setTotalUnrealizedPnl(data.total_unrealized_pnl ?? data.total_pnl ?? 0);
    setTotalRealizedPnl(data.total_realized_pnl ?? 0);
    setTotalPnlToday(
      data.total_pnl_today ?? ((data.total_unrealized_pnl ?? data.total_pnl ?? 0) + (data.total_realized_pnl ?? 0))
    );
    setClosedToday(Array.isArray(data.closed_today) ? data.closed_today : []);
    setWinsToday(data.wins_today ?? 0);
    setLossesToday(data.losses_today ?? 0);
    setCached(
      'sentcomPositions',
      {
        positions: positionsArr,
        totalPnl: data.total_pnl ?? 0,
        totalUnrealizedPnl: data.total_unrealized_pnl ?? data.total_pnl ?? 0,
        totalRealizedPnl: data.total_realized_pnl ?? 0,
        totalPnlToday: data.total_pnl_today ?? 0,
        closedToday: Array.isArray(data.closed_today) ? data.closed_today : [],
        winsToday: data.wins_today ?? 0,
        lossesToday: data.losses_today ?? 0,
      },
      15000,
    );
  }, [setCached]);

  const fetchPositions = useCallback(async () => {
    try {
      const data = await safeGet('/api/sentcom/positions');
      if (data?.success) {
        _applyPayload(data);
      }
    } catch (err) {
      console.error('Error fetching positions:', err);
    } finally {
      setLoading(false);
    }
  }, [_applyPayload]);

  useEffect(() => {
    const cached = getCached('sentcomPositions');
    if (cached?.data && isFirstMount.current) {
      setPositions(cached.data.positions || []);
      setTotalPnl(cached.data.totalPnl ?? 0);
      setTotalUnrealizedPnl(cached.data.totalUnrealizedPnl ?? 0);
      setTotalRealizedPnl(cached.data.totalRealizedPnl ?? 0);
      setTotalPnlToday(cached.data.totalPnlToday ?? 0);
      setClosedToday(cached.data.closedToday || []);
      setWinsToday(cached.data.winsToday ?? 0);
      setLossesToday(cached.data.lossesToday ?? 0);
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
      _applyPayload(p);
    }
  }, [wsSentcom?.positions, _applyPayload]);

  return {
    positions,
    totalPnl,                 // legacy (= unrealized only — kept for back-compat)
    totalUnrealizedPnl,
    totalRealizedPnl,
    totalPnlToday,            // realized + unrealized = operator's day-PnL
    closedToday,
    winsToday,
    lossesToday,
    loading,
    refresh: fetchPositions,
  };
};
