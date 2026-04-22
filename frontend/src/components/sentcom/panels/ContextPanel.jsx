import React from 'react';
import { Loader, Wifi } from 'lucide-react';
import { GlassCard } from '../primitives/GlassCard';

export const ContextPanel = ({ context, loading }) => {
  if (loading) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-24">
          <Loader className="w-5 h-5 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-6 h-6 rounded-full bg-cyan-500/20 flex items-center justify-center">
          <Wifi className="w-3 h-3 text-cyan-400" />
        </div>
        <span className="text-sm font-medium text-zinc-300">Market Context</span>
      </div>
      
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">Regime</span>
          <span className={`text-xs font-bold ${
            context?.regime === 'RISK_ON' ? 'text-emerald-400' :
            context?.regime === 'RISK_OFF' ? 'text-rose-400' :
            'text-zinc-400'
          }`}>
            {context?.regime || 'UNKNOWN'}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">SPY Trend</span>
          <span className={`text-xs font-bold ${
            context?.spy_trend === 'Bullish' ? 'text-emerald-400' :
            context?.spy_trend === 'Bearish' ? 'text-rose-400' :
            'text-zinc-400'
          }`}>
            {context?.spy_trend || '--'}
          </span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">VIX</span>
          <span className="text-xs font-bold text-zinc-300">{context?.vix || '--'}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-xs text-zinc-500">Market</span>
          <span className={`text-xs font-bold ${context?.market_open ? 'text-emerald-400' : 'text-zinc-500'}`}>
            {context?.market_open ? 'OPEN' : 'CLOSED'}
          </span>
        </div>
      </div>
    </GlassCard>
  );
};
