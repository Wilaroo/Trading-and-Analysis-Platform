import { useCallback, useEffect, useState } from 'react';
import { safeGet } from '../../../utils/api';
import { safePolling } from '../../../utils/safePolling';

// Hook for AI Insights data — uses single aggregated endpoint instead of 5 separate calls
export const useAIInsights = (pollInterval = 60000) => {
  const [shadowDecisions, setShadowDecisions] = useState([]);
  const [shadowPerformance, setShadowPerformance] = useState(null);
  const [timeseriesStatus, setTimeseriesStatus] = useState(null);
  const [predictionAccuracy, setPredictionAccuracy] = useState(null);
  const [recentPredictions, setRecentPredictions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchInsights = useCallback(async () => {
    try {
      const data = await safeGet('/api/ai-modules/insights-summary');
      if (data?.success) {
        setShadowDecisions(data.shadow_decisions || []);
        setShadowPerformance(data.shadow_performance || null);
        setTimeseriesStatus(data.timeseries_status || null);
        setPredictionAccuracy(data.prediction_accuracy || null);
        setRecentPredictions(data.recent_predictions || []);
      }
    } catch (err) {
      console.error('Error fetching AI insights:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Single call instead of 5 — reduced startup delay from 12s to 6s
    const timer = setTimeout(() => fetchInsights(), 6000);
    const cleanup = safePolling(fetchInsights, pollInterval, { immediate: false });
    return () => { clearTimeout(timer); cleanup(); };
  }, [fetchInsights, pollInterval]);

  return { shadowDecisions, shadowPerformance, timeseriesStatus, predictionAccuracy, recentPredictions, loading, refresh: fetchInsights };
};
