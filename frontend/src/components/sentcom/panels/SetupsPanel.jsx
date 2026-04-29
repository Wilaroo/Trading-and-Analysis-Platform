import React from 'react';
import { Crosshair, Loader } from 'lucide-react';
import ClickableTicker from '../../shared/ClickableTicker';
import { GlassCard } from '../primitives/GlassCard';

export const SetupsPanel = ({ setups, loading }) => {
  if (loading && setups.length === 0) {
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
        <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center">
          <Crosshair className="w-3 h-3 text-violet-400" />
        </div>
        <span className="text-sm font-medium text-zinc-300">Setups We're Watching</span>
      </div>
      
      {setups.length === 0 ? (
        <div className="text-center py-4">
          <Crosshair className="w-6 h-6 text-zinc-600 mx-auto mb-2" />
          <p className="text-xs text-zinc-500">No setups currently</p>
        </div>
      ) : (
        <div className="space-y-2">
          {setups.map((setup, i) => (
            <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-black/20">
              <div className="flex items-center gap-2">
                <ClickableTicker symbol={setup.symbol} variant="inline" className="text-xs font-bold" />
                <span className="text-[12px] text-zinc-500">{setup.setup_type}</span>
              </div>
              {setup.trigger_price && (
                <span className="text-xs text-cyan-400">${setup.trigger_price?.toFixed(2)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};
