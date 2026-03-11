/**
 * UI Mockups for Trading Interface Options
 * These are visual mockups to help decide on the best approach
 */
import React, { useState } from 'react';
import { 
  TrendingUp, TrendingDown, AlertTriangle, Activity, 
  Target, Clock, Zap, Eye, Bot, MessageSquare,
  ChevronDown, ChevronUp, ArrowRight, CheckCircle,
  XCircle, Loader, Bell, BarChart3, Wallet, Shield
} from 'lucide-react';

// ============================================================
// OPTION A+B HYBRID MOCKUP
// Left: Unified "Active Trading" panel
// Center: AI Chat with Order Queue status bar
// ============================================================

export const OptionABHybridMockup = () => {
  const [activeTab, setActiveTab] = useState('positions');
  const [guidanceExpanded, setGuidanceExpanded] = useState(true);
  
  // Sample data
  const positions = [
    { symbol: 'TMC', shares: 10000, avgCost: 7.92, currentPrice: 7.45, pnl: -4700, pnlPct: -5.9 },
    { symbol: 'INTC', shares: 1000, avgCost: 44.76, currentPrice: 45.20, pnl: 440, pnlPct: 0.98 },
    { symbol: 'TSLA', shares: 101, avgCost: 449.10, currentPrice: 442.50, pnl: -666.60, pnlPct: -1.47 }
  ];
  
  const guidance = [
    { symbol: 'TMC', type: 'warning', message: 'Stop tested 3x today - consider tightening or exiting', time: '2m ago' },
    { symbol: 'TSLA', type: 'info', message: 'Approaching first target at $455 - scale out 50%?', time: '5m ago' }
  ];
  
  const orderQueue = { pending: 0, executing: 0, filled: 3, connected: true };
  
  return (
    <div className="flex gap-4 p-4 bg-zinc-950 min-h-screen">
      {/* LEFT PANEL - Active Trading (combines Positions + Guidance + Insights) */}
      <div className="w-80 flex-shrink-0">
        <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
          {/* Panel Header */}
          <div className="p-3 border-b border-zinc-700 bg-zinc-800/50">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Wallet className="w-5 h-5 text-cyan-400" />
                <span className="font-semibold text-white">Active Trading</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="text-xs text-zinc-500">Total P&L:</span>
                <span className="text-sm font-mono text-red-400">-$4,926.60</span>
              </div>
            </div>
          </div>
          
          {/* Tabs */}
          <div className="flex border-b border-zinc-700">
            {['positions', 'guidance', 'insights'].map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex-1 py-2 text-xs font-medium transition-colors ${
                  activeTab === tab 
                    ? 'text-cyan-400 border-b-2 border-cyan-400 bg-cyan-400/5' 
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {tab === 'positions' && `Positions (${positions.length})`}
                {tab === 'guidance' && `Guidance (${guidance.length})`}
                {tab === 'insights' && 'Insights'}
              </button>
            ))}
          </div>
          
          {/* Tab Content */}
          <div className="p-3 max-h-[500px] overflow-auto">
            {/* POSITIONS TAB */}
            {activeTab === 'positions' && (
              <div className="space-y-2">
                {positions.map(pos => (
                  <div key={pos.symbol} className="p-3 bg-zinc-800/50 rounded-lg border border-zinc-700/50 hover:border-zinc-600 transition-colors cursor-pointer">
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${pos.pnl >= 0 ? 'bg-emerald-400' : 'bg-red-400'}`} />
                        <span className="font-medium text-white">{pos.symbol}</span>
                        <span className="text-xs text-zinc-500">{pos.shares.toLocaleString()} shares</span>
                      </div>
                      <span className={`font-mono text-sm ${pos.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pos.pnl >= 0 ? '+' : ''}${pos.pnl.toFixed(2)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs text-zinc-500">
                      <span>Avg: ${pos.avgCost.toFixed(2)} → ${pos.currentPrice.toFixed(2)}</span>
                      <span className={pos.pnlPct >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                        ({pos.pnlPct >= 0 ? '+' : ''}{pos.pnlPct.toFixed(2)}%)
                      </span>
                    </div>
                    
                    {/* Inline micro-guidance for this position */}
                    {guidance.filter(g => g.symbol === pos.symbol).length > 0 && (
                      <div className="mt-2 p-2 bg-yellow-500/10 rounded border border-yellow-500/20">
                        <div className="flex items-start gap-2">
                          <AlertTriangle className="w-3 h-3 text-yellow-400 mt-0.5 flex-shrink-0" />
                          <span className="text-xs text-yellow-200">
                            {guidance.find(g => g.symbol === pos.symbol)?.message}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
            
            {/* GUIDANCE TAB */}
            {activeTab === 'guidance' && (
              <div className="space-y-2">
                <div className="text-xs text-zinc-500 mb-3">Real-time coaching for your open positions</div>
                {guidance.map((g, i) => (
                  <div key={i} className={`p-3 rounded-lg border ${
                    g.type === 'warning' ? 'bg-yellow-500/10 border-yellow-500/30' : 'bg-cyan-500/10 border-cyan-500/30'
                  }`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-white">{g.symbol}</span>
                      <span className="text-xs text-zinc-500">{g.time}</span>
                    </div>
                    <p className={`text-sm ${g.type === 'warning' ? 'text-yellow-200' : 'text-cyan-200'}`}>
                      {g.message}
                    </p>
                    <div className="flex gap-2 mt-2">
                      <button className="px-2 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 rounded text-white">
                        Ask AI
                      </button>
                      <button className="px-2 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 rounded text-white">
                        View Chart
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            
            {/* INSIGHTS TAB */}
            {activeTab === 'insights' && (
              <div className="space-y-2">
                <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
                  <div className="flex items-center gap-2 mb-1">
                    <AlertTriangle className="w-4 h-4 text-red-400" />
                    <span className="font-medium text-red-400">High Risk</span>
                  </div>
                  <p className="text-sm text-red-200">100% Technology exposure. Consider diversifying.</p>
                </div>
                <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                  <div className="flex items-center gap-2 mb-1">
                    <Shield className="w-4 h-4 text-yellow-400" />
                    <span className="font-medium text-yellow-400">Position Size</span>
                  </div>
                  <p className="text-sm text-yellow-200">TMC is 50% of portfolio. Large single-stock risk.</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
      
      {/* CENTER - AI Chat with Order Queue Status Bar */}
      <div className="flex-1">
        <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden h-full">
          {/* AI Chat Header with Bot + Order Status */}
          <div className="p-3 border-b border-zinc-700 bg-zinc-800/50">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Bot className="w-5 h-5 text-emerald-400" />
                <span className="font-semibold text-white">AI Trading Assistant</span>
                <span className="px-2 py-0.5 text-xs bg-emerald-500/20 text-emerald-400 rounded">AUTO</span>
              </div>
              
              {/* Compact Order Queue Status */}
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-800 rounded-lg border border-zinc-700">
                  <Activity className={`w-4 h-4 ${orderQueue.connected ? 'text-cyan-400' : 'text-zinc-500'}`} />
                  <span className="text-xs text-zinc-400">Orders:</span>
                  <div className="flex items-center gap-1">
                    {orderQueue.pending > 0 && (
                      <span className="px-1.5 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 rounded">
                        {orderQueue.pending} pending
                      </span>
                    )}
                    {orderQueue.executing > 0 && (
                      <span className="px-1.5 py-0.5 text-xs bg-cyan-500/20 text-cyan-400 rounded animate-pulse">
                        {orderQueue.executing} executing
                      </span>
                    )}
                    <span className="px-1.5 py-0.5 text-xs bg-emerald-500/20 text-emerald-400 rounded">
                      {orderQueue.filled} filled
                    </span>
                  </div>
                  <span className={`w-2 h-2 rounded-full ${orderQueue.connected ? 'bg-cyan-400' : 'bg-zinc-500'}`} />
                </div>
              </div>
            </div>
          </div>
          
          {/* Chat Content */}
          <div className="p-4 h-96 flex items-center justify-center">
            <div className="text-center text-zinc-500">
              <MessageSquare className="w-12 h-12 mx-auto mb-2 opacity-50" />
              <p>AI Chat Area</p>
              <p className="text-xs">Ask about positions, get trade ideas...</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};


// ============================================================
// OPTION D MOCKUP
// Full "Trading Mode" Dashboard Tab
// ============================================================

export const OptionDTradingDashboardMockup = () => {
  const positions = [
    { symbol: 'TMC', shares: 10000, avgCost: 7.92, currentPrice: 7.45, pnl: -4700, pnlPct: -5.9, stopPrice: 7.20 },
    { symbol: 'INTC', shares: 1000, avgCost: 44.76, currentPrice: 45.20, pnl: 440, pnlPct: 0.98, stopPrice: 43.50 },
    { symbol: 'TSLA', shares: 101, avgCost: 449.10, currentPrice: 442.50, pnl: -666.60, pnlPct: -1.47, stopPrice: 435.00 }
  ];
  
  const orderHistory = [
    { id: 'a1b2', symbol: 'AAPL', action: 'BUY', qty: 50, status: 'filled', fillPrice: 185.50, time: '09:45:23' },
    { id: 'c3d4', symbol: 'NVDA', action: 'SELL', qty: 25, status: 'filled', fillPrice: 890.25, time: '10:12:45' },
    { id: 'e5f6', symbol: 'AMD', action: 'BUY', qty: 100, status: 'cancelled', time: '10:30:00' }
  ];
  
  const guidance = [
    { symbol: 'TMC', priority: 'high', message: 'Stop tested 3x - price at $7.45, stop at $7.20', action: 'Consider exit or tighten stop' },
    { symbol: 'TSLA', priority: 'medium', message: 'Approaching T1 at $455', action: 'Scale out 50% at target' },
    { symbol: 'INTC', priority: 'low', message: 'Trend intact, let it run', action: 'Move stop to breakeven' }
  ];
  
  return (
    <div className="p-4 bg-zinc-950 min-h-screen">
      {/* Top Navigation - Tabs */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex bg-zinc-900 rounded-lg p-1 border border-zinc-700">
          {['Command', 'Charts', 'Trading', 'Analytics'].map(tab => (
            <button
              key={tab}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                tab === 'Trading' 
                  ? 'bg-cyan-500 text-white' 
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
        
        {/* Global Stats Bar */}
        <div className="flex items-center gap-4 ml-auto">
          <div className="px-3 py-1.5 bg-zinc-900 rounded-lg border border-zinc-700">
            <span className="text-xs text-zinc-500">Account:</span>
            <span className="ml-2 font-mono text-white">$994,666.05</span>
          </div>
          <div className="px-3 py-1.5 bg-zinc-900 rounded-lg border border-zinc-700">
            <span className="text-xs text-zinc-500">Day P&L:</span>
            <span className="ml-2 font-mono text-red-400">-$4,926.60</span>
          </div>
          <div className="px-3 py-1.5 bg-emerald-500/20 rounded-lg border border-emerald-500/30">
            <span className="text-xs text-emerald-400">IB Connected</span>
          </div>
        </div>
      </div>
      
      {/* Main Dashboard Grid */}
      <div className="grid grid-cols-12 gap-4">
        
        {/* LEFT COLUMN - Positions with Live P&L */}
        <div className="col-span-5">
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
            <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-5 h-5 text-cyan-400" />
                <span className="font-semibold text-white">Open Positions</span>
                <span className="px-2 py-0.5 text-xs bg-zinc-700 text-zinc-300 rounded">
                  {positions.length} active
                </span>
              </div>
            </div>
            
            <div className="divide-y divide-zinc-800">
              {positions.map(pos => (
                <div key={pos.symbol} className="p-4 hover:bg-zinc-800/30 transition-colors">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                        pos.pnl >= 0 ? 'bg-emerald-500/20' : 'bg-red-500/20'
                      }`}>
                        {pos.pnl >= 0 ? (
                          <TrendingUp className="w-5 h-5 text-emerald-400" />
                        ) : (
                          <TrendingDown className="w-5 h-5 text-red-400" />
                        )}
                      </div>
                      <div>
                        <div className="font-semibold text-white text-lg">{pos.symbol}</div>
                        <div className="text-xs text-zinc-500">{pos.shares.toLocaleString()} shares @ ${pos.avgCost}</div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-xl font-mono font-bold ${pos.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pos.pnl >= 0 ? '+' : ''}${pos.pnl.toLocaleString()}
                      </div>
                      <div className={`text-sm ${pos.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pos.pnlPct >= 0 ? '+' : ''}{pos.pnlPct.toFixed(2)}%
                      </div>
                    </div>
                  </div>
                  
                  {/* Price Bar */}
                  <div className="mt-3 p-2 bg-zinc-800/50 rounded-lg">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="text-red-400">Stop: ${pos.stopPrice}</span>
                        <ArrowRight className="w-3 h-3 text-zinc-600" />
                        <span className="text-white">Now: ${pos.currentPrice}</span>
                        <ArrowRight className="w-3 h-3 text-zinc-600" />
                        <span className="text-emerald-400">T1: ${(pos.avgCost * 1.05).toFixed(2)}</span>
                      </div>
                      <div className="flex gap-1">
                        <button className="px-2 py-1 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded text-xs">
                          Close
                        </button>
                        <button className="px-2 py-1 bg-zinc-700 hover:bg-zinc-600 text-white rounded text-xs">
                          Adjust
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        
        {/* CENTER COLUMN - Order Pipeline + Guidance */}
        <div className="col-span-4 space-y-4">
          {/* Order Pipeline Visual */}
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
            <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center gap-2">
              <Activity className="w-5 h-5 text-cyan-400" />
              <span className="font-semibold text-white">Order Pipeline</span>
            </div>
            
            <div className="p-4">
              {/* Pipeline Visualization */}
              <div className="flex items-center justify-between mb-4">
                <div className="flex-1 text-center">
                  <div className="w-16 h-16 mx-auto rounded-full bg-yellow-500/20 border-2 border-yellow-500/50 flex items-center justify-center mb-2">
                    <span className="text-2xl font-bold text-yellow-400">0</span>
                  </div>
                  <span className="text-xs text-zinc-400">Pending</span>
                </div>
                <ArrowRight className="w-6 h-6 text-zinc-600" />
                <div className="flex-1 text-center">
                  <div className="w-16 h-16 mx-auto rounded-full bg-cyan-500/20 border-2 border-cyan-500/50 flex items-center justify-center mb-2">
                    <span className="text-2xl font-bold text-cyan-400">0</span>
                  </div>
                  <span className="text-xs text-zinc-400">Executing</span>
                </div>
                <ArrowRight className="w-6 h-6 text-zinc-600" />
                <div className="flex-1 text-center">
                  <div className="w-16 h-16 mx-auto rounded-full bg-emerald-500/20 border-2 border-emerald-500/50 flex items-center justify-center mb-2">
                    <span className="text-2xl font-bold text-emerald-400">3</span>
                  </div>
                  <span className="text-xs text-zinc-400">Filled</span>
                </div>
              </div>
              
              {/* Recent Orders */}
              <div className="text-xs text-zinc-500 mb-2">Recent Executions</div>
              <div className="space-y-1">
                {orderHistory.slice(0, 3).map(order => (
                  <div key={order.id} className="flex items-center justify-between p-2 bg-zinc-800/50 rounded">
                    <div className="flex items-center gap-2">
                      {order.status === 'filled' ? (
                        <CheckCircle className="w-4 h-4 text-emerald-400" />
                      ) : (
                        <XCircle className="w-4 h-4 text-red-400" />
                      )}
                      <span className={`font-medium ${order.action === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>
                        {order.action}
                      </span>
                      <span className="text-white">{order.symbol}</span>
                      <span className="text-zinc-500">x{order.qty}</span>
                    </div>
                    <div className="text-right">
                      {order.fillPrice && (
                        <span className="text-white font-mono">${order.fillPrice}</span>
                      )}
                      <span className="text-zinc-500 ml-2">{order.time}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          
          {/* In-Trade Guidance */}
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
            <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center gap-2">
              <Zap className="w-5 h-5 text-yellow-400" />
              <span className="font-semibold text-white">In-Trade Guidance</span>
              <span className="ml-auto px-2 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 rounded">
                {guidance.filter(g => g.priority === 'high').length} alerts
              </span>
            </div>
            
            <div className="p-3 space-y-2 max-h-64 overflow-auto">
              {guidance.map((g, i) => (
                <div key={i} className={`p-3 rounded-lg border ${
                  g.priority === 'high' ? 'bg-red-500/10 border-red-500/30' :
                  g.priority === 'medium' ? 'bg-yellow-500/10 border-yellow-500/30' :
                  'bg-zinc-800/50 border-zinc-700'
                }`}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium text-white">{g.symbol}</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      g.priority === 'high' ? 'bg-red-500/20 text-red-400' :
                      g.priority === 'medium' ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-zinc-700 text-zinc-400'
                    }`}>
                      {g.priority}
                    </span>
                  </div>
                  <p className="text-sm text-zinc-300 mb-2">{g.message}</p>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-cyan-400">→ {g.action}</span>
                    <button className="px-2 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 rounded text-white">
                      Take Action
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        
        {/* RIGHT COLUMN - Performance Stats */}
        <div className="col-span-3 space-y-4">
          {/* Today's Performance */}
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
            <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-cyan-400" />
              <span className="font-semibold text-white">Today's Performance</span>
            </div>
            
            <div className="p-4 space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-zinc-400">Trades</span>
                <span className="font-mono text-white">8</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-zinc-400">Win Rate</span>
                <span className="font-mono text-emerald-400">62.5%</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-zinc-400">Avg Win</span>
                <span className="font-mono text-emerald-400">+$845</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-zinc-400">Avg Loss</span>
                <span className="font-mono text-red-400">-$423</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-zinc-400">Profit Factor</span>
                <span className="font-mono text-cyan-400">2.0</span>
              </div>
              <div className="pt-3 border-t border-zinc-700">
                <div className="flex justify-between items-center">
                  <span className="text-zinc-400">Realized P&L</span>
                  <span className="font-mono text-emerald-400">+$2,450</span>
                </div>
                <div className="flex justify-between items-center mt-1">
                  <span className="text-zinc-400">Unrealized P&L</span>
                  <span className="font-mono text-red-400">-$4,926</span>
                </div>
              </div>
            </div>
          </div>
          
          {/* Risk Status */}
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl overflow-hidden">
            <div className="p-3 border-b border-zinc-700 bg-zinc-800/50 flex items-center gap-2">
              <Shield className="w-5 h-5 text-yellow-400" />
              <span className="font-semibold text-white">Risk Status</span>
            </div>
            
            <div className="p-4 space-y-3">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-zinc-400">Daily Loss Limit</span>
                  <span className="text-yellow-400">49% used</span>
                </div>
                <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
                  <div className="h-full w-1/2 bg-yellow-500 rounded-full" />
                </div>
              </div>
              
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-zinc-400">Position Exposure</span>
                  <span className="text-red-400">85%</span>
                </div>
                <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
                  <div className="h-full w-[85%] bg-red-500 rounded-full" />
                </div>
              </div>
              
              <div className="p-2 bg-yellow-500/10 rounded border border-yellow-500/30">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-yellow-400" />
                  <span className="text-xs text-yellow-200">100% Tech sector exposure</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default { OptionABHybridMockup, OptionDTradingDashboardMockup };
