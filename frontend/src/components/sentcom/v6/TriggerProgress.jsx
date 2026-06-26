/**
 * TriggerProgress — V6 §A micro progress-bars for the selected symbol's live
 * setups, shown at the top of the Thinking pane. Each bar = live
 * `trigger_probability`; row shows distance-to-trigger % and a `next eval Xs`
 * countdown. Long=emerald, short=rose. Polls 1s via useTriggerProgress.
 */
import React from 'react';
import { useTriggerProgress } from '../hooks/useTriggerProgress';

const dirColor = (dir) => (dir === 'short' ? '#fb7185' : '#34d399');

export const TriggerProgress = ({ symbol }) => {
  const data = useTriggerProgress(symbol);
  if (!symbol) return null;
  const triggers = data?.triggers || [];
  const nextEval = data?.next_eval_s;

  return (
    <div className="px-3 py-2 border-b border-white/5 bg-black/20 shrink-0" data-testid="v6-trigger-progress">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[9px] uppercase tracking-widest text-zinc-500">{symbol} triggers</span>
        {nextEval != null && (
          <span className="text-[9px] font-mono text-zinc-400" data-testid="v6-trigger-next-eval">
            next eval {nextEval}s
          </span>
        )}
      </div>
      {triggers.length === 0 ? (
        <div className="text-[10px] text-zinc-600">No live setups for {symbol}.</div>
      ) : (
        <div className="space-y-1.5">
          {triggers.map((t, i) => {
            const pct = Math.round((t.trigger_probability || 0) * 100);
            const c = dirColor(t.direction);
            return (
              <div key={`${t.setup_type}-${i}`} data-testid="v6-trigger-row">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-zinc-300 truncate">{t.setup_type}</span>
                  <span className="font-mono text-zinc-500 shrink-0 ml-2">
                    {t.distance_pct != null ? `${t.distance_pct}%` : '—'} · {pct}%
                  </span>
                </div>
                <div className="h-1 rounded-full bg-white/10 overflow-hidden mt-0.5">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${pct}%`, backgroundColor: c }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default TriggerProgress;
