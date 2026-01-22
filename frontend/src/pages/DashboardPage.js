import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Zap,
  BarChart3,
  DollarSign,
  Target,
  Activity,
  Clock,
  ChevronRight
} from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip
} from 'recharts';
import api from '../utils/api';

// ===================== COMPONENTS =====================
const Card = ({ children, className = '', onClick, hover = true }) => (
  <div 
    onClick={onClick}
    className={`bg-paper rounded-lg p-4 border border-white/10 ${
      hover ? 'transition-all duration-200 hover:border-primary/30' : ''
    } ${onClick ? 'cursor-pointer' : ''} ${className}`}
  >
    {children}
  </div>
);

const Skeleton = ({ className = '' }) => (
  <div className={`skeleton rounded ${className}`} />
);

const PriceDisplay = ({ value, showArrow = true, className = '' }) => {
  const isPositive = value > 0;
  const isNeutral = value === 0;
  
  return (
    <span className={`font-mono-data flex items-center gap-1 ${
      isNeutral ? 'text-zinc-400' : isPositive ? 'text-green-400' : 'text-red-400'
    } ${className}`}>
      {showArrow && !isNeutral && (
        isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />
      )}
      {isPositive ? '+' : ''}{value?.toFixed(2)}%
    </span>
  );
};

const StatsCard = ({ icon: Icon, label, value, change, loading }) => (
  <Card className="flex items-center gap-4">
    <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center">
      <Icon className="w-6 h-6 text-primary" />
    </div>
    <div className="flex-1">
      <p className="text-xs text-zinc-500 uppercase tracking-wider">{label}</p>
      {loading ? (
        <Skeleton className="h-7 w-24 mt-1" />
      ) : (
        <p className="text-2xl font-bold font-mono-data">{value}</p>
      )}
    </div>
    {change !== undefined && <PriceDisplay value={change} />}
  </Card>
);

