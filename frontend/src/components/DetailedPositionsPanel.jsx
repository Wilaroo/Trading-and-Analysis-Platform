/**
 * DetailedPositionsPanel.jsx - Detailed position list for Command Center
 * 
 * Shows all open positions in a detailed list format with:
 * - Entry/current/P&L data
 * - Setup type, trade style, timeframe
 * - Stop loss level + distance
 * - AI context (Gate, TQS)
 * - Holding time, MFE/MAE, R:R status
 * - Active monitoring alerts
 */
import React from 'react';
import { motion } from 'framer-motion';
import { 
  Target, TrendingUp, TrendingDown, Clock, Shield, Zap,
  BarChart3, Activity, AlertTriangle, Loader, Eye,
  ArrowUp, ArrowDown, Award
} from 'lucide-react';

const formatCurrency = (val) => {
  if (val == null || isNaN(val)) return '$0.00';
  return val.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
};

const formatHoldingTime = (entryTime) => {
  if (!entryTime) return '—';
  const now = new Date();
  const entry = new Date(entryTime);
  const diffMs = now - entry;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHrs = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays > 0) return `${diffDays}d ${diffHrs % 24}h`;
  if (diffHrs > 0) return `${diffHrs}h ${diffMins % 60}m`;
  return `${diffMins}m`;
};

const calcStopDistance = (pos) => {
  if (!pos.stop_price || !pos.current_price) return null;
  const dist = pos.direction === 'short'
    ? ((pos.stop_price - pos.current_price) / pos.current_price) * 100
    : ((pos.current_price - pos.stop_price) / pos.current_price) * 100;
  return dist;
};

const calcRiskReward = (pos) => {
  if (!pos.stop_price || !pos.entry_price) return null;
  const risk = Math.abs(pos.entry_price - pos.stop_price);
  if (risk === 0) return null;
  const targets = pos.target_prices || [];
  const target = targets[0];
  if (!target) return null;
  const reward = Math.abs(target - pos.entry_price);
  return { ratio: (reward / risk).toFixed(1), risk, reward };
};

