import React from 'react';
import { AlertCircle, Bell, Loader } from 'lucide-react';
import { GlassCard } from '../primitives/GlassCard';

export const AlertsPanel = ({ alerts, loading }) => {
  if (loading && alerts.length === 0) {
    return (
      <GlassCard className="p-4">
        <div className="flex items-center justify-center h-24">
          <Loader className="w-5 h-5 text-amber-400 animate-spin" />
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-amber-500/20 flex items-center justify-center">
            <Bell className="w-3 h-3 text-amber-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Recent Alerts</span>
        </div>
        {alerts.length > 0 && (
          <span className="text-xs text-amber-400">{alerts.length} new</span>
        )}
      </div>
      
      {alerts.length === 0 ? (
        <p className="text-xs text-zinc-500 text-center py-4">No alerts</p>
      ) : (
        <div className="space-y-2">
          {alerts.map((alert, i) => (
            <div key={i} className="flex items-center gap-2 p-2 rounded-lg bg-black/20">
              <AlertCircle className={`w-3 h-3 ${
                alert.type === 'warning' ? 'text-amber-400' :
                alert.type === 'info' ? 'text-cyan-400' :
                'text-zinc-400'
              }`} />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-zinc-300 truncate">{alert.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
};
