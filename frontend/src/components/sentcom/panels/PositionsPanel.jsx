import React from 'react';
import { DollarSign, Eye, Loader } from 'lucide-react';
import ClickableTicker from '../../shared/ClickableTicker';
import { Sparkline, generateSparklineData } from '../primitives/Sparkline';
import { GlassCard } from '../primitives/GlassCard';

export const PositionsPanel = ({ positions, totalPnl, loading, onSelectPosition }) => {
  if (loading) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-32">
          <Loader className="w-6 h-6 text-cyan-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center">
            <DollarSign className="w-3 h-3 text-emerald-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Our Positions</span>
        </div>
        <span className={`text-lg font-bold ${totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
          {totalPnl >= 0 ? '+' : ''}{totalPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
        </span>
      </div>
      
      {positions.length === 0 ? (
        <div className="text-center py-8">
          <Eye className="w-8 h-8 text-zinc-600 mx-auto mb-2" />
          <p className="text-sm text-zinc-500">No open positions</p>
          <p className="text-xs text-zinc-600 mt-1">We're scanning for setups...</p>
        </div>
      ) : (
        <div className="space-y-3">
          {positions.map((pos, i) => (
            <div 
              key={pos.symbol || i}
              onClick={() => onSelectPosition?.(pos)}
              className="flex items-center justify-between p-3 rounded-xl bg-black/30 border border-white/5 hover:border-cyan-500/30 cursor-pointer transition-all"
            >
              <div className="flex items-center gap-3">
                <ClickableTicker symbol={pos.symbol} variant="inline" className="text-sm font-bold" />
                <span className={`text-[12px] px-1.5 py-0.5 rounded ${
                  pos.status === 'running' ? 'bg-emerald-500/20 text-emerald-400' :
                  pos.status === 'watching' ? 'bg-amber-500/20 text-amber-400' :
                  'bg-cyan-500/20 text-cyan-400'
                }`}>
                  {pos.status || 'open'}
                </span>
              </div>
              
              <div className="flex items-center gap-4">
                <div className="w-16 h-6 overflow-hidden rounded">
                  <Sparkline 
                    data={pos.sparkline_data || generateSparklineData(pos.pnl, pos.pnl_percent)} 
                    color={pos.pnl >= 0 ? 'emerald' : 'rose'} 
                  />
                </div>
                <span className={`text-sm font-bold ${pos.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {pos.pnl >= 0 ? '+' : ''}{pos.pnl?.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) || '$0'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};
