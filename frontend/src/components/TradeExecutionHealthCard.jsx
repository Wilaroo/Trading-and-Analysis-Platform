import React, { useState, useEffect, useCallback, memo } from 'react';
import { ShieldCheck, ShieldAlert, ShieldX, Loader2 } from 'lucide-react';
import api from '../utils/api';

/**
 * Compact inline badge showing 24h trade-execution health.
 *
 * Polls /api/trading-bot/execution-health every 60s. Displays:
 *   - ✅ emerald when failure_rate < 5%  (stops honored)
 *   - ⚠️  amber   when 5% ≤ failure_rate < 15%  (investigate)
 *   - ❌ red     when failure_rate ≥ 15%  (stop trading, fix stops)
 *   - grey      when < 5 closed trades in window
 *
 * Click → opens a tiny popover with failure_by_setup / total_R_bled.
 */
const TradeExecutionHealthCard = memo(({ onClick }) => {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await api.get('/api/trading-bot/execution-health?hours=24');
      if (res.data?.success) {
        setReport(res.data.report);
        setError(false);
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 60000); // every 60s
    return () => clearInterval(id);
  }, [fetchHealth]);

  if (loading) {
    return (
      <div
        className="flex items-center gap-1.5 px-2 py-1 rounded-lg border border-white/5 bg-black/30"
        data-testid="execution-health-loading"
      >
        <Loader2 className="w-3 h-3 text-zinc-500 animate-spin" />
        <span className="text-[9px] font-mono text-zinc-500">exec</span>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div
        className="flex items-center gap-1.5 px-2 py-1 rounded-lg border border-white/5 bg-black/30"
        data-testid="execution-health-error"
        title="Could not fetch execution health"
      >
        <ShieldX className="w-3 h-3 text-zinc-500" />
        <span className="text-[9px] font-mono text-zinc-500">exec ?</span>
      </div>
    );
  }

  const level = report.alert_level;
  const rate = report.failure_rate;
  const ratePct = (rate * 100).toFixed(1);
  const nClosed = report.n_closed_trades;

  const styles = {
    ok: {
      Icon: ShieldCheck,
      border: 'border-emerald-500/30',
      bg: 'bg-emerald-500/10',
      text: 'text-emerald-400',
      label: 'HEALTHY',
    },
    warning: {
      Icon: ShieldAlert,
      border: 'border-amber-500/40',
      bg: 'bg-amber-500/15',
      text: 'text-amber-400',
      label: 'WATCH',
    },
    critical: {
      Icon: ShieldX,
      border: 'border-red-500/50',
      bg: 'bg-red-500/20',
      text: 'text-red-400',
      label: 'CRITICAL',
    },
    insufficient_data: {
      Icon: ShieldCheck,
      border: 'border-zinc-600/30',
      bg: 'bg-zinc-800/40',
      text: 'text-zinc-500',
      label: 'LOW-DATA',
    },
  };

  const s = styles[level] || styles.insufficient_data;
  const { Icon } = s;

  const tooltip = level === 'insufficient_data'
    ? `Only ${nClosed} closed trades in last 24h`
    : `Stop-honor rate: ${(100 - rate * 100).toFixed(1)}% | ${report.n_failed}/${nClosed} failed | R bled: ${report.total_R_bled.toFixed(1)}`;

  return (
    <button
      onClick={onClick}
      data-testid="execution-health-card"
      title={tooltip}
      className={`flex items-center gap-1.5 px-2 py-1 rounded-lg border ${s.border} ${s.bg} hover:brightness-125 transition-all cursor-pointer`}
    >
      <Icon className={`w-3 h-3 ${s.text}`} />
      <span className={`text-[9px] font-mono font-bold ${s.text}`}>
        EXEC {s.label}
      </span>
      {level !== 'insufficient_data' && (
        <span className={`text-[9px] font-mono ${s.text} opacity-70`}>
          {ratePct}%
        </span>
      )}
    </button>
  );
});

TradeExecutionHealthCard.displayName = 'TradeExecutionHealthCard';

export default TradeExecutionHealthCard;
