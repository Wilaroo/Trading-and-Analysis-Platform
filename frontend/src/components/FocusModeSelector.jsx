/**
 * FocusModeSelector - UI component for selecting system focus mode
 * 
 * Displays current mode and allows switching between:
 * - Live Trading (default)
 * - Data Collection
 * - AI Training
 * - Backtesting
 */

import React, { useState, useRef, useEffect } from 'react';
import { 
  Activity, 
  Download, 
  Brain, 
  FlaskConical,
  ChevronDown,
  Clock,
  AlertTriangle,
  Loader2
} from 'lucide-react';
import { useFocusMode, FOCUS_MODES } from '../contexts/FocusModeContext';

// Icon mapping
const MODE_ICONS = {
  live: Activity,
  collecting: Download,
  training: Brain,
  backtesting: FlaskConical
};

const FocusModeSelector = ({ compact = false }) => {
  const {
    focusMode,
    modeConfig,
    isChangingMode,
    progress,
    getElapsedTime,
    setMode,
    resetToLive,
    isInFocusMode
  } = useFocusMode();
  
  const [isOpen, setIsOpen] = useState(false);
  const [elapsedTime, setElapsedTime] = useState(0);
  const dropdownRef = useRef(null);
  
  // Format elapsed time
  const formatTime = (seconds) => {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m`;
  };
  
  // Update elapsed time every second when in a focus mode
  useEffect(() => {
    if (!isInFocusMode()) {
      setElapsedTime(0);
      return;
    }
    
    const interval = setInterval(() => {
      setElapsedTime(getElapsedTime());
    }, 1000);
    
    return () => clearInterval(interval);
  }, [focusMode, getElapsedTime, isInFocusMode]);
  
  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);
  
  const handleModeSelect = async (mode) => {
    if (mode === focusMode) {
      setIsOpen(false);
      return;
    }
    
    // If switching from a non-live mode, confirm
    if (isInFocusMode() && mode !== 'live') {
      const confirmed = window.confirm(
        `You're currently in ${modeConfig.label} mode. Switch to ${FOCUS_MODES[mode].label}?`
      );
      if (!confirmed) return;
    }
    
    setIsOpen(false);
    await setMode(mode);
  };
  
  const Icon = MODE_ICONS[focusMode] || Activity;
  
  // Compact version for header
  if (compact) {
    return (
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all
            ${modeConfig.bgColor} ${modeConfig.color} ${modeConfig.borderColor} border
            hover:brightness-110 ${isChangingMode ? 'opacity-50' : ''}`}
          disabled={isChangingMode}
          data-testid="focus-mode-selector"
        >
          {isChangingMode ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Icon className="w-3.5 h-3.5" />
          )}
          <span className="hidden sm:inline">{modeConfig.shortLabel}</span>
          {isInFocusMode() && (
            <span className="text-[10px] opacity-70">
              {formatTime(elapsedTime)}
            </span>
          )}
          <ChevronDown className="w-3 h-3 opacity-60" />
        </button>
        
        {/* Dropdown */}
        {isOpen && (
          <div className="absolute right-0 top-full mt-1 w-56 rounded-lg border border-white/10 bg-zinc-900 shadow-xl z-50 overflow-hidden">
            <div className="p-2 border-b border-white/10">
              <p className="text-xs text-zinc-400">Focus Mode</p>
              {isInFocusMode() && progress.message && (
                <p className="text-xs text-white mt-1 truncate">{progress.message}</p>
              )}
            </div>
            
            {Object.values(FOCUS_MODES).map((mode) => {
              const ModeIcon = MODE_ICONS[mode.id];
              const isActive = focusMode === mode.id;
              
              return (
                <button
                  key={mode.id}
                  onClick={() => handleModeSelect(mode.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors
                    ${isActive ? `${mode.bgColor} ${mode.color}` : 'text-zinc-300 hover:bg-white/5'}`}
                >
                  <ModeIcon className="w-4 h-4" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">{mode.label}</p>
                    <p className="text-xs text-zinc-500 truncate">{mode.description}</p>
                  </div>
                  {isActive && (
                    <div className="w-2 h-2 rounded-full bg-current" />
                  )}
                </button>
              );
            })}
            
            {isInFocusMode() && (
              <div className="p-2 border-t border-white/10">
                <button
                  onClick={() => resetToLive()}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg
                    bg-red-500/20 text-red-400 hover:bg-red-500/30 text-sm transition-colors"
                >
                  <AlertTriangle className="w-3.5 h-3.5" />
                  Stop & Return to Live
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }
  
  // Full version with progress
  return (
    <div className="rounded-xl border border-white/10 overflow-hidden" 
         style={{ background: 'linear-gradient(135deg, rgba(21, 28, 36, 0.95), rgba(30, 40, 55, 0.95))' }}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${modeConfig.bgColor}`}>
            <Icon className={`w-4 h-4 ${modeConfig.color}`} />
          </div>
          <div>
            <h3 className="text-sm font-medium text-white">{modeConfig.label}</h3>
            <p className="text-xs text-zinc-500">{modeConfig.description}</p>
          </div>
        </div>
        
        {isInFocusMode() && (
          <div className="flex items-center gap-2 text-xs text-zinc-400">
            <Clock className="w-3.5 h-3.5" />
            {formatTime(elapsedTime)}
          </div>
        )}
      </div>
      
      {/* Progress (if in focus mode) */}
      {isInFocusMode() && (
        <div className="p-3">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="text-zinc-400">{progress.message || 'Processing...'}</span>
            <span className={modeConfig.color}>{progress.percent}%</span>
          </div>
          <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
            <div 
              className={`h-full transition-all duration-300 ${modeConfig.bgColor.replace('/20', '')}`}
              style={{ width: `${progress.percent}%` }}
            />
          </div>
          
          {progress.currentStep > 0 && progress.totalSteps > 0 && (
            <p className="text-xs text-zinc-500 mt-1">
              Step {progress.currentStep} of {progress.totalSteps}
            </p>
          )}
        </div>
      )}
      
      {/* Mode selector buttons */}
      <div className="grid grid-cols-4 gap-1 p-2 bg-black/20">
        {Object.values(FOCUS_MODES).map((mode) => {
          const ModeIcon = MODE_ICONS[mode.id];
          const isActive = focusMode === mode.id;
          
          return (
            <button
              key={mode.id}
              onClick={() => handleModeSelect(mode.id)}
              disabled={isChangingMode}
              className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-xs transition-all
                ${isActive 
                  ? `${mode.bgColor} ${mode.color} ${mode.borderColor} border` 
                  : 'text-zinc-500 hover:text-zinc-300 hover:bg-white/5 border border-transparent'
                }
                ${isChangingMode ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <ModeIcon className="w-4 h-4" />
              <span className="truncate max-w-full">{mode.shortLabel}</span>
            </button>
          );
        })}
      </div>
      
      {/* Stop button (if in focus mode) */}
      {isInFocusMode() && (
        <div className="p-2 border-t border-white/10">
          <button
            onClick={() => resetToLive()}
            disabled={isChangingMode}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg
              bg-red-500/20 text-red-400 hover:bg-red-500/30 text-sm transition-colors
              disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isChangingMode ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <AlertTriangle className="w-4 h-4" />
            )}
            Stop & Return to Live
          </button>
        </div>
      )}
    </div>
  );
};

export default FocusModeSelector;
