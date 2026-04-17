/**
 * SentCom Intelligence Panel
 * ==========================
 * Shows SentCom's real-time trading brain:
 * - Current trading mode (Aggressive/Normal/Cautious/Defensive)
 * - Today's decision stats (evaluated, taken, skipped)
 * - Recent decision log with reasoning
 * - Confidence gate activity
 */
import React, { useState, useEffect, useCallback, memo } from 'react';
import {
  Brain, Shield, TrendingUp, TrendingDown, Activity,
  ChevronDown, ChevronRight, RefreshCw, Zap, Ban,
  ArrowUpRight, ArrowDownRight, Minus, Eye
} from 'lucide-react';
import { api } from '../../utils/api';

const MODE_STYLES = {
  aggressive: {
    bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400',
    label: 'AGGRESSIVE', icon: Zap, desc: 'Full position sizing, high-conviction entries',
  },
  normal: {
    bg: 'bg-cyan-500/10', border: 'border-cyan-500/30', text: 'text-cyan-400',
    label: 'NORMAL', icon: TrendingUp, desc: 'Standard sizing, balanced approach',
  },
  cautious: {
    bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400',
    label: 'CAUTIOUS', icon: Eye, desc: 'Reduced sizing, selective entries only',
  },
  defensive: {
    bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400',
    label: 'DEFENSIVE', icon: Shield, desc: 'Minimal exposure, capital preservation mode',
  },
};

