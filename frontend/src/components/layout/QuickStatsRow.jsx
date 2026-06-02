import React from 'react';
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Briefcase,
  Bell,
  Activity,
  Zap
} from 'lucide-react';
import { Card } from '../shared/UIComponents';
import { formatCurrency } from '../../utils/tradingUtils';

const regimeColors = {
  'Trending Up': 'text-green-400',
  'Trending Down': 'text-red-400',
  'Consolidation': 'text-yellow-400',
  'High Volatility': 'text-orange-400'
};

const QuickStatsRow = ({
  account,
  totalPnL,
  positions,
  enhancedAlerts,
  alerts,
  marketContext,
  opportunities,
  expandedStatCard,
  setExpandedStatCard,
  setSelectedTicker,
  setSelectedEnhancedAlert,
}) => {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3" data-testid="quick-stats-row">
      {/* Net Liquidation */}
      <Card className="col-span-1">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
            <DollarSign className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <p className="text-[10px] text-zinc-500 uppercase">Net Liquidation</p>
            <p className="text-lg font-bold font-mono text-white" data-testid="net-liquidation">
              {formatCurrency(account?.net_liquidation)}
            </p>
          </div>
        </div>
      </Card>
      
      {/* Today's P&L */}
      <Card className="col-span-1">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
            totalPnL >= 0 ? 'bg-green-500/10' : 'bg-red-500/10'
          }`}>
            {totalPnL >= 0 ? <TrendingUp className="w-5 h-5 text-green-400" /> : <TrendingDown className="w-5 h-5 text-red-400" />}
          </div>
          <div>
            <p className="text-[10px] text-zinc-500 uppercase">Today&apos;s P&L</p>
            <p className={`text-lg font-bold font-mono ${totalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`} data-testid="todays-pnl">
              {formatCurrency(account?.unrealized_pnl || totalPnL)}
            </p>
          </div>
        </div>
      </Card>
      
      {/* Positions (with dropdown) */}
      <Card 
        className="col-span-1 cursor-pointer hover:border-purple-500/30 transition-colors relative" 
        onClick={() => setExpandedStatCard(expandedStatCard === 'positions' ? null : 'positions')}
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center">
            <Briefcase className="w-5 h-5 text-purple-400" />
          </div>
          <div>
            <p className="text-[10px] text-zinc-500 uppercase">Positions</p>
            <p className="text-lg font-bold font-mono text-white" data-testid="positions-count">{positions.length}</p>
          </div>
        </div>
        {expandedStatCard === 'positions' && (
          <div className="absolute top-full left-0 right-0 mt-1 z-50 bg-[#111] border border-white/10 rounded-lg p-3 shadow-xl min-w-[280px]" data-testid="positions-dropdown">
            <p className="text-[10px] text-zinc-500 uppercase mb-2">Holdings</p>
            <div className="space-y-1 max-h-[200px] overflow-y-auto">
              {positions.length > 0 ? positions.map((pos, idx) => (
                <div key={idx} className="flex items-center justify-between p-1.5 bg-zinc-900/50 rounded hover:bg-zinc-800/50 cursor-pointer"
                  onClick={(e) => { e.stopPropagation(); setSelectedTicker({ symbol: pos.symbol, quote: { price: pos.avg_cost } }); }}>
                  <div>
                    <span className="font-bold text-white text-sm">{pos.symbol}</span>
                    <span className="text-xs text-zinc-500 ml-1">{pos.quantity} sh</span>
                  </div>
                  <span className={`text-xs font-mono ${(pos.unrealized_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatCurrency(pos.unrealized_pnl || 0)}
                  </span>
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">No positions</p>
              )}
            </div>
          </div>
        )}
      </Card>
      
      {/* Alerts (with dropdown) */}
      <Card 
        className="col-span-1 cursor-pointer hover:border-yellow-500/30 transition-colors relative" 
        onClick={() => setExpandedStatCard(expandedStatCard === 'alerts' ? null : 'alerts')}
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-yellow-500/10 flex items-center justify-center">
            <Bell className="w-5 h-5 text-yellow-400" />
          </div>
          <div>
            <p className="text-[10px] text-zinc-500 uppercase">Alerts</p>
            <p className="text-lg font-bold font-mono text-white" data-testid="alerts-count">{enhancedAlerts.length + alerts.length}</p>
          </div>
        </div>
        {expandedStatCard === 'alerts' && (
          <div className="absolute top-full left-0 right-0 mt-1 z-50 bg-[#111] border border-white/10 rounded-lg p-3 shadow-xl min-w-[320px]" data-testid="alerts-dropdown">
            <p className="text-[10px] text-zinc-500 uppercase mb-2">Active Alerts</p>
            <div className="space-y-1 max-h-[250px] overflow-y-auto">
              {enhancedAlerts.length > 0 ? enhancedAlerts.slice(0, 8).map((alert, idx) => (
                <div key={idx} className="p-2 bg-zinc-900/50 rounded hover:bg-zinc-800/50 cursor-pointer"
                  onClick={(e) => { e.stopPropagation(); setSelectedEnhancedAlert(alert); }}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-white">{alert.symbol}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      alert.grade === 'A' ? 'bg-green-500 text-black' :
                      alert.grade === 'B' ? 'bg-cyan-500 text-black' : 'bg-yellow-500 text-black'
                    }`}>{alert.grade}</span>
                  </div>
                  <p className="text-[10px] text-zinc-400 mt-0.5 truncate">{alert.headline}</p>
                </div>
              )) : alerts.length > 0 ? alerts.slice(0, 8).map((alert, idx) => (
                <div key={idx} className="p-1.5 bg-zinc-900/50 rounded text-xs text-zinc-300">
                  {alert.symbol || alert.message || JSON.stringify(alert).substring(0, 60)}
                </div>
              )) : (
                <p className="text-xs text-zinc-500 text-center py-2">No active alerts</p>
              )}
            </div>
          </div>
        )}
      </Card>
      
      {/* Market Regime */}
      <Card className="col-span-1">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
            marketContext?.regime === 'Trending Up' ? 'bg-green-500/10' :
            marketContext?.regime === 'Trending Down' ? 'bg-red-500/10' :
            'bg-yellow-500/10'
          }`}>
            <Activity className={`w-5 h-5 ${regimeColors[marketContext?.regime] || 'text-zinc-400'}`} />
          </div>
          <div>
            <p className="text-[10px] text-zinc-500 uppercase">Market</p>
            <p className={`text-sm font-bold ${regimeColors[marketContext?.regime] || 'text-zinc-400'}`} data-testid="market-regime">
              {marketContext?.regime || 'Loading...'}
            </p>
          </div>
        </div>
      </Card>
      
      {/* Opportunities */}
      <Card className="col-span-1">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
            <Zap className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <p className="text-[10px] text-zinc-500 uppercase">Opportunities</p>
            <p className="text-lg font-bold font-mono text-white" data-testid="opportunities-count">{opportunities.length}</p>
          </div>
        </div>
      </Card>
    </div>
  );
};

export default QuickStatsRow;