const AlertItem = ({ alert }) => (
  <motion.div
    initial={{ opacity: 0, x: 20 }}
    animate={{ opacity: 1, x: 0 }}
    exit={{ opacity: 0, x: -20 }}
    className="glass-card rounded-lg p-4 flex items-start gap-4"
  >
    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
      alert.score >= 70 ? 'bg-green-500/20' : alert.score >= 50 ? 'bg-yellow-500/20' : 'bg-blue-500/20'
    }`}>
      <Zap className={`w-5 h-5 ${
        alert.score >= 70 ? 'text-green-400' : alert.score >= 50 ? 'text-yellow-400' : 'text-blue-400'
      }`} />
    </div>
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2 mb-1">
        <span className="font-bold text-primary">{alert.symbol}</span>
        <span className="badge badge-info">{alert.strategy_id}</span>
      </div>
      <p className="text-sm text-zinc-400 truncate">{alert.strategy_name}</p>
      <p className="text-xs text-zinc-500 mt-1">{new Date(alert.timestamp).toLocaleTimeString()}</p>
    </div>
  </motion.div>
);

// TradingView Mini Chart
const TradingViewMiniChart = ({ symbol = 'AAPL' }) => {
  const containerRef = useRef(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.innerHTML = '';
      
      const script = document.createElement('script');
      script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js';
      script.type = 'text/javascript';
      script.async = true;
      script.innerHTML = JSON.stringify({
        symbol: symbol,
        width: '100%',
        height: '100%',
        locale: 'en',
        dateRange: '1M',
        colorTheme: 'dark',
        isTransparent: true,
        autosize: true,
        largeChartUrl: ''
      });

      containerRef.current.appendChild(script);
    }
  }, [symbol]);

  return (
    <div className="tradingview-widget-container h-full" ref={containerRef}>
      <div className="tradingview-widget-container__widget h-full"></div>
    </div>
  );
};

// ===================== DASHBOARD PAGE =====================
const DashboardPage = ({ data, loading, onRefresh, streamingQuotes }) => {
  const { stats, overview, alerts, watchlist } = data;
  
  // Mini chart for portfolio performance
  const performanceData = [
    { name: 'Mon', value: 0 },
    { name: 'Tue', value: 1.2 },
    { name: 'Wed', value: 0.8 },
    { name: 'Thu', value: 2.1 },
    { name: 'Fri', value: 1.8 },
  ];

  return (
    <div className="space-y-6 animate-fade-in" data-testid="dashboard-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-zinc-500 text-sm">Market overview and portfolio snapshot</p>
        </div>
        <button 
          onClick={onRefresh}
          className="btn-secondary flex items-center gap-2"
          data-testid="refresh-dashboard"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard 
          icon={DollarSign} 
          label="Portfolio Value" 
          value={stats?.portfolio_value ? `$${stats.portfolio_value.toLocaleString()}` : '$0'}
          change={stats?.daily_pnl_percent}
          loading={loading}
        />
        <StatsCard 
          icon={Activity} 
          label="Today's P&L" 
          value={stats?.daily_pnl ? `$${stats.daily_pnl.toLocaleString()}` : '$0'}
          change={stats?.daily_pnl_percent}
          loading={loading}
        />
        <StatsCard 
          icon={Target} 
          label="Active Alerts" 
          value={alerts?.length || 0}
          loading={loading}
        />
        <StatsCard 
          icon={BarChart3} 
          label="Watchlist" 
          value={watchlist?.length || 0}
          loading={loading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Content - Top Movers */}
        <div className="lg:col-span-2 space-y-6">
          {/* Top Movers */}
          <Card hover={false}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold flex items-center gap-2">
                <TrendingUp className="w-5 h-5 text-primary" />
                Top Movers
              </h2>
            </div>
            
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Price</th>
                    <th>Change</th>
                    <th>Volume</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {overview?.top_movers?.slice(0, 5).map((stock, idx) => {
                    // Use streaming quote if available
                    const streamQuote = streamingQuotes[stock.symbol];
                    const price = streamQuote?.price || stock.price;
                    const change = streamQuote?.change_percent || stock.change_percent;
                    
                    return (
                      <tr key={idx}>
                        <td className="font-bold text-primary">{stock.symbol}</td>
                        <td className="font-mono-data">${price?.toFixed(2)}</td>
                        <td><PriceDisplay value={change} /></td>
                        <td className="text-zinc-400 text-sm">
                          {((stock.volume || 0) / 1000000).toFixed(2)}M
                        </td>
                        <td>
                          <ChevronRight className="w-4 h-4 text-zinc-500" />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Mini Chart */}
          <Card hover={false}>
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <Activity className="w-5 h-5 text-primary" />
              S&P 500 Overview
            </h2>
            <div className="h-64">
              <TradingViewMiniChart symbol="AMEX:SPY" />
            </div>
          </Card>
        </div>

        {/* Sidebar Content */}
        <div className="space-y-6">
          {/* Performance Chart */}
          <Card hover={false}>
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-primary" />
              Weekly Performance
            </h2>
            <div className="h-32">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={performanceData}>
                  <defs>
                    <linearGradient id="perfGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 10 }} />
                  <YAxis hide />
                  <Tooltip 
                    contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                    labelStyle={{ color: '#fff' }}
                  />
                  <Area type="monotone" dataKey="value" stroke="#10b981" fillOpacity={1} fill="url(#perfGradient)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* Recent Alerts */}
          <Card hover={false}>
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <Zap className="w-5 h-5 text-yellow-400" />
              Recent Alerts
            </h2>
            <div className="space-y-3 max-h-64 overflow-y-auto">
              <AnimatePresence>
                {alerts?.slice(0, 5).map((alert, idx) => (
                  <AlertItem key={alert._id || idx} alert={alert} />
                ))}
              </AnimatePresence>
              {(!alerts || alerts.length === 0) && (
                <p className="text-zinc-500 text-sm text-center py-4">No recent alerts</p>
              )}
            </div>
          </Card>

          {/* Watchlist Preview */}
          <Card hover={false}>
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <Target className="w-5 h-5 text-primary" />
              Watchlist
            </h2>
            <div className="space-y-2">
              {watchlist?.slice(0, 5).map((item, idx) => {
                const streamQuote = streamingQuotes[item.symbol];
                return (
                  <div key={idx} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                    <span className="font-medium">{item.symbol}</span>
                    {streamQuote && (
                      <div className="text-right">
                        <span className="font-mono-data text-sm">${streamQuote.price?.toFixed(2)}</span>
                        <PriceDisplay value={streamQuote.change_percent} className="text-xs ml-2" />
                      </div>
                    )}
                  </div>
                );
              })}
              {(!watchlist || watchlist.length === 0) && (
                <p className="text-zinc-500 text-sm text-center py-4">No items in watchlist</p>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default DashboardPage;
