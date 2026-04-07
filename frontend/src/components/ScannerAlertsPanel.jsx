/**
 * ScannerAlertsPanel.jsx - Scanner alerts + setups list for Command Center
 * 
 * Shows live scanner alerts and setups being watched in a list format.
 */
import React from 'react';
import { motion } from 'framer-motion';
import { 
  Activity, Bell, Crosshair, TrendingUp, TrendingDown,
  Loader, Radio, AlertCircle, Zap, Target
} from 'lucide-react';

const ScannerAlertsPanel = ({ alerts, setups, alertsLoading, setupsLoading }) => {
  return (
    <div className="rounded-xl bg-gradient-to-br from-white/[0.06] to-white/[0.02] border border-white/10 overflow-hidden" data-testid="scanner-alerts-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-black/30">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-amber-500/20 to-amber-600/10 flex items-center justify-center">
            <Radio className="w-3 h-3 text-amber-400" />
          </div>
          <span className="text-sm font-bold text-white">Scanner</span>
        </div>
        {alerts.length > 0 && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 font-bold">
            {alerts.length} alerts
          </span>
        )}
      </div>

      {/* Content */}
      <div className="max-h-[400px] overflow-y-auto scrollbar-thin scrollbar-thumb-white/10">
        {/* Alerts Section */}
        <div className="p-3 space-y-1.5">
          {alertsLoading && alerts.length === 0 ? (
            <div className="flex items-center justify-center py-4">
              <Loader className="w-4 h-4 text-amber-400 animate-spin" />
            </div>
          ) : alerts.length === 0 ? (
            <div className="flex items-center justify-center py-3 gap-1.5">
              <Activity className="w-3.5 h-3.5 text-zinc-600" />
              <p className="text-[10px] text-zinc-500">No active alerts</p>
            </div>
          ) : (
            alerts.map((alert, i) => (
              <motion.div
                key={alert.id || i}
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="p-2.5 rounded-lg bg-black/30 border border-white/5 hover:border-white/15 transition-all"
                data-testid={`scanner-alert-${i}`}
              >
                <div className="flex items-start gap-2">
                  <AlertCircle className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${
                    alert.type === 'warning' || alert.severity === 'high' ? 'text-amber-400' :
                    alert.type === 'opportunity' || alert.severity === 'medium' ? 'text-cyan-400' :
                    alert.type === 'info' ? 'text-zinc-400' :
                    'text-violet-400'
                  }`} />
                  <div className="flex-1 min-w-0">
                    {alert.symbol && (
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="text-xs font-bold text-white">{alert.symbol}</span>
                        {alert.setup_type && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-cyan-500/15 text-cyan-400">
                            {alert.setup_type}
                          </span>
                        )}
                        {alert.scan_tier && (
                          <span className={`text-[8px] px-1 py-0.5 rounded font-medium ${
                            alert.scan_tier === 'intraday' ? 'bg-violet-500/15 text-violet-400' :
                            alert.scan_tier === 'swing' ? 'bg-blue-500/15 text-blue-400' :
                            'bg-zinc-500/15 text-zinc-400'
                          }`} data-testid={`scan-tier-${alert.scan_tier}`}>
                            {alert.scan_tier.toUpperCase()}
                          </span>
                        )}
                        {alert.direction && (
                          <span className={`text-[9px] ${
                            alert.direction === 'long' ? 'text-emerald-400' : 'text-rose-400'
                          }`}>
                            {alert.direction === 'long' ? <TrendingUp className="w-2.5 h-2.5 inline" /> : <TrendingDown className="w-2.5 h-2.5 inline" />}
                          </span>
                        )}
                      </div>
                    )}
                    <p className="text-[10px] text-zinc-400 leading-relaxed">{alert.message}</p>
                    {alert.trigger_price && (
                      <p className="text-[9px] text-zinc-500 mt-0.5">
                        Trigger: ${alert.trigger_price?.toFixed?.(2) || alert.trigger_price}
                        {alert.quality_score && ` | Quality: ${alert.quality_score}`}
                      </p>
                    )}
                  </div>
                  {alert.timestamp && (
                    <span className="text-[8px] text-zinc-600 flex-shrink-0">
                      {new Date(alert.timestamp).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                    </span>
                  )}
                </div>
              </motion.div>
            ))
          )}
        </div>

        {/* Setups Section */}
        {(setups.length > 0 || setupsLoading) && (
          <div className="px-3 pb-3">
            <div className="flex items-center gap-1.5 mb-2 pt-2 border-t border-white/5">
              <Crosshair className="w-3 h-3 text-violet-400" />
              <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Watching</span>
              {setups.length > 0 && (
                <span className="text-[9px] text-violet-400">{setups.length}</span>
              )}
            </div>
            
            {setupsLoading && setups.length === 0 ? (
              <div className="flex items-center justify-center py-2">
                <Loader className="w-3 h-3 text-violet-400 animate-spin" />
              </div>
            ) : (
              <div className="space-y-1">
                {setups.slice(0, 6).map((setup, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between p-2 rounded-lg bg-black/20 border border-white/5"
                    data-testid={`setup-watch-${i}`}
                  >
                    <div className="flex items-center gap-2">
                      <Target className="w-3 h-3 text-violet-400" />
                      <span className="text-xs font-bold text-white">{setup.symbol}</span>
                      <span className="text-[9px] text-zinc-500">{setup.setup_type}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {setup.trigger_price && (
                        <span className="text-[10px] text-cyan-400">${setup.trigger_price?.toFixed?.(2) || setup.trigger_price}</span>
                      )}
                      {setup.confidence && (
                        <span className={`text-[9px] px-1 py-0.5 rounded ${
                          setup.confidence >= 55 ? 'bg-emerald-500/15 text-emerald-400' :
                          setup.confidence >= 30 ? 'bg-amber-500/15 text-amber-400' :
                          'bg-zinc-500/15 text-zinc-400'
                        }`}>
                          {setup.confidence}%
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ScannerAlertsPanel;
