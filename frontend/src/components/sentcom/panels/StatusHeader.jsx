import React from 'react';
import { Brain, Circle } from 'lucide-react';
import { PulsingDot } from '../primitives/PulsingDot';
import { OrderPipeline } from './OrderPipeline';

export const StatusHeader = ({ status, context }) => {
  const connected = status?.connected || false;
  const state = status?.state || 'offline';
  const regime = context?.regime || status?.regime || 'UNKNOWN';
  
  return (
    <div className="flex items-center justify-between p-4 border-b border-white/5">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/30 to-violet-500/30 flex items-center justify-center shadow-lg shadow-cyan-500/20">
          <Brain className="w-6 h-6 text-cyan-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">SENTCOM</h1>
          <div className="flex items-center gap-3 mt-1">
            <div className="flex items-center gap-1.5">
              {connected ? (
                <PulsingDot color="emerald" />
              ) : (
                <Circle className="w-2 h-2 text-zinc-500" />
              )}
              <span className={`text-xs font-medium ${connected ? 'text-emerald-400' : 'text-zinc-500'}`}>
                {connected ? 'CONNECTED' : 'OFFLINE'}
              </span>
            </div>
            {regime !== 'UNKNOWN' && (
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                regime === 'RISK_ON' ? 'bg-emerald-500/20 text-emerald-400' :
                regime === 'RISK_OFF' ? 'bg-rose-500/20 text-rose-400' :
                'bg-zinc-500/20 text-zinc-400'
              }`}>
                {regime}
              </span>
            )}
          </div>
        </div>
      </div>
      
      <OrderPipeline status={status} />
    </div>
  );
};
