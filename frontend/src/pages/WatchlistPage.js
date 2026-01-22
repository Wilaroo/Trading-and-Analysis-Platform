import React, { useState, useEffect, useCallback } from 'react';
import { Eye, Plus, Trash2, RefreshCw, Sparkles, TrendingUp, TrendingDown } from 'lucide-react';
import api from '../utils/api';

const Card = ({ children, className = '', hover = true }) => (
  <div className={`bg-paper rounded-lg p-4 border border-white/10 ${
    hover ? 'transition-all duration-200 hover:border-primary/30' : ''
  } ${className}`}>
    {children}
  </div>
);

const PriceDisplay = ({ value, className = '' }) => {
  const isPositive = value > 0;
  const isNeutral = value === 0;
  
  return (
    <span className={`font-mono-data flex items-center gap-1 ${
      isNeutral ? 'text-zinc-400' : isPositive ? 'text-green-400' : 'text-red-400'
    } ${className}`}>
      {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
      {isPositive ? '+' : ''}{value?.toFixed(2)}%
    </span>
  );
};

// ===================== WATCHLIST PAGE =====================
const WatchlistPage = () => {
  const [watchlist, setWatchlist] = useState([]);
  const [newSymbol, setNewSymbol] = useState('');
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [aiInsight, setAiInsight] = useState('');
  const [quotes, setQuotes] = useState({});

  const loadWatchlist = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/watchlist');
      setWatchlist(res.data.watchlist || []);
      
      // Fetch quotes for watchlist items
      if (res.data.watchlist?.length > 0) {
        const symbols = res.data.watchlist.map(w => w.symbol);
        const quotesRes = await api.post('/api/quotes/batch', symbols);
        const quotesMap = {};
        quotesRes.data.quotes.forEach(q => { quotesMap[q.symbol] = q; });
        setQuotes(quotesMap);
      }
    } catch (err) { console.error('Failed to load watchlist:', err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadWatchlist(); }, [loadWatchlist]);

  const addToWatchlist = async () => {
    if (!newSymbol.trim()) return;
    try {
      await api.post('/api/watchlist/add', { symbol: newSymbol.toUpperCase() });
      setNewSymbol('');
      loadWatchlist();
    } catch (err) { console.error('Failed to add to watchlist:', err); }
  };

  const removeFromWatchlist = async (symbol) => {
    try {
      await api.delete(`/api/watchlist/${symbol}`);
      loadWatchlist();
    } catch (err) { console.error('Failed to remove from watchlist:', err); }
  };

  const generateWatchlist = async () => {
    setGenerating(true);
    try {
      const res = await api.post('/api/watchlist/generate');
      setWatchlist(res.data.watchlist || []);
      setAiInsight(res.data.ai_insight);
      
      // Fetch quotes for new watchlist
      if (res.data.watchlist?.length > 0) {
        const symbols = res.data.watchlist.map(w => w.symbol);
        const quotesRes = await api.post('/api/quotes/batch', symbols);
        const quotesMap = {};
        quotesRes.data.quotes.forEach(q => { quotesMap[q.symbol] = q; });
        setQuotes(quotesMap);
      }
    } catch (err) { console.error('Failed to generate watchlist:', err); }
    finally { setGenerating(false); }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="watchlist-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Eye className="w-6 h-6 text-primary" />
            Watchlist
          </h1>
          <p className="text-zinc-500 text-sm">Track your favorite stocks</p>
        </div>
        <button
          onClick={generateWatchlist}
          disabled={generating}
          className="btn-primary flex items-center gap-2"
          data-testid="generate-watchlist-btn"
        >
          {generating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
          AI Generate
        </button>
      </div>

      {/* Add Symbol */}
      <Card hover={false}>
        <div className="flex gap-4">
          <input
            type="text"
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
            onKeyPress={(e) => e.key === 'Enter' && addToWatchlist()}
            placeholder="Enter symbol (e.g., AAPL)"
            className="flex-1 bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
            data-testid="watchlist-symbol-input"
          />
          <button onClick={addToWatchlist} className="btn-primary flex items-center gap-2" data-testid="add-watchlist-btn">
            <Plus className="w-4 h-4" />
            Add
          </button>
        </div>
      </Card>

      {/* AI Insight */}
      {aiInsight && (
        <Card hover={false} className="bg-primary/5 border-primary/20">
          <div className="flex items-start gap-3">
            <Sparkles className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-semibold text-primary mb-1">AI Insight</h3>
              <p className="text-sm text-zinc-300">{aiInsight}</p>
            </div>
          </div>
        </Card>
      )}

      {/* Watchlist Table */}
      <Card hover={false}>
        <h2 className="font-semibold mb-4">Your Watchlist ({watchlist.length})</h2>
        {loading ? (
          <div className="animate-pulse space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-12 bg-white/5 rounded"></div>
            ))}
          </div>
        ) : watchlist.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Price</th>
                  <th>Change</th>
                  <th>Score</th>
                  <th>Matched Strategies</th>
                  <th>Added</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {watchlist.map((item, idx) => {
                  const quote = quotes[item.symbol];
                  return (
                    <tr key={idx}>
                      <td className="font-bold text-primary">{item.symbol}</td>
                      <td className="font-mono">${quote?.price?.toFixed(2) || '--'}</td>
                      <td>{quote?.change_percent !== undefined ? <PriceDisplay value={quote.change_percent} /> : '--'}</td>
                      <td>
                        {item.score !== undefined && (
                          <div className="flex items-center gap-2">
                            <div className="w-12 h-2 bg-white/10 rounded-full overflow-hidden">
                              <div className={`h-full rounded-full ${
                                item.score >= 70 ? 'bg-green-400' : item.score >= 50 ? 'bg-yellow-400' : 'bg-blue-400'
                              }`} style={{ width: `${item.score}%` }} />
                            </div>
                            <span className="text-sm">{item.score}</span>
                          </div>
                        )}
                      </td>
                      <td>
                        <div className="flex gap-1 flex-wrap">
                          {item.matched_strategies?.slice(0, 3).map((s, i) => (
                            <span key={i} className="badge badge-info text-xs">{s}</span>
                          ))}
                        </div>
                      </td>
                      <td className="text-zinc-500 text-sm">
                        {item.added_at ? new Date(item.added_at).toLocaleDateString() : '--'}
                      </td>
                      <td>
                        <button
                          onClick={() => removeFromWatchlist(item.symbol)}
                          className="text-zinc-500 hover:text-red-400 transition-colors"
                          data-testid={`remove-${item.symbol}`}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-12">
            <Eye className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-500">Your watchlist is empty</p>
            <p className="text-zinc-600 text-sm mt-1">Add symbols or generate an AI watchlist</p>
          </div>
        )}
      </Card>
    </div>
  );
};

export default WatchlistPage;
