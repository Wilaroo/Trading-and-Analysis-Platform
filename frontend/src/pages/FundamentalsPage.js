import React, { useState, useEffect } from 'react';
import { PieChart, Search, RefreshCw, TrendingUp, TrendingDown, DollarSign, BarChart3 } from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

// ===================== FUNDAMENTALS PAGE =====================
const FundamentalsPage = () => {
  const [symbol, setSymbol] = useState('AAPL');
  const [inputSymbol, setInputSymbol] = useState('AAPL');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const loadFundamentals = async (sym) => {
    setLoading(true);
    try {
      const res = await api.get(`/api/fundamentals/${sym}`);
      setData(res.data);
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
          <p className="text-zinc-500 text-sm">Company financials and valuation metrics</p>
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

      {data && (
        <>
          {/* Company Info */}
          <Card hover={false}>
            <div className="flex items-start gap-4 mb-4">
              <div className="w-12 h-12 bg-primary/20 rounded-lg flex items-center justify-center">
                <span className="text-xl font-bold text-primary">{data.symbol?.charAt(0)}</span>
              </div>
              <div>
                <h2 className="text-xl font-bold">{data.symbol}</h2>
                <p className="text-zinc-400">{data.name || 'Company Name'}</p>
                <p className="text-sm text-zinc-500">{data.sector} • {data.industry}</p>
              </div>
            </div>
          </Card>

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
              <MetricCard label="EV/EBITDA" value={data.ev_to_ebitda?.toFixed(2)} />
              <MetricCard label="PEG Ratio" value={data.peg_ratio?.toFixed(2)} good={data.peg_ratio < 1.5} />
              <MetricCard label="Market Cap" value={data.market_cap ? `$${(data.market_cap / 1e9).toFixed(1)}B` : null} />
              <MetricCard label="Enterprise Value" value={data.enterprise_value ? `$${(data.enterprise_value / 1e9).toFixed(1)}B` : null} />
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
              <MetricCard label="ROIC" value={data.roic ? (data.roic * 100).toFixed(1) : null} unit="%" good={data.roic > 0.1} />
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
              <MetricCard label="EPS Growth" value={data.eps_growth ? (data.eps_growth * 100).toFixed(1) : null} unit="%" good={data.eps_growth > 0.1} />
            </div>
          </Card>

          {/* Dividends & Financial Health */}
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
                <MetricCard label="Debt/Equity" value={data.debt_to_equity?.toFixed(2)} good={data.debt_to_equity < 1} />
                <MetricCard label="Current Ratio" value={data.current_ratio?.toFixed(2)} good={data.current_ratio > 1.5} />
                <MetricCard label="Quick Ratio" value={data.quick_ratio?.toFixed(2)} good={data.quick_ratio > 1} />
                <MetricCard label="Beta" value={data.beta?.toFixed(2)} />
              </div>
            </Card>
          </div>

          <p className="text-xs text-zinc-500 text-center">
            * Data may be simulated when live APIs are unavailable
          </p>
        </>
      )}
    </div>
  );
};

export default FundamentalsPage;
