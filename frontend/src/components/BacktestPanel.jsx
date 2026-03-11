import React, { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  Play,
  Settings,
  BarChart3,
  Target,
  DollarSign,
  Clock,
  AlertTriangle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Activity,
  Percent,
  Sparkles
} from 'lucide-react';
import api from '../utils/api';
import AdvancedBacktestPanel from './AdvancedBacktestPanel';

// Toggle to use advanced backtesting
const USE_ADVANCED_BACKTEST = true;

// Card component
const Card = ({ children, className = '' }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${className}`}>
    {children}
  </div>
);

// Stat Card
const StatCard = ({ label, value, subValue, color = 'primary', icon: Icon }) => (
  <div className="bg-white/5 rounded-lg p-3 border border-white/10">
    <div className="flex items-center justify-between mb-1">
      <span className="text-xs text-zinc-400">{label}</span>
      {Icon && <Icon className={`w-4 h-4 text-${color}`} />}
    </div>
    <p className={`text-xl font-bold text-${color}`}>{value}</p>
    {subValue && <p className="text-xs text-zinc-500">{subValue}</p>}
  </div>
);

// Config Input
const ConfigInput = ({ label, value, onChange, type = 'number', suffix = '', min, max, step }) => (
  <div className="space-y-1">
    <label className="text-xs text-zinc-400">{label}</label>
    <div className="relative">
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(type === 'number' ? parseFloat(e.target.value) : e.target.value)}
        min={min}
        max={max}
        step={step}
        className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 text-sm focus:border-primary/50 focus:outline-none"
      />
      {suffix && (
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-zinc-500">
          {suffix}
        </span>
      )}
    </div>
  </div>
);

// Trade Row in Results
const TradeRow = ({ trade, index }) => {
  const isWin = trade.pnl > 0;
  
  return (
    <div className={`flex items-center justify-between p-2 rounded text-sm ${
      isWin ? 'bg-green-500/5' : 'bg-red-500/5'
    }`}>
      <div className="flex items-center gap-3">
        <span className="text-zinc-500 font-mono">#{index + 1}</span>
        <span>{trade.entry_date?.substring(5, 10)}</span>
        <span className={isWin ? 'text-green-400' : 'text-red-400'}>
          {trade.exit_reason}
        </span>
      </div>
      <div className="flex items-center gap-4">
        <span className={`font-mono ${isWin ? 'text-green-400' : 'text-red-400'}`}>
          ${trade.pnl?.toFixed(0)}
        </span>
        <span className="text-zinc-400 font-mono">
          {trade.r_multiple?.toFixed(1)}R
        </span>
        <span className="text-zinc-500 text-xs">
          {trade.bars_held} bars
        </span>
      </div>
    </div>
  );
};

// Equity Curve Chart (simple)
const EquityCurve = ({ data }) => {
  if (!data || data.length === 0) return null;
  
  const equities = data.map(d => d.equity);
  const min = Math.min(...equities);
  const max = Math.max(...equities);
  const range = max - min || 1;
  
  return (
    <div className="h-32 flex items-end gap-0.5">
      {data.slice(-100).map((point, i) => {
        const height = ((point.equity - min) / range) * 100;
        const prevEquity = i > 0 ? data[Math.max(0, data.length - 100 + i - 1)].equity : point.equity;
        const isUp = point.equity >= prevEquity;
        
        return (
          <div
            key={i}
            className={`flex-1 rounded-t ${isUp ? 'bg-green-500/60' : 'bg-red-500/60'}`}
            style={{ height: `${Math.max(5, height)}%` }}
            title={`$${point.equity.toFixed(0)}`}
          />
        );
      })}
    </div>
  );
};

const BacktestPanel = () => {
  const [symbol, setSymbol] = useState('AAPL');
  const [timeframe, setTimeframe] = useState('1Day');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showTrades, setShowTrades] = useState(false);
  
  // Configuration
  const [config, setConfig] = useState({
    starting_capital: 100000,
    max_position_size_pct: 10,
    max_concurrent_positions: 5,
    default_stop_pct: 2.0,
    default_target_pct: 4.0,
    use_trailing_stop: false,
    trailing_stop_pct: 1.5,
    min_tqs_score: 60,
    min_volume: 100000,
    min_price: 5,
    max_price: 500,
    max_bars_to_hold: 20
  });
  
  const updateConfig = (key, value) => {
    setConfig(prev => ({ ...prev, [key]: value }));
  };
  
  const runBacktest = useCallback(async () => {
    setLoading(true);
    setResult(null);
    
    try {
      const res = await api.post('/api/slow-learning/backtest/run', {
        symbol: symbol.toUpperCase(),
        timeframe,
        name: `Backtest ${symbol}`,
        ...config
      });
      
      if (res.data.success && res.data.result) {
        setResult(res.data.result);
      }
    } catch (err) {
      console.error('Backtest error:', err);
    } finally {
      setLoading(false);
    }
  }, [symbol, timeframe, config]);
  
  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-primary" />
          <h3 className="font-semibold">Strategy Backtester</h3>
        </div>
        <button
          onClick={() => setShowConfig(!showConfig)}
          className="text-sm text-zinc-400 hover:text-white flex items-center gap-1"
        >
          <Settings className="w-4 h-4" />
          Config
          {showConfig ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>
      
      {/* Main Controls */}
      <div className="flex gap-4 mb-4">
        <div className="flex-1">
          <label className="text-xs text-zinc-400 block mb-1">Symbol</label>
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 uppercase focus:border-primary/50 focus:outline-none"
            placeholder="AAPL"
          />
        </div>
        <div className="w-32">
          <label className="text-xs text-zinc-400 block mb-1">Timeframe</label>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded px-3 py-2 focus:border-primary/50 focus:outline-none"
          >
            <option value="1Min">1 Min</option>
            <option value="5Min">5 Min</option>
            <option value="15Min">15 Min</option>
            <option value="1Hour">1 Hour</option>
            <option value="1Day">Daily</option>
          </select>
        </div>
        <div className="flex items-end">
          <button
            onClick={runBacktest}
            disabled={loading || !symbol}
            className="btn-primary flex items-center gap-2"
          >
            {loading ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            Run Backtest
          </button>
        </div>
      </div>
      
      {/* Configuration Panel */}
      <AnimatePresence>
        {showConfig && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 p-4 bg-white/5 rounded-lg border border-white/10">
              <ConfigInput
                label="Starting Capital"
                value={config.starting_capital}
                onChange={(v) => updateConfig('starting_capital', v)}
                suffix="$"
              />
              <ConfigInput
                label="Position Size"
                value={config.max_position_size_pct}
                onChange={(v) => updateConfig('max_position_size_pct', v)}
                suffix="%"
                min={1}
                max={100}
              />
              <ConfigInput
                label="Stop Loss"
                value={config.default_stop_pct}
                onChange={(v) => updateConfig('default_stop_pct', v)}
                suffix="%"
                min={0.5}
                max={10}
                step={0.5}
              />
              <ConfigInput
                label="Take Profit"
                value={config.default_target_pct}
                onChange={(v) => updateConfig('default_target_pct', v)}
                suffix="%"
                min={0.5}
                max={20}
                step={0.5}
              />
              <ConfigInput
                label="Min TQS Score"
                value={config.min_tqs_score}
                onChange={(v) => updateConfig('min_tqs_score', v)}
                min={0}
                max={100}
              />
              <ConfigInput
                label="Min Volume"
                value={config.min_volume}
                onChange={(v) => updateConfig('min_volume', v)}
              />
              <ConfigInput
                label="Max Bars to Hold"
                value={config.max_bars_to_hold}
                onChange={(v) => updateConfig('max_bars_to_hold', v)}
                min={1}
                max={100}
              />
              <div className="flex items-end">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={config.use_trailing_stop}
                    onChange={(e) => updateConfig('use_trailing_stop', e.target.checked)}
                    className="rounded border-white/20"
                  />
                  <span className="text-sm">Trailing Stop</span>
                </label>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      
      {/* Results */}
      {result && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-4"
        >
          {/* Header */}
          <div className="flex items-center justify-between">
            <div>
              <h4 className="font-medium">{result.name}</h4>
              <p className="text-xs text-zinc-400">
                {result.start_date} to {result.end_date} • {result.total_trades} trades
              </p>
            </div>
            <div className={`text-2xl font-bold ${result.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${result.total_pnl?.toFixed(0)}
              <span className="text-sm ml-1">
                ({result.total_pnl_pct?.toFixed(1)}%)
              </span>
            </div>
          </div>
          
          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard
              label="Win Rate"
              value={`${(result.win_rate * 100).toFixed(0)}%`}
              subValue={`${result.winning_trades}W / ${result.losing_trades}L`}
              color={result.win_rate >= 0.5 ? 'green-400' : 'red-400'}
              icon={result.win_rate >= 0.5 ? TrendingUp : TrendingDown}
            />
            <StatCard
              label="Profit Factor"
              value={result.profit_factor?.toFixed(2)}
              color={result.profit_factor >= 1 ? 'green-400' : 'red-400'}
              icon={Activity}
            />
            <StatCard
              label="Avg R"
              value={`${result.avg_r?.toFixed(2)}R`}
              subValue={`Total: ${result.total_r?.toFixed(1)}R`}
              color={result.avg_r >= 0 ? 'green-400' : 'red-400'}
              icon={Target}
            />
            <StatCard
              label="Max Drawdown"
              value={`-${result.max_drawdown_pct?.toFixed(1)}%`}
              subValue={`$${result.max_drawdown?.toFixed(0)}`}
              color="red-400"
              icon={AlertTriangle}
            />
          </div>
          
          {/* Equity Curve */}
          {result.equity_curve?.length > 0 && (
            <div className="bg-white/5 rounded-lg p-3 border border-white/10">
              <p className="text-xs text-zinc-400 mb-2">Equity Curve</p>
              <EquityCurve data={result.equity_curve} />
            </div>
          )}
          
          {/* Trades List */}
          {result.trades?.length > 0 && (
            <div>
              <button
                onClick={() => setShowTrades(!showTrades)}
                className="flex items-center gap-2 text-sm text-zinc-400 hover:text-white"
              >
                {showTrades ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                {showTrades ? 'Hide' : 'Show'} {result.trades.length} Trades
              </button>
              
              <AnimatePresence>
                {showTrades && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="space-y-1 mt-3 max-h-64 overflow-y-auto">
                      {result.trades.map((trade, i) => (
                        <TradeRow key={trade.id || i} trade={trade} index={i} />
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </motion.div>
      )}
      
      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-8 h-8 text-primary animate-spin" />
          <span className="ml-3 text-zinc-400">Running backtest...</span>
        </div>
      )}
    </Card>
  );
};

// Export the appropriate panel based on feature flag
const BacktestPanelWrapper = (props) => {
  if (USE_ADVANCED_BACKTEST) {
    return <AdvancedBacktestPanel {...props} />;
  }
  return <LegacyBacktestPanel {...props} />;
};

// Rename original to Legacy
const LegacyBacktestPanel = BacktestPanel;

export default BacktestPanelWrapper;
