/**
 * useBriefingLiveData — P2-A Morning Briefing rich UI.
 * One hook pulling both top-movers + overnight-sentiment data at once so
 * the modal can render the two new sections without two separate network
 * waterfalls. Backend builds the dynamic watchlist (positions + scanner
 * top-10 + core indices) server-side so the frontend stays thin.
 *
 * Returns:
 *   {
 *     loading, error,
 *     watchlist,              // symbols the backend chose for this briefing
 *     topMovers: [...],        // ranked by |change_pct|, success-only
 *     marketState,
 *     sentimentResults: [...], // ranked by notable then |swing|
 *     notableSwingCount,
 *     reload
 *   }
 */

import { useCallback, useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

async function _get(path) {
  try {
    const resp = await fetch(`${BACKEND_URL}${path}`);
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

export function useBriefingLiveData({ enabled = true } = {}) {
  const [topMovers, setTopMovers] = useState([]);
  const [marketState, setMarketState] = useState(null);
  const [sentimentResults, setSentimentResults] = useState([]);
  const [notableSwingCount, setNotableSwingCount] = useState(0);
  const [yesterdayCloseHours, setYesterdayCloseHours] = useState(null);
  const [yesterdayCloseStart, setYesterdayCloseStart] = useState(null);
  const [watchlist, setWatchlist] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    try {
      const [moversRes, sentRes] = await Promise.all([
        _get('/api/live/briefing-top-movers'),
        _get('/api/live/overnight-sentiment'),
      ]);
      if (moversRes && moversRes.success) {
        setTopMovers(
          (moversRes.snapshots || []).filter((s) => s.success).slice(0, 8)
        );
        setMarketState(moversRes.market_state || null);
        setWatchlist(moversRes.watchlist || []);
      } else {
        setTopMovers([]);
      }
      if (sentRes && sentRes.success) {
        setSentimentResults(sentRes.results || []);
        setNotableSwingCount(sentRes.notable_count || 0);
        setYesterdayCloseHours(sentRes.yesterday_close_hours || null);
        setYesterdayCloseStart(sentRes.yesterday_close_start || null);
        if (!moversRes || !moversRes.success) {
          setWatchlist(sentRes.watchlist || []);
        }
      } else {
        setSentimentResults([]);
        setNotableSwingCount(0);
        setYesterdayCloseHours(null);
        setYesterdayCloseStart(null);
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (enabled) reload();
  }, [enabled, reload]);

  return {
    loading,
    error,
    watchlist,
    topMovers,
    marketState,
    sentimentResults,
    notableSwingCount,
    yesterdayCloseHours,
    yesterdayCloseStart,
    reload,
  };
}

export default useBriefingLiveData;
