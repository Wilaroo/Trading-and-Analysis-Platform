/**
 * DetailedPositionsPanel.jsx - Rich position board for Command Center
 *
 * Shows all open positions with:
 * - Market value, cost basis, portfolio weight %
 * - Risk level badges (ok/warning/danger/critical)
 * - Today's intraday change vs total P&L
 * - Missing-stop warnings for IB-only positions
 * - Setup, style, regime, holding time, MFE/MAE, quality
 * - Sortable by P&L, value, % change
 */
import React, { useState } from 'react';
import { motion } from 'framer-motion';
import ClickableTicker from './shared/ClickableTicker';
import {
  Target, TrendingUp, TrendingDown, Clock, Shield, Zap,
  BarChart3, Activity, AlertTriangle, Loader, Eye,
  ArrowUp, ArrowDown, Award, ChevronDown, DollarSign,
  ShieldAlert, Percent
} from 'lucide-react';

const fmt = (val) => {
  if (val == null || isNaN(val)) return '$0';
  const abs = Math.abs(val);
  if (abs >= 1000) return `$${(val / 1000).toFixed(1)}k`;
  return `$${val.toFixed(0)}`;
};

const fmtFull = (val) => {
  if (val == null || isNaN(val)) return '$0.00';
  return val.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
};

const holdTime = (entryTime) => {
  if (!entryTime) return null;
  const ms = Date.now() - new Date(entryTime).getTime();
  const mins = Math.floor(ms / 60000);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);
  if (days > 0) return `${days}d ${hrs % 24}h`;
  if (hrs > 0) return `${hrs}h ${mins % 60}m`;
  return `${mins}m`;
};

const stopDist = (pos) => {
  if (!pos.stop_price || !pos.current_price) return null;
  const d = pos.direction === 'short'
    ? ((pos.stop_price - pos.current_price) / pos.current_price) * 100
    : ((pos.current_price - pos.stop_price) / pos.current_price) * 100;
  return d;
};

const rrCalc = (pos) => {
  if (!pos.stop_price || !pos.entry_price) return null;
  const risk = Math.abs(pos.entry_price - pos.stop_price);
  if (risk === 0) return null;
  const target = (pos.target_prices || [])[0];
  if (!target) return null;
  return (Math.abs(target - pos.entry_price) / risk).toFixed(1);
};

const RISK_STYLES = {
  critical: { bg: 'bg-red-500/20', border: 'border-red-500/40', text: 'text-red-400', label: 'CRITICAL' },
  danger:   { bg: 'bg-orange-500/15', border: 'border-orange-500/30', text: 'text-orange-400', label: 'HIGH RISK' },
  warning:  { bg: 'bg-amber-500/10', border: 'border-amber-500/20', text: 'text-amber-400', label: 'CAUTION' },
  ok:       { bg: '', border: '', text: '', label: '' },
};

const SORT_OPTIONS = [
  { id: 'pnl', label: 'P&L $' },
  { id: 'pnl_pct', label: 'P&L %' },
  { id: 'value', label: 'Value' },
  { id: 'weight', label: 'Weight' },
];

