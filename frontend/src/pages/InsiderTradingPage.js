import React, { useState, useEffect } from 'react';
import { Users, Search, RefreshCw, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

// ===================== INSIDER TRADING PAGE =====================
const InsiderTradingPage = () => {
  const [symbol, setSymbol] = useState('AAPL');
  const [inputSymbol, setInputSymbol] = useState('AAPL');
  const [data, setData] = useState(null);
  const [unusualActivity, setUnusualActivity] = useState([]);
  const [loading, setLoading] = useState(false);

  const loadInsiderData = async (sym) => {
    setLoading(true);
    try {
      const [tradesRes, unusualRes] = await Promise.all([
        api.get(`/api/insider/${sym}`),
        api.get('/api/insider/unusual')
      ]);
      setData(tradesRes.data);
      setUnusualActivity(unusualRes.data.unusual_activity || unusualRes.data.all_activity || []);
    } catch (err) { console.error('Failed to load insider data:', err); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadInsiderData(symbol); }, [symbol]);

  const handleSearch = () => {
    setSymbol(inputSymbol.toUpperCase());
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="insider-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Users className="w-6 h-6 text-primary" />
            Insider Trading
          </h1>
          <p className="text-zinc-500 text-sm">Track insider buying and selling activity</p>
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
            data-testid="insider-symbol-input"
          />
          <button onClick={handleSearch} className="btn-primary flex items-center gap-2" data-testid="search-insider-btn">
            {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Search
          </button>
        </div>
      </Card>

      {/* Unusual Activity */}
      <Card hover={false}>
        <h2 className="font-semibold mb-4 flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-yellow-400" />
          Unusual Insider Activity
        </h2>
        {unusualActivity.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Value</th>
                  <th>Net Activity</th>
                  <th>Signal</th>
                </tr>
              </thead>
              <tbody>
                {unusualActivity.slice(0, 10).map((item, idx) => (
                  <tr key={idx} className={item.is_unusual ? 'bg-yellow-500/5' : ''}>
                    <td className="font-bold text-primary">{item.symbol}</td>
                    <td>
                      <span className={`badge ${
                        item.recent_buys > item.recent_sells 
                          ? 'bg-green-500/20 text-green-400' 
                          : 'bg-red-500/20 text-red-400'
                      }`}>
                        {item.recent_buys > item.recent_sells ? 'Net Buying' : 'Net Selling'}
                      </span>
                    </td>
                    <td className="font-mono">${(item.total_value / 1000000).toFixed(2)}M</td>
                    <td className={`font-mono ${item.net_value > 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {item.net_value > 0 ? '+' : ''}{(item.net_value / 1000000).toFixed(2)}M
                    </td>
                    <td>
                      <span className={`flex items-center gap-1 ${
                        item.signal === 'BULLISH' ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {item.signal === 'BULLISH' ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                        {item.signal}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-zinc-500 text-center py-4">No unusual activity detected</p>
        )}
      </Card>

      {/* Symbol-specific trades */}
      {data && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="bg-green-500/5 border-green-500/20">
              <p className="text-xs text-zinc-500 uppercase">Total Buys</p>
              <p className="text-2xl font-bold text-green-400 mt-1">
                ${(data.summary?.total_buys / 1000000)?.toFixed(2)}M
              </p>
              <p className="text-sm text-zinc-500 mt-1">{data.summary?.buy_count} transactions</p>
            </Card>
            <Card className="bg-red-500/5 border-red-500/20">
              <p className="text-xs text-zinc-500 uppercase">Total Sells</p>
              <p className="text-2xl font-bold text-red-400 mt-1">
                ${(data.summary?.total_sells / 1000000)?.toFixed(2)}M
              </p>
              <p className="text-sm text-zinc-500 mt-1">{data.summary?.sell_count} transactions</p>
            </Card>
            <Card className={`${data.summary?.signal === 'BULLISH' ? 'bg-green-500/5 border-green-500/20' : 'bg-red-500/5 border-red-500/20'}`}>
              <p className="text-xs text-zinc-500 uppercase">Net Activity</p>
              <p className={`text-2xl font-bold mt-1 ${data.summary?.net_activity > 0 ? 'text-green-400' : 'text-red-400'}`}>
                ${(data.summary?.net_activity / 1000000)?.toFixed(2)}M
              </p>
              <p className="text-sm text-zinc-500 mt-1">Signal: {data.summary?.signal}</p>
            </Card>
          </div>

          {/* Recent Trades */}
          <Card hover={false}>
            <h2 className="font-semibold mb-4">Recent Insider Trades - {data.symbol}</h2>
            {data.trades?.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Insider</th>
                      <th>Position</th>
                      <th>Type</th>
                      <th>Shares</th>
                      <th>Price</th>
                      <th>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trades.map((trade, idx) => (
                      <tr key={idx}>
                        <td className="text-zinc-400">{trade.date}</td>
                        <td className="font-medium">{trade.insider_name}</td>
                        <td className="text-zinc-400 text-sm">{trade.position}</td>
                        <td>
                          <span className={`badge ${
                            trade.transaction_type === 'Buy' 
                              ? 'bg-green-500/20 text-green-400' 
                              : 'bg-red-500/20 text-red-400'
                          }`}>
                            {trade.transaction_type}
                          </span>
                        </td>
                        <td className="font-mono">{trade.shares?.toLocaleString()}</td>
                        <td className="font-mono">${trade.price?.toFixed(2)}</td>
                        <td className="font-mono">${(trade.value / 1000000)?.toFixed(2)}M</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-zinc-500 text-center py-4">No recent insider trades</p>
            )}
          </Card>

          <p className="text-xs text-zinc-500 text-center">
            * Data is simulated for demonstration purposes
          </p>
        </>
      )}
    </div>
  );
};

export default InsiderTradingPage;
