import React, { useState, useEffect } from 'react';
import { Activity, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  Cell
} from 'recharts';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

// ===================== COT DATA PAGE =====================
const COTDataPage = () => {
  const [summary, setSummary] = useState([]);
  const [selectedMarket, setSelectedMarket] = useState(null);
  const [marketData, setMarketData] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadCOTSummary = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/cot/summary');
      setSummary(res.data.markets || []);
    } catch (err) { console.error('Failed to load COT data:', err); }
    finally { setLoading(false); }
  };

  const loadMarketData = async (market) => {
    try {
      const res = await api.get(`/api/cot/${encodeURIComponent(market)}`);
      setMarketData(res.data);
      setSelectedMarket(market);
    } catch (err) { console.error('Failed to load market data:', err); }
  };

  useEffect(() => { loadCOTSummary(); }, []);

  return (
    <div className="space-y-6 animate-fade-in" data-testid="cot-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Activity className="w-6 h-6 text-primary" />
            Commitment of Traders (COT)
          </h1>
          <p className="text-zinc-500 text-sm">CFTC futures positioning data</p>
        </div>
        <button onClick={loadCOTSummary} className="btn-secondary flex items-center gap-2">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Summary Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading ? (
          Array.from({ length: 6 }).map((_, idx) => (
            <Card key={idx} className="animate-pulse">
              <div className="h-6 bg-white/5 rounded w-1/2 mb-3"></div>
              <div className="h-8 bg-white/5 rounded w-3/4 mb-2"></div>
              <div className="h-4 bg-white/5 rounded w-1/3"></div>
            </Card>
          ))
        ) : (
          summary.map((market, idx) => (
            <Card 
              key={idx} 
              onClick={() => loadMarketData(market.market)}
              className="cursor-pointer"
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className="font-semibold">{market.market}</h3>
                <span className={`badge ${
                  market.signal === 'BULLISH' 
                    ? 'bg-green-500/20 text-green-400' 
                    : market.signal === 'BEARISH'
                    ? 'bg-red-500/20 text-red-400'
                    : 'bg-zinc-500/20 text-zinc-400'
                }`}>
                  {market.signal}
                </span>
              </div>
              
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Commercial Net:</span>
                  <span className={`font-mono ${market.commercial_net > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {market.commercial_net?.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Non-Commercial Net:</span>
                  <span className={`font-mono ${market.non_commercial_net > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {market.non_commercial_net?.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Weekly Change:</span>
                  <span className={`font-mono flex items-center gap-1 ${market.change > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {market.change > 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                    {market.change > 0 ? '+' : ''}{market.change?.toLocaleString()}
                  </span>
                </div>
              </div>
            </Card>
          ))
        )}
      </div>

      {/* Market Detail */}
      {marketData && (
        <Card hover={false}>
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-semibold">{marketData.market} - Historical Positioning</h2>
            <button 
              onClick={() => setMarketData(null)}
              className="text-zinc-500 hover:text-white text-sm"
            >
              Close
            </button>
          </div>

          {/* Positioning Chart */}
          <div className="h-64 mb-6">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={marketData.historical || []}>
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 10 }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 10 }} />
                <Tooltip 
                  contentStyle={{ background: '#18181b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                  labelStyle={{ color: '#fff' }}
                />
                <Bar dataKey="commercial_net" name="Commercial" fill="#10b981" />
                <Bar dataKey="non_commercial_net" name="Non-Commercial" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Current Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <p className="text-xs text-zinc-500 uppercase">Commercial Long</p>
              <p className="text-lg font-mono text-green-400">{marketData.commercial_long?.toLocaleString()}</p>
            </div>
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <p className="text-xs text-zinc-500 uppercase">Commercial Short</p>
              <p className="text-lg font-mono text-red-400">{marketData.commercial_short?.toLocaleString()}</p>
            </div>
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <p className="text-xs text-zinc-500 uppercase">Non-Comm Long</p>
              <p className="text-lg font-mono text-blue-400">{marketData.non_commercial_long?.toLocaleString()}</p>
            </div>
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <p className="text-xs text-zinc-500 uppercase">Non-Comm Short</p>
              <p className="text-lg font-mono text-orange-400">{marketData.non_commercial_short?.toLocaleString()}</p>
            </div>
          </div>
        </Card>
      )}

      <p className="text-xs text-zinc-500 text-center">
        * COT data is simulated for demonstration purposes
      </p>
    </div>
  );
};

export default COTDataPage;