// Single position row
const PositionRow = ({ pos, alerts, onClick }) => {
  const isProfit = (pos.pnl || 0) >= 0;
  const stopDist = calcStopDistance(pos);
  const rr = calcRiskReward(pos);
  const ai = pos.ai_context;
  const gate = ai?.confidence_gate;
  const posAlerts = alerts.filter(a => 
    a.message?.toLowerCase().includes(pos.symbol?.toLowerCase())
  );

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      onClick={() => onClick?.(pos)}
      className={`p-3 rounded-xl border cursor-pointer transition-all hover:border-white/20 ${
        isProfit 
          ? 'bg-emerald-500/5 border-emerald-500/15 hover:bg-emerald-500/10' 
          : 'bg-rose-500/5 border-rose-500/15 hover:bg-rose-500/10'
      }`}
      data-testid={`position-row-${pos.symbol}`}
    >
      {/* Row 1: Symbol + Direction + P&L */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-white">{pos.symbol}</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase ${
            pos.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
          }`}>
            {pos.direction === 'long' ? <ArrowUp className="w-2.5 h-2.5 inline" /> : <ArrowDown className="w-2.5 h-2.5 inline" />}
            {' '}{pos.direction}
          </span>
          {pos.source && (
            <span className={`text-[9px] px-1.5 py-0.5 rounded ${
              pos.source === 'bot' ? 'bg-purple-500/20 text-purple-400' : 'bg-blue-500/20 text-blue-400'
            }`}>
              {pos.source.toUpperCase()}
            </span>
          )}
          {pos.shares > 0 && (
            <span className="text-[10px] text-zinc-500">{pos.shares} sh</span>
          )}
        </div>
        <div className="text-right">
          <span className={`text-sm font-bold ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
            {isProfit ? '+' : ''}{formatCurrency(pos.pnl)}
          </span>
          <span className={`text-[10px] ml-1.5 ${isProfit ? 'text-emerald-400/70' : 'text-rose-400/70'}`}>
            {isProfit ? '+' : ''}{pos.pnl_percent?.toFixed(2)}%
          </span>
        </div>
      </div>

      {/* Row 2: Setup + Style + Timeframe + Holding */}
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        {pos.setup_type && pos.setup_type !== 'unknown' && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-400 border border-cyan-500/20">
            {pos.setup_variant || pos.setup_type}
          </span>
        )}
        {pos.trade_style && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-400 border border-white/10">
            {pos.trade_style.replace(/_/g, ' ')}
          </span>
        )}
        {pos.timeframe && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-400 border border-white/10">
            {pos.timeframe}
          </span>
        )}
        {pos.market_regime && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded border ${
            pos.market_regime === 'RISK_ON' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
            pos.market_regime === 'RISK_OFF' ? 'bg-rose-500/10 text-rose-400 border-rose-500/20' :
            'bg-white/5 text-zinc-400 border-white/10'
          }`}>
            {pos.market_regime}
          </span>
        )}
        <div className="flex items-center gap-1 text-[10px] text-zinc-500 ml-auto">
          <Clock className="w-2.5 h-2.5" />
          {formatHoldingTime(pos.entry_time)}
        </div>
      </div>

      {/* Row 3: Price levels + Stop distance + R:R */}
      <div className="grid grid-cols-4 gap-2 mb-2">
        <div>
          <p className="text-[9px] text-zinc-600 uppercase">Entry</p>
          <p className="text-[10px] text-zinc-300 font-medium">${pos.entry_price?.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[9px] text-zinc-600 uppercase">Current</p>
          <p className="text-[10px] text-white font-medium">${pos.current_price?.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[9px] text-zinc-600 uppercase">Stop</p>
          <div className="flex items-center gap-1">
            <p className="text-[10px] text-zinc-300 font-medium">
              {pos.stop_price ? `$${pos.stop_price.toFixed(2)}` : '—'}
            </p>
            {stopDist != null && (
              <span className={`text-[8px] ${stopDist > 3 ? 'text-emerald-400' : stopDist > 1 ? 'text-amber-400' : 'text-rose-400'}`}>
                ({stopDist.toFixed(1)}%)
              </span>
            )}
          </div>
        </div>
        <div>
          <p className="text-[9px] text-zinc-600 uppercase">R:R</p>
          <p className={`text-[10px] font-medium ${
            rr ? (parseFloat(rr.ratio) >= 2 ? 'text-emerald-400' : parseFloat(rr.ratio) >= 1 ? 'text-amber-400' : 'text-rose-400') : 'text-zinc-500'
          }`}>
            {rr ? `1:${rr.ratio}` : '—'}
          </p>
        </div>
      </div>

      {/* Row 4: MFE/MAE + Quality + AI Context */}
      <div className="flex items-center gap-2 flex-wrap">
        {(pos.mfe_pct > 0 || pos.mae_pct) && (
          <div className="flex items-center gap-2">
            {pos.mfe_pct > 0 && (
              <span className="text-[9px] text-emerald-400 flex items-center gap-0.5">
                <TrendingUp className="w-2.5 h-2.5" /> MFE +{pos.mfe_pct?.toFixed(2)}%
              </span>
            )}
            {pos.mae_pct < 0 && (
              <span className="text-[9px] text-rose-400 flex items-center gap-0.5">
                <TrendingDown className="w-2.5 h-2.5" /> MAE {pos.mae_pct?.toFixed(2)}%
              </span>
            )}
          </div>
        )}
        {pos.quality_grade && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded flex items-center gap-0.5 ${
            pos.quality_grade.startsWith('A') ? 'bg-emerald-500/15 text-emerald-400' :
            pos.quality_grade.startsWith('B') ? 'bg-cyan-500/15 text-cyan-400' :
            'bg-zinc-500/15 text-zinc-400'
          }`}>
            <Award className="w-2.5 h-2.5" /> {pos.quality_grade}
          </span>
        )}
        {gate && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded flex items-center gap-0.5 ${
            gate.decision === 'GO' ? 'bg-emerald-500/15 text-emerald-400' :
            gate.decision === 'REDUCE' ? 'bg-amber-500/15 text-amber-400' :
            'bg-rose-500/15 text-rose-400'
          }`}>
            <Zap className="w-2.5 h-2.5" /> Gate: {gate.decision}
          </span>
        )}
        {ai?.tqs_score != null && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded flex items-center gap-0.5 ${
            ai.tqs_score >= 70 ? 'bg-emerald-500/15 text-emerald-400' :
            ai.tqs_score >= 50 ? 'bg-amber-500/15 text-amber-400' :
            'bg-rose-500/15 text-rose-400'
          }`}>
            <BarChart3 className="w-2.5 h-2.5" /> TQS: {ai.tqs_score}
          </span>
        )}
      </div>

      {/* Row 5: Active monitoring alerts */}
      {posAlerts.length > 0 && (
        <div className="mt-2 pt-2 border-t border-white/5">
          {posAlerts.slice(0, 2).map((alert, i) => (
            <div key={i} className="flex items-center gap-1.5 text-[9px]">
              <AlertTriangle className={`w-2.5 h-2.5 flex-shrink-0 ${
                alert.type === 'warning' ? 'text-amber-400' : 'text-cyan-400'
              }`} />
              <span className="text-zinc-400 truncate">{alert.message}</span>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
};

const DetailedPositionsPanel = ({ positions, totalPnl, loading, alerts, onSelectPosition }) => {
  const openPositions = positions.filter(p => p.status !== 'closed');

  return (
    <div className="rounded-xl bg-gradient-to-br from-white/[0.06] to-white/[0.02] border border-white/10 overflow-hidden" data-testid="detailed-positions-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-black/30">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500/20 to-emerald-600/10 flex items-center justify-center">
            <Target className="w-3 h-3 text-emerald-400" />
          </div>
          <span className="text-sm font-bold text-white">Positions</span>
          <span className="text-[10px] text-zinc-500">({openPositions.length})</span>
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-sm font-bold ${(totalPnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {(totalPnl || 0) >= 0 ? '+' : ''}{formatCurrency(totalPnl || 0)}
          </span>
        </div>
      </div>

      {/* Content */}
      <div className="p-3 space-y-2 max-h-[400px] overflow-y-auto scrollbar-thin scrollbar-thumb-white/10">
        {loading && positions.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <Loader className="w-5 h-5 text-emerald-400 animate-spin" />
          </div>
        ) : openPositions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Eye className="w-8 h-8 text-zinc-600 mb-2" />
            <p className="text-xs text-zinc-500">No open positions</p>
            <p className="text-[10px] text-zinc-600 mt-1">Scanner is searching for opportunities...</p>
          </div>
        ) : (
          openPositions.map((pos, i) => (
            <PositionRow 
              key={pos.trade_id || pos.symbol || i} 
              pos={pos} 
              alerts={alerts || []}
              onClick={onSelectPosition}
            />
          ))
        )}
      </div>
    </div>
  );
};

export default DetailedPositionsPanel;