// ─── Single Position Row ───────────────────────────────────────
const PositionRow = ({ pos, onClick }) => {
  const isProfit = (pos.pnl || 0) >= 0;
  const sd = stopDist(pos);
  const rr = rrCalc(pos);
  const ai = pos.ai_context;
  const gate = ai?.confidence_gate;
  const risk = RISK_STYLES[pos.risk_level] || RISK_STYLES.ok;
  const ht = holdTime(pos.entry_time);
  const isIbOnly = pos.source === 'ib';
  const noStop = !pos.stop_price;

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      onClick={() => onClick?.(pos)}
      className={`p-3 rounded-xl border cursor-pointer transition-all hover:border-white/25 ${
        pos.risk_level === 'critical' ? 'bg-red-500/8 border-red-500/30' :
        pos.risk_level === 'danger' ? 'bg-orange-500/5 border-orange-500/20' :
        isProfit ? 'bg-emerald-500/5 border-emerald-500/15 hover:bg-emerald-500/10'
                 : 'bg-rose-500/5 border-rose-500/15 hover:bg-rose-500/10'
      }`}
      data-testid={`position-row-${pos.symbol}`}
    >
      {/* Row 1: Symbol + Source + P&L + Value */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <ClickableTicker symbol={pos.symbol} variant="inline" className="text-sm font-bold" />
          <span className={`text-[11px] px-1.5 py-0.5 rounded font-bold uppercase ${
            pos.direction === 'long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
          }`}>
            {pos.direction === 'long' ? <ArrowUp className="w-2.5 h-2.5 inline" /> : <ArrowDown className="w-2.5 h-2.5 inline" />}
            {' '}{pos.direction}
          </span>
          <span className={`text-[11px] px-1.5 py-0.5 rounded font-medium ${
            pos.source === 'bot' ? 'bg-purple-500/20 text-purple-400' : 'bg-blue-500/20 text-blue-400'
          }`}>
            {pos.source === 'bot' ? 'BOT' : 'IB'}
          </span>
          {pos.shares > 0 && (
            <span className="text-[12px] text-zinc-500">{pos.shares.toLocaleString()} sh</span>
          )}
          {/* Portfolio weight */}
          {pos.portfolio_weight > 0 && (
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-500 border border-white/5">
              {pos.portfolio_weight.toFixed(1)}%
            </span>
          )}
        </div>
        <div className="text-right flex items-center gap-3">
          {/* Market value */}
          <div className="text-right">
            <span className="text-[12px] text-zinc-500 block">{fmt(pos.market_value)}</span>
          </div>
          {/* Total P&L */}
          <div className="text-right">
            <span className={`text-sm font-bold ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
              {isProfit ? '+' : ''}{fmtFull(pos.pnl)}
            </span>
            <span className={`text-[12px] ml-1 ${isProfit ? 'text-emerald-400/70' : 'text-rose-400/70'}`}>
              {isProfit ? '+' : ''}{pos.pnl_percent?.toFixed(2)}%
            </span>
          </div>
        </div>
      </div>

      {/* Row 2: Risk badge + Setup info + Holding time */}
      <div className="flex items-center gap-1.5 mb-2 flex-wrap">
        {/* Risk level badge */}
        {risk.label && (
          <span className={`text-[8px] px-1.5 py-0.5 rounded font-black uppercase tracking-wider ${risk.bg} ${risk.text} border ${risk.border} flex items-center gap-0.5`}>
            <ShieldAlert className="w-2.5 h-2.5" />
            {risk.label}
          </span>
        )}
        {/* No stop warning for IB positions */}
        {noStop && (
          <span className="text-[8px] px-1.5 py-0.5 rounded font-bold uppercase bg-amber-500/15 text-amber-400 border border-amber-500/20 flex items-center gap-0.5">
            <AlertTriangle className="w-2.5 h-2.5" />
            NO STOP
          </span>
        )}
        {pos.setup_type && pos.setup_type !== 'unknown' && pos.setup_type !== '' && (
          <span className="text-[11px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-400 border border-cyan-500/20">
            {(pos.setup_variant || pos.setup_type).replace(/_/g, ' ')}
          </span>
        )}
        {pos.trade_style && pos.trade_style !== '' && (
          <span className="text-[11px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-400 border border-white/10">
            {pos.trade_style.replace(/_/g, ' ')}
          </span>
        )}
        {pos.timeframe && pos.timeframe !== '' && (
          <span className="text-[11px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-400 border border-white/10">
            {pos.timeframe}
          </span>
        )}
        {pos.market_regime && pos.market_regime !== '' && pos.market_regime !== 'UNKNOWN' && (
          <span className={`text-[11px] px-1.5 py-0.5 rounded border ${
            pos.market_regime === 'RISK_ON' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
            pos.market_regime === 'RISK_OFF' ? 'bg-rose-500/10 text-rose-400 border-rose-500/20' :
            'bg-white/5 text-zinc-400 border-white/10'
          }`}>
            {pos.market_regime.replace(/_/g, ' ')}
          </span>
        )}
        {ht && (
          <div className="flex items-center gap-1 text-[12px] text-zinc-500 ml-auto">
            <Clock className="w-2.5 h-2.5" />
            {ht}
          </div>
        )}
      </div>

      {/* Row 3: Price levels — responsive grid */}
      <div className="grid grid-cols-4 gap-2 mb-2">
        <div>
          <p className="text-[11px] text-zinc-600 uppercase">Entry</p>
          <p className="text-[12px] text-zinc-300 font-mono">${pos.entry_price?.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[11px] text-zinc-600 uppercase">Current</p>
          <p className="text-[12px] text-white font-mono font-medium">${pos.current_price?.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-[11px] text-zinc-600 uppercase">Stop</p>
          <div className="flex items-center gap-1">
            <p className="text-[12px] text-zinc-300 font-mono">
              {pos.stop_price ? `$${pos.stop_price.toFixed(2)}` : <span className="text-zinc-600">--</span>}
            </p>
            {sd != null && (
              <span className={`text-[8px] ${sd > 3 ? 'text-emerald-400' : sd > 1 ? 'text-amber-400' : 'text-rose-400'}`}>
                ({sd.toFixed(1)}%)
              </span>
            )}
          </div>
        </div>
        <div>
          <p className="text-[11px] text-zinc-600 uppercase">R:R</p>
          <p className={`text-[12px] font-mono ${
            rr ? (parseFloat(rr) >= 2 ? 'text-emerald-400' : parseFloat(rr) >= 1 ? 'text-amber-400' : 'text-rose-400') : 'text-zinc-600'
          }`}>
            {rr ? `1:${rr}` : '--'}
          </p>
        </div>
      </div>

      {/* Row 4: AI Context + Quality + MFE/MAE */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {(pos.mfe_pct > 0 || pos.mae_pct < 0) && (
          <>
            {pos.mfe_pct > 0 && (
              <span className="text-[11px] text-emerald-400 flex items-center gap-0.5">
                <TrendingUp className="w-2.5 h-2.5" /> +{pos.mfe_pct?.toFixed(1)}%
              </span>
            )}
            {pos.mae_pct < 0 && (
              <span className="text-[11px] text-rose-400 flex items-center gap-0.5">
                <TrendingDown className="w-2.5 h-2.5" /> {pos.mae_pct?.toFixed(1)}%
              </span>
            )}
          </>
        )}
        {pos.quality_grade && pos.quality_grade !== '' && (
          <span className={`text-[11px] px-1.5 py-0.5 rounded flex items-center gap-0.5 ${
            pos.quality_grade.startsWith('A') ? 'bg-emerald-500/15 text-emerald-400' :
            pos.quality_grade.startsWith('B') ? 'bg-cyan-500/15 text-cyan-400' :
            pos.quality_grade.startsWith('C') ? 'bg-amber-500/15 text-amber-400' :
            'bg-zinc-500/15 text-zinc-400'
          }`}>
            <Award className="w-2.5 h-2.5" /> Grade {pos.quality_grade}
          </span>
        )}
        {gate && (
          <span className={`text-[11px] px-1.5 py-0.5 rounded flex items-center gap-0.5 ${
            gate.decision === 'GO' ? 'bg-emerald-500/15 text-emerald-400' :
            gate.decision === 'REDUCE' ? 'bg-amber-500/15 text-amber-400' :
            'bg-rose-500/15 text-rose-400'
          }`}>
            <Zap className="w-2.5 h-2.5" /> Gate: {gate.decision}
          </span>
        )}
        {ai?.tqs_score != null && (
          <span className={`text-[11px] px-1.5 py-0.5 rounded flex items-center gap-0.5 ${
            ai.tqs_score >= 70 ? 'bg-emerald-500/15 text-emerald-400' :
            ai.tqs_score >= 50 ? 'bg-amber-500/15 text-amber-400' :
            'bg-rose-500/15 text-rose-400'
          }`}>
            <BarChart3 className="w-2.5 h-2.5" /> TQS: {ai.tqs_score}
          </span>
        )}
        {/* Today's change (intraday) */}
        {pos.today_change !== 0 && pos.today_change != null && (
          <span className={`text-[11px] px-1.5 py-0.5 rounded flex items-center gap-0.5 ml-auto ${
            pos.today_change >= 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'
          }`}>
            <Activity className="w-2.5 h-2.5" />
            Today: {pos.today_change >= 0 ? '+' : ''}{fmt(pos.today_change)}
          </span>
        )}
      </div>
    </motion.div>
  );
};

// ─── Main Panel ────────────────────────────────────────────────
const DetailedPositionsPanel = ({
  positions,
  totalPnl,
  loading,
  alerts,
  onSelectPosition,
  totalMarketValue,
  totalTodayChange,
  botCount,
  ibCount,
  positionsAtRisk,
}) => {
  const [sortBy, setSortBy] = useState('pnl');
  const [sortAsc, setSortAsc] = useState(false);
  const [filterSource, setFilterSource] = useState('all');

  const openPositions = positions.filter(p => p.status !== 'closed');

  // Filter by source
  const filtered = filterSource === 'all'
    ? openPositions
    : openPositions.filter(p => p.source === filterSource);

  // Sort
  const sorted = [...filtered].sort((a, b) => {
    let va, vb;
    if (sortBy === 'pnl') { va = a.pnl || 0; vb = b.pnl || 0; }
    else if (sortBy === 'pnl_pct') { va = a.pnl_percent || 0; vb = b.pnl_percent || 0; }
    else if (sortBy === 'value') { va = a.market_value || 0; vb = b.market_value || 0; }
    else if (sortBy === 'weight') { va = a.portfolio_weight || 0; vb = b.portfolio_weight || 0; }
    else { va = a.pnl || 0; vb = b.pnl || 0; }
    return sortAsc ? va - vb : vb - va;
  });

  const toggleSort = (id) => {
    if (sortBy === id) setSortAsc(!sortAsc);
    else { setSortBy(id); setSortAsc(false); }
  };

  return (
    <div className="rounded-xl bg-gradient-to-br from-white/[0.06] to-white/[0.02] border border-white/10 overflow-hidden" data-testid="detailed-positions-panel">
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/10 bg-black/30">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500/20 to-emerald-600/10 flex items-center justify-center">
              <Target className="w-3 h-3 text-emerald-400" />
            </div>
            <span className="text-sm font-bold text-white">Positions</span>
            <span className="text-[12px] text-zinc-500">({openPositions.length})</span>
            {positionsAtRisk > 0 && (
              <span className="text-[11px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30 flex items-center gap-0.5 font-bold">
                <ShieldAlert className="w-2.5 h-2.5" /> {positionsAtRisk} at risk
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {totalMarketValue > 0 && (
              <span className="text-[12px] text-zinc-400">
                <DollarSign className="w-3 h-3 inline" />
                {(totalMarketValue / 1000).toFixed(0)}k invested
              </span>
            )}
            <span className={`text-sm font-bold ${(totalPnl || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {(totalPnl || 0) >= 0 ? '+' : ''}{fmtFull(totalPnl || 0)}
            </span>
          </div>
        </div>

        {/* Sort + Source filter bar */}
        <div className="flex items-center justify-between gap-2">
          {/* Sort buttons */}
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-zinc-600 uppercase mr-1">Sort:</span>
            {SORT_OPTIONS.map(opt => (
              <button
                key={opt.id}
                onClick={() => toggleSort(opt.id)}
                className={`text-[11px] px-2 py-0.5 rounded transition-colors ${
                  sortBy === opt.id
                    ? 'bg-white/10 text-white font-medium'
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
                data-testid={`sort-${opt.id}`}
              >
                {opt.label}
                {sortBy === opt.id && (
                  <ChevronDown className={`w-2.5 h-2.5 inline ml-0.5 transition-transform ${sortAsc ? 'rotate-180' : ''}`} />
                )}
              </button>
            ))}
          </div>
          {/* Source filter */}
          <div className="flex items-center gap-1">
            {['all', 'bot', 'ib'].map(src => (
              <button
                key={src}
                onClick={() => setFilterSource(src)}
                className={`text-[11px] px-2 py-0.5 rounded transition-colors ${
                  filterSource === src
                    ? src === 'bot' ? 'bg-purple-500/20 text-purple-400'
                    : src === 'ib' ? 'bg-blue-500/20 text-blue-400'
                    : 'bg-white/10 text-white'
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
                data-testid={`filter-source-${src}`}
              >
                {src === 'all' ? `All (${openPositions.length})`
                  : src === 'bot' ? `Bot (${botCount || 0})`
                  : `IB (${ibCount || 0})`}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="p-3 space-y-2 max-h-[500px] overflow-y-auto scrollbar-thin scrollbar-thumb-white/10">
        {loading && positions.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <Loader className="w-5 h-5 text-emerald-400 animate-spin" />
          </div>
        ) : sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Eye className="w-8 h-8 text-zinc-600 mb-2" />
            <p className="text-xs text-zinc-500">
              {filterSource !== 'all' ? `No ${filterSource.toUpperCase()} positions` : 'No open positions'}
            </p>
            <p className="text-[12px] text-zinc-600 mt-1">Scanner is searching for opportunities...</p>
          </div>
        ) : (
          sorted.map((pos, i) => (
            <PositionRow
              key={pos.trade_id || pos.symbol || i}
              pos={pos}
              onClick={onSelectPosition}
            />
          ))
        )}
      </div>
    </div>
  );
};

export default DetailedPositionsPanel;
