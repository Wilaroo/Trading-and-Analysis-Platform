import React, { useState, useEffect, useCallback, memo } from 'react';
import { AlertTriangle, X, ExternalLink } from 'lucide-react';
import api from '../utils/api';

/**
 * Full-width warning banner that only renders when bot execution health is
 * CRITICAL (failure_rate ≥ 15% over last 24h). Silent otherwise.
 *
 * Shows top failing setups and aggregate R bled so user can triage fast.
 * Dismissable for the current session (sessionStorage).
 *
 * Polling: 60s, matches TradeExecutionHealthCard cadence.
 */
const BotHealthBanner = memo(({ onClickDetails }) => {
  const [report, setReport] = useState(null);
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem('bot-health-banner-dismissed') === '1'
  );

  const fetchHealth = useCallback(async () => {
    try {
      const res = await api.get('/api/trading-bot/execution-health?hours=24');
      if (res.data?.success) {
        setReport(res.data.report);
      }
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 60000);
    return () => clearInterval(id);
  }, [fetchHealth]);

  const dismiss = useCallback(() => {
    sessionStorage.setItem('bot-health-banner-dismissed', '1');
    setDismissed(true);
  }, []);

  // Only render when CRITICAL and not dismissed
  if (!report || report.alert_level !== 'critical' || dismissed) {
    return null;
  }

  const topSetups = Object.entries(report.failure_by_setup || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3);

  const ratePct = (report.failure_rate * 100).toFixed(1);

  return (
    <div
      data-testid="bot-health-banner"
      className="w-full bg-gradient-to-r from-red-950/80 via-red-900/60 to-red-950/80 border-y border-red-500/40 backdrop-blur-sm"
      role="alert"
    >
      <div className="max-w-[1800px] mx-auto px-4 py-2.5 flex items-center gap-4">
        <div className="flex items-center gap-2 shrink-0">
          <div className="relative">
            <AlertTriangle className="w-5 h-5 text-red-400" />
            <div className="absolute inset-0 animate-ping">
              <AlertTriangle className="w-5 h-5 text-red-500/40" />
            </div>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-red-300">
              Execution Health — CRITICAL
            </p>
            <p className="text-[12px] text-red-200/80">
              {report.n_failed} of {report.n_closed_trades} stops failed in last 24h
              ({ratePct}% — threshold 15%)
            </p>
          </div>
        </div>

        <div className="flex-1 flex items-center gap-3 overflow-x-auto">
          {topSetups.length > 0 && (
            <div className="flex items-center gap-2 px-2.5 py-1 rounded bg-black/30 border border-red-500/20">
              <span className="text-[11px] text-red-300/70 uppercase font-bold">
                Top failing
              </span>
              {topSetups.map(([setup, count]) => (
                <span
                  key={setup}
                  className="text-[12px] font-mono text-red-200 whitespace-nowrap"
                >
                  {setup}
                  <span className="text-red-400/70">×{count}</span>
                </span>
              ))}
            </div>
          )}

          {report.total_R_bled > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-black/30 border border-red-500/20">
              <span className="text-[11px] text-red-300/70 uppercase font-bold">
                Excess R bled
              </span>
              <span className="text-xs font-mono font-bold text-red-300">
                {report.total_R_bled.toFixed(1)}R
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {onClickDetails && (
            <button
              onClick={onClickDetails}
              data-testid="bot-health-banner-details"
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-200 text-[12px] font-bold transition-colors"
            >
              Details
              <ExternalLink className="w-3 h-3" />
            </button>
          )}
          <button
            onClick={dismiss}
            data-testid="bot-health-banner-dismiss"
            className="p-1 rounded hover:bg-red-500/20 text-red-300/70 hover:text-red-200 transition-colors"
            title="Dismiss for this session"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
});

BotHealthBanner.displayName = 'BotHealthBanner';

export default BotHealthBanner;
