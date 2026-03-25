/**
 * FocusModeBadge - Auto-managed focus mode status indicator
 * 
 * Shows current system mode when NOT in LIVE mode.
 * Hidden when in LIVE mode (normal operations).
 * Provides an "Abort → Live" button for emergency stops.
 * 
 * Focus mode is now auto-managed by the backend:
 * - Training → auto-activates TRAINING mode
 * - Backtesting → auto-activates BACKTESTING mode
 * - Data collection → auto-activates COLLECTING mode
 * - Job completion → auto-restores LIVE mode
 */

import React from 'react';
import { 
  Activity, 
  Download, 
  Brain, 
  FlaskConical,
  Loader2,
  X
} from 'lucide-react';
import { useFocusMode } from '../contexts/FocusModeContext';

const MODE_CONFIG = {
  live: { icon: Activity, label: 'Live', color: '#10b981', bg: 'rgba(16, 185, 129, 0.1)' },
  collecting: { icon: Download, label: 'Collecting', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.15)' },
  training: { icon: Brain, label: 'Training', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' },
  backtesting: { icon: FlaskConical, label: 'Backtesting', color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.15)' },
};

const FocusModeBadge = () => {
  const {
    focusMode,
    progress,
    getElapsedTime,
    resetToLive,
  } = useFocusMode();

  // Hidden when in LIVE mode
  if (focusMode === 'live') return null;

  const config = MODE_CONFIG[focusMode] || MODE_CONFIG.live;
  const Icon = config.icon;
  const elapsed = getElapsedTime ? getElapsedTime() : '';
  const pct = progress?.percent || 0;
  const msg = progress?.message || '';

  return (
    <div
      data-testid="focus-mode-badge"
      className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium"
      style={{
        background: config.bg,
        border: `1px solid ${config.color}40`,
        color: config.color,
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
      }}
    >
      <Loader2 size={13} className="animate-spin" style={{ color: config.color }} />
      
      <span className="whitespace-nowrap">
        {config.label}
        {pct > 0 && pct < 100 ? ` ${pct}%` : ''}
      </span>
      
      {elapsed && (
        <span className="opacity-60 hidden sm:inline">{elapsed}</span>
      )}
      
      {msg && (
        <span 
          className="opacity-70 hidden md:inline max-w-[140px] truncate"
          title={msg}
        >
          {msg}
        </span>
      )}

      {/* Abort button */}
      <button
        data-testid="focus-mode-abort-btn"
        onClick={() => resetToLive()}
        className="ml-1 p-0.5 rounded hover:bg-white/10 transition-colors"
        title="Abort and return to Live mode"
      >
        <X size={12} />
      </button>
    </div>
  );
};

export default FocusModeBadge;
