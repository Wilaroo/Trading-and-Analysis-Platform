import React from 'react';
import { ArrowRight, CheckCircle, Clock, Zap } from 'lucide-react';

// ============================================================================
// Hooks — extracted to ./sentcom/hooks/*
// ============================================================================

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

export const OrderPipeline = ({ status }) => {
  const pipeline = status?.order_pipeline || { pending: 0, executing: 0, filled: 0 };
  
  return (
    <div className="flex items-center gap-3 px-4 py-2 rounded-xl bg-black/40 border border-white/5">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
          <Clock className="w-4 h-4 text-amber-400" />
        </div>
        <div>
          <p className="text-lg font-bold text-amber-400">{pipeline.pending}</p>
          <p className="text-[11px] text-zinc-500 uppercase">Pending</p>
        </div>
      </div>
      
      <ArrowRight className="w-4 h-4 text-zinc-600" />
      
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
          <Zap className="w-4 h-4 text-cyan-400" />
        </div>
        <div>
          <p className="text-lg font-bold text-cyan-400">{pipeline.executing}</p>
          <p className="text-[11px] text-zinc-500 uppercase">Executing</p>
        </div>
      </div>
      
      <ArrowRight className="w-4 h-4 text-zinc-600" />
      
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center">
          <CheckCircle className="w-4 h-4 text-emerald-400" />
        </div>
        <div>
          <p className="text-lg font-bold text-emerald-400">{pipeline.filled}</p>
          <p className="text-[11px] text-zinc-500 uppercase">Filled</p>
        </div>
      </div>
    </div>
  );
};
