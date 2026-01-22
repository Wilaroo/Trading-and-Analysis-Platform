import React, { useState, useEffect, useCallback } from 'react';
import { Briefcase, Plus, Trash2, RefreshCw, DollarSign, TrendingUp, TrendingDown } from 'lucide-react';
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

// ===================== PORTFOLIO PAGE =====================
const PortfolioPage = () => {
  const [portfolio, setPortfolio] = useState({ positions: [], total_value: 0, total_cost: 0, total_pnl: 0, total_pnl_percent: 0 });
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newPosition, setNewPosition] = useState({ symbol: '', shares: '', avg_cost: '' });

  const loadPortfolio = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/portfolio');
      setPortfolio(res.data);
    } catch (err) { console.error('Failed to load portfolio:', err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadPortfolio(); }, [loadPortfolio]);

  const addPosition = async () => {
    if (!newPosition.symbol || !newPosition.shares || !newPosition.avg_cost) return;
    try {
      await api.post('/api/portfolio/add', {
        symbol: newPosition.symbol.toUpperCase(),
        shares: parseFloat(newPosition.shares),
        avg_cost: parseFloat(newPosition.avg_cost)
      });
      setNewPosition({ symbol: '', shares: '', avg_cost: '' });
      setShowAddForm(false);
      loadPortfolio();
    } catch (err) { console.error('Failed to add position:', err); }
  };

  const removePosition = async (symbol) => {
    try {
      await api.delete(`/api/portfolio/positions/${symbol}`);
      loadPortfolio();
    } catch (err) { console.error('Failed to remove position:', err); }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="portfolio-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Briefcase className="w-6 h-6 text-primary" />
            Portfolio
          </h1>
          <p className="text-zinc-500 text-sm">Track your positions and P&L</p>
        </div>
        <div className="flex gap-2">
          <button onClick={loadPortfolio} className="btn-secondary flex items-center gap-2" data-testid="refresh-portfolio">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button onClick={() => setShowAddForm(!showAddForm)} className="btn-primary flex items-center gap-2" data-testid="add-position-btn">
            <Plus className="w-4 h-4" />
            Add Position
          </button>
        </div>
      </div>

      {/* Portfolio Summary */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card className="bg-gradient-to-br from-primary/10 to-primary/5">
          <p className="text-xs text-zinc-500 uppercase">Total Value</p>
          <p className="text-2xl font-bold mt-1">${portfolio.total_value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</p>
        </Card>
        <Card>
          <p className="text-xs text-zinc-500 uppercase">Total Cost</p>
          <p className="text-2xl font-bold mt-1">${portfolio.total_cost?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</p>
        </Card>
        <Card>
          <p className="text-xs text-zinc-500 uppercase">Total P&L</p>
          <p className={`text-2xl font-bold mt-1 ${portfolio.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {portfolio.total_pnl >= 0 ? '+' : ''}{portfolio.total_pnl?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </p>
        </Card>
        <Card>
          <p className="text-xs text-zinc-500 uppercase">P&L %</p>
          <p className={`text-2xl font-bold mt-1 ${portfolio.total_pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {portfolio.total_pnl_percent >= 0 ? '+' : ''}{portfolio.total_pnl_percent?.toFixed(2)}%
          </p>
        </Card>
      </div>

      {/* Add Position Form */}
      {showAddForm && (
        <Card hover={false}>
          <h3 className="font-semibold mb-4">Add New Position</h3>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="text-xs text-zinc-500 uppercase block mb-2">Symbol</label>
              <input
                type="text"
                value={newPosition.symbol}
                onChange={(e) => setNewPosition({ ...newPosition, symbol: e.target.value.toUpperCase() })}
                placeholder="AAPL"
                className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
                data-testid="position-symbol-input"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 uppercase block mb-2">Shares</label>
              <input
                type="number"
                value={newPosition.shares}
                onChange={(e) => setNewPosition({ ...newPosition, shares: e.target.value })}
                placeholder="100"
                className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
                data-testid="position-shares-input"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 uppercase block mb-2">Avg Cost</label>
              <input
                type="number"
                step="0.01"
                value={newPosition.avg_cost}
                onChange={(e) => setNewPosition({ ...newPosition, avg_cost: e.target.value })}
                placeholder="150.00"
                className="w-full bg-subtle border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-500 focus:border-primary/50 focus:outline-none"
                data-testid="position-cost-input"
              />
            </div>
            <div className="flex items-end">
              <button onClick={addPosition} className="btn-primary w-full" data-testid="submit-position-btn">
                Add Position
              </button>
            </div>
          </div>
        </Card>
      )}

      {/* Positions Table */}
      <Card hover={false}>
        <h2 className="font-semibold mb-4">Positions ({portfolio.positions?.length || 0})</h2>
        {loading ? (
          <div className="animate-pulse space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-12 bg-white/5 rounded"></div>
            ))}
          </div>
        ) : portfolio.positions?.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Shares</th>
                  <th>Avg Cost</th>
                  <th>Current Price</th>
                  <th>Market Value</th>
                  <th>P&L</th>
                  <th>P&L %</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {portfolio.positions.map((position, idx) => (
                  <tr key={idx}>
                    <td className="font-bold text-primary">{position.symbol}</td>
                    <td className="font-mono">{position.shares}</td>
                    <td className="font-mono">${position.avg_cost?.toFixed(2)}</td>
                    <td className="font-mono">${position.current_price?.toFixed(2) || '--'}</td>
                    <td className="font-mono">${position.market_value?.toFixed(2) || '--'}</td>
                    <td className={`font-mono ${position.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {position.pnl >= 0 ? '+' : ''}${position.pnl?.toFixed(2) || '0.00'}
                    </td>
                    <td>
                      {position.pnl_percent !== undefined && <PriceDisplay value={position.pnl_percent} />}
                    </td>
                    <td>
                      <button
                        onClick={() => removePosition(position.symbol)}
                        className="text-zinc-500 hover:text-red-400 transition-colors"
                        data-testid={`remove-position-${position.symbol}`}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-12">
            <DollarSign className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-500">No positions yet</p>
            <p className="text-zinc-600 text-sm mt-1">Add your first position to start tracking</p>
          </div>
        )}
      </Card>
    </div>
  );
};

export default PortfolioPage;