const DECISION_ICONS = {
  GO: { icon: ArrowUpRight, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  REDUCE: { icon: Minus, color: 'text-amber-400', bg: 'bg-amber-500/10' },
  SKIP: { icon: Ban, color: 'text-red-400', bg: 'bg-red-500/10' },
};

const ScoreBreakdown = memo(({ decision }) => {
  // Parse additive scoring components from reasoning text
  const parsePoints = (reasoning) => {
    if (!reasoning || !reasoning.length) return [];
    const components = [];
    reasoning.forEach(r => {
      const match = r.match(/\(([+-]\d+)\)/);
      if (match) {
        const pts = parseInt(match[1]);
        let label = r.split('(')[0].trim();
        // Shorten common labels
        if (label.includes('Regime')) label = 'Regime';
        else if (label.includes('AI confirms') || label.includes('AI detects') || label.includes('AI sees')) label = 'AI Regime';
        else if (label.includes('Model consensus')) label = 'Consensus';
        else if (label.includes('Live ')) label = 'Live Model';
        else if (label.includes('Cross-model')) label = 'Cross-Model';
        else if (label.includes('Quality')) label = 'Quality';
        else if (label.includes('CNN-LSTM') || label.includes('temporal')) label = 'CNN-LSTM';
        else if (label.includes('CNN')) label = 'CNN Visual';
        else if (label.includes('TFT')) label = 'TFT Multi-TF';
        else if (label.includes('VAE')) label = 'VAE Regime';
        else if (label.includes('Learning') || label.includes('Historical')) label = 'Learning';
        components.push({ label, pts });
      }
    });
    return components;
  };

  const components = parsePoints(decision.reasoning);
  if (!components.length) return null;

  const maxPts = Math.max(...components.map(c => Math.abs(c.pts)), 1);

  return (
    <div className="mt-1.5 space-y-0.5" data-testid="score-breakdown">
      {components.map((c, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <span className="text-[9px] text-zinc-500 w-16 text-right truncate">{c.label}</span>
          <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden relative">
            <div
              className={`h-full rounded-full ${c.pts >= 0 ? 'bg-emerald-500/60' : 'bg-red-500/60'}`}
              style={{ width: `${Math.min(100, (Math.abs(c.pts) / maxPts) * 100)}%` }}
            />
          </div>
          <span className={`text-[9px] font-mono w-6 text-right ${
            c.pts > 0 ? 'text-emerald-400' : c.pts < 0 ? 'text-red-400' : 'text-zinc-500'
          }`}>
            {c.pts > 0 ? '+' : ''}{c.pts}
          </span>
        </div>
      ))}
    </div>
  );
});

const DecisionRow = memo(({ decision }) => {
  const style = DECISION_ICONS[decision.decision] || DECISION_ICONS.SKIP;
  const Icon = style.icon;
  const ts = decision.timestamp ? new Date(decision.timestamp) : null;
  const timeStr = ts ? ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';

  return (
    <div className="flex items-start gap-2 py-2 border-b border-white/5 last:border-0" data-testid={`decision-row-${decision.symbol}`}>
      <div className={`w-6 h-6 rounded flex items-center justify-center flex-shrink-0 mt-0.5 ${style.bg}`}>
        <Icon className={`w-3.5 h-3.5 ${style.color}`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-white">{decision.symbol}</span>
            <span className="text-[10px] text-zinc-500 font-mono">{decision.setup_type}</span>
            <span className={`text-[10px] font-medium ${style.color}`}>{decision.decision}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-[10px] font-mono ${
              decision.confidence_score >= 55 ? 'text-emerald-400' :
              decision.confidence_score >= 30 ? 'text-amber-400' :
              'text-zinc-400'
            }`}>{decision.confidence_score} pts</span>
            <span className="text-[10px] text-zinc-600">{timeStr}</span>
          </div>
        </div>
        {decision.reasoning && decision.reasoning.length > 0 && (
          <div className="mt-1 space-y-0.5">
            {decision.reasoning
              .filter(r => !r.includes('logged only') && !r.includes('AI regime'))
              .slice(0, 3).map((r, i) => (
              <p key={i} className="text-[10px] text-zinc-500 leading-tight">{r}</p>
            ))}
          </div>
        )}
        <ScoreBreakdown decision={decision} />
      </div>
    </div>
  );
});

const SentComIntelligencePanel = memo(({ onRefresh, wsConfidenceGate }) => {
  const [summary, setSummary] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showDecisions, setShowDecisions] = useState(true);

  // Use WebSocket data when available, fall back to REST on initial load
  useEffect(() => {
    if (wsConfidenceGate) {
      if (wsConfidenceGate.summary) setSummary(wsConfidenceGate.summary);
      if (wsConfidenceGate.decisions) setDecisions(wsConfidenceGate.decisions);
      setLoading(false);
    }
  }, [wsConfidenceGate]);

  const fetchData = useCallback(async () => {
    try {
      const [summaryRes, decisionsRes] = await Promise.allSettled([
        api.get('/api/ai-training/confidence-gate/summary'),
        api.get('/api/ai-training/confidence-gate/decisions?limit=20'),
      ]);

      if (summaryRes.status === 'fulfilled' && summaryRes.value.data?.success) {
        setSummary(summaryRes.value.data);
      }
      if (decisionsRes.status === 'fulfilled' && decisionsRes.value.data?.success) {
        setDecisions(decisionsRes.value.data.decisions || []);
      }
    } catch (err) {
      console.error('SentCom intelligence fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial REST fetch only (WebSocket handles subsequent updates)
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const modeKey = summary?.trading_mode || 'normal';
  const modeStyle = MODE_STYLES[modeKey] || MODE_STYLES.normal;
  const ModeIcon = modeStyle.icon;
  const today = summary?.today || { evaluated: 0, taken: 0, skipped: 0, take_rate: 0 };

  return (
    <div className="mt-6" data-testid="sentcom-intelligence-panel">
      {/* Section Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-violet-400" />
          <h2 className="text-base font-semibold text-white">SentCom Intelligence</h2>
          <span className="text-xs text-zinc-500">Pre-trade confidence gate</span>
        </div>
        <button
          onClick={fetchData}
          className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-400 transition-colors"
          data-testid="refresh-sentcom-intel-btn"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Trading Mode Banner */}
      <div className={`p-4 rounded-xl border ${modeStyle.border} ${modeStyle.bg} mb-4`} data-testid="trading-mode-banner">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${modeStyle.bg} border ${modeStyle.border}`}>
              <ModeIcon className={`w-5 h-5 ${modeStyle.text}`} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className={`text-sm font-bold ${modeStyle.text}`}>{modeStyle.label}</span>
                <span className="text-xs text-zinc-500">Trading Mode</span>
              </div>
              <p className="text-xs text-zinc-400 mt-0.5">{summary?.mode_reason || modeStyle.desc}</p>
            </div>
          </div>

          {/* Today's Stats */}
          <div className="flex items-center gap-4">
            <div className="text-center">
              <div className="text-lg font-bold text-white">{today.evaluated}</div>
              <div className="text-[10px] text-zinc-500">Evaluated</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-emerald-400">{today.taken}</div>
              <div className="text-[10px] text-zinc-500">Taken</div>
            </div>
            <div className="text-center">
              <div className="text-lg font-bold text-red-400">{today.skipped}</div>
              <div className="text-[10px] text-zinc-500">Skipped</div>
            </div>
            {today.evaluated > 0 && (
              <div className="text-center pl-3 border-l border-white/10">
                <div className={`text-lg font-bold ${today.take_rate >= 0.5 ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {(today.take_rate * 100).toFixed(0)}%
                </div>
                <div className="text-[10px] text-zinc-500">Take Rate</div>
              </div>
            )}
          </div>
        </div>

        {/* Streak indicator */}
        {summary?.streak && summary.streak.count >= 3 && (
          <div className="mt-3 pt-3 border-t border-white/5 flex items-center gap-2">
            <Activity className="w-3 h-3 text-zinc-500" />
            <span className="text-xs text-zinc-400">
              Current streak: <span className={summary.streak.type === 'GO' ? 'text-emerald-400' : summary.streak.type === 'SKIP' ? 'text-red-400' : 'text-amber-400'}>
                {summary.streak.count}x {summary.streak.type}
              </span>
            </span>
          </div>
        )}
      </div>

      {/* Decision Log */}
      <div className="rounded-xl border border-white/5 bg-white/[0.02] overflow-hidden">
        <button
          onClick={() => setShowDecisions(!showDecisions)}
          className="w-full flex items-center justify-between p-3 hover:bg-white/[0.02] transition-colors"
          data-testid="toggle-decisions-btn"
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-zinc-300">Recent Decisions</span>
            <span className="text-[10px] text-zinc-600">({decisions.length})</span>
          </div>
          {showDecisions ? <ChevronDown className="w-3.5 h-3.5 text-zinc-500" /> : <ChevronRight className="w-3.5 h-3.5 text-zinc-500" />}
        </button>

        {showDecisions && (
          <div className="px-3 pb-3 max-h-80 overflow-auto">
            {decisions.length === 0 ? (
              <div className="text-center py-6">
                <Brain className="w-8 h-8 text-zinc-700 mx-auto mb-2" />
                <p className="text-xs text-zinc-500">No decisions yet today</p>
                <p className="text-[10px] text-zinc-600 mt-1">SentCom will log each trade evaluation here</p>
              </div>
            ) : (
              decisions.map((d, i) => <DecisionRow key={`${d.symbol}-${d.timestamp}-${i}`} decision={d} />)
            )}
          </div>
        )}
      </div>
    </div>
  );
});

export default SentComIntelligencePanel;
