import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { 
  PieChart, 
  Search, 
  RefreshCw, 
  TrendingUp, 
  TrendingDown, 
  DollarSign, 
  BarChart3,
  Shield,
  Clock,
  Target,
  Activity,
  Zap
} from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

// VST Score Gauge Component
const VSTScoreGauge = ({ score, label, icon: Icon, interpretation, color = 'primary', components = {} }) => {
  const getScoreColor = (s) => {
    if (s >= 7) return 'text-green-400';
    if (s >= 5.5) return 'text-blue-400';
    if (s >= 4) return 'text-yellow-400';
    return 'text-red-400';
  };
  
  const getScoreBg = (s) => {
    if (s >= 7) return 'from-green-500/20 to-green-500/5';
    if (s >= 5.5) return 'from-blue-500/20 to-blue-500/5';
    if (s >= 4) return 'from-yellow-500/20 to-yellow-500/5';
    return 'from-red-500/20 to-red-500/5';
  };
  
  const getProgressColor = (s) => {
    if (s >= 7) return 'bg-green-400';
    if (s >= 5.5) return 'bg-blue-400';
    if (s >= 4) return 'bg-yellow-400';
    return 'bg-red-400';
  };

  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className={`bg-gradient-to-br ${getScoreBg(score)} rounded-xl p-5 border border-white/10`}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className={`p-2 rounded-lg bg-white/10`}>
            <Icon className={`w-5 h-5 ${getScoreColor(score)}`} />
          </div>
          <span className="text-sm font-medium text-zinc-300">{label}</span>
        </div>
        <span className={`text-xs px-2 py-1 rounded-full bg-white/10 ${getScoreColor(score)}`}>
          {interpretation}
        </span>
      </div>
      
      <div className="flex items-end gap-2 mb-3">
        <span className={`text-4xl font-bold font-mono ${getScoreColor(score)}`}>
          {score?.toFixed(2)}
        </span>
        <span className="text-zinc-500 text-sm mb-1">/ 10.00</span>
      </div>
      
      {/* Progress bar */}
      <div className="h-2 bg-white/10 rounded-full overflow-hidden mb-4">
        <motion.div 
          initial={{ width: 0 }}
          animate={{ width: `${(score / 10) * 100}%` }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          className={`h-full rounded-full ${getProgressColor(score)}`}
        />
      </div>
      
      {/* Component breakdown */}
      {Object.keys(components).length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(components).map(([key, value]) => (
            <div key={key} className="text-xs">
              <span className="text-zinc-500">{key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}: </span>
              <span className={`font-mono ${getScoreColor(value)}`}>{value?.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
};

// VST Composite Card
const VSTCompositeCard = ({ vst, rv, rs, rt }) => {
  const getRecColor = (rec) => {
    if (rec === 'STRONG BUY' || rec === 'BUY') return 'bg-green-500/20 text-green-400 border-green-500/30';
    if (rec === 'SELL') return 'bg-red-500/20 text-red-400 border-red-500/30';
    return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
  };
  
  const getScoreColor = (s) => {
    if (s >= 7) return 'text-green-400';
    if (s >= 5.5) return 'text-blue-400';
    if (s >= 4) return 'text-yellow-400';
    return 'text-red-400';
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-gradient-to-br from-primary/20 via-primary/10 to-accent/10 rounded-xl p-6 border border-primary/30"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-3 rounded-xl bg-primary/20">
            <Target className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h3 className="text-lg font-bold">VST Composite Score</h3>
            <p className="text-xs text-zinc-500">Value • Safety • Timing</p>
          </div>
        </div>
        <span className={`badge text-sm px-3 py-1 ${getRecColor(vst?.recommendation)}`}>
          {vst?.recommendation}
        </span>
      </div>
      
      <div className="flex items-center justify-center py-6">
        <div className="relative">
          {/* Circular progress background */}
          <svg className="w-40 h-40 transform -rotate-90">
            <circle
              cx="80"
              cy="80"
              r="70"
              fill="none"
              stroke="rgba(255,255,255,0.1)"
              strokeWidth="12"
            />
            <motion.circle
              cx="80"
              cy="80"
              r="70"
              fill="none"
              stroke={vst?.score >= 7 ? '#22c55e' : vst?.score >= 5.5 ? '#3b82f6' : vst?.score >= 4 ? '#eab308' : '#ef4444'}
              strokeWidth="12"
              strokeLinecap="round"
              initial={{ strokeDasharray: "0 440" }}
              animate={{ strokeDasharray: `${(vst?.score / 10) * 440} 440` }}
              transition={{ duration: 1, ease: "easeOut" }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className={`text-4xl font-bold font-mono ${getScoreColor(vst?.score)}`}>
              {vst?.score?.toFixed(2)}
            </span>
            <span className="text-zinc-500 text-sm">/ 10.00</span>
          </div>
        </div>
      </div>
      
      {/* Score breakdown */}
      <div className="grid grid-cols-3 gap-4 mt-4">
        <div className="text-center">
          <p className="text-xs text-zinc-500 uppercase">Value</p>
          <p className={`text-xl font-bold font-mono ${getScoreColor(rv?.score)}`}>{rv?.score?.toFixed(2)}</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-zinc-500 uppercase">Safety</p>
          <p className={`text-xl font-bold font-mono ${getScoreColor(rs?.score)}`}>{rs?.score?.toFixed(2)}</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-zinc-500 uppercase">Timing</p>
          <p className={`text-xl font-bold font-mono ${getScoreColor(rt?.score)}`}>{rt?.score?.toFixed(2)}</p>
        </div>
      </div>
      
      <p className="text-xs text-zinc-500 text-center mt-4">
        Weights: Value {(vst?.weights_used?.rv * 100)?.toFixed(0)}% • Safety {(vst?.weights_used?.rs * 100)?.toFixed(0)}% • Timing {(vst?.weights_used?.rt * 100)?.toFixed(0)}%
      </p>
    </motion.div>
  );
};

// ===================== FUNDAMENTALS PAGE =====================
const FundamentalsPage = () => {
  const [symbol, setSymbol] = useState('AAPL');
  const [inputSymbol, setInputSymbol] = useState('AAPL');
  const [data, setData] = useState(null);
  const [vstData, setVstData] = useState(null);
  const [loading, setLoading] = useState(false);

  const loadFundamentals = async (sym) => {
    setLoading(true);
    try {
      const [fundRes, vstRes] = await Promise.all([
        api.get(`/api/fundamentals/${sym}`),
        api.get(`/api/vst/${sym}`)
      ]);
      setData(fundRes.data);
      setVstData(vstRes.data);
    } catch (err) { console.error('Failed to load fundamentals:', err); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadFundamentals(symbol); }, [symbol]);

  const handleSearch = () => {
    setSymbol(inputSymbol.toUpperCase());
  };

  const MetricCard = ({ label, value, unit = '', good = null }) => (
    <div className="bg-white/5 rounded-lg p-3">
      <p className="text-xs text-zinc-500 uppercase mb-1">{label}</p>
      <p className={`text-lg font-mono font-semibold ${
        good === true ? 'text-green-400' : good === false ? 'text-red-400' : 'text-white'
      }`}>
        {value !== null && value !== undefined ? `${value}${unit}` : '--'}
      </p>
    </div>
  );

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fundamentals-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <PieChart className="w-6 h-6 text-primary" />
            Fundamental Analysis
          </h1>
          <p className="text-zinc-500 text-sm">VST Scoring + Company financials</p>
        </div>
      </div>

      {/* Search */}
      <Card hover={false}>
        <div className="flex gap-4">
          <input
            type="text"
            value={inputSymbol}
            onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
            onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Enter symbol..."
            className="flex-1 bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
            data-testid="fundamentals-symbol-input"
          />
          <button onClick={handleSearch} className="btn-primary flex items-center gap-2" data-testid="search-fundamentals-btn">
            {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Analyze
          </button>
        </div>
      </Card>

      {vstData && (
        <>
          {/* Company Header */}
          <Card hover={false}>
            <div className="flex items-start gap-4">
              <div className="w-14 h-14 bg-primary/20 rounded-xl flex items-center justify-center">
                <span className="text-2xl font-bold text-primary">{vstData.symbol?.charAt(0)}</span>
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <h2 className="text-2xl font-bold">{vstData.symbol}</h2>
                  {vstData.vst_composite?.recommendation && (
                    <span className={`badge text-sm ${
                      vstData.vst_composite.recommendation === 'STRONG BUY' || vstData.vst_composite.recommendation === 'BUY'
                        ? 'bg-green-500/20 text-green-400 border-green-500/30'
                        : vstData.vst_composite.recommendation === 'SELL'
                        ? 'bg-red-500/20 text-red-400 border-red-500/30'
                        : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                    }`}>
                      {vstData.vst_composite.recommendation}
                    </span>
                  )}
                </div>
                <p className="text-zinc-400">{data?.company_name || `${vstData.symbol} Inc.`}</p>
                <p className="text-sm text-zinc-500">{data?.sector} • {data?.industry}</p>
              </div>
            </div>
          </Card>

          {/* VST Scores */}
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            {/* VST Composite */}
            <VSTCompositeCard 
              vst={vstData.vst_composite}
              rv={vstData.relative_value}
              rs={vstData.relative_safety}
              rt={vstData.relative_timing}
            />
            
            {/* Individual Scores */}
            <VSTScoreGauge 
              score={vstData.relative_value?.score}
              label="Relative Value (RV)"
              icon={DollarSign}
              interpretation={vstData.relative_value?.interpretation}
              components={vstData.relative_value?.components}
            />
            
            <VSTScoreGauge 
              score={vstData.relative_safety?.score}
              label="Relative Safety (RS)"
              icon={Shield}
              interpretation={vstData.relative_safety?.interpretation}
              components={vstData.relative_safety?.components}
            />
            
            <VSTScoreGauge 
              score={vstData.relative_timing?.score}
              label="Relative Timing (RT)"
              icon={Clock}
              interpretation={vstData.relative_timing?.interpretation}
              components={vstData.relative_timing?.components}
            />
          </div>
          
          {/* Timing Metrics */}
          {vstData.relative_timing?.metrics && (
            <Card hover={false}>
              <h3 className="font-semibold mb-4 flex items-center gap-2">
                <Activity className="w-5 h-5 text-cyan-400" />
                Timing Metrics
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500">1W Return</p>
                  <p className={`font-mono font-bold ${vstData.relative_timing.metrics.return_1w >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {vstData.relative_timing.metrics.return_1w >= 0 ? '+' : ''}{vstData.relative_timing.metrics.return_1w?.toFixed(2)}%
                  </p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500">1M Return</p>
                  <p className={`font-mono font-bold ${vstData.relative_timing.metrics.return_1m >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {vstData.relative_timing.metrics.return_1m >= 0 ? '+' : ''}{vstData.relative_timing.metrics.return_1m?.toFixed(2)}%
                  </p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500">3M Return</p>
                  <p className={`font-mono font-bold ${vstData.relative_timing.metrics.return_3m >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {vstData.relative_timing.metrics.return_3m >= 0 ? '+' : ''}{vstData.relative_timing.metrics.return_3m?.toFixed(2)}%
                  </p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500">RSI</p>
                  <p className={`font-mono font-bold ${
                    vstData.relative_timing.metrics.rsi > 70 ? 'text-red-400' : 
                    vstData.relative_timing.metrics.rsi < 30 ? 'text-green-400' : 'text-white'
                  }`}>
                    {vstData.relative_timing.metrics.rsi?.toFixed(1)}
                  </p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500">Above SMA20</p>
                  <p className={`font-mono font-bold ${vstData.relative_timing.metrics.above_sma20 ? 'text-green-400' : 'text-red-400'}`}>
                    {vstData.relative_timing.metrics.above_sma20 ? 'Yes' : 'No'}
                  </p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500">Above SMA50</p>
                  <p className={`font-mono font-bold ${vstData.relative_timing.metrics.above_sma50 ? 'text-green-400' : 'text-red-400'}`}>
                    {vstData.relative_timing.metrics.above_sma50 ? 'Yes' : 'No'}
                  </p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 text-center">
                  <p className="text-xs text-zinc-500">Golden Cross</p>
                  <p className={`font-mono font-bold ${vstData.relative_timing.metrics.sma20_above_sma50 ? 'text-green-400' : 'text-red-400'}`}>
                    {vstData.relative_timing.metrics.sma20_above_sma50 ? 'Yes' : 'No'}
                  </p>
                </div>
              </div>
            </Card>
          )}
        </>
      )}

      {data && (
        <>
          {/* Valuation Metrics */}
          <Card hover={false}>
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-primary" />
              Valuation
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard label="P/E Ratio" value={data.pe_ratio?.toFixed(2)} good={data.pe_ratio < 25} />
              <MetricCard label="Forward P/E" value={data.forward_pe?.toFixed(2)} />
              <MetricCard label="P/B Ratio" value={data.price_to_book?.toFixed(2)} good={data.price_to_book < 3} />
              <MetricCard label="P/S Ratio" value={data.price_to_sales?.toFixed(2)} />
              <MetricCard label="PEG Ratio" value={data.peg_ratio?.toFixed(2)} good={data.peg_ratio < 1.5} />
              <MetricCard label="Market Cap" value={data.market_cap ? `$${(data.market_cap / 1e9).toFixed(1)}B` : null} />
            </div>
          </Card>

          {/* Profitability */}
          <Card hover={false}>
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-green-400" />
              Profitability
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard label="Gross Margin" value={data.gross_margin ? (data.gross_margin * 100).toFixed(1) : null} unit="%" good={data.gross_margin > 0.4} />
              <MetricCard label="Operating Margin" value={data.operating_margin ? (data.operating_margin * 100).toFixed(1) : null} unit="%" good={data.operating_margin > 0.15} />
              <MetricCard label="Profit Margin" value={data.profit_margin ? (data.profit_margin * 100).toFixed(1) : null} unit="%" good={data.profit_margin > 0.1} />
              <MetricCard label="ROE" value={data.roe ? (data.roe * 100).toFixed(1) : null} unit="%" good={data.roe > 0.15} />
              <MetricCard label="ROA" value={data.roa ? (data.roa * 100).toFixed(1) : null} unit="%" good={data.roa > 0.05} />
            </div>
          </Card>

          {/* Growth */}
          <Card hover={false}>
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-cyan-400" />
              Growth
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard label="Revenue Growth" value={data.revenue_growth ? (data.revenue_growth * 100).toFixed(1) : null} unit="%" good={data.revenue_growth > 0.1} />
              <MetricCard label="Earnings Growth" value={data.earnings_growth ? (data.earnings_growth * 100).toFixed(1) : null} unit="%" good={data.earnings_growth > 0.1} />
              <MetricCard label="EPS (TTM)" value={data.eps?.toFixed(2)} />
            </div>
          </Card>

          {/* Financial Health */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card hover={false}>
              <h3 className="font-semibold mb-4">Dividends</h3>
              <div className="grid grid-cols-2 gap-3">
                <MetricCard label="Dividend Yield" value={data.dividend_yield ? (data.dividend_yield * 100).toFixed(2) : null} unit="%" />
                <MetricCard label="Payout Ratio" value={data.payout_ratio ? (data.payout_ratio * 100).toFixed(1) : null} unit="%" good={data.payout_ratio < 0.6} />
              </div>
            </Card>
            <Card hover={false}>
              <h3 className="font-semibold mb-4">Financial Health</h3>
              <div className="grid grid-cols-2 gap-3">
                <MetricCard label="Debt/Equity" value={data.debt_to_equity?.toFixed(2)} good={data.debt_to_equity < 100} />
                <MetricCard label="Current Ratio" value={data.current_ratio?.toFixed(2)} good={data.current_ratio > 1.5} />
                <MetricCard label="Quick Ratio" value={data.quick_ratio?.toFixed(2)} good={data.quick_ratio > 1} />
                <MetricCard label="Beta" value={data.beta?.toFixed(2)} />
              </div>
            </Card>
          </div>

          <p className="text-xs text-zinc-500 text-center">
            * VST scores based on VectorVest-style methodology. Data may be simulated when live APIs unavailable.
          </p>
        </>
      )}
    </div>
  );
};

export default FundamentalsPage;
