/**
 * ThinkingPane — V6 §4 right-of-chart "Thinking" column.
 *
 * Wraps the live SentCom stream-of-consciousness (the real V5 `UnifiedStreamV5`,
 * fed by `useSentComStream` messages) inside a `GlassHaloPane` whose halo color +
 * breathe cadence are bound to §3 app-state. This is the ONLY pane that carries
 * the ambient halo (per spec). Trigger-condition micro progress-bars (feature A,
 * needs `/api/trigger-progress/{sym}`) are a follow-up sub-step.
 */
import React from 'react';
import { GlassHaloPane, haloColor } from './GlassHaloPane';
import UnifiedStreamV5 from '../v5/UnifiedStreamV5';

export const ThinkingPane = ({
  state = 'cyan',
  messages = [],
  loading = false,
  onSymbolClick,
  hoveredSymbol,
  onHoverSymbol,
  className = '',
  style = {},
}) => (
  <GlassHaloPane state={state} className={className} style={style} testId="v6-thinking-pane">
    <div className="px-3 py-2 border-b border-white/5 flex items-center justify-between shrink-0">
      <span className="text-[11px] uppercase tracking-widest text-zinc-300">Thinking</span>
      <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
        <span
          className="w-1.5 h-1.5 rounded-full animate-pulse"
          style={{ backgroundColor: haloColor(state) }}
        />
        live
      </span>
    </div>
    <div className="flex-1 min-h-0 overflow-y-auto" data-testid="v6-thinking-stream">
      <UnifiedStreamV5
        messages={messages}
        loading={loading}
        onSymbolClick={onSymbolClick}
        hoveredSymbol={hoveredSymbol}
        onHoverSymbol={onHoverSymbol}
      />
    </div>
  </GlassHaloPane>
);

export default ThinkingPane;
