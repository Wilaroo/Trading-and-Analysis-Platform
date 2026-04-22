import React from 'react';
import { Activity, Bell, Crosshair, Eye, Loader, Radio, Star } from 'lucide-react';
import ClickableTicker from '../../shared/ClickableTicker';
import { GlassCard } from '../primitives/GlassCard';

// Combined Market Intelligence Panel - Market Regime + Setups + Alerts
export const MarketIntelPanel = ({ context, setups, alerts, contextLoading, setupsLoading, alertsLoading }) => {
  return (
    <div className="space-y-4">
      {/* Market Regime Section */}
      <GlassCard className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-6 h-6 rounded-full bg-cyan-500/20 flex items-center justify-center">
            <Activity className="w-3 h-3 text-cyan-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Market Regime</span>
        </div>
        
        {contextLoading ? (
          <div className="flex items-center justify-center h-16">
            <Loader className="w-5 h-5 text-cyan-400 animate-spin" />
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <div className="p-2 rounded-lg bg-black/30">
              <span className="text-[10px] text-zinc-500 block">Regime</span>
              <span className={`text-sm font-bold ${
                context?.regime === 'RISK_ON' ? 'text-emerald-400' :
                context?.regime === 'RISK_OFF' ? 'text-rose-400' :
                'text-zinc-400'
              }`}>
                {context?.regime || 'UNKNOWN'}
              </span>
            </div>
            <div className="p-2 rounded-lg bg-black/30">
              <span className="text-[10px] text-zinc-500 block">SPY</span>
              <span className={`text-sm font-bold ${
                context?.spy_trend === 'Bullish' ? 'text-emerald-400' :
                context?.spy_trend === 'Bearish' ? 'text-rose-400' :
                'text-zinc-400'
              }`}>
                {context?.spy_trend || '--'}
              </span>
            </div>
            <div className="p-2 rounded-lg bg-black/30">
              <span className="text-[10px] text-zinc-500 block">VIX</span>
              <span className="text-sm font-bold text-zinc-300">{context?.vix || '--'}</span>
            </div>
            <div className="p-2 rounded-lg bg-black/30">
              <span className="text-[10px] text-zinc-500 block">Market</span>
              <span className={`text-sm font-bold ${context?.market_open ? 'text-emerald-400' : 'text-zinc-500'}`}>
                {context?.market_open ? 'OPEN' : 'CLOSED'}
              </span>
            </div>
          </div>
        )}
      </GlassCard>

      {/* Setups We're Watching */}
      <GlassCard className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center">
            <Eye className="w-3 h-3 text-violet-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Setups We're Watching</span>
          {setups.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-500/20 text-violet-400">
              {setups.length}
            </span>
          )}
        </div>
        
        {setupsLoading && setups.length === 0 ? (
          <div className="flex items-center justify-center h-16">
            <Loader className="w-5 h-5 text-violet-400 animate-spin" />
          </div>
        ) : setups.length === 0 ? (
          <div className="text-center py-3">
            <Crosshair className="w-4 h-4 text-zinc-600 mx-auto mb-1" />
            <p className="text-[10px] text-zinc-500">No setups currently</p>
          </div>
        ) : (
          <div className="space-y-2 max-h-[200px] overflow-y-auto">
            {setups.slice(0, 5).map((setup, i) => (
              <div 
                key={i}
                className="p-2 rounded-lg bg-black/30 hover:bg-black/50 cursor-pointer transition-all"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ClickableTicker symbol={setup.symbol} variant="inline" className="font-bold text-sm" />
                    <span className="text-[9px] px-1.5 py-0.5 bg-violet-500/20 text-violet-400 rounded-full">
                      {setup.setup_type || setup.type}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Star className="w-3 h-3 text-amber-400" />
                    <span className="text-xs font-bold text-white">{setup.score || setup.confidence || '--'}</span>
                  </div>
                </div>
                {setup.trigger_price && (
                  <div className="text-[10px] text-zinc-500 mt-1">
                    Entry: ${setup.trigger_price?.toFixed(2)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </GlassCard>

      {/* Live Scanner Alerts */}
      <GlassCard className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-6 h-6 rounded-full bg-amber-500/20 flex items-center justify-center">
            <Bell className="w-3 h-3 text-amber-400" />
          </div>
          <span className="text-sm font-medium text-zinc-300">Live Scanner Alerts</span>
          {alerts.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
              {alerts.length}
            </span>
          )}
        </div>
        
        {alertsLoading && alerts.length === 0 ? (
          <div className="flex items-center justify-center h-16">
            <Loader className="w-5 h-5 text-amber-400 animate-spin" />
          </div>
        ) : alerts.length === 0 ? (
          <div className="text-center py-3">
            <Radio className="w-4 h-4 text-zinc-600 mx-auto mb-1" />
            <p className="text-[10px] text-zinc-500">Scanning for opportunities...</p>
          </div>
        ) : (
          <div className="space-y-2 max-h-[200px] overflow-y-auto">
            {alerts.slice(0, 5).map((alert, i) => (
              <div 
                key={i}
                className="p-2 rounded-lg bg-black/30 hover:bg-black/50 cursor-pointer transition-all"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ClickableTicker symbol={alert.symbol} variant="inline" className="font-bold text-sm" />
                    <span className={`text-[9px] px-1.5 py-0.5 rounded-full ${
                      alert.direction === 'LONG' ? 'bg-emerald-500/20 text-emerald-400' :
                      alert.direction === 'SHORT' ? 'bg-rose-500/20 text-rose-400' :
                      'bg-zinc-500/20 text-zinc-400'
                    }`}>
                      {alert.direction || alert.setup_type}
                    </span>
                  </div>
                  <span className="text-xs text-zinc-400">${alert.price?.toFixed(2) || '--'}</span>
                </div>
                <div className="text-[10px] text-zinc-500 mt-1">
                  {alert.setup_type} • {alert.score ? `Score: ${alert.score}` : ''}
                </div>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
};
