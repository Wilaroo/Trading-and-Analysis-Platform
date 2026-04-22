import React, { useState } from 'react';
import { AlertCircle, Crosshair, Loader } from 'lucide-react';
import { toast } from 'sonner';
import api from '../../../utils/api';

// Stop Fix Actions Component - Shows button when there are risky stops
export const StopFixPanel = ({ thoughts = [], onRefresh }) => {
  const [isFixing, setIsFixing] = useState(false);
  const [fixResult, setFixResult] = useState(null);
  
  // Check if there are any stop warnings in thoughts
  const stopWarnings = thoughts.filter(t => 
    t.action_type === 'stop_warning' && 
    (t.metadata?.severity === 'critical' || t.metadata?.severity === 'warning')
  );
  
  if (stopWarnings.length === 0) return null;
  
  const handleFixAllStops = async () => {
    setIsFixing(true);
    setFixResult(null);
    
    try {
      const { data } = await api.post('/api/trading-bot/fix-all-risky-stops');
      
      if (data?.success) {
        setFixResult({
          success: true,
          message: data.message || `Fixed ${data.fixes_applied} stops`,
          fixes: data.fixes || []
        });
        
        if (onRefresh) {
          setTimeout(onRefresh, 1000);
        }
        toast.success(`Fixed ${data.fixes_applied || 0} risky stops`);
      } else {
        setFixResult({ success: false, message: data.error || "Couldn't fix stops" });
        toast.error("Couldn't fix stops: " + (data.error || "Unknown error"));
      }
    } catch (err) {
      console.error('Stop fix error:', err);
      setFixResult({ success: false, message: "Connection error" });
      toast.error("Connection error while fixing stops");
    } finally {
      setIsFixing(false);
    }
  };
  
  return (
    <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 mb-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-rose-400" />
          <span className="text-sm font-medium text-rose-400">
            {stopWarnings.length} Risky Stop{stopWarnings.length > 1 ? 's' : ''} Detected
          </span>
        </div>
        <button
          onClick={handleFixAllStops}
          disabled={isFixing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/20 border border-rose-500/40 text-rose-400 text-xs font-medium hover:bg-rose-500/30 transition-all disabled:opacity-50"
        >
          {isFixing ? <Loader className="w-3 h-3 animate-spin" /> : <Crosshair className="w-3 h-3" />}
          Fix All Stops
        </button>
      </div>
      {fixResult && (
        <div className={`mt-2 text-xs ${fixResult.success ? 'text-emerald-400' : 'text-rose-400'}`}>
          {fixResult.message}
        </div>
      )}
    </div>
  );
};
